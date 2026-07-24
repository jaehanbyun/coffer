from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import threading

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, insert, select, text, update
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from coffer.db import (
    RepositorySchemaNotReady,
    RepositoryStore,
    metadata as repository_metadata,
    repositories,
)
from coffer.inventory import (
    INVENTORY_SCHEMA,
    PINNED_DISTRIBUTION_VERSION,
    PINNED_ENUMERATOR,
)
from coffer.quota import (
    Descriptor,
    OCI_IMAGE_INDEX,
    OCI_IMAGE_MANIFEST,
    QuotaExceeded,
    QuotaSchemaNotReady,
    QuotaStore,
    ReconciliationClaimPage,
    Reservation,
    StaleReconciliationClaim,
    project_quotas,
    quota_descriptors,
    quota_inventory_imports,
    quota_manifests,
    quota_reservation_descriptors,
    quota_reservations,
)
from coffer.quota_import import (
    InventoryArtifact,
    InventoryImportConflict,
    InventoryImportFailed,
    import_inventory,
    parse_inventory_artifact,
)
from coffer.quota_import_verification import (
    InventoryVerificationFailed,
    verify_inventory_import,
)


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
INVALID_PROJECT_ID = "33333333-3333-4333-8333-333333333333"
REPOSITORY_IDS = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
)
CLAIM_PROJECT_ID = "44444444-4444-4444-8444-444444444444"
CLAIM_REPOSITORY_IDS = (
    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
)
ABANDONED_PROJECT_ID = "55555555-5555-4555-8555-555555555555"
ABANDONED_REPOSITORY_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
LEGACY_PROJECT_ID = "66666666-6666-4666-8666-666666666666"
LEGACY_REPOSITORY_ID = "99999999-9999-4999-8999-999999999999"
IMPORT_PROJECT_ID = "77777777-7777-4777-8777-777777777777"
IMPORT_REPOSITORY_ID = "88888888-8888-4888-8888-888888888888"


def digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def database_url(args: argparse.Namespace, password: str) -> URL:
    if args.engine == "postgresql":
        return URL.create(
            "postgresql+psycopg",
            username="coffer",
            password=password,
            host="127.0.0.1",
            port=args.port,
            database="coffer",
            query={"connect_timeout": "10"},
        )
    return URL.create(
        "mysql+pymysql",
        username="coffer",
        password=password,
        host="127.0.0.1",
        port=args.port,
        database="coffer",
        query={"charset": "utf8mb4", "connect_timeout": "10"},
    )


def migration_config(repository_root: Path, url: URL) -> Config:
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option(
        "script_location", str(repository_root / "src/coffer/migrations")
    )
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    return config


def backend_connection_ids(stores: tuple[QuotaStore, QuotaStore]) -> tuple[int, int]:
    statement = (
        text("SELECT pg_backend_pid()")
        if stores[0]._engine.dialect.name == "postgresql"
        else text("SELECT CONNECTION_ID()")
    )
    with stores[0]._engine.connect() as first, stores[1]._engine.connect() as second:
        return first.execute(statement).scalar_one(), second.execute(statement).scalar_one()


def claim_then_exit(
    database_connection: str,
    claimed_at: datetime,
    send_connection: Connection,
) -> None:
    store = QuotaStore(database_connection)
    try:
        page = store.claim_reconciliation_candidates(
            worker_id="abandoned-process",
            claimed_at=claimed_at,
            lease_for=timedelta(minutes=1),
            stale_before=claimed_at,
            limit=1,
        )
        if len(page.claims) != 1:
            raise AssertionError("the disposable process did not acquire one claim")
        claim = page.claims[0]
        send_connection.send(
            (claim.reservation_id, claim.claim_token, claim.version)
        )
    finally:
        store._engine.dispose()
        send_connection.close()
    os._exit(17)


