from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import re
from typing import Protocol
import uuid

import falcon

from coffer.db import RepositoryStore
from coffer.quota import QuotaStore, ReconciliationReadNotAuthorized
from coffer.tokens import (
    AccessGrant,
    CredentialExpiresTooSoon,
    IssuedToken,
    REPOSITORY_NAME,
    TokenIssuer,
)


INTERNAL_TOKEN_PATH = "/v1/internal/maintenance/registry-token"
INTERNAL_SERVICE_TYPE = "oci-registry"
REQUIRED_ROLES = frozenset({"service", "registry_maintenance"})
SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
Clock = Callable[[], datetime]
LOG = logging.getLogger(__name__)


class MaintenanceTokenDenied(Exception):
    def __init__(self) -> None:
        super().__init__("maintenance token request denied")


class MaintenanceTokenUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__("maintenance token service unavailable")


class MaintenanceAuthorityDenied(Exception):
    def __init__(self) -> None:
        super().__init__("maintenance authority denied")


@dataclass(frozen=True, slots=True)
class MaintenancePrincipal:
    application_credential_id: str
    user_id: str
    project_id: str
    roles: tuple[str, ...]
    expires_at: datetime
    workload_id: str
    audit_ids: tuple[str, ...] = ()

    @classmethod
    def from_environ(cls, environ: Mapping[str, object]) -> MaintenancePrincipal:
        if environ.get("HTTP_X_IDENTITY_STATUS") != "Confirmed":
            raise MaintenanceTokenDenied()
        token_auth = environ.get("keystone.token_auth")
        user_auth = getattr(token_auth, "user", None)
        project_id = getattr(user_auth, "project_id", None)
        user_id = getattr(user_auth, "user_id", None)
        application_credential_id = getattr(
            user_auth,
            "application_credential_id",
            None,
        )
        expires_at = getattr(user_auth, "expires", None)
        access_rules = getattr(
            user_auth,
            "application_credential_access_rules",
            None,
        )
        workload_id = environ.get("coffer.maintenance_workload_id")
        roles = tuple(getattr(user_auth, "role_names", ()) or ())
        exact_access_rule = (
            isinstance(access_rules, (list, tuple))
            and len(access_rules) == 1
            and isinstance(access_rules[0], Mapping)
            and access_rules[0].get("service") == INTERNAL_SERVICE_TYPE
            and access_rules[0].get("method") == "POST"
            and access_rules[0].get("path") == INTERNAL_TOKEN_PATH
        )
        if (
            not getattr(user_auth, "project_scoped", False)
            or not isinstance(project_id, str)
            or environ.get("HTTP_X_PROJECT_ID") != project_id
            or not isinstance(user_id, str)
            or environ.get("HTTP_X_USER_ID") != user_id
            or not isinstance(application_credential_id, str)
            or not application_credential_id
            or not exact_access_rule
            or not isinstance(expires_at, datetime)
            or not isinstance(workload_id, str)
            or not workload_id
            or any(not isinstance(role, str) for role in roles)
        ):
            raise MaintenanceTokenDenied()
        audit_ids = tuple(
            audit_id
            for audit_id in (
                getattr(user_auth, "audit_id", None),
                getattr(user_auth, "audit_chain_id", None),
            )
            if isinstance(audit_id, str) and audit_id
        )
        return cls(
            application_credential_id=application_credential_id,
            user_id=user_id,
            project_id=project_id,
            roles=roles,
            expires_at=expires_at,
            workload_id=workload_id,
            audit_ids=audit_ids,
        )


class MaintenancePolicy:
    def __init__(
        self,
        *,
        service_project_id: str,
        maintenance_user_id: str,
        workload_ids: frozenset[str],
    ) -> None:
        if (
            not service_project_id
            or not maintenance_user_id
            or not workload_ids
            or any(
                not item or item.strip() != item or len(item) > 128
                for item in workload_ids
            )
        ):
            raise ValueError("maintenance policy configuration is invalid")
        self._service_project_id = service_project_id
        self._maintenance_user_id = maintenance_user_id
        self._workload_ids = workload_ids

    def authorize(
        self,
        principal: MaintenancePrincipal,
        *,
        checked_at: datetime,
    ) -> None:
        if (
            checked_at.tzinfo is None
            or checked_at.utcoffset() is None
            or principal.expires_at.tzinfo is None
            or principal.expires_at.utcoffset() is None
            or principal.expires_at <= checked_at
            or principal.project_id != self._service_project_id
            or principal.user_id != self._maintenance_user_id
            or frozenset(principal.roles) != REQUIRED_ROLES
            or len(principal.roles) != len(REQUIRED_ROLES)
            or principal.workload_id not in self._workload_ids
            or not principal.application_credential_id
            or not principal.user_id
        ):
            raise MaintenanceTokenDenied()


