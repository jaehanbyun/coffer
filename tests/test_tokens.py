from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from coffer.authorization import RegistryScopeAuthorizer
from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.keystone import ApplicationCredentialPrincipal
from coffer.policy import create_enforcer
from coffer.tokens import (
    AccessGrant,
    CredentialExpiresTooSoon,
    InvalidTokenRequest,
    TokenIssuer,
    TokenRequest,
    parse_token_request,
)


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
SERVICE = "coffer-registry"


def _principal(
    *roles: str,
    project_id: str = PROJECT_A,
    expires_at: datetime | None = None,
) -> ApplicationCredentialPrincipal:
    return ApplicationCredentialPrincipal(
        application_credential_id="app-credential-id",
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        project_id=project_id,
        roles=roles,
        expires_at=expires_at or NOW + timedelta(hours=1),
        audit_ids=("audit-id",),
    )


def _request(*scope: str) -> TokenRequest:
    return parse_token_request(
        {"service": [SERVICE], "scope": list(scope)}, expected_service=SERVICE
    )


def _authorize(
    request: TokenRequest,
    principal: ApplicationCredentialPrincipal,
    *repositories: tuple[str, str],
) -> tuple[AccessGrant, ...]:
    conf = new_config()
    conf(args=[])
    store = RepositoryStore("sqlite://", bootstrap_schema=True)
    for project_id, name in repositories:
        store.create(project_id, name)
    authorizer = RegistryScopeAuthorizer(store, create_enforcer(conf))
    return authorizer.authorize(request, principal)


def test_scope_parser_accepts_encoded_result_shape_and_multiple_unique_scopes() -> None:
    request = _request(
        f"repository:p/{PROJECT_A}/zeta:push,pull "
        f"repository:p/{PROJECT_A}/alpha:pull"
    )

    assert [scope.name for scope in request.scopes] == [
        f"p/{PROJECT_A}/alpha",
        f"p/{PROJECT_A}/zeta",
    ]
    assert request.scopes[1].actions == ("pull", "push")


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"service": ["wrong-service"]},
        {"service": [SERVICE, SERVICE]},
        {"service": [SERVICE], "offline_token": ["yes"]},
        {"service": [SERVICE], "unknown": ["value"]},
        {
            "service": [SERVICE],
            "scope": [f"registry:p/{PROJECT_A}/demo:pull"],
        },
        {
            "service": [SERVICE],
            "scope": [f"repository:p/{PROJECT_A}/../demo:pull"],
        },
        {
            "service": [SERVICE],
            "scope": [f"repository:p/{PROJECT_A}/demo:pull,pull"],
        },
        {
            "service": [SERVICE],
            "scope": [f"repository:p/{PROJECT_A}/demo:catalog"],
        },
    ],
)
def test_malformed_or_ambiguous_token_requests_fail_closed(
    parameters: dict[str, list[str]],
) -> None:
    with pytest.raises(InvalidTokenRequest):
        parse_token_request(parameters, expected_service=SERVICE)


def test_repeated_repository_scopes_merge_actions_for_docker_clients() -> None:
    request = parse_token_request(
        {
            "service": [SERVICE],
            "scope": [
                f"repository:p/{PROJECT_A}/demo:pull",
                f"repository:p/{PROJECT_A}/demo:pull,push",
            ],
        },
        expected_service=SERVICE,
    )

    assert len(request.scopes) == 1
    assert request.scopes[0].name == f"p/{PROJECT_A}/demo"
    assert request.scopes[0].actions == ("pull", "push")


@pytest.mark.parametrize(
    ("roles", "requested", "expected"),
    [
        (("reader",), "pull,push,delete", ("pull",)),
        (("member",), "pull,push,delete", ("pull", "push")),
        (("admin",), "pull,push,delete", ("pull", "push", "delete")),
        (("service",), "pull,push,delete", ()),
        (("Reader",), "pull", ()),
    ],
)
def test_actions_are_the_intersection_of_request_and_project_roles(
    roles: tuple[str, ...], requested: str, expected: tuple[str, ...]
) -> None:
    request = _request(f"repository:p/{PROJECT_A}/demo:{requested}")

    grants = _authorize(request, _principal(*roles), (PROJECT_A, "demo"))

    if expected:
        assert len(grants) == 1
        assert grants[0].actions == expected
    else:
        assert grants == ()