def exercise_concurrency(
    engine_name: str, stores: tuple[QuotaStore, QuotaStore]
) -> dict[str, object]:
    shared = Descriptor(digest(f"{engine_name}-shared"), 100)
    manifests = (
        Descriptor(digest(f"{engine_name}-manifest-a"), 50),
        Descriptor(digest(f"{engine_name}-manifest-b"), 50),
    )
    stores[0].set_limit(PROJECT_ID, 150)
    barrier = threading.Barrier(2)

    def attempt(index: int) -> tuple[str, object | None]:
        barrier.wait(timeout=10)
        try:
            reservation = stores[index].reserve(
                project_id=PROJECT_ID,
                repository_id=REPOSITORY_IDS[index],
                manifest_digest=manifests[index].digest,
                request_id=f"req-{engine_name}-{index}",
                descriptors=(manifests[index], shared),
            )
        except QuotaExceeded:
            return "denied", None
        return "admitted", reservation

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(attempt, range(2)))
    admitted = [index for index, result in enumerate(results) if result[0] == "admitted"]
    denied = [index for index, result in enumerate(results) if result[0] == "denied"]
    if len(admitted) != 1 or len(denied) != 1:
        raise AssertionError(f"expected one admitted and one denied, got {results!r}")

    winner = admitted[0]
    loser = denied[0]
    reservation = results[winner][1]
    assert reservation is not None
    retry = stores[1 - winner].reserve(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_IDS[winner],
        manifest_digest=manifests[winner].digest,
        request_id=f"req-{engine_name}-{winner}",
        descriptors=(manifests[winner], shared),
    )
    assert retry.id == reservation.id
    committed = stores[1 - winner].commit(reservation.id)
    assert stores[winner].commit(reservation.id).id == committed.id
    assert stores[0].usage(PROJECT_ID).used_bytes == 150
    assert stores[1].usage(PROJECT_ID).reserved_bytes == 0

    released = stores[0].reconcile_absent(reservation.id)
    assert released.state == "released"
    assert stores[1].reconcile_absent(reservation.id).state == "released"
    assert stores[0].usage(PROJECT_ID).used_bytes == 0

    loser_reservation = stores[loser].reserve(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_IDS[loser],
        manifest_digest=manifests[loser].digest,
        request_id=f"req-{engine_name}-loser",
        descriptors=(manifests[loser], shared),
    )
    assert stores[winner].mark_release_pending(loser_reservation.id).state == (
        "release_pending"
    )
    resurrected = stores[loser].reserve(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_IDS[loser],
        manifest_digest=manifests[loser].digest,
        request_id=f"req-{engine_name}-retry",
        descriptors=(manifests[loser], shared),
    )
    assert resurrected.id == loser_reservation.id
    assert resurrected.state == "pending"
    assert stores[winner].mark_release_pending(resurrected.id).state == (
        "release_pending"
    )
    assert stores[loser].reconcile_absent(resurrected.id).state == "released"
    final_usage = stores[0].usage(PROJECT_ID)
    assert final_usage.used_bytes == 0
    assert final_usage.reserved_bytes == 0
    return {
        "admitted": 1,
        "denied": 1,
        "final_reserved_bytes": final_usage.reserved_bytes,
        "final_used_bytes": final_usage.used_bytes,
        "retry_idempotent": True,
    }