def _bounded_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > 128
    ):
        raise MaintenanceTokenDenied()
    return value


@dataclass(frozen=True, slots=True)
class ReconciliationTokenRequest:
    repository_id: str
    reservation_id: str
    claim_token: str
    expected_version: int

    def __post_init__(self) -> None:
        for value in (
            self.repository_id,
            self.reservation_id,
            self.claim_token,
        ):
            _bounded_identifier(value)
        if (
            isinstance(self.expected_version, bool)
            or not isinstance(self.expected_version, int)
            or self.expected_version <= 0
        ):
            raise MaintenanceTokenDenied()


@dataclass(frozen=True, slots=True)
class LiveComparisonTokenRequest:
    repository_id: str
    session_id: str
    inventory_digest: str

    def __post_init__(self) -> None:
        _bounded_identifier(self.repository_id)
        _bounded_identifier(self.session_id)
        if (
            not isinstance(self.inventory_digest, str)
            or SHA256_DIGEST.fullmatch(self.inventory_digest) is None
        ):
            raise MaintenanceTokenDenied()


MaintenanceRequest = ReconciliationTokenRequest | LiveComparisonTokenRequest


def parse_maintenance_token_request(
    document: Mapping[str, object],
) -> MaintenanceRequest:
    if not isinstance(document, Mapping):
        raise MaintenanceTokenDenied()
    mode = document.get("mode")
    if mode == "reconciliation" and set(document) == {
        "mode",
        "repository_id",
        "reservation_id",
        "claim_token",
        "expected_version",
    }:
        return ReconciliationTokenRequest(
            repository_id=document["repository_id"],  # type: ignore[arg-type]
            reservation_id=document["reservation_id"],  # type: ignore[arg-type]
            claim_token=document["claim_token"],  # type: ignore[arg-type]
            expected_version=document["expected_version"],  # type: ignore[arg-type]
        )
    if mode == "live_comparison" and set(document) == {
        "mode",
        "repository_id",
        "session_id",
        "inventory_digest",
    }:
        return LiveComparisonTokenRequest(
            repository_id=document["repository_id"],  # type: ignore[arg-type]
            session_id=document["session_id"],  # type: ignore[arg-type]
            inventory_digest=document["inventory_digest"],  # type: ignore[arg-type]
        )
    raise MaintenanceTokenDenied()


@dataclass(frozen=True, slots=True)
class AuthorizedRepositoryRead:
    project_id: str
    repository_name: str
    authority_id: str
    expires_at: datetime


class MaintenanceAuthority(Protocol):
    def authorize(
        self,
        request: MaintenanceRequest,
        *,
        workload_id: str,
        checked_at: datetime,
    ) -> AuthorizedRepositoryRead: ...


class ReconciliationMaintenanceAuthority:
    def __init__(
        self,
        quotas: QuotaStore,
        repositories: RepositoryStore,
    ) -> None:
        self._quotas = quotas
        self._repositories = repositories

    def authorize(
        self,
        request: MaintenanceRequest,
        *,
        workload_id: str,
        checked_at: datetime,
    ) -> AuthorizedRepositoryRead:
        if not isinstance(request, ReconciliationTokenRequest):
            raise MaintenanceAuthorityDenied()
        try:
            authority = self._quotas.authorize_reconciliation_read(
                reservation_id=request.reservation_id,
                repository_id=request.repository_id,
                claim_token=request.claim_token,
                expected_version=request.expected_version,
                worker_id=workload_id,
                checked_at=checked_at,
            )
        except ReconciliationReadNotAuthorized:
            raise MaintenanceAuthorityDenied() from None
        repository = self._repositories.get(
            authority.project_id,
            authority.repository_id,
        )
        if repository is None:
            raise MaintenanceAuthorityDenied()
        return AuthorizedRepositoryRead(
            project_id=repository.project_id,
            repository_name=repository.name,
            authority_id=authority.reservation_id,
            expires_at=authority.expires_at,
        )


