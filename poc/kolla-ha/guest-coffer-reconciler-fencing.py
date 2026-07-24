from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import time

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine

from coffer.config import parse_config
from coffer.quota import (
    Descriptor,
    MAX_TRANSACTION_ATTEMPTS,
    QuotaStore,
    ReconciliationCursor,
    StaleReconciliationClaim,
    project_quotas,
    quota_descriptors,
    quota_manifests,
    quota_reconciliation_claims,
    quota_reservation_descriptors,
    quota_reservations,
)


CLAIM_PROJECT = "55555555-5555-4555-8555-555555555561"
ABANDON_PROJECT = "55555555-5555-4555-8555-555555555562"
PROJECTS = (CLAIM_PROJECT, ABANDON_PROJECT)
CLAIM_REPOSITORIES = (
    "66666666-6666-4666-8666-666666666671",
    "66666666-6666-4666-8666-666666666672",
    "66666666-6666-4666-8666-666666666673",
)
ABANDON_REPOSITORY = "66666666-6666-4666-8666-666666666674"
WORKERS = (
    "stage5-reconcile-controller-1",
    "stage5-reconcile-controller-2",
)
ZERO_RESERVATION_ID = "00000000-0000-4000-8000-000000000000"


def digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def reservation_ids() -> object:
    return select(quota_reservations.c.id).where(
        quota_reservations.c.project_id.in_(PROJECTS)
    )


def cleanup(engine: Engine) -> None:
    ids = reservation_ids()
    with engine.begin() as connection:
        connection.execute(
            delete(quota_reconciliation_claims).where(
                quota_reconciliation_claims.c.reservation_id.in_(ids)
            )
        )
        connection.execute(
            delete(quota_manifests).where(
                quota_manifests.c.project_id.in_(PROJECTS)
            )
        )
        connection.execute(
            delete(quota_reservation_descriptors).where(
                quota_reservation_descriptors.c.reservation_id.in_(ids)
            )
        )
        connection.execute(
            delete(quota_reservations).where(
                quota_reservations.c.project_id.in_(PROJECTS)
            )
        )
        connection.execute(
            delete(quota_descriptors).where(
                quota_descriptors.c.project_id.in_(PROJECTS)
            )
        )
        connection.execute(
            delete(project_quotas).where(project_quotas.c.project_id.in_(PROJECTS))
        )


def residue_count(engine: Engine) -> int:
    ids = reservation_ids()
    statements = (
        select(func.count())
        .select_from(quota_reconciliation_claims)
        .where(quota_reconciliation_claims.c.reservation_id.in_(ids)),
        select(func.count())
        .select_from(quota_manifests)
        .where(quota_manifests.c.project_id.in_(PROJECTS)),
        select(func.count())
        .select_from(quota_reservation_descriptors)
        .where(quota_reservation_descriptors.c.reservation_id.in_(ids)),
        select(func.count())
        .select_from(quota_reservations)
        .where(quota_reservations.c.project_id.in_(PROJECTS)),
        select(func.count())
        .select_from(quota_descriptors)
        .where(quota_descriptors.c.project_id.in_(PROJECTS)),
        select(func.count())
        .select_from(project_quotas)
        .where(project_quotas.c.project_id.in_(PROJECTS)),
    )
    with engine.connect() as connection:
        return sum(
            int(connection.execute(statement).scalar_one())
            for statement in statements
        )


def require_clean(engine: Engine) -> None:
    if residue_count(engine) != 0:
        raise RuntimeError("allowlisted reconciler rows are not clean")


def parse_cursor(value: str) -> ReconciliationCursor:
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("reconciliation cursor must be timezone-aware")
    return ReconciliationCursor(timestamp, ZERO_RESERVATION_ID)


def cursor_before_next_database_second() -> datetime:
    cursor = datetime.now(UTC).replace(microsecond=0)
    next_second = cursor + timedelta(seconds=1)
    while datetime.now(UTC) <= next_second:
        time.sleep(0.05)
    return cursor


def setup_claims(store: QuotaStore) -> str:
    store.set_limit(CLAIM_PROJECT, 1000)
    cursor = cursor_before_next_database_second()
    for index, repository_id in enumerate(CLAIM_REPOSITORIES):
        manifest = Descriptor(digest(f"stage5-claim-{index}"), 10)
        store.reserve(
            project_id=CLAIM_PROJECT,
            repository_id=repository_id,
            manifest_digest=manifest.digest,
            request_id=f"req-stage5-claim-{index}",
            descriptors=(manifest,),
        )
    return cursor.isoformat()


