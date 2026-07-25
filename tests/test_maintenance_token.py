from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from coffer.db import RepositoryStore
from coffer.maintenance_token import (
    AuthorizedRepositoryRead,
    LiveComparisonTokenRequest,
    MaintenanceAuthorityDenied,
    MaintenancePolicy,
    MaintenancePrincipal,
    MaintenanceTokenBroker,
    MaintenanceTokenDenied,
    MaintenanceTokenUnavailable,
    ReconciliationMaintenanceAuthority,
    ReconciliationTokenRequest,
    parse_maintenance_token_request,
)
from coffer.quota import Descriptor, QuotaStore
from coffer.tokens import TokenIssuer


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
SERVICE_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "22222222-2222-4222-8222-222222222222"
RESERVATION_ID = "33333333-3333-4333-8333-333333333333"
CLAIM_TOKEN = "44444444-4444-4444-8444-444444444444"
USER_ID = "55555555-5555-4555-8555-555555555555"
WORKER_ID = "reconciler-a"
SERVICE = "coffer-registry"


def _principal(
    *,
    project_id: str = SERVICE_PROJECT_ID,
    roles: tuple[str, ...] = ("service", "registry_maintenance"),
    workload_id: str = WORKER_ID,
    expires_at: datetime = NOW + timedelta(hours=1),
) -> MaintenancePrincipal:
    return MaintenancePrincipal(
        application_credential_id="maintenance-credential",
        user_id=USER_ID,
        project_id=project_id,
        roles=roles,
        workload_id=workload_id,
        expires_at=expires_at,
    )


def _policy() -> MaintenancePolicy:
    return MaintenancePolicy(
        service_project_id=SERVICE_PROJECT_ID,
        maintenance_user_id=USER_ID,
        workload_ids=frozenset({WORKER_ID, "comparison-job"}),
    )


def _issuer(clock=lambda: NOW) -> TokenIssuer:
    return TokenIssuer(
        private_key=rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        ),
        issuer="https://coffer.internal/auth/token",
        service=SERVICE,
        clock=clock,
    )


class FakeAuthority:
    def __init__(
        self,
        *,
        repository_name: str = "server-resolved",
        expires_at: datetime = NOW + timedelta(minutes=2),
    ) -> None:
        self.repository_name = repository_name
        self.expires_at = expires_at
        self.calls: list[tuple[object, str, datetime]] = []

    def authorize(
        self,
        request: object,
        *,
        workload_id: str,
        checked_at: datetime,
    ) -> AuthorizedRepositoryRead:
        self.calls.append((request, workload_id, checked_at))
        return AuthorizedRepositoryRead(
            project_id=TENANT_PROJECT_ID,
            repository_name=self.repository_name,
            authority_id=RESERVATION_ID,
            expires_at=self.expires_at,
        )


@pytest.mark.parametrize(
    "principal",
    (
        _principal(project_id="wrong-project"),
        MaintenancePrincipal(
            application_credential_id="maintenance-credential",
            user_id="wrong-user",
            project_id=SERVICE_PROJECT_ID,
            roles=("service", "registry_maintenance"),
            workload_id=WORKER_ID,
            expires_at=NOW + timedelta(hours=1),
        ),
        _principal(roles=("service",)),
        _principal(roles=("registry_maintenance",)),
        _principal(roles=("admin",)),
        _principal(roles=("service", "registry_maintenance", "admin")),
        _principal(workload_id="unknown-worker"),
        _principal(expires_at=NOW),
    ),
)
def test_policy_requires_exact_service_project_roles_and_workload(
    principal: MaintenancePrincipal,
) -> None:
    with pytest.raises(MaintenanceTokenDenied) as denied:
        _policy().authorize(principal, checked_at=NOW)

    assert str(denied.value) == "maintenance token request denied"


def test_broker_issues_one_server_resolved_pull_only_repository_claim() -> None:
    authority = FakeAuthority()
    issuer = _issuer()
    broker = MaintenanceTokenBroker(
        policy=_policy(),
        authority=authority,
        issuer=issuer,
        clock=lambda: NOW,
    )
    request = ReconciliationTokenRequest(
        repository_id=REPOSITORY_ID,
        reservation_id=RESERVATION_ID,
        claim_token=CLAIM_TOKEN,
        expected_version=7,
    )

    issued = broker.issue(_principal(), request)
    claims = jwt.decode(
        issued.token,
        jwt.PyJWK.from_dict(issuer.jwks()["keys"][0]).key,
        algorithms=["RS256"],
        audience=SERVICE,
        issuer="https://coffer.internal/auth/token",
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )

    assert authority.calls == [(request, WORKER_ID, NOW)]
    assert claims["sub"] == USER_ID
    assert claims["access"] == [
        {
            "type": "repository",
            "name": f"p/{TENANT_PROJECT_ID}/server-resolved",
            "actions": ["pull"],
        }
    ]
    assert "refresh_token" not in issued.response()
    assert issued.expires_in == 120


@pytest.mark.parametrize(
    "extra",
    (
        {"project_id": TENANT_PROJECT_ID},
        {"repository": f"p/{TENANT_PROJECT_ID}/caller-selected"},
        {"actions": ["push"]},
        {"audience": "caller-selected"},
        {"subject": "caller-selected"},
    ),
)
def test_request_parser_rejects_caller_selected_authority(
    extra: dict[str, object],
) -> None:
    document: dict[str, object] = {
        "mode": "reconciliation",
        "repository_id": REPOSITORY_ID,
        "reservation_id": RESERVATION_ID,
        "claim_token": CLAIM_TOKEN,
        "expected_version": 1,
        **extra,
    }

    with pytest.raises(MaintenanceTokenDenied) as denied:
        parse_maintenance_token_request(document)

    assert str(denied.value) == "maintenance token request denied"
    assert not any(str(value) in str(denied.value) for value in extra.values())


