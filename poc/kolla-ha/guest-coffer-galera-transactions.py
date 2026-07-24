from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import logging
import threading
import time

from sqlalchemy import delete, event, func, select
from sqlalchemy.engine import Engine

from coffer.config import parse_config
from coffer.quota import (
    Descriptor,
    MAX_TRANSACTION_ATTEMPTS,
    QuotaExceeded,
    QuotaStore,
    project_quotas,
    quota_descriptors,
    quota_manifests,
    quota_reconciliation_claims,
    quota_reservation_descriptors,
    quota_reservations,
)


CONCURRENCY_PROJECT = "55555555-5555-4555-8555-555555555551"
RETRY_PROJECT = "55555555-5555-4555-8555-555555555552"
PROJECTS = (CONCURRENCY_PROJECT, RETRY_PROJECT)
REPOSITORIES = (
    "66666666-6666-4666-8666-666666666661",
    "66666666-6666-4666-8666-666666666662",
)
EXPECTED_RESULT = (
    "coffer_galera_transactions concurrency_admitted=1 "
    "concurrency_denied=1 retry_code=1205 retry_attempt=2 "
    "retry_operation=set_limit residue=0"
)


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
        raise RuntimeError("allowlisted Galera transaction rows are not clean")


def exercise_concurrency(connection: str) -> tuple[int, int]:
    stores = (QuotaStore(connection), QuotaStore(connection))
    shared = Descriptor(digest("stage5-galera-shared"), 100)
    manifests = (
        Descriptor(digest("stage5-galera-manifest-a"), 50),
        Descriptor(digest("stage5-galera-manifest-b"), 50),
    )
    stores[0].set_limit(CONCURRENCY_PROJECT, 150)
    barrier = threading.Barrier(2)

    def reserve(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            stores[index].reserve(
                project_id=CONCURRENCY_PROJECT,
                repository_id=REPOSITORIES[index],
                manifest_digest=manifests[index].digest,
                request_id=f"req-stage5-galera-{index}",
                descriptors=(manifests[index], shared),
            )
        except QuotaExceeded:
            return "denied"
        return "admitted"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(reserve, range(2)))
        admitted = results.count("admitted")
        denied = results.count("denied")
        if (admitted, denied) != (1, 1):
            raise RuntimeError("concurrent quota admission did not have one winner")
        usage = stores[0].usage(CONCURRENCY_PROJECT)
        if (
            usage.limit_bytes,
            usage.used_bytes,
            usage.reserved_bytes,
        ) != (150, 0, 150):
            raise RuntimeError("concurrent quota accounting is inconsistent")
        return admitted, denied
    finally:
        for store in stores:
            store._engine.dispose()


@dataclass(slots=True)
class RetryRecord:
    message: str
    operation: str | None
    attempt: int | None


class RetryCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[RetryRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() != (
            "retrying quota write after database transaction conflict"
        ):
            return
        self.records.append(
            RetryRecord(
                message=record.getMessage(),
                operation=getattr(record, "quota_operation", None),
                attempt=getattr(record, "quota_retry_attempt", None),
            )
        )


def exercise_retry(connection: str) -> tuple[int, int, str]:
    setup = QuotaStore(connection)
    retry_store = QuotaStore(connection)
    holder = QuotaStore(connection)
    setup.set_limit(RETRY_PROJECT, 1024)
    retry_store._engine.dispose()
    query_started = threading.Event()
    conflict_codes: list[int] = []
    capture = RetryCapture()
    quota_logger = logging.getLogger("coffer.quota")
    previous_propagate = quota_logger.propagate
    quota_logger.addHandler(capture)
    quota_logger.propagate = False

    @event.listens_for(retry_store._engine, "connect")
    def set_lock_timeout(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("SET SESSION innodb_lock_wait_timeout=1")
        finally:
            cursor.close()

    @event.listens_for(retry_store._engine, "before_cursor_execute")
    def observe_locking_query(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if "project_quotas" in statement and "FOR UPDATE" in statement.upper():
            query_started.set()

    @event.listens_for(retry_store._engine, "handle_error")
    def observe_error(exception_context: object) -> None:
        original = exception_context.original_exception  # type: ignore[attr-defined]
        arguments = getattr(original, "args", ())
        if arguments and isinstance(arguments[0], int):
            conflict_codes.append(arguments[0])

    try:
        with holder._engine.connect() as lock_connection:
            transaction = lock_connection.begin()
            lock_connection.execute(
                select(project_quotas)
                .where(project_quotas.c.project_id == RETRY_PROJECT)
                .with_for_update()
            ).one()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(retry_store.set_limit, RETRY_PROJECT, 2048)
                if not query_started.wait(timeout=10):
                    raise RuntimeError("retrying writer did not reach the locked row")
                time.sleep(1.5)
                transaction.commit()
                usage = future.result(timeout=10)
        if usage.limit_bytes != 2048:
            raise RuntimeError("retried quota update did not commit")
        if conflict_codes != [1205]:
            raise RuntimeError("the real retry conflict was not MySQL 1205")
        if len(capture.records) != 1:
            raise RuntimeError("the quota retry count was not exactly one")
        record = capture.records[0]
        if (record.operation, record.attempt) != ("set_limit", 2):
            raise RuntimeError("the installed retry metadata is inconsistent")
        return conflict_codes[0], int(record.attempt), str(record.operation)
    finally:
        quota_logger.removeHandler(capture)
        quota_logger.propagate = previous_propagate
        setup._engine.dispose()
        retry_store._engine.dispose()
        holder._engine.dispose()


def connection_from_config(path: str) -> str:
    conf = parse_config(args=[], default_config_files=[path])
    connection = conf.database.connection
    if not connection or not connection.startswith("mysql+pymysql://"):
        raise RuntimeError("deployed Coffer database connection is not MySQL")
    return connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "run"))
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
                "coffer_galera_transactions state=ready retry_bound=3 "
                "residue=0 mutation=none"
            )
            return
        cleanup(store._engine)
        require_clean(store._engine)
        try:
            admitted, denied = exercise_concurrency(connection)
            retry_code, retry_attempt, retry_operation = exercise_retry(connection)
        finally:
            cleanup(store._engine)
        require_clean(store._engine)
        result = (
            "coffer_galera_transactions "
            f"concurrency_admitted={admitted} concurrency_denied={denied} "
            f"retry_code={retry_code} retry_attempt={retry_attempt} "
            f"retry_operation={retry_operation} residue=0"
        )
        if result != EXPECTED_RESULT:
            raise RuntimeError("Galera transaction result was not exact")
        print(result)
    finally:
        store._engine.dispose()


if __name__ == "__main__":
    main()
