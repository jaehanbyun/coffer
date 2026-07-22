from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
import re
import stat
import uuid

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import jwt

from coffer.keystone import ApplicationCredentialPrincipal


ALLOWED_QUERY_PARAMETERS = {
    "account",
    "client_id",
    "offline_token",
    "scope",
    "service",
}
ALLOWED_ACTIONS = frozenset({"pull", "push", "delete"})
ACTION_ORDER = ("pull", "push", "delete")
PROJECT_ID = re.compile(
    r"(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})"
)
REPOSITORY_SUFFIX = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
)
REPOSITORY_NAME = re.compile(
    rf"p/(?P<project_id>{PROJECT_ID.pattern})/(?P<repository>{REPOSITORY_SUFFIX.pattern})"
)
MAX_SCOPE_COUNT = 8


class InvalidTokenRequest(Exception):
    pass


class CredentialExpiresTooSoon(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RequestedScope:
    type: str
    name: str
    project_id: str
    repository: str
    actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TokenRequest:
    service: str
    scopes: tuple[RequestedScope, ...]
    account: str | None
    client_id: str | None


@dataclass(frozen=True, slots=True)
class AccessGrant:
    type: str
    name: str
    actions: tuple[str, ...]

    def to_claim(self) -> dict[str, object]:
        return {"type": self.type, "name": self.name, "actions": list(self.actions)}


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_in: int
    issued_at: datetime
    jti: str
    access: tuple[AccessGrant, ...]

    def response(self) -> dict[str, object]:
        return {
            "token": self.token,
            "expires_in": self.expires_in,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
        }


def _exactly_one(
    parameters: Mapping[str, Sequence[str]], name: str, *, required: bool = False
) -> str | None:
    values = parameters.get(name, ())
    if not values:
        if required:
            raise InvalidTokenRequest(f"{name} is required")
        return None
    if len(values) != 1 or not values[0]:
        raise InvalidTokenRequest(f"{name} must appear exactly once")
    return values[0]


def _parse_scope(value: str) -> RequestedScope:
    parts = value.split(":", 2)
    if len(parts) != 3 or parts[0] != "repository":
        raise InvalidTokenRequest("only repository scopes are supported")
    name, action_text = parts[1:]
    match = REPOSITORY_NAME.fullmatch(name)
    if match is None:
        raise InvalidTokenRequest("repository scope is not canonical")

    requested_actions = action_text.split(",")
    if (
        not requested_actions
        or any(not action for action in requested_actions)
        or len(set(requested_actions)) != len(requested_actions)
        or not set(requested_actions).issubset(ALLOWED_ACTIONS)
    ):
        raise InvalidTokenRequest("repository actions are invalid")
    actions = tuple(action for action in ACTION_ORDER if action in requested_actions)
    return RequestedScope(
        type="repository",
        name=name,
        project_id=match.group("project_id"),
        repository=match.group("repository"),
        actions=actions,
    )


def parse_token_request(
    parameters: Mapping[str, Sequence[str]], *, expected_service: str
) -> TokenRequest:
    unknown = set(parameters) - ALLOWED_QUERY_PARAMETERS
    if unknown:
        raise InvalidTokenRequest("unsupported token request parameter")

    service = _exactly_one(parameters, "service", required=True)
    if service != expected_service:
        raise InvalidTokenRequest("unknown registry service")
    account = _exactly_one(parameters, "account")
    client_id = _exactly_one(parameters, "client_id")
    offline_token = _exactly_one(parameters, "offline_token")
    if offline_token not in (None, "false", "true"):
        raise InvalidTokenRequest("offline_token must be true or false")

    raw_scopes: list[str] = []
    for value in parameters.get("scope", ()):
        raw_scopes.extend(part for part in value.split(" ") if part)
    if len(raw_scopes) > MAX_SCOPE_COUNT:
        raise InvalidTokenRequest("too many repository scopes")

    parsed_scopes = tuple(_parse_scope(value) for value in raw_scopes)
    merged_actions: dict[str, set[str]] = {}
    scopes_by_name: dict[str, RequestedScope] = {}
    for scope in parsed_scopes:
        scopes_by_name.setdefault(scope.name, scope)
        merged_actions.setdefault(scope.name, set()).update(scope.actions)
    scopes = tuple(
        RequestedScope(
            type=scopes_by_name[name].type,
            name=name,
            project_id=scopes_by_name[name].project_id,
            repository=scopes_by_name[name].repository,
            actions=tuple(
                action for action in ACTION_ORDER if action in merged_actions[name]
            ),
        )
        for name in sorted(scopes_by_name)
    )
    return TokenRequest(
        service=service,
        scopes=scopes,
        account=account,
        client_id=client_id,
    )


def _base64url_uint(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode()


def public_jwk(public_key: rsa.RSAPublicKey, *, key_id: str | None = None) -> dict[str, str]:
    numbers = public_key.public_numbers()
    material = {
        "e": _base64url_uint(numbers.e),
        "kty": "RSA",
        "n": _base64url_uint(numbers.n),
    }
    if key_id is None:
        canonical = json.dumps(material, separators=(",", ":"), sort_keys=True)
        key_id = base64.urlsafe_b64encode(
            hashlib.sha256(canonical.encode()).digest()
        ).rstrip(b"=").decode()
    return {
        **material,
        "alg": "RS256",
        "kid": key_id,
        "use": "sig",
    }


Clock = Callable[[], datetime]


class TokenIssuer:
    def __init__(
        self,
        *,
        private_key: rsa.RSAPrivateKey,
        issuer: str,
        service: str,
        lifetime_seconds: int = 300,
        minimum_lifetime_seconds: int = 60,
        maximum_lifetime_seconds: int = 300,
        key_id: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        if not minimum_lifetime_seconds <= lifetime_seconds <= maximum_lifetime_seconds:
            raise ValueError("token lifetime must be between 60 and 300 seconds")
        if private_key.key_size < 2048:
            raise ValueError("token signing key must be at least 2048 bits")
        self._private_key = private_key
        self.issuer = issuer
        self.service = service
        self.lifetime_seconds = lifetime_seconds
        self.minimum_lifetime_seconds = minimum_lifetime_seconds
        self.maximum_lifetime_seconds = maximum_lifetime_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self.key_id = public_jwk(private_key.public_key(), key_id=key_id)["kid"]

    @classmethod
    def from_pem_file(
        cls,
        private_key_file: str,
        **kwargs: object,
    ) -> "TokenIssuer":
        if not private_key_file:
            raise ValueError("token private_key_file is required")
        file_mode = stat.S_IMODE(os.stat(private_key_file).st_mode)
        if file_mode & 0o077:
            raise ValueError("token private key file must not be group/world accessible")
        with open(private_key_file, "rb") as stream:
            private_key = serialization.load_pem_private_key(
                stream.read(), password=None
            )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError("token signing key must be an RSA private key")
        return cls(private_key=private_key, **kwargs)

    def jwks(self) -> dict[str, object]:
        return {"keys": [public_jwk(self._private_key.public_key(), key_id=self.key_id)]}

    def issue(
        self,
        principal: ApplicationCredentialPrincipal,
        access: Sequence[AccessGrant],
    ) -> IssuedToken:
        issued_at = self._clock().astimezone(UTC).replace(microsecond=0)
        maximum_expiry = issued_at + timedelta(seconds=self.lifetime_seconds)
        credential_expiry = principal.expires_at.astimezone(UTC).replace(microsecond=0)
        expires_at = min(maximum_expiry, credential_expiry)
        expires_in = int((expires_at - issued_at).total_seconds())
        if expires_in < self.minimum_lifetime_seconds:
            raise CredentialExpiresTooSoon(
                "credential lifetime is below the registry token compatibility floor"
            )

        jti = str(uuid.uuid4())
        claims = {
            "iss": self.issuer,
            "sub": principal.user_id,
            "aud": self.service,
            "exp": expires_at,
            "nbf": issued_at,
            "iat": issued_at,
            "jti": jti,
            "access": [grant.to_claim() for grant in access],
        }
        token = jwt.encode(
            claims,
            self._private_key,
            algorithm="RS256",
            headers={"alg": "RS256", "kid": self.key_id, "typ": "JWT"},
        )
        return IssuedToken(
            token=token,
            expires_in=expires_in,
            issued_at=issued_at,
            jti=jti,
            access=tuple(access),
        )
