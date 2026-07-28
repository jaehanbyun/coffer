from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import http.client
import json
import os
from pathlib import Path
import stat
import ssl
from typing import Any, Protocol
from urllib.parse import urlsplit

from keystoneauth1 import session as keystone_session
from keystoneauth1.identity import v3

from coffer.maintenance_token import (
    INTERNAL_SERVICE_TYPE,
    INTERNAL_TOKEN_PATH,
    REQUIRED_ROLES,
)
from coffer.quota import SHA256_DIGEST
from coffer.quota_reconciliation import (
    MANIFEST_ACCEPT,
    ManifestPresence,
    ProbeObservation,
)
from coffer.tokens import REPOSITORY_NAME


MAX_CREDENTIAL_BYTES = 4096
MAX_IDENTITY_TOKEN_BYTES = 64 * 1024
MAX_MAINTENANCE_RESPONSE_BYTES = 64 * 1024
MAX_DISTRIBUTION_TOKEN_BYTES = 64 * 1024
MAX_TOKEN_LIFETIME_SECONDS = 300


class MaintenanceProbeUnavailable(Exception):
    """One authenticated reconciliation dependency failed safely."""

    def __init__(self) -> None:
        super().__init__("authenticated reconciliation probe unavailable")


class IdentityTokenSource(Protocol):
    def issue_token(self) -> str: ...


class HTTPSConnection(Protocol):
    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None: ...

    def getresponse(self) -> Any: ...

    def close(self) -> None: ...


HTTPSConnectionFactory = Callable[
    [str, int, float, ssl.SSLContext],
    HTTPSConnection,
]
SSLContextFactory = Callable[[], ssl.SSLContext]


def _default_https_connection(
    host: str,
    port: int,
    timeout_seconds: float,
    context: ssl.SSLContext,
) -> HTTPSConnection:
    return http.client.HTTPSConnection(
        host,
        port,
        timeout=timeout_seconds,
        context=context,
    )


@dataclass(frozen=True, slots=True)
class _HTTPSEndpoint:
    host: str
    port: int
    path: str


def _parse_https_endpoint(
    value: str,
    *,
    exact_path: str | None = None,
    origin_only: bool = False,
) -> _HTTPSEndpoint:
    if not isinstance(value, str) or not value:
        raise ValueError("authenticated reconciliation endpoint is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("authenticated reconciliation endpoint is invalid") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("authenticated reconciliation endpoint is invalid")
    if exact_path is not None and parsed.path != exact_path:
        raise ValueError("authenticated reconciliation endpoint path is invalid")
    if origin_only and parsed.path not in {"", "/"}:
        raise ValueError("authenticated reconciliation origin is invalid")
    return _HTTPSEndpoint(
        host=parsed.hostname,
        port=port or 443,
        path=parsed.path or "/",
    )


def _bounded_token(value: object, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or value.strip() != value
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in value)
    ):
        raise MaintenanceProbeUnavailable()
    return value


def read_owner_only_credential(path: str) -> str:
    """Read one bounded credential without following a link or retaining bytes."""

    candidate = Path(path)
    if not candidate.is_absolute():
        raise MaintenanceProbeUnavailable()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    material = bytearray()
    try:
        descriptor = os.open(candidate, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size < 1
            or metadata.st_size > MAX_CREDENTIAL_BYTES
        ):
            raise MaintenanceProbeUnavailable()
        while len(material) <= MAX_CREDENTIAL_BYTES:
            chunk = os.read(
                descriptor,
                min(1024, MAX_CREDENTIAL_BYTES + 1 - len(material)),
            )
            if not chunk:
                break
            material.extend(chunk)
        if len(material) > MAX_CREDENTIAL_BYTES:
            raise MaintenanceProbeUnavailable()
        if material.endswith(b"\n"):
            del material[-1:]
        if (
            not material
            or b"\x00" in material
            or b"\n" in material
            or b"\r" in material
        ):
            raise MaintenanceProbeUnavailable()
        try:
            value = material.decode("utf-8")
        except UnicodeDecodeError:
            raise MaintenanceProbeUnavailable() from None
        return _bounded_token(value, maximum=MAX_CREDENTIAL_BYTES)
    except MaintenanceProbeUnavailable:
        raise
    except Exception:
        raise MaintenanceProbeUnavailable() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for index in range(len(material)):
            material[index] = 0


