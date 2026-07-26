from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from coffer.observability import (
    CofferMetrics,
    QUOTA_TRANSACTION_OPERATIONS,
    QUOTA_TRANSACTION_RESULTS,
)
from coffer.quota import (
    QUOTA_TRANSACTION_RESULTS as STORE_TRANSACTION_RESULTS,
    QUOTA_WRITE_OPERATIONS,
    QuotaStore,
)


PROJECT_ID = "project-a"


def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'quota.sqlite'}"


def transaction_error(code: int) -> OperationalError:
    return OperationalError(
        "quota write",
        {},
        RuntimeError(code, "redacted database failure"),
    )


def test_success_is_observed_once_without_identity(tmp_path: Path) -> None:
    observations: list[tuple[str, int, str]] = []
    store = QuotaStore(
        database_url(tmp_path),
        bootstrap_schema=True,
        transaction_observer=lambda operation, attempts, result: (
            observations.append((operation, attempts, result))
        ),
    )

    store.set_limit(PROJECT_ID, 1024)

    assert observations == [("limit", 1, "success")]
    assert PROJECT_ID not in repr(observations)


def test_retry_success_is_observed_only_at_terminal_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[tuple[str, int, str]] = []
    store = QuotaStore(
        database_url(tmp_path),
        bootstrap_schema=True,
        transaction_observer=lambda operation, attempts, result: (
            observations.append((operation, attempts, result))
        ),
    )
    original_writer = store._writer
    attempts = 0

    @contextmanager
    def flaky_writer():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise transaction_error(1213)
        with original_writer() as connection:
            yield connection

    monkeypatch.setattr(store, "_writer", flaky_writer)

    store.set_limit(PROJECT_ID, 1024)

    assert attempts == 3
    assert observations == [("limit", 3, "success")]


def test_conflict_exhaustion_is_observed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[tuple[str, int, str]] = []
    store = QuotaStore(
        database_url(tmp_path),
        bootstrap_schema=True,
        transaction_observer=lambda operation, attempts, result: (
            observations.append((operation, attempts, result))
        ),
    )

    @contextmanager
    def conflicting_writer():
        raise transaction_error(1205)
        yield

    monkeypatch.setattr(store, "_writer", conflicting_writer)

    with pytest.raises(OperationalError):
        store.set_limit(PROJECT_ID, 1024)

    assert observations == [("limit", 3, "conflict_exhausted")]


def test_database_failure_is_observed_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[tuple[str, int, str]] = []
    store = QuotaStore(
        database_url(tmp_path),
        bootstrap_schema=True,
        transaction_observer=lambda operation, attempts, result: (
            observations.append((operation, attempts, result))
        ),
    )

    @contextmanager
    def unavailable_writer():
        raise transaction_error(2006)
        yield

    monkeypatch.setattr(store, "_writer", unavailable_writer)

    with pytest.raises(OperationalError):
        store.set_limit(PROJECT_ID, 1024)

    assert observations == [("limit", 1, "database_error")]


def test_domain_rejection_is_observed(tmp_path: Path) -> None:
    observations: list[tuple[str, int, str]] = []
    store = QuotaStore(
        database_url(tmp_path),
        bootstrap_schema=True,
        transaction_observer=lambda operation, attempts, result: (
            observations.append((operation, attempts, result))
        ),
    )

    with pytest.raises(ValueError):
        store.set_limit(PROJECT_ID, -1)

    assert observations == [("limit", 1, "rejected")]


def test_observer_failure_never_changes_quota_write_or_logs_exception(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_observer(
        operation: str,
        attempts: int,
        result: str,
    ) -> None:
        raise RuntimeError("credential-secret-must-not-be-logged")

    store = QuotaStore(
        database_url(tmp_path),
        bootstrap_schema=True,
        transaction_observer=failing_observer,
    )

    with caplog.at_level(logging.ERROR, logger="coffer.quota"):
        usage = store.set_limit(PROJECT_ID, 1024)

    assert usage.limit_bytes == 1024
    assert "quota transaction observation failed" in caplog.text
    assert "credential-secret-must-not-be-logged" not in caplog.text
    record = caplog.records[-1]
    assert record.quota_operation == "limit"
    assert record.quota_transaction_attempts == 1
    assert record.quota_transaction_result == "success"


def test_metric_histogram_reconstructs_exact_max_attempt() -> None:
    metrics = CofferMetrics(component="edge")

    metrics.observe_quota_transaction("reserve", 1, "success")
    metrics.observe_quota_transaction("reserve", 3, "success")
    metrics.observe_quota_transaction("claim", 2, "conflict_exhausted")
    rendered = metrics.render().decode()

    assert (
        'coffer_quota_transaction_attempts_bucket{le="1.0",'
        'operation="reserve",result="success"} 1.0'
    ) in rendered
    assert (
        'coffer_quota_transaction_attempts_bucket{le="2.0",'
        'operation="reserve",result="success"} 1.0'
    ) in rendered
    assert (
        'coffer_quota_transaction_attempts_bucket{le="3.0",'
        'operation="reserve",result="success"} 2.0'
    ) in rendered
    assert (
        'coffer_quota_transaction_attempts_count{operation="reserve",'
        'result="success"} 2.0'
    ) in rendered
    assert (
        'coffer_quota_transaction_attempts_sum{operation="reserve",'
        'result="success"} 4.0'
    ) in rendered
    for forbidden in (
        PROJECT_ID,
        "repository-a",
        "sha256:",
        "claim-token",
        "database failure",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("operation", "attempts", "result", "message"),
    [
        ("project-a", 1, "success", "operation"),
        ("reserve", 0, "success", "attempts"),
        ("reserve", 4, "success", "attempts"),
        ("reserve", True, "success", "attempts"),
        ("reserve", 1, "project-a", "result"),
    ],
)
def test_metric_refuses_unbounded_transaction_values(
    operation: str,
    attempts: int,
    result: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        CofferMetrics().observe_quota_transaction(
            operation,
            attempts,
            result,
        )


def test_store_and_metric_contracts_have_exact_same_allowlists() -> None:
    assert QUOTA_WRITE_OPERATIONS == QUOTA_TRANSACTION_OPERATIONS
    assert STORE_TRANSACTION_RESULTS == QUOTA_TRANSACTION_RESULTS


def test_store_refuses_non_callable_observer(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="observer"):
        QuotaStore(
            database_url(tmp_path),
            bootstrap_schema=True,
            transaction_observer="project-a",  # type: ignore[arg-type]
        )