def exercise_reconciliation_claims(
    database_connection: str,
    stores: tuple[QuotaStore, QuotaStore],
) -> dict[str, object]:
    stores[0].set_limit(CLAIM_PROJECT_ID, 1000)
    reservations: list[Reservation] = []
    for index, repository_id in enumerate(CLAIM_REPOSITORY_IDS):
        manifest = Descriptor(digest(f"claim-manifest-{index}"), 10)
        reservations.append(
            stores[0].reserve(
                project_id=CLAIM_PROJECT_ID,
                repository_id=repository_id,
                manifest_digest=manifest.digest,
                request_id=f"claim-request-{index}",
                descriptors=(manifest,),
            )
        )
    claimed_at = datetime.now(UTC)
    barrier = threading.Barrier(2)

    def acquire(index: int) -> ReconciliationClaimPage:
        barrier.wait(timeout=10)
        return stores[index].claim_reconciliation_candidates(
            worker_id=f"database-worker-{index}",
            claimed_at=claimed_at,
            lease_for=timedelta(minutes=1),
            stale_before=claimed_at,
            limit=2,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        pages = tuple(executor.map(acquire, range(2)))
    claims = list(pages[0].claims + pages[1].claims)
    first_ids = {claim.reservation_id for claim in pages[0].claims}
    second_ids = {claim.reservation_id for claim in pages[1].claims}
    assert not first_ids & second_ids
    expected_ids = {reservation.id for reservation in reservations}
    covered_ids = first_ids | second_ids
    contention_retry_required = covered_ids != expected_ids
    if contention_retry_required:
        retry_index = min(range(2), key=lambda index: len(pages[index].claims))
        retry = stores[retry_index].claim_reconciliation_candidates(
            worker_id=f"database-worker-{retry_index}-retry",
            claimed_at=claimed_at,
            lease_for=timedelta(minutes=1),
            stale_before=claimed_at,
            limit=2,
        )
        retry_ids = {claim.reservation_id for claim in retry.claims}
        assert not covered_ids & retry_ids
        claims.extend(retry.claims)
        covered_ids |= retry_ids
    assert covered_ids == expected_ids
    assert len({claim.claim_token for claim in claims}) == len(reservations)
    assert not stores[0].claim_reconciliation_candidates(
        worker_id="blocked-worker",
        claimed_at=claimed_at,
        lease_for=timedelta(minutes=1),
        stale_before=claimed_at,
        limit=3,
    ).claims
    for claim in claims:
        assert stores[0].release_reconciliation_claim(claim.claim_token)
        assert stores[0].reconcile_absent(claim.reservation_id).state == "released"
    assert stores[0].usage(CLAIM_PROJECT_ID).reserved_bytes == 0

    stores[0].set_limit(ABANDONED_PROJECT_ID, 1000)
    abandoned_manifest = Descriptor(digest("abandoned-manifest"), 10)
    abandoned = stores[0].reserve(
        project_id=ABANDONED_PROJECT_ID,
        repository_id=ABANDONED_REPOSITORY_ID,
        manifest_digest=abandoned_manifest.digest,
        request_id="abandoned-request",
        descriptors=(abandoned_manifest,),
    )
    process_claimed_at = datetime.now(UTC)
    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=claim_then_exit,
        args=(database_connection, process_claimed_at, send_connection),
    )
    process.start()
    send_connection.close()
    if not receive_connection.poll(20):
        process.terminate()
        process.join(timeout=10)
        raise AssertionError("the disposable claimant process did not respond")
    reservation_id, abandoned_token, abandoned_version = receive_connection.recv()
    receive_connection.close()
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=10)
        raise AssertionError("the disposable claimant process did not exit")
    assert process.exitcode == 17
    assert reservation_id == abandoned.id
    assert stores[0].get_reservation(abandoned.id).state == "pending"
    assert stores[0].usage(ABANDONED_PROJECT_ID).reserved_bytes == 10
    assert not stores[1].claim_reconciliation_candidates(
        worker_id="recovery-worker",
        claimed_at=process_claimed_at + timedelta(seconds=30),
        lease_for=timedelta(minutes=1),
        stale_before=process_claimed_at + timedelta(seconds=30),
        limit=1,
    ).claims

    recovered_at = process_claimed_at + timedelta(seconds=61)
    recovered = stores[1].claim_reconciliation_candidates(
        worker_id="recovery-worker",
        claimed_at=recovered_at,
        lease_for=timedelta(minutes=1),
        stale_before=recovered_at,
        limit=1,
    ).claims
    assert len(recovered) == 1
    assert recovered[0].reservation_id == abandoned.id
    assert recovered[0].claim_token != abandoned_token
    try:
        stores[0].reconcile_present(
            abandoned.id,
            expected_version=abandoned_version,
            expected_claim_token=abandoned_token,
            claim_checked_at=recovered_at,
        )
    except StaleReconciliationClaim:
        pass
    else:
        raise AssertionError("the abandoned claim token was accepted")
    released = stores[1].reconcile_absent(
        abandoned.id,
        expected_version=recovered[0].version,
        expected_claim_token=recovered[0].claim_token,
        claim_checked_at=recovered_at,
    )
    assert released.state == "released"
    assert stores[0].usage(ABANDONED_PROJECT_ID).reserved_bytes == 0
    return {
        "abandoned_process_exit": process.exitcode,
        "claim_batches_disjoint": True,
        "contention_retry_required": contention_retry_required,
        "expired_claim_recovered": True,
        "stale_token_fenced": True,
    }