def _validate_runtime_file(
    path: str,
    *,
    modes: frozenset[int],
    require_current_owner: bool,
) -> None:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise MaintenanceProbeUnavailable()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(candidate, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) not in modes
            or metadata.st_size < 1
            or (
                require_current_owner
                and metadata.st_uid != os.geteuid()
            )
        ):
            raise MaintenanceProbeUnavailable()
    except MaintenanceProbeUnavailable:
        raise
    except Exception:
        raise MaintenanceProbeUnavailable() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def build_verified_ssl_context(cafile: str) -> ssl.SSLContext:
    _validate_runtime_file(
        cafile,
        modes=frozenset({0o600, 0o644}),
        require_current_owner=False,
    )
    try:
        context = ssl.create_default_context(cafile=cafile)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context
    except Exception:
        raise MaintenanceProbeUnavailable() from None


def build_mtls_ssl_context(
    *,
    cafile: str,
    certfile: str,
    keyfile: str,
) -> ssl.SSLContext:
    _validate_runtime_file(
        certfile,
        modes=frozenset({0o600, 0o644}),
        require_current_owner=True,
    )
    _validate_runtime_file(
        keyfile,
        modes=frozenset({0o600}),
        require_current_owner=True,
    )
    context = build_verified_ssl_context(cafile)
    try:
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        return context
    except Exception:
        raise MaintenanceProbeUnavailable() from None


PluginFactory = Callable[..., Any]
SessionFactory = Callable[..., Any]
Clock = Callable[[], datetime]


