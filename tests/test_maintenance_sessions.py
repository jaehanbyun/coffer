from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
import pytest
from sqlalchemy import insert

from coffer.db import RepositoryStore
from coffer.maintenance_token import (
    LiveComparisonMaintenanceAuthority,
    LiveComparisonTokenRequest,
    MaintenanceAuthorityDenied,
    MaintenancePolicy,
    MaintenancePrincipal,
    MaintenanceTokenBroker,
)
from coffer.quota import (
    ComparisonSessionConflict,
    ComparisonSessionNotAuthorized,
    ComparisonSessionNotReady,
    Descriptor,
    QuotaStore,
    quota_inventory_imports,
)
from coffer.tokens import AccessGrant, TokenIssuer


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
WORKLOAD_ID = "comparison-a"
INVENTORY_DIGEST = f"sha256:{'1' * 64}"
NOW = datetime.now(UTC).replace(microsecond=0)


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _fixture(
    tmp_path: Path,
    *,
    marker: bool = True,
) -> tuple[QuotaStore, RepositoryStore, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = f"sqlite:///{tmp_path / 'comparison.sqlite'}"
    repositories = RepositoryStore(connection, bootstrap_schema=True)
    repository = repositories.create(PROJECT_ID, "baseline")
    quotas = QuotaStore(connection, bootstrap_schema=True)
    quotas.set_limit(PROJECT_ID, 10_000)
    manifest = Descriptor(_digest("manifest"), 10)
    reservation = quotas.reserve(
        project_id=PROJECT_ID,
        repository_id=repository.id,
        manifest_digest=manifest.digest,
        request_id=f"inventory:{INVENTORY_DIGEST.removeprefix('sha256:')}",
        descriptors=(manifest,),
    )
    quotas.reconcile_present(reservation.id)
    if marker:
        with quotas._writer() as connection:
            connection.execute(
                insert(quota_inventory_imports).values(
                    scope="baseline",
                    inventory_digest=INVENTORY_DIGEST,
                    project_count=1,
                    repository_count=1,
                    manifest_count=1,
                    descriptor_count=1,
                    imported_at=NOW,
                )
            )
    return quotas, repositories, repository.id


def _approve(quotas: QuotaStore, *, request_id: str = "approval-request"):
    return quotas.approve_live_comparison_session(
        request_id=request_id,
        inventory_digest=INVENTORY_DIGEST,
        workload_id=WORKLOAD_ID,
        writer_exclusion_ref="writer-exclusion-evidence-1",
        approved_at=NOW,
        lifetime=timedelta(minutes=5),
    )


def test_session_approval_is_finite_idempotent_and_secret_free(
    tmp_path: Path,
) -> None:
    quotas, _repositories, _repository_id = _fixture(tmp_path)

    first = _approve(quotas)
    replay = _approve(quotas)

    assert replay == first
    assert first.state == "approved"
    assert first.expires_at == NOW + timedelta(minutes=5)
    assert first.closed_at is None
    assert set(first.__dataclass_fields__) == {
        "id",
        "request_id",
        "inventory_digest",
        "workload_id",
        "writer_exclusion_ref",
        "state",
        "approved_at",
        "expires_at",
        "closed_at",
    }


def test_session_approval_requires_marker_and_no_active_reconciliation_claim(
    tmp_path: Path,
) -> None:
    missing_marker, _repositories, _repository_id = _fixture(
        tmp_path / "missing",
        marker=False,
    )
    with pytest.raises(ComparisonSessionNotReady):
        _approve(missing_marker)

    quotas, _repositories, _repository_id = _fixture(tmp_path / "claimed")
    claimed_at = datetime.now(UTC) + timedelta(minutes=1)
    claim = quotas.claim_reconciliation_candidates(
        worker_id="reconciler-a",
        claimed_at=claimed_at,
        lease_for=timedelta(minutes=2),
        stale_before=claimed_at,
        limit=1,
    )
    assert claim.claims
    with pytest.raises(ComparisonSessionNotReady):
        _approve(quotas)


@pytest.mark.parametrize(
    "lifetime",
    (timedelta(seconds=59), timedelta(seconds=3601)),
)
def test_session_approval_rejects_unbounded_lifetime(
    tmp_path: Path,
    lifetime: timedelta,
) -> None:
    quotas, _repositories, _repository_id = _fixture(tmp_path)

    with pytest.raises(ComparisonSessionNotReady):
        quotas.approve_live_comparison_session(
            request_id="approval-request",
            inventory_digest=INVENTORY_DIGEST,
            workload_id=WORKLOAD_ID,
            writer_exclusion_ref="writer-exclusion-evidence-1",
            approved_at=NOW,
            lifetime=lifetime,
        )


def test_request_reuse_with_different_authority_fails_closed(
    tmp_path: Path,
) -> None:
    quotas, _repositories, _repository_id = _fixture(tmp_path)
    _approve(quotas)

    with pytest.raises(ComparisonSessionConflict):
        quotas.approve_live_comparison_session(
            request_id="approval-request",
            inventory_digest=INVENTORY_DIGEST,
            workload_id="comparison-b",
            writer_exclusion_ref="writer-exclusion-evidence-1",
            approved_at=NOW,
            lifetime=timedelta(minutes=5),
        )


def test_session_completion_and_revocation_are_irreversible_and_idempotent(
    tmp_path: Path,
) -> None:
    quotas, _repositories, _repository_id = _fixture(tmp_path)
    session = _approve(quotas)
    completed = quotas.close_live_comparison_session(
        session.id,
        final_state="completed",
        closed_at=NOW + timedelta(minutes=1),
    )
    replay = quotas.close_live_comparison_session(
        session.id,
        final_state="completed",
        closed_at=NOW + timedelta(minutes=2),
    )

    assert completed.state == "completed"
    assert replay == completed
    with pytest.raises(ComparisonSessionConflict):
        quotas.close_live_comparison_session(
            session.id,
            final_state="revoked",
            closed_at=NOW + timedelta(minutes=2),
        )


def test_live_authority_resolves_imported_repository_and_session_expiry(
    tmp_path: Path,
) -> None:
    quotas, repositories, repository_id = _fixture(tmp_path)
    session = _approve(quotas)
    authority = LiveComparisonMaintenanceAuthority(quotas, repositories)
    request = LiveComparisonTokenRequest(
        repository_id=repository_id,
        session_id=session.id,
        inventory_digest=INVENTORY_DIGEST,
    )

    authorized = authority.authorize(
        request,
        workload_id=WORKLOAD_ID,
        checked_at=NOW + timedelta(seconds=1),
    )

    assert authorized.project_id == PROJECT_ID
    assert authorized.repository_name == "baseline"
    assert authorized.authority_id == session.id
    assert authorized.expires_at == session.expires_at


def test_live_session_reduces_to_one_short_lived_pull_claim(
    tmp_path: Path,
) -> None:
    quotas, repositories, repository_id = _fixture(tmp_path)
    session = _approve(quotas)
    issuer = TokenIssuer(
        private_key=rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        ),
        issuer="https://coffer.internal/auth/token",
        service="coffer-registry",
        clock=lambda: NOW,
    )
    broker = MaintenanceTokenBroker(
        policy=MaintenancePolicy(
            service_project_id="service-project",
            maintenance_user_id="maintenance-user",
            workload_ids=frozenset({WORKLOAD_ID}),
        ),
        authority=LiveComparisonMaintenanceAuthority(quotas, repositories),
        issuer=issuer,
        clock=lambda: NOW,
    )

    issued = broker.issue(
        MaintenancePrincipal(
            application_credential_id="maintenance-credential",
            user_id="maintenance-user",
            project_id="service-project",
            roles=("service", "registry_maintenance"),
            expires_at=NOW + timedelta(hours=1),
            workload_id=WORKLOAD_ID,
        ),
        LiveComparisonTokenRequest(
            repository_id=repository_id,
            session_id=session.id,
            inventory_digest=INVENTORY_DIGEST,
        ),
    )

    assert issued.expires_in == 300
    assert issued.access == (
        AccessGrant(
            "repository",
            f"p/{PROJECT_ID}/baseline",
            ("pull",),
        ),
    )