def assert_database_constraint(url: URL) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(project_quotas).values(
                    project_id=INVALID_PROJECT_ID,
                    limit_bytes=-1,
                    used_bytes=0,
                    reserved_bytes=0,
                    updated_at=datetime.now(UTC),
                )
            )
    except DBAPIError:
        return
    finally:
        engine.dispose()
    raise AssertionError("the migrated database accepted a negative quota limit")


def inventory_artifact() -> tuple[InventoryArtifact, str]:
    child_digest = f"sha256:{'1' * 64}"
    index_digest = f"sha256:{'2' * 64}"
    config_digest = f"sha256:{'3' * 64}"
    layer_digest = f"sha256:{'4' * 64}"
    descriptors = [
        {
            "digest": child_digest,
            "media_type": OCI_IMAGE_MANIFEST,
            "size": 101,
        },
        {
            "digest": index_digest,
            "media_type": OCI_IMAGE_INDEX,
            "size": 79,
        },
        {
            "digest": config_digest,
            "media_type": "application/vnd.oci.image.config.v1+json",
            "size": 17,
        },
        {
            "digest": layer_digest,
            "media_type": "application/vnd.oci.image.layer.v1.tar+gzip",
            "size": 23,
        },
    ]
    descriptors.sort(key=lambda value: value["digest"])
    value = {
        "projects": [
            {
                "descriptor_count": 4,
                "descriptors": descriptors,
                "logical_bytes": 220,
                "project_id": IMPORT_PROJECT_ID,
            }
        ],
        "repositories": [
            {
                "manifests": [
                    {
                        "digest": child_digest,
                        "media_type": OCI_IMAGE_MANIFEST,
                        "references": [
                            {
                                "digest": config_digest,
                                "media_type": (
                                    "application/vnd.oci.image.config.v1+json"
                                ),
                                "size": 17,
                            },
                            {
                                "digest": layer_digest,
                                "media_type": (
                                    "application/vnd.oci.image.layer.v1.tar+gzip"
                                ),
                                "size": 23,
                            },
                        ],
                        "size": 101,
                    },
                    {
                        "digest": index_digest,
                        "media_type": OCI_IMAGE_INDEX,
                        "references": [
                            {
                                "digest": child_digest,
                                "media_type": OCI_IMAGE_MANIFEST,
                                "size": 101,
                            }
                        ],
                        "size": 79,
                    },
                ],
                "project_id": IMPORT_PROJECT_ID,
                "repository_id": IMPORT_REPOSITORY_ID,
            }
        ],
        "schema": INVENTORY_SCHEMA,
        "source": {
            "distribution_version": PINNED_DISTRIBUTION_VERSION,
            "enumerator": PINNED_ENUMERATOR,
            "snapshot_scans": 2,
        },
        "summary": {
            "descriptor_count": 4,
            "logical_bytes": 220,
            "manifest_count": 2,
            "project_count": 1,
            "repository_count": 1,
        },
    }
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    artifact_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    return (
        parse_inventory_artifact(value, artifact_digest=artifact_digest),
        index_digest,
    )


def table_count(connection: object, table: object) -> int:
    return connection.execute(  # type: ignore[attr-defined]
        select(func.count()).select_from(table)  # type: ignore[arg-type]
    ).scalar_one()