def test_cross_project_scope_produces_no_grant() -> None:
    request = _request(f"repository:p/{PROJECT_B}/demo:pull,push")

    assert _authorize(
        request, _principal("admin"), (PROJECT_B, "demo")
    ) == ()


def test_nonexistent_repository_produces_no_grant() -> None:
    request = _request(f"repository:p/{PROJECT_A}/missing:pull,push")

    assert _authorize(request, _principal("admin")) == ()


def test_issuer_produces_distribution_claims_and_public_jwks() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = TokenIssuer(
        private_key=private_key,
        issuer="https://coffer.example.test/auth/token",
        service=SERVICE,
        clock=lambda: NOW,
    )
    request = _request(f"repository:p/{PROJECT_A}/demo:pull,push,delete")
    grants = _authorize(
        request, _principal("member"), (PROJECT_A, "demo")
    )

    issued = issuer.issue(_principal("member"), grants)
    header = jwt.get_unverified_header(issued.token)
    claims = jwt.decode(
        issued.token,
        private_key.public_key(),
        algorithms=["RS256"],
        audience=SERVICE,
        issuer="https://coffer.example.test/auth/token",
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )

    assert header == {"alg": "RS256", "kid": issuer.key_id, "typ": "JWT"}
    assert claims["sub"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert claims["aud"] == SERVICE
    assert claims["iat"] == int(NOW.timestamp())
    assert claims["nbf"] == int(NOW.timestamp())
    assert claims["exp"] == int((NOW + timedelta(minutes=5)).timestamp())
    assert claims["jti"] == issued.jti
    assert claims["access"] == [
        {
            "type": "repository",
            "name": f"p/{PROJECT_A}/demo",
            "actions": ["pull", "push"],
        }
    ]
    assert issued.expires_in == 300
    assert issued.response() == {
        "token": issued.token,
        "expires_in": 300,
        "issued_at": "2026-07-21T12:00:00Z",
    }
    assert issuer.jwks() == {
        "keys": [
            {
                "kty": "RSA",
                "n": issuer.jwks()["keys"][0]["n"],
                "e": "AQAB",
                "alg": "RS256",
                "kid": issuer.key_id,
                "use": "sig",
            }
        ]
    }


def test_registry_token_never_outlives_keystone_token() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = TokenIssuer(
        private_key=private_key,
        issuer="coffer",
        service=SERVICE,
        clock=lambda: NOW,
    )
    principal = _principal("reader", expires_at=NOW + timedelta(seconds=90))

    issued = issuer.issue(principal, ())

    assert issued.expires_in == 90


def test_credential_expiring_below_compatibility_floor_is_rejected() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = TokenIssuer(
        private_key=private_key,
        issuer="coffer",
        service=SERVICE,
        clock=lambda: NOW,
    )
    principal = _principal("reader", expires_at=NOW + timedelta(seconds=59))

    with pytest.raises(CredentialExpiresTooSoon):
        issuer.issue(principal, ())


def test_signer_rejects_weak_key_and_lifetime_above_five_minutes() -> None:
    with pytest.raises(ValueError, match="2048 bits"):
        TokenIssuer(
            private_key=rsa.generate_private_key(
                public_exponent=65537, key_size=1024
            ),
            issuer="coffer",
            service=SERVICE,
        )
    with pytest.raises(ValueError, match="60 and 300"):
        TokenIssuer(
            private_key=rsa.generate_private_key(
                public_exponent=65537, key_size=2048
            ),
            issuer="coffer",
            service=SERVICE,
            lifetime_seconds=301,
        )


def test_signer_rejects_group_or_world_readable_private_key(tmp_path: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_file = tmp_path / "signing.pem"
    private_key_file.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_key_file.chmod(0o644)

    with pytest.raises(ValueError, match="group/world"):
        TokenIssuer.from_pem_file(
            str(private_key_file), issuer="coffer", service=SERVICE
        )