def test_live_comparison_request_is_typed_and_stale_session_denial_is_safe() -> None:
    inventory_digest = f"sha256:{'1' * 64}"
    request = parse_maintenance_token_request(
        {
            "mode": "live_comparison",
            "repository_id": REPOSITORY_ID,
            "session_id": "session-stale-secret",
            "inventory_digest": inventory_digest,
        }
    )
    assert request == LiveComparisonTokenRequest(
        repository_id=REPOSITORY_ID,
        session_id="session-stale-secret",
        inventory_digest=inventory_digest,
    )

    class StaleSessionAuthority:
        def authorize(self, *_args, **_kwargs):
            raise MaintenanceAuthorityDenied()

    broker = MaintenanceTokenBroker(
        policy=_policy(),
        authority=StaleSessionAuthority(),
        issuer=_issuer(),
        clock=lambda: NOW,
    )
    with pytest.raises(MaintenanceTokenDenied) as denied:
        broker.issue(_principal(workload_id="comparison-job"), request)

    assert str(denied.value) == "maintenance token request denied"
    assert "session-stale-secret" not in str(denied.value)


def test_unexpected_authority_failure_is_fixed_and_secret_safe() -> None:
    class BrokenAuthority:
        def authorize(self, *_args, **_kwargs):
            raise RuntimeError("credential-secret")

    broker = MaintenanceTokenBroker(
        policy=_policy(),
        authority=BrokenAuthority(),
        issuer=_issuer(),
        clock=lambda: NOW,
    )
    request = ReconciliationTokenRequest(
        repository_id=REPOSITORY_ID,
        reservation_id=RESERVATION_ID,
        claim_token=CLAIM_TOKEN,
        expected_version=1,
    )

    with pytest.raises(MaintenanceTokenUnavailable) as unavailable:
        broker.issue(_principal(), request)

    assert str(unavailable.value) == "maintenance token service unavailable"
    assert "credential-secret" not in str(unavailable.value)


def _manifest_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _reconciliation_fixture(
    tmp_path: Path,
) -> tuple[
    ReconciliationMaintenanceAuthority,
    ReconciliationTokenRequest,
    datetime,
]:
    connection = f"sqlite:///{tmp_path / 'maintenance.sqlite'}"
    repositories = RepositoryStore(connection, bootstrap_schema=True)
    repository = repositories.create(TENANT_PROJECT_ID, "current-route")
    quotas = QuotaStore(connection, bootstrap_schema=True)
    quotas.set_limit(TENANT_PROJECT_ID, 10_000)
    manifest = Descriptor(_manifest_digest("manifest"), 10)
    reservation = quotas.reserve(
        project_id=TENANT_PROJECT_ID,
        repository_id=repository.id,
        manifest_digest=manifest.digest,
        request_id="request",
        descriptors=(manifest,),
    )
    claimed_at = datetime.now(UTC) + timedelta(minutes=1)
    claim = quotas.claim_reconciliation_candidates(
        worker_id=WORKER_ID,
        claimed_at=claimed_at,
        lease_for=timedelta(minutes=2),
        stale_before=claimed_at,
        limit=1,
    ).claims[0]
    return (
        ReconciliationMaintenanceAuthority(quotas, repositories),
        ReconciliationTokenRequest(
            repository_id=repository.id,
            reservation_id=reservation.id,
            claim_token=claim.claim_token,
            expected_version=claim.version,
        ),
        claimed_at,
    )


def test_sql_authority_resolves_current_route_from_live_claim(tmp_path: Path) -> None:
    authority, request, checked_at = _reconciliation_fixture(tmp_path)

    authorized = authority.authorize(
        request,
        workload_id=WORKER_ID,
        checked_at=checked_at,
    )

    assert authorized.project_id == TENANT_PROJECT_ID
    assert authorized.repository_name == "current-route"
    assert authorized.authority_id == request.reservation_id


@pytest.mark.parametrize("change", ("claim", "version", "worker", "expiry"))
def test_sql_authority_denies_stale_or_mismatched_claim(
    tmp_path: Path,
    change: str,
) -> None:
    authority, request, checked_at = _reconciliation_fixture(tmp_path)
    workload_id = WORKER_ID
    if change == "claim":
        request = ReconciliationTokenRequest(
            repository_id=request.repository_id,
            reservation_id=request.reservation_id,
            claim_token="00000000-0000-4000-8000-000000000000",
            expected_version=request.expected_version,
        )
    elif change == "version":
        request = ReconciliationTokenRequest(
            repository_id=request.repository_id,
            reservation_id=request.reservation_id,
            claim_token=request.claim_token,
            expected_version=request.expected_version + 1,
        )
    elif change == "worker":
        workload_id = "reconciler-b"
    else:
        checked_at += timedelta(minutes=3)

    with pytest.raises(MaintenanceAuthorityDenied) as denied:
        authority.authorize(
            request,
            workload_id=workload_id,
            checked_at=checked_at,
        )

    assert str(denied.value) == "maintenance authority denied"
    assert request.claim_token not in str(denied.value)