def exercise_inventory_import(
    stores: tuple[QuotaStore, QuotaStore],
) -> dict[str, object]:
    artifact, failing_digest = inventory_artifact()
    with stores[0]._engine.begin() as connection:
        connection.execute(
            insert(repositories).values(
                id=IMPORT_REPOSITORY_ID,
                project_id=IMPORT_PROJECT_ID,
                name="inventory-import",
                immutable_tags=False,
                created_at=datetime.now(UTC),
            )
        )
    stores[0].set_limit(IMPORT_PROJECT_ID, 10)

    constraint_name = "ck_poc_inventory_forced_failure"
    with stores[0]._engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE quota_reservations ADD CONSTRAINT "
            f"{constraint_name} CHECK (manifest_digest <> '{failing_digest}')"
        )
    try:
        try:
            import_inventory(stores[0], artifact)
        except InventoryImportFailed:
            pass
        else:
            raise AssertionError("the forced shared-SQL import failure was accepted")
        with stores[0]._engine.connect() as connection:
            for table in (
                quota_inventory_imports,
                quota_reservations,
                quota_reservation_descriptors,
                quota_manifests,
                quota_descriptors,
            ):
                assert table_count(connection, table) == 0
        usage = stores[0].usage(IMPORT_PROJECT_ID)
        assert (usage.used_bytes, usage.reserved_bytes) == (0, 0)
    finally:
        with stores[0]._engine.begin() as connection:
            connection.exec_driver_sql(
                f"ALTER TABLE quota_reservations DROP CONSTRAINT {constraint_name}"
            )

    barrier = threading.Barrier(2)

    def run(index: int) -> str:
        barrier.wait(timeout=10)
        return import_inventory(stores[index], artifact).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(run, range(2)))
    assert statuses == ["already_imported", "imported"]
    replay = import_inventory(stores[0], artifact)
    assert replay.status == "already_imported"
    assert replay.over_limit_project_count == 1
    usage = stores[1].usage(IMPORT_PROJECT_ID)
    assert (usage.limit_bytes, usage.used_bytes, usage.reserved_bytes) == (10, 220, 0)
    with stores[0]._engine.connect() as connection:
        assert table_count(connection, quota_inventory_imports) == 1
        assert table_count(connection, quota_reservations) == 2
        assert table_count(connection, quota_reservation_descriptors) == 5
        assert table_count(connection, quota_manifests) == 2
        assert table_count(connection, quota_descriptors) == 4

    verification = verify_inventory_import(stores[0], artifact)
    assert verification.status == "verified"
    assert verification.reservation_descriptor_count == 5
    assert verification.over_limit_project_count == 1
    with stores[0]._engine.begin() as connection:
        connection.execute(
            update(quota_manifests)
            .where(quota_manifests.c.digest == failing_digest)
            .values(state="released")
        )
    try:
        verify_inventory_import(stores[1], artifact)
    except InventoryVerificationFailed:
        pass
    else:
        raise AssertionError("post-import manifest drift passed verification")
    with stores[0]._engine.begin() as connection:
        connection.execute(
            update(quota_manifests)
            .where(quota_manifests.c.digest == failing_digest)
            .values(state="committed")
        )
    assert verify_inventory_import(stores[1], artifact).status == "verified"

    different = replace(artifact, digest=f"sha256:{'9' * 64}")
    try:
        import_inventory(stores[1], different)
    except InventoryImportConflict:
        pass
    else:
        raise AssertionError("a different baseline replaced the committed import")
    return {
        "atomic_failure_rollback": True,
        "different_baseline_rejected": True,
        "drifted_ledger_rejected": True,
        "exact_ledger_verified": True,
        "exact_replay_noop": True,
        "one_writer": True,
        "over_limit_usage_recorded": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("postgresql", "mariadb"), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()

    password = args.password_file.read_text().strip()
    if not password:
        raise ValueError("database password file is empty")
    url = database_url(args, password)
    config = migration_config(args.repository_root, url)
    database_connection = url.render_as_string(hide_password=False)

    legacy_engine = create_engine(url)
    repository_metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            insert(repositories).values(
                id=LEGACY_REPOSITORY_ID,
                project_id=LEGACY_PROJECT_ID,
                name="legacy",
                immutable_tags=True,
                created_at=datetime.now(UTC),
            )
        )
    legacy_engine.dispose()

    try:
        QuotaStore(database_connection)
    except QuotaSchemaNotReady:
        pass
    else:
        raise AssertionError("an empty database was accepted without migration")
    try:
        RepositoryStore(database_connection)
    except RepositorySchemaNotReady:
        pass
    else:
        raise AssertionError(
            "an unversioned repository table was accepted without migration"
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    stores = (
        QuotaStore(database_connection),
        QuotaStore(database_connection),
    )
    adopted = RepositoryStore(database_connection).get(
        LEGACY_PROJECT_ID, LEGACY_REPOSITORY_ID
    )
    assert adopted is not None
    assert adopted.name == "legacy"
    assert adopted.immutable_tags
    connection_ids = backend_connection_ids(stores)
    assert connection_ids[0] != connection_ids[1]

    schema = inspect(stores[0]._engine)
    assert {
        "alembic_version",
        "project_quotas",
        "quota_descriptors",
        "quota_inventory_imports",
        "quota_manifests",
        "quota_reconciliation_claims",
        "quota_reservation_descriptors",
        "quota_reservations",
        "repositories",
    }.issubset(schema.get_table_names())
    assert {
        "ix_quota_reservations_project_state",
        "ix_quota_reservations_reconcile",
    }.issubset(
        index["name"] for index in schema.get_indexes("quota_reservations")
    )
    assert {"ix_quota_reconciliation_claims_expires"}.issubset(
        index["name"]
        for index in schema.get_indexes("quota_reconciliation_claims")
    )
    assert_database_constraint(url)
    concurrency = exercise_concurrency(args.engine, stores)
    claims = exercise_reconciliation_claims(
        database_connection, stores
    )

    version_statement = (
        text("SHOW server_version")
        if args.engine == "postgresql"
        else text("SELECT VERSION()")
    )
    with stores[0]._engine.connect() as connection:
        version = connection.execute(version_statement).scalar_one()
    for store in stores:
        store._engine.dispose()

    command.downgrade(config, "base")
    try:
        QuotaStore(database_connection)
    except QuotaSchemaNotReady:
        pass
    else:
        raise AssertionError("a downgraded database was accepted as current")
    try:
        RepositoryStore(database_connection)
    except RepositorySchemaNotReady:
        pass
    else:
        raise AssertionError(
            "a downgraded repository schema was accepted as current"
        )
    retained_engine = create_engine(url)
    with retained_engine.connect() as connection:
        assert connection.execute(
            select(repositories.c.id).where(
                repositories.c.project_id == LEGACY_PROJECT_ID,
                repositories.c.id == LEGACY_REPOSITORY_ID,
            )
        ).scalar_one() == LEGACY_REPOSITORY_ID
    retained_engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
    final_stores = (
        QuotaStore(database_connection),
        QuotaStore(database_connection),
    )
    readopted = RepositoryStore(database_connection).get(
        LEGACY_PROJECT_ID, LEGACY_REPOSITORY_ID
    )
    assert readopted is not None
    assert readopted.name == "legacy"
    inventory_import = exercise_inventory_import(
        final_stores,
    )
    for store in final_stores:
        store._engine.dispose()

    print(
        json.dumps(
            {
                "backend_connections_distinct": True,
                "concurrency": concurrency,
                "engine": args.engine,
                "inventory_import": inventory_import,
                "reconciliation_claims": claims,
                "migration_downgrade_reupgrade": True,
                "migration_repeat_upgrade": True,
                "repository_metadata_adopted": True,
                "repository_metadata_retained_on_downgrade": True,
                "server_version": str(version),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