@dataclass(frozen=True, slots=True)
class _IssuancePrincipal:
    user_id: str
    expires_at: datetime


class MaintenanceTokenBroker:
    def __init__(
        self,
        *,
        policy: MaintenancePolicy,
        authority: MaintenanceAuthority,
        issuer: TokenIssuer,
        clock: Clock | None = None,
    ) -> None:
        self._policy = policy
        self._authority = authority
        self._issuer = issuer
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(
        self,
        principal: MaintenancePrincipal,
        request: MaintenanceRequest,
    ) -> IssuedToken:
        try:
            checked_at = self._clock()
            if checked_at.tzinfo is None or checked_at.utcoffset() is None:
                raise MaintenanceTokenUnavailable()
            checked_at = checked_at.astimezone(UTC)
            self._policy.authorize(principal, checked_at=checked_at)
            authority = self._authority.authorize(
                request,
                workload_id=principal.workload_id,
                checked_at=checked_at,
            )
            if (
                authority.expires_at.tzinfo is None
                or authority.expires_at.utcoffset() is None
                or authority.expires_at <= checked_at
            ):
                raise MaintenanceAuthorityDenied()
            canonical_repository = (
                f"p/{authority.project_id}/{authority.repository_name}"
            )
            route = REPOSITORY_NAME.fullmatch(canonical_repository)
            if (
                route is None
                or route.group("project_id") != authority.project_id
            ):
                raise MaintenanceAuthorityDenied()
            subject = _IssuancePrincipal(
                user_id=principal.user_id,
                expires_at=min(
                    principal.expires_at.astimezone(UTC),
                    authority.expires_at.astimezone(UTC),
                ),
            )
            return self._issuer.issue(
                subject,
                (
                    AccessGrant(
                        type="repository",
                        name=canonical_repository,
                        actions=("pull",),
                    ),
                ),
            )
        except MaintenanceTokenDenied:
            raise
        except MaintenanceTokenUnavailable:
            raise
        except (MaintenanceAuthorityDenied, CredentialExpiresTooSoon, ValueError):
            raise MaintenanceTokenDenied() from None
        except Exception:
            raise MaintenanceTokenUnavailable() from None


class MaintenanceTokenResource:
    def __init__(self, broker: MaintenanceTokenBroker) -> None:
        self._broker = broker

    @staticmethod
    def _prepare_response(resp: falcon.Response, request_id: str) -> None:
        resp.set_header("X-Openstack-Request-Id", request_id)
        resp.set_header("Cache-Control", "no-store")
        resp.set_header("Pragma", "no-cache")

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        request_id = f"req-{uuid.uuid4()}"
        self._prepare_response(resp, request_id)
        req.env.pop("HTTP_AUTHORIZATION", None)
        req.env.pop("HTTP_X_AUTH_TOKEN", None)
        try:
            principal = MaintenancePrincipal.from_environ(req.env)
            document = req.get_media()
            request = parse_maintenance_token_request(document)
            issued = self._broker.issue(principal, request)
        except MaintenanceTokenDenied:
            LOG.info(
                "Maintenance token decision request_id=%s result=denied",
                request_id,
            )
            resp.status = falcon.HTTP_403
            resp.media = {"title": "Maintenance token denied"}
            return
        except MaintenanceTokenUnavailable:
            LOG.warning(
                "Maintenance token decision request_id=%s result=unavailable",
                request_id,
            )
            resp.status = falcon.HTTP_503
            resp.media = {"title": "Maintenance token service unavailable"}
            return
        except Exception:
            LOG.info(
                "Maintenance token decision request_id=%s result=invalid_request",
                request_id,
            )
            resp.status = falcon.HTTP_400
            resp.media = {"title": "Invalid maintenance token request"}
            return

        LOG.info(
            "Maintenance token decision request_id=%s jti=%s "
            "application_credential_id=%s user_id=%s audit_ids=%s "
            "authority_type=%s result=issued",
            request_id,
            issued.jti,
            principal.application_credential_id,
            principal.user_id,
            list(principal.audit_ids),
            type(request).__name__,
        )
        resp.media = issued.response()
