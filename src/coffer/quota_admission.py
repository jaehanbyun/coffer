from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Protocol
from urllib.parse import urlsplit
import uuid

import falcon
import jwt
from oslo_db import exception as db_exception
from sqlalchemy import exc as sa_exception

from coffer.db import RepositoryStore
from coffer.quota import (
    Descriptor,
    InvalidManifest,
    MAX_DESCRIPTOR_COUNT,
    MAX_MANIFEST_BYTES,
    ParsedManifest,
    QuotaExceeded,
    QuotaNotConfigured,
    QuotaStore,
    Reservation,
    parse_manifest,
)
from coffer.tokens import REPOSITORY_NAME


MAX_AUTHORIZATION_BYTES = 16 * 1024
REQUEST_ID = re.compile(r"req-[A-Za-z0-9._:-]{1,124}")
MANIFEST_REFERENCE = re.compile(
    r"(?:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}|sha256:[0-9a-f]{64})"
)
DATABASE_ERRORS = (db_exception.DBError, sa_exception.SQLAlchemyError)


class InvalidRegistryToken(Exception):
    pass


class RepositoryNotAuthorized(Exception):
    pass


class DescriptorNotFound(Exception):
    pass


class DescriptorNotAuthorized(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedRegistryPrincipal:
    project_id: str
    repository: str
    canonical_name: str
    subject: str
    jti: str


@dataclass(frozen=True, slots=True)
class UpstreamResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


@dataclass(frozen=True, slots=True)
class PreparedManifest:
    repository_id: str
    parsed: ParsedManifest


class ManifestUpstream(Protocol):
    def descriptor_size(
        self,
        *,
        repository: str,
        digest: str,
        manifest: bool,
        headers: Mapping[str, str],
    ) -> int: ...

    def put_manifest(
        self,
        *,
        repository: str,
        reference: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> UpstreamResponse: ...


class RegistryTokenVerifier:
    def __init__(
        self,
        jwks: Mapping[str, object],
        *,
        issuer: str,
        service: str,
    ) -> None:
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValueError("JWKS must contain at least one key")
        self._keys = {
            key["kid"]: jwt.PyJWK.from_dict(key).key
            for key in keys
            if isinstance(key, dict) and isinstance(key.get("kid"), str)
        }
        if not self._keys:
            raise ValueError("JWKS has no keyed verification material")
        self._issuer = issuer
        self._service = service

    @property
    def service(self) -> str:
        return self._service

    def verify(self, authorization: str | None, repository: str) -> VerifiedRegistryPrincipal:
        if authorization is None or len(authorization.encode()) > MAX_AUTHORIZATION_BYTES:
            raise InvalidRegistryToken("Bearer token is required")
        scheme, separator, token = authorization.partition(" ")
        if scheme != "Bearer" or separator != " " or not token or " " in token:
            raise InvalidRegistryToken("Bearer token is malformed")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise InvalidRegistryToken("Bearer token header is invalid")
            key = self._keys.get(header["kid"])
            if key is None:
                raise InvalidRegistryToken("Bearer token key is unknown")
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._service,
                issuer=self._issuer,
                options={"require": ["exp", "nbf", "iat", "jti", "sub", "access"]},
            )
        except jwt.PyJWTError as exc:
            raise InvalidRegistryToken("Bearer token verification failed") from exc

        match = REPOSITORY_NAME.fullmatch(repository)
        if match is None:
            raise RepositoryNotAuthorized("repository is not canonical")
        access = claims.get("access")
        if not isinstance(access, list):
            raise InvalidRegistryToken("Bearer token access is invalid")
        granted = any(
            isinstance(grant, dict)
            and grant.get("type") == "repository"
            and grant.get("name") == repository
            and isinstance(grant.get("actions"), list)
            and "push" in grant["actions"]
            for grant in access
        )
        if not granted:
            raise RepositoryNotAuthorized("push action is not granted")
        subject = claims.get("sub")
        jti = claims.get("jti")
        if not isinstance(subject, str) or not subject or not isinstance(jti, str) or not jti:
            raise InvalidRegistryToken("Bearer token identity is invalid")
        return VerifiedRegistryPrincipal(
            project_id=match.group("project_id"),
            repository=match.group("repository"),
            canonical_name=repository,
            subject=subject,
            jti=jti,
        )


class ManifestAdmissionService:
    def __init__(self, repositories: RepositoryStore, quotas: QuotaStore) -> None:
        self._repositories = repositories
        self._quotas = quotas

    def prepare(
        self,
        principal: VerifiedRegistryPrincipal,
        *,
        reference: str,
        body: bytes,
        media_type: str | None,
    ) -> PreparedManifest:
        repository = self._repositories.get_by_name(
            principal.project_id, principal.repository
        )
        if repository is None:
            raise RepositoryNotAuthorized("repository is not registered")
        if MANIFEST_REFERENCE.fullmatch(reference) is None:
            raise InvalidManifest("manifest reference is invalid")
        parsed = parse_manifest(body, media_type=media_type)
        if reference.startswith("sha256:") and reference != parsed.digest:
            raise InvalidManifest("manifest path digest does not match its body")
        return PreparedManifest(repository.id, parsed)

    def ensure_quota_authority(self, principal: VerifiedRegistryPrincipal) -> None:
        self._quotas.usage(principal.project_id)

    def reserve(
        self,
        principal: VerifiedRegistryPrincipal,
        *,
        prepared: PreparedManifest,
        request_id: str,
    ) -> Reservation:
        parsed = prepared.parsed
        graph: dict[str, Descriptor] = {
            descriptor.digest: descriptor for descriptor in parsed.descriptors
        }
        for child in parsed.child_manifests:
            child_graph = self._quotas.manifest_graph(
                principal.project_id, child.digest
            )
            if child_graph is None:
                raise InvalidManifest("index child manifest is not committed")
            known_self = next(
                (item for item in child_graph if item.digest == child.digest), None
            )
            if known_self is None or known_self.size != child.size:
                raise InvalidManifest("index child descriptor size does not match")
            for descriptor in child_graph:
                existing = graph.get(descriptor.digest)
                if existing is not None and existing.size != descriptor.size:
                    raise InvalidManifest("resolved graph has conflicting sizes")
                graph[descriptor.digest] = descriptor
                if len(graph) > MAX_DESCRIPTOR_COUNT:
                    raise InvalidManifest(
                        "resolved descriptor graph exceeds the maximum"
                    )

        return self._quotas.reserve(
            project_id=principal.project_id,
            repository_id=prepared.repository_id,
            manifest_digest=parsed.digest,
            request_id=request_id,
            descriptors=tuple(sorted(graph.values(), key=lambda item: item.digest)),
        )

    def commit(self, reservation_id: str) -> Reservation:
        return self._quotas.commit(reservation_id)

    def mark_indeterminate(self, reservation_id: str) -> Reservation:
        return self._quotas.mark_release_pending(reservation_id)

    def release_absent(self, reservation_id: str) -> Reservation:
        return self._quotas.reconcile_absent(reservation_id)


def _distribution_error(
    resp: falcon.Response,
    status: str,
    code: str,
    message: str,
    *,
    retry_after: str | None = None,
    challenge: str | None = None,
) -> None:
    resp.status = status
    resp.content_type = falcon.MEDIA_JSON
    resp.media = {"errors": [{"code": code, "message": message}]}
    if retry_after is not None:
        resp.set_header("Retry-After", retry_after)
    if challenge is not None:
        resp.set_header("WWW-Authenticate", challenge)


class ManifestAdmissionResource:
    def __init__(
        self,
        verifier: RegistryTokenVerifier,
        admission: ManifestAdmissionService,
        upstream: ManifestUpstream,
        *,
        token_realm: str,
    ) -> None:
        parsed_realm = urlsplit(token_realm)
        if (
            parsed_realm.scheme not in {"http", "https"}
            or not parsed_realm.netloc
            or not parsed_realm.path
            or parsed_realm.query
            or parsed_realm.fragment
        ):
            raise ValueError("token realm must be one absolute HTTP(S) URL")
        self._verifier = verifier
        self._admission = admission
        self._upstream = upstream
        self._token_realm = token_realm

    def _challenge(self, repository: str) -> str:
        return (
            f'Bearer realm="{self._token_realm}",'
            f'service="{self._verifier.service}",'
            f'scope="repository:{repository}:pull,push"'
        )

    def on_put(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        repository: str,
        reference: str,
    ) -> None:
        request_id = req.get_header("X-Openstack-Request-Id")
        if request_id is None or REQUEST_ID.fullmatch(request_id) is None:
            request_id = f"req-{uuid.uuid4()}"
        resp.set_header("X-Openstack-Request-Id", request_id)
        authorization = req.env.pop("HTTP_AUTHORIZATION", None)
        try:
            principal = self._verifier.verify(authorization, repository)
        except (InvalidRegistryToken, RepositoryNotAuthorized):
            authorization = None
            _distribution_error(
                resp,
                falcon.HTTP_401,
                "UNAUTHORIZED",
                "authentication required",
                challenge=self._challenge(repository),
            )
            return

        if req.content_length is not None and req.content_length > MAX_MANIFEST_BYTES:
            authorization = None
            _distribution_error(
                resp,
                falcon.HTTP_413,
                "MANIFEST_INVALID",
                "manifest body is too large",
            )
            return
        body = req.bounded_stream.read(MAX_MANIFEST_BYTES + 1)
        if len(body) > MAX_MANIFEST_BYTES:
            authorization = None
            _distribution_error(
                resp,
                falcon.HTTP_413,
                "MANIFEST_INVALID",
                "manifest body is too large",
            )
            return

        try:
            prepared = self._admission.prepare(
                principal,
                reference=reference,
                body=body,
                media_type=req.content_type,
            )
        except RepositoryNotAuthorized:
            authorization = None
            _distribution_error(
                resp,
                falcon.HTTP_401,
                "UNAUTHORIZED",
                "authentication required",
                challenge=self._challenge(repository),
            )
            return
        except InvalidManifest as exc:
            authorization = None
            _distribution_error(
                resp, falcon.HTTP_400, "MANIFEST_INVALID", str(exc)
            )
            return

        forwarded_headers = {
            name: value
            for name, value in req.headers.items()
            if name.lower() not in {"content-length", "connection"}
        }
        forwarded_headers["Authorization"] = authorization
        try:
            try:
                self._admission.ensure_quota_authority(principal)
            except (QuotaNotConfigured, *DATABASE_ERRORS):
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "quota authority unavailable",
                    retry_after="5",
                )
                return
            child_manifests = {
                descriptor.digest for descriptor in prepared.parsed.child_manifests
            }
            try:
                for descriptor in prepared.parsed.descriptors:
                    if descriptor.digest == prepared.parsed.digest:
                        continue
                    actual_size = self._upstream.descriptor_size(
                        repository=repository,
                        digest=descriptor.digest,
                        manifest=descriptor.digest in child_manifests,
                        headers=forwarded_headers,
                    )
                    if actual_size != descriptor.size:
                        raise InvalidManifest(
                            "descriptor size does not match upstream content"
                        )
            except DescriptorNotAuthorized:
                _distribution_error(
                    resp,
                    falcon.HTTP_401,
                    "UNAUTHORIZED",
                    "authentication required",
                    challenge=self._challenge(repository),
                )
                return
            except DescriptorNotFound:
                _distribution_error(
                    resp,
                    falcon.HTTP_400,
                    "MANIFEST_BLOB_UNKNOWN",
                    "referenced descriptor is not present",
                )
                return
            except InvalidManifest as exc:
                _distribution_error(
                    resp, falcon.HTTP_400, "MANIFEST_INVALID", str(exc)
                )
                return
            except Exception:
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "registry metadata dependency unavailable",
                    retry_after="5",
                )
                return

            try:
                reservation = self._admission.reserve(
                    principal,
                    prepared=prepared,
                    request_id=request_id,
                )
            except InvalidManifest as exc:
                _distribution_error(
                    resp, falcon.HTTP_400, "MANIFEST_INVALID", str(exc)
                )
                return
            except QuotaExceeded:
                _distribution_error(
                    resp,
                    falcon.HTTP_429,
                    "TOOMANYREQUESTS",
                    "project logical quota exceeded",
                    retry_after="60",
                )
                return
            except (QuotaNotConfigured, *DATABASE_ERRORS):
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "quota authority unavailable",
                    retry_after="5",
                )
                return

            try:
                upstream = self._upstream.put_manifest(
                    repository=repository,
                    reference=reference,
                    headers=forwarded_headers,
                    body=body,
                )
            except Exception:
                try:
                    self._admission.mark_indeterminate(reservation.id)
                except DATABASE_ERRORS:
                    pass
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "registry dependency unavailable",
                    retry_after="5",
                )
                return
        finally:
            forwarded_headers.pop("Authorization", None)
            authorization = None

        if 200 <= upstream.status < 300:
            try:
                self._admission.commit(reservation.id)
            except DATABASE_ERRORS:
                try:
                    self._admission.mark_indeterminate(reservation.id)
                except DATABASE_ERRORS:
                    pass
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "quota commit is indeterminate",
                    retry_after="5",
                )
                return
        elif 400 <= upstream.status < 500 and reservation.state == "pending":
            try:
                self._admission.release_absent(reservation.id)
            except DATABASE_ERRORS:
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "quota reconciliation unavailable",
                    retry_after="5",
                )
                return
        else:
            try:
                self._admission.mark_indeterminate(reservation.id)
            except DATABASE_ERRORS:
                _distribution_error(
                    resp,
                    falcon.HTTP_503,
                    "UNAVAILABLE",
                    "quota reconciliation unavailable",
                    retry_after="5",
                )
                return
        resp.status = upstream.status
        for name, value in upstream.headers:
            if name.lower() not in {"connection", "transfer-encoding"}:
                resp.append_header(name, value)
        resp.data = upstream.body


def build_manifest_admission_application(
    verifier: RegistryTokenVerifier,
    admission: ManifestAdmissionService,
    upstream: ManifestUpstream,
    *,
    token_realm: str,
) -> falcon.App:
    application = falcon.App()
    resource = ManifestAdmissionResource(
        verifier, admission, upstream, token_realm=token_realm
    )

    def sink(req: falcon.Request, resp: falcon.Response) -> None:
        match = re.fullmatch(r"/v2/(.+)/manifests/([^/]+)", req.path)
        if match is None:
            raise falcon.HTTPNotFound()
        if req.method != "PUT":
            raise falcon.HTTPMethodNotAllowed(["PUT"])
        resource.on_put(req, resp, match.group(1), match.group(2))

    application.add_sink(sink, prefix="/v2/")
    return application
