from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

import coffer.quota as quota
from coffer.quota import (
    Descriptor,
    QuotaNotConfigured,
    QuotaStore,
    StaleReconciliationClaim,
)


PROJECT = "11111111-1111-4111-8111-111111111111"
NOW = datetime.now(UTC) + timedelta(days=1)


def digest(index: int) -> str:
    return f"sha256:{index:064x}"


def make_store(tmp_path: Path, *, limit: int = 10_000) -> QuotaStore:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'control-evidence.sqlite'}",
        bootstrap_schema=True,
    )
    store.set_limit(PROJECT, limit)
    return store


def reserve(
    store: QuotaStore,
    index: int,
    *,
    size: int = 10,
) -> quota.Reservation:
    return store.reserve(
        project_id=PROJECT,
        repository_id=f"22222222-2222-4222-8222-{index:012d}",
        manifest_digest=digest(index),
        request_id=f"control-evidence-{index}",
        descriptors=(Descriptor(digest(index), size),),
    )


def claim(
    store: QuotaStore,
    *,
    observed_at: datetime = NOW,
) -> quota.ReconciliationClaim:
    return store.claim_reconciliation_candidates(
        worker_id="worker-a",
        claimed_at=observed_at,
        lease_for=timedelta(minutes=1),
        stale_before=observed_at,
        limit=1,
    ).claims[0]