def claim(store: QuotaStore, worker_id: str, cursor: str) -> int:
    if worker_id not in WORKERS:
        raise ValueError("reconciliation worker is not allowlisted")
    now = datetime.now(UTC)
    page = store.claim_reconciliation_candidates(
        worker_id=worker_id,
        claimed_at=now,
        lease_for=timedelta(seconds=60),
        stale_before=now,
        limit=2,
        after=parse_cursor(cursor),
    )
    return len(page.claims)


def finish_claims(store: QuotaStore) -> None:
    with store._engine.connect() as connection:
        rows = tuple(
            connection.execute(
                select(
                    quota_reconciliation_claims.c.reservation_id,
                    quota_reconciliation_claims.c.claim_token,
                    quota_reconciliation_claims.c.worker_id,
                    quota_reservations.c.version,
                )
                .select_from(
                    quota_reconciliation_claims.join(
                        quota_reservations,
                        quota_reconciliation_claims.c.reservation_id
                        == quota_reservations.c.id,
                    )
                )
                .where(quota_reservations.c.project_id == CLAIM_PROJECT)
                .order_by(quota_reconciliation_claims.c.reservation_id)
            )
        )
    if len(rows) != 3:
        raise RuntimeError("reconciliation workers did not cover three rows")
    if {row.worker_id for row in rows} != set(WORKERS):
        raise RuntimeError("claims were not divided across separate workers")
    if len({row.reservation_id for row in rows}) != 3:
        raise RuntimeError("reconciliation claim batches overlapped")
    if len({row.claim_token for row in rows}) != 3:
        raise RuntimeError("reconciliation claim tokens are not unique")
    checked_at = datetime.now(UTC)
    for row in rows:
        released = store.reconcile_absent(
            row.reservation_id,
            expected_version=row.version,
            expected_claim_token=row.claim_token,
            claim_checked_at=checked_at,
        )
        if released.state != "released":
            raise RuntimeError("claimed reconciliation row was not released")
    usage = store.usage(CLAIM_PROJECT)
    if (usage.used_bytes, usage.reserved_bytes) != (0, 0):
        raise RuntimeError("claimed reconciliation quota was not restored")


def setup_abandon(store: QuotaStore) -> str:
    store.set_limit(ABANDON_PROJECT, 1000)
    cursor = cursor_before_next_database_second()
    manifest = Descriptor(digest("stage5-abandoned-claim"), 10)
    store.reserve(
        project_id=ABANDON_PROJECT,
        repository_id=ABANDON_REPOSITORY,
        manifest_digest=manifest.digest,
        request_id="req-stage5-abandoned-claim",
        descriptors=(manifest,),
    )
    return cursor.isoformat()


def abandon(store: QuotaStore, cursor: str) -> None:
    now = datetime.now(UTC)
    claims = store.claim_reconciliation_candidates(
        worker_id=WORKERS[1],
        claimed_at=now,
        lease_for=timedelta(seconds=2),
        stale_before=now,
        limit=1,
        after=parse_cursor(cursor),
    ).claims
    if len(claims) != 1:
        raise RuntimeError("abandoned worker did not acquire one claim")