class KeystoneApplicationCredentialTokenSource:
    """Exchange owner-only access-rule credentials for one request-local token."""

    __slots__ = (
        "_auth_url",
        "_credential_id_file",
        "_credential_secret_file",
        "_expected_project_id",
        "_expected_user_id",
        "_plugin_factory",
        "_session_factory",
        "_timeout",
        "_verify",
        "_clock",
    )

    def __init__(
        self,
        *,
        auth_url: str,
        cafile: str,
        timeout_seconds: float,
        credential_id_file: str,
        credential_secret_file: str,
        expected_project_id: str,
        expected_user_id: str,
        plugin_factory: PluginFactory = v3.ApplicationCredential,
        session_factory: SessionFactory = keystone_session.Session,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        endpoint = _parse_https_endpoint(auth_url)
        if endpoint.path.rstrip("/") != "/v3":
            raise ValueError("Keystone application-credential endpoint is invalid")
        if (
            not 0 < timeout_seconds <= 60
            or not expected_project_id
            or not expected_user_id
        ):
            raise ValueError("Keystone application-credential settings are invalid")
        _validate_runtime_file(
            cafile,
            modes=frozenset({0o600, 0o644}),
            require_current_owner=False,
        )
        self._auth_url = auth_url
        self._verify = cafile
        self._timeout = timeout_seconds
        self._credential_id_file = credential_id_file
        self._credential_secret_file = credential_secret_file
        self._expected_project_id = expected_project_id
        self._expected_user_id = expected_user_id
        self._plugin_factory = plugin_factory
        self._session_factory = session_factory
        self._clock = clock

    def issue_token(self) -> str:
        credential_id = ""
        credential_secret = ""
        plugin: Any | None = None
        session: Any | None = None
        access: Any | None = None
        try:
            credential_id = read_owner_only_credential(
                self._credential_id_file
            )
            credential_secret = read_owner_only_credential(
                self._credential_secret_file
            )
            plugin = self._plugin_factory(
                auth_url=self._auth_url,
                application_credential_id=credential_id,
                application_credential_secret=credential_secret,
                include_catalog=False,
            )
            session = self._session_factory(
                auth=plugin,
                verify=self._verify,
                timeout=self._timeout,
                app_name="coffer",
                app_version="0.1.0",
            )
            access = plugin.get_access(session)
            access_rules = getattr(
                access,
                "application_credential_access_rules",
                None,
            )
            exact_access_rule = (
                isinstance(access_rules, (list, tuple))
                and len(access_rules) == 1
                and isinstance(access_rules[0], Mapping)
                and access_rules[0].get("service") == INTERNAL_SERVICE_TYPE
                and access_rules[0].get("method") == "POST"
                and access_rules[0].get("path") == INTERNAL_TOKEN_PATH
            )
            expires_at = getattr(access, "expires", None)
            now = self._clock()
            if (
                getattr(access, "application_credential_id", None)
                != credential_id
                or not getattr(access, "project_scoped", False)
                or getattr(access, "project_id", None)
                != self._expected_project_id
                or getattr(access, "user_id", None) != self._expected_user_id
                or tuple(sorted(getattr(access, "role_names", ()) or ()))
                != tuple(sorted(REQUIRED_ROLES))
                or not exact_access_rule
                or not isinstance(expires_at, datetime)
                or expires_at.tzinfo is None
                or expires_at.utcoffset() is None
                or now.tzinfo is None
                or now.utcoffset() is None
                or expires_at <= now
            ):
                raise MaintenanceProbeUnavailable()
            return _bounded_token(
                getattr(access, "auth_token", None),
                maximum=MAX_IDENTITY_TOKEN_BYTES,
            )
        except MaintenanceProbeUnavailable:
            raise
        except Exception:
            raise MaintenanceProbeUnavailable() from None
        finally:
            credential_secret = ""
            credential_id = ""
            access = None
            session = None
            plugin = None


class AuthenticatedReconciliationManifestProbe:
    """Exchange exact claim authority, then perform one bearer-authenticated HEAD."""

    def __init__(
        self,
        *,
        registry_url: str,
        maintenance_token_url: str,
        identity_token_source: IdentityTokenSource,
        registry_ssl_context: ssl.SSLContext,
        maintenance_ssl_context_factory: SSLContextFactory,
        registry_timeout_seconds: float,
        maintenance_timeout_seconds: float,
        connection_factory: HTTPSConnectionFactory = _default_https_connection,
    ) -> None:
        if (
            not 0 < registry_timeout_seconds <= 60
            or not 0 < maintenance_timeout_seconds <= 60
        ):
            raise ValueError("authenticated reconciliation timeout is invalid")
        self._registry = _parse_https_endpoint(
            registry_url,
            origin_only=True,
        )
        self._maintenance = _parse_https_endpoint(
            maintenance_token_url,
            exact_path=INTERNAL_TOKEN_PATH,
        )
        self._identity_token_source = identity_token_source
        self._registry_ssl_context = registry_ssl_context
        self._maintenance_ssl_context_factory = maintenance_ssl_context_factory
        self._registry_timeout = registry_timeout_seconds
        self._maintenance_timeout = maintenance_timeout_seconds
        self._connection_factory = connection_factory

    def _exchange_distribution_token(
        self,
        *,
        identity_token: str,
        repository_id: str,
        reservation_id: str,
        claim_token: str,
        expected_version: int,
    ) -> str:
        body = json.dumps(
            {
                "claim_token": claim_token,
                "expected_version": expected_version,
                "mode": "reconciliation",
                "repository_id": repository_id,
                "reservation_id": reservation_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        connection = self._connection_factory(
            self._maintenance.host,
            self._maintenance.port,
            self._maintenance_timeout,
            self._maintenance_ssl_context_factory(),
        )
        try:
            connection.request(
                "POST",
                self._maintenance.path,
                body=body,
                headers={
                    "Accept": "application/json",
                    "Cache-Control": "no-store",
                    "Content-Type": "application/json",
                    "X-Auth-Token": identity_token,
                },
            )
            response = connection.getresponse()
            content_length = response.getheader("Content-Length")
            if (
                content_length is not None
                and (
                    not content_length.isdigit()
                    or int(content_length) > MAX_MAINTENANCE_RESPONSE_BYTES
                )
            ):
                raise MaintenanceProbeUnavailable()
            document_bytes = response.read(MAX_MAINTENANCE_RESPONSE_BYTES + 1)
            if (
                response.status != 200
                or len(document_bytes) > MAX_MAINTENANCE_RESPONSE_BYTES
                or response.getheader("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
                != "application/json"
            ):
                raise MaintenanceProbeUnavailable()
            try:
                document = json.loads(document_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise MaintenanceProbeUnavailable() from None
            if (
                not isinstance(document, dict)
                or set(document) != {"token", "expires_in", "issued_at"}
                or isinstance(document.get("expires_in"), bool)
                or not isinstance(document.get("expires_in"), int)
                or not 1 <= document["expires_in"] <= MAX_TOKEN_LIFETIME_SECONDS
                or not isinstance(document.get("issued_at"), str)
                or not document["issued_at"].endswith("Z")
            ):
                raise MaintenanceProbeUnavailable()
            return _bounded_token(
                document.get("token"),
                maximum=MAX_DISTRIBUTION_TOKEN_BYTES,
            )
        except MaintenanceProbeUnavailable:
            raise
        except Exception:
            raise MaintenanceProbeUnavailable() from None
        finally:
            connection.close()

    def _probe_distribution(
        self,
        *,
        repository: str,
        digest: str,
        distribution_token: str,
    ) -> ProbeObservation:
        connection = self._connection_factory(
            self._registry.host,
            self._registry.port,
            self._registry_timeout,
            self._registry_ssl_context,
        )
        try:
            connection.request(
                "HEAD",
                f"/v2/{repository}/manifests/{digest}",
                headers={
                    "Accept": MANIFEST_ACCEPT,
                    "Authorization": f"Bearer {distribution_token}",
                    "Cache-Control": "no-store",
                },
            )
            response = connection.getresponse()
            status = response.status
            if status == 404:
                return ProbeObservation(ManifestPresence.ABSENT, status)
            if status != 200:
                return ProbeObservation(
                    ManifestPresence.INDETERMINATE,
                    status,
                )
            content_digests = [
                value.strip()
                for name, value in response.getheaders()
                if name.lower() == "docker-content-digest"
            ]
            if content_digests == [digest]:
                return ProbeObservation(ManifestPresence.PRESENT, status)
            return ProbeObservation(ManifestPresence.INDETERMINATE, status)
        except Exception:
            return ProbeObservation(ManifestPresence.INDETERMINATE, None)
        finally:
            connection.close()

    def probe(
        self,
        *,
        repository: str,
        digest: str,
        repository_id: str,
        reservation_id: str,
        claim_token: str,
        expected_version: int,
    ) -> ProbeObservation:
        if (
            REPOSITORY_NAME.fullmatch(repository) is None
            or SHA256_DIGEST.fullmatch(digest) is None
            or not repository_id
            or repository_id.strip() != repository_id
            or len(repository_id) > 128
            or not reservation_id
            or reservation_id.strip() != reservation_id
            or len(reservation_id) > 128
            or not claim_token
            or claim_token.strip() != claim_token
            or len(claim_token) > 256
            or isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            return ProbeObservation(ManifestPresence.INDETERMINATE, None)

        identity_token = ""
        distribution_token = ""
        try:
            identity_token = self._identity_token_source.issue_token()
            distribution_token = self._exchange_distribution_token(
                identity_token=identity_token,
                repository_id=repository_id,
                reservation_id=reservation_id,
                claim_token=claim_token,
                expected_version=expected_version,
            )
            return self._probe_distribution(
                repository=repository,
                digest=digest,
                distribution_token=distribution_token,
            )
        except Exception:
            return ProbeObservation(ManifestPresence.INDETERMINATE, None)
        finally:
            distribution_token = ""
            identity_token = ""