def test_empty_snapshot_is_identity_free_and_invariant(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    snapshot = store.control_evidence_snapshot(
        PROJECT,
        observed_at=NOW,
    )

    assert asdict(snapshot) == {
        "active_claims": 0,
        "claim_invariant_violations": 0,
        "descriptor_invariant_violations": 0,
        "eligible_active_claims": 0,
        "expected_reserved_bytes": 0,
        "expected_used_bytes": 0,
        "limit_bytes": 10_000,
        "mismatched_pending_deltas": 0,
        "pending_reservations": 0,
        "reserved_bytes": 0,
        "stale_claims": 0,
        "used_bytes": 0,
    }
    assert snapshot.quota_invariant
    assert snapshot.claims_exact
    serialized = repr(asdict(snapshot))
    assert PROJECT not in serialized
    assert "project_id" not in serialized
    assert "reservation_id" not in serialized
    assert "claim_token" not in serialized


def test_snapshot_recomputes_committed_pending_and_active_claims(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    committed = reserve(store, 1, size=10)
    store.commit(committed.id)
    reserve(store, 2, size=20)
    current_claim = claim(store)

    snapshot = store.control_evidence_snapshot(
        PROJECT,
        observed_at=NOW + timedelta(seconds=30),
    )

    assert snapshot.used_bytes == 10
    assert snapshot.expected_used_bytes == 10
    assert snapshot.reserved_bytes == 20
    assert snapshot.expected_reserved_bytes == 20
    assert snapshot.pending_reservations == 1
    assert snapshot.mismatched_pending_deltas == 0
    assert snapshot.descriptor_invariant_violations == 0
    assert snapshot.active_claims == 1
    assert snapshot.eligible_active_claims == 1
    assert snapshot.stale_claims == 0
    assert snapshot.claim_invariant_violations == 0
    assert snapshot.quota_invariant
    assert snapshot.claims_exact
    assert current_claim.version > 0


def test_snapshot_reports_expired_claim_without_making_it_active(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    reserve(store, 1)
    claim(store)

    snapshot = store.control_evidence_snapshot(
        PROJECT,
        observed_at=NOW + timedelta(minutes=2),
    )

    assert snapshot.active_claims == 0
    assert snapshot.eligible_active_claims == 0
    assert snapshot.stale_claims == 1
    assert snapshot.claim_invariant_violations == 0
    assert snapshot.claims_exact


@pytest.mark.parametrize(
    "drift",
    (
        "used",
        "reserved",
        "delta",
        "descriptor-size",
        "missing-descriptor",
        "over-limit",
    ),
)
def test_snapshot_preserves_quota_invariant_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    store = make_store(tmp_path, limit=100)
    committed = reserve(store, 1, size=10)
    store.commit(committed.id)
    pending = reserve(store, 2, size=20)
    with store._engine.begin() as connection:
        if drift == "used":
            connection.execute(
                update(quota.project_quotas)
                .where(quota.project_quotas.c.project_id == PROJECT)
                .values(used_bytes=11)
            )
        elif drift == "reserved":
            connection.execute(
                update(quota.project_quotas)
                .where(quota.project_quotas.c.project_id == PROJECT)
                .values(reserved_bytes=21)
            )
        elif drift == "delta":
            connection.execute(
                update(quota.quota_reservations)
                .where(quota.quota_reservations.c.id == pending.id)
                .values(delta_bytes=19)
            )
        elif drift == "descriptor-size":
            connection.execute(
                update(quota.quota_reservation_descriptors)
                .where(
                    quota.quota_reservation_descriptors.c.reservation_id
                    == pending.id
                )
                .values(digest=digest(1), size=11)
            )
        elif drift == "missing-descriptor":
            connection.execute(
                quota.quota_reservation_descriptors.delete().where(
                    quota.quota_reservation_descriptors.c.reservation_id
                    == pending.id
                )
            )
        else:
            connection.execute(
                update(quota.project_quotas)
                .where(quota.project_quotas.c.project_id == PROJECT)
                .values(limit_bytes=29)
            )

    snapshot = store.control_evidence_snapshot(
        PROJECT,
        observed_at=NOW,
    )

    assert not snapshot.quota_invariant
    if drift == "delta":
        assert snapshot.mismatched_pending_deltas == 1
    if drift in {"descriptor-size", "missing-descriptor"}:
        assert snapshot.descriptor_invariant_violations == 1


@pytest.mark.parametrize("drift", ("version", "state"))
def test_snapshot_detects_active_claim_invariant_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    store = make_store(tmp_path)
    reservation = reserve(store, 1)
    current_claim = claim(store)
    with store._engine.begin() as connection:
        values = (
            {"version": quota.quota_reservations.c.version + 1}
            if drift == "version"
            else {"state": "released"}
        )
        connection.execute(
            update(quota.quota_reservations)
            .where(quota.quota_reservations.c.id == reservation.id)
            .values(**values)
        )

    snapshot = store.control_evidence_snapshot(
        PROJECT,
        observed_at=NOW + timedelta(seconds=30),
    )

    assert snapshot.active_claims == 1
    assert snapshot.eligible_active_claims == 0
    assert snapshot.claim_invariant_violations == 1
    assert not snapshot.claims_exact
    assert current_claim.version > 0


def test_claim_version_binding_is_enforced_by_mutation_path(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    reservation = reserve(store, 1)
    current_claim = claim(store)
    with store._engine.begin() as connection:
        connection.execute(
            update(quota.quota_reconciliation_claims)
            .where(
                quota.quota_reconciliation_claims.c.reservation_id
                == reservation.id
            )
            .values(reservation_version=current_claim.version + 1)
        )

    with pytest.raises(StaleReconciliationClaim):
        store.reconcile_present(
            reservation.id,
            expected_version=current_claim.version,
            expected_claim_token=current_claim.claim_token,
            claim_checked_at=NOW + timedelta(seconds=1),
        )
    assert store.get_reservation(reservation.id).state == "pending"


def test_claim_token_requires_an_expected_reservation_version(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    reservation = reserve(store, 1)
    current_claim = claim(store)

    with pytest.raises(ValueError, match="version is required"):
        store.reconcile_present(
            reservation.id,
            expected_claim_token=current_claim.claim_token,
            claim_checked_at=NOW + timedelta(seconds=1),
        )
    assert store.get_reservation(reservation.id).state == "pending"


def test_snapshot_does_not_repair_or_mutate_drift(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    pending = reserve(store, 1, size=10)
    with store._engine.begin() as connection:
        connection.execute(
            update(quota.project_quotas)
            .where(quota.project_quotas.c.project_id == PROJECT)
            .values(reserved_bytes=9)
        )
        connection.execute(
            update(quota.quota_reservations)
            .where(quota.quota_reservations.c.id == pending.id)
            .values(delta_bytes=8)
        )
    before_quota = store.usage(PROJECT)
    before_reservation = store.get_reservation(pending.id)

    first = store.control_evidence_snapshot(PROJECT, observed_at=NOW)
    second = store.control_evidence_snapshot(PROJECT, observed_at=NOW)

    assert first == second
    assert not first.quota_invariant
    assert store.usage(PROJECT) == before_quota
    assert store.get_reservation(pending.id) == before_reservation


@pytest.mark.parametrize(
    ("project_id", "observed_at", "message"),
    (
        ("", NOW, "project"),
        (" project-a", NOW, "project"),
        ("project-a", datetime(2026, 7, 26), "timezone-aware"),
    ),
)
def test_snapshot_rejects_invalid_authority_and_time(
    tmp_path: Path,
    project_id: str,
    observed_at: datetime,
    message: str,
) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match=message):
        store.control_evidence_snapshot(
            project_id,
            observed_at=observed_at,
        )


def test_snapshot_requires_an_existing_project_quota(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    with pytest.raises(QuotaNotConfigured):
        store.control_evidence_snapshot(
            "33333333-3333-4333-8333-333333333333",
            observed_at=NOW,
        )


@pytest.mark.parametrize(
    ("bound", "message"),
    (
        ("pending", "pending reservation"),
        ("descriptors", "committed descriptor"),
        ("claims", "claim bound"),
    ),
)
def test_snapshot_refuses_unbounded_sql_sets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
    message: str,
) -> None:
    store = make_store(tmp_path)
    first = reserve(store, 1)
    second = reserve(store, 2)
    if bound == "pending":
        monkeypatch.setattr(quota, "MAX_CONTROL_EVIDENCE_PENDING", 1)
    elif bound == "descriptors":
        store.commit(first.id)
        store.commit(second.id)
        monkeypatch.setattr(
            quota,
            "MAX_CONTROL_EVIDENCE_DESCRIPTOR_ROWS",
            1,
        )
    else:
        store.claim_reconciliation_candidates(
            worker_id="worker-a",
            claimed_at=NOW,
            lease_for=timedelta(minutes=1),
            stale_before=NOW,
            limit=2,
        )
        monkeypatch.setattr(quota, "MAX_CONTROL_EVIDENCE_CLAIMS", 1)

    with pytest.raises(ValueError, match=message):
        store.control_evidence_snapshot(PROJECT, observed_at=NOW)