def recover_fenced_claim(store: QuotaStore, cursor: str) -> None:
    with store._engine.connect() as connection:
        old = connection.execute(
            select(
                quota_reconciliation_claims.c.reservation_id,
                quota_reconciliation_claims.c.claim_token,
                quota_reconciliation_claims.c.expires_at,
                quota_reservations.c.version,
            )
            .select_from(
                quota_reconciliation_claims.join(
                    quota_reservations,
                    quota_reconciliation_claims.c.reservation_id
                    == quota_reservations.c.id,
                )
            )
            .where(
                quota_reservations.c.project_id == ABANDON_PROJECT,
                quota_reconciliation_claims.c.worker_id == WORKERS[1],
            )
        ).one()
    expires_at = old.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    remaining = (expires_at - datetime.now(UTC)).total_seconds()
    if remaining > 0:
        time.sleep(remaining + 0.5)
    recovered_at = datetime.now(UTC)
    before_expiry = expires_at - timedelta(milliseconds=1)
    blocked = store.claim_reconciliation_candidates(
        worker_id=WORKERS[0],
        claimed_at=before_expiry,
        lease_for=timedelta(seconds=60),
        stale_before=before_expiry,
        limit=1,
        after=parse_cursor(cursor),
    )
    if blocked.claims:
        raise RuntimeError("an unexpired reconciliation lease was reassigned")
    replacement = store.claim_reconciliation_candidates(
        worker_id=WORKERS[0],
        claimed_at=recovered_at,
        lease_for=timedelta(seconds=60),
        stale_before=recovered_at,
        limit=1,
        after=parse_cursor(cursor),
    ).claims
    if len(replacement) != 1:
        raise RuntimeError("expired reconciliation claim was not recovered")
    current = replacement[0]
    if current.reservation_id != old.reservation_id:
        raise RuntimeError("recovery selected an unexpected reservation")
    if current.claim_token == old.claim_token:
        raise RuntimeError("recovery reused an abandoned claim token")
    try:
        store.reconcile_present(
            old.reservation_id,
            expected_version=old.version,
            expected_claim_token=old.claim_token,
            claim_checked_at=recovered_at,
        )
    except StaleReconciliationClaim:
        pass
    else:
        raise RuntimeError("an abandoned claim token crossed the fence")
    released = store.reconcile_absent(
        current.reservation_id,
        expected_version=current.version,
        expected_claim_token=current.claim_token,
        claim_checked_at=datetime.now(UTC),
    )
    if released.state != "released":
        raise RuntimeError("the recovery worker did not release the reservation")
    usage = store.usage(ABANDON_PROJECT)
    if (usage.used_bytes, usage.reserved_bytes) != (0, 0):
        raise RuntimeError("abandoned reconciliation quota was not restored")


def connection_from_config(path: str) -> str:
    conf = parse_config(args=[], default_config_files=[path])
    connection = conf.database.connection
    if not connection or not connection.startswith("mysql+pymysql://"):
        raise RuntimeError("deployed Coffer database connection is not MySQL")
    return connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "preflight",
            "cleanup",
            "setup-claims",
            "claim",
            "finish-claims",
            "setup-abandon",
            "abandon",
            "recover",
        ),
    )
    parser.add_argument("--worker")
    parser.add_argument("--cursor")
    parser.add_argument("--config", default="/etc/coffer/coffer.conf")
    args = parser.parse_args()
    connection = connection_from_config(args.config)
    store = QuotaStore(connection)
    try:
        if MAX_TRANSACTION_ATTEMPTS != 3:
            raise RuntimeError("installed transaction retry bound is not three")
        if args.action == "preflight":
            require_clean(store._engine)
            print(
                "coffer_reconciler_fencing state=ready retry_bound=3 "
                "residue=0 mutation=none"
            )
        elif args.action == "cleanup":
            cleanup(store._engine)
            require_clean(store._engine)
            print("coffer_reconciler_fencing cleanup=passed residue=0")
        elif args.action == "setup-claims":
            require_clean(store._engine)
            cursor = setup_claims(store)
            print(
                "coffer_reconciler_fencing state=claims-ready "
                f"reservations=3 cursor={cursor}"
            )
        elif args.action == "claim":
            if args.worker is None or args.cursor is None:
                raise ValueError("claim requires worker and cursor")
            count = claim(store, args.worker, args.cursor)
            print(
                f"coffer_reconciler_worker worker={args.worker} claims={count}"
            )
        elif args.action == "finish-claims":
            finish_claims(store)
            print(
                "coffer_reconciler_fencing disjoint=passed workers=2 "
                "reservations=3 restored=yes"
            )
        elif args.action == "setup-abandon":
            cleanup(store._engine)
            require_clean(store._engine)
            cursor = setup_abandon(store)
            print(
                "coffer_reconciler_fencing state=abandon-ready "
                f"reservations=1 cursor={cursor}"
            )
        elif args.action == "abandon":
            if args.cursor is None:
                raise ValueError("abandon requires cursor")
            abandon(store, args.cursor)
            print(
                "coffer_reconciler_worker worker="
                f"{WORKERS[1]} claims=1 exit=clean"
            )
        elif args.action == "recover":
            if args.cursor is None:
                raise ValueError("recovery requires cursor")
            recover_fenced_claim(store, args.cursor)
            print(
                "coffer_reconciler_fencing lease=expired recovered=yes "
                "stale_token=fenced restored=yes"
            )
    finally:
        store._engine.dispose()


if __name__ == "__main__":
    main()