@pytest.mark.parametrize(
    "change",
    ("session", "digest", "repository", "workload", "expiry", "closed"),
)
def test_live_authority_denies_stale_or_mismatched_session(
    tmp_path: Path,
    change: str,
) -> None:
    quotas, repositories, repository_id = _fixture(tmp_path)
    session = _approve(quotas)
    request = LiveComparisonTokenRequest(
        repository_id=repository_id,
        session_id=session.id,
        inventory_digest=INVENTORY_DIGEST,
    )
    workload_id = WORKLOAD_ID
    checked_at = NOW + timedelta(seconds=1)
    if change == "session":
        request = LiveComparisonTokenRequest(
            repository_id=repository_id,
            session_id="00000000-0000-4000-8000-000000000000",
            inventory_digest=INVENTORY_DIGEST,
        )
    elif change == "digest":
        request = LiveComparisonTokenRequest(
            repository_id=repository_id,
            session_id=session.id,
            inventory_digest=f"sha256:{'2' * 64}",
        )
    elif change == "repository":
        request = LiveComparisonTokenRequest(
            repository_id="00000000-0000-4000-8000-000000000000",
            session_id=session.id,
            inventory_digest=INVENTORY_DIGEST,
        )
    elif change == "workload":
        workload_id = "comparison-b"
    elif change == "expiry":
        checked_at = NOW + timedelta(minutes=6)
    else:
        quotas.close_live_comparison_session(
            session.id,
            final_state="revoked",
            closed_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(MaintenanceAuthorityDenied) as denied:
        LiveComparisonMaintenanceAuthority(
            quotas,
            repositories,
        ).authorize(
            request,
            workload_id=workload_id,
            checked_at=checked_at,
        )

    assert str(denied.value) == "maintenance authority denied"
    assert session.id not in str(denied.value)


def test_live_authority_refuses_active_reconciliation_claim_after_approval(
    tmp_path: Path,
) -> None:
    quotas, _repositories, repository_id = _fixture(tmp_path)
    session = _approve(quotas)
    claimed_at = datetime.now(UTC) + timedelta(minutes=1)
    claim = quotas.claim_reconciliation_candidates(
        worker_id="reconciler-a",
        claimed_at=claimed_at,
        lease_for=timedelta(minutes=2),
        stale_before=claimed_at,
        limit=1,
    )
    assert claim.claims

    with pytest.raises(ComparisonSessionNotAuthorized):
        quotas.authorize_live_comparison_read(
            session_id=session.id,
            inventory_digest=INVENTORY_DIGEST,
            repository_id=repository_id,
            workload_id=WORKLOAD_ID,
            checked_at=claimed_at + timedelta(seconds=1),
        )


def test_live_authority_refuses_repository_created_after_baseline_import(
    tmp_path: Path,
) -> None:
    quotas, repositories, _repository_id = _fixture(tmp_path)
    session = _approve(quotas)
    later = repositories.create(PROJECT_ID, "later")
    manifest = Descriptor(_digest("later-manifest"), 10)
    reservation = quotas.reserve(
        project_id=PROJECT_ID,
        repository_id=later.id,
        manifest_digest=manifest.digest,
        request_id="ordinary-request",
        descriptors=(manifest,),
    )
    quotas.reconcile_present(reservation.id)

    with pytest.raises(ComparisonSessionNotAuthorized):
        quotas.authorize_live_comparison_read(
            session_id=session.id,
            inventory_digest=INVENTORY_DIGEST,
            repository_id=later.id,
            workload_id=WORKLOAD_ID,
            checked_at=NOW + timedelta(seconds=1),
        )
