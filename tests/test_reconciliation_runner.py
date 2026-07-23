from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
import signal
import subprocess
import threading

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect

from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.quota import Descriptor, QuotaStore, ReconciliationCursor
from coffer.quota_reconciliation import ReconciliationRun
from coffer.reconciliation_runner import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_TEMPFAIL,
    MUTATION_GRACE_SECONDS,
    PeriodicRunner,
    ReconciliationCycle,
    RunnerConfigurationError,
    RunnerSettings,
    installed_stop_signals,
    run_with_config,
)


ROOT = Path(__file__).resolve().parents[1]


def result(
    *,
    scanned: int = 1,
    present: int = 0,
    absent: int = 0,
    indeterminate: int = 0,
    stale: int = 0,
) -> ReconciliationRun:
    return ReconciliationRun(
        scanned=scanned,
        present=present,
        absent=absent,
        indeterminate=indeterminate,
        stale=stale,
        next_cursor=None,
    )


def config(**overrides: object):
    conf = new_config()
    conf(args=[])
    baseline = {
        "mode": "once",
        "upstream_url": "http://127.0.0.1:5000",
        "cafile": None,
        "allow_insecure_http": True,
        "timeout_seconds": 10.0,
        "worker_id": None,
        "stale_after_seconds": 300,
        "lease_seconds": 120,
        "batch_limit": 10,
        "max_pages_per_cycle": 100,
        "interval_seconds": 60.0,
        "jitter_fraction": 0.1,
        "retry_initial_seconds": 5.0,
        "retry_max_seconds": 60.0,
    }
    baseline.update(overrides)
    for name, value in baseline.items():
        conf.set_override(name, value, group="reconciliation")
    return conf


class FakeReconciler:
    def __init__(self, outcomes: Iterator[ReconciliationRun | Exception]) -> None:
        self._outcomes = outcomes
        self.calls = 0
        self.afters: list[ReconciliationCursor | None] = []
        self.scan_starts: list[datetime | None] = []

    def run_once(
        self,
        *,
        after: ReconciliationCursor | None = None,
        scan_started_at: datetime | None = None,
    ) -> ReconciliationRun:
        self.calls += 1
        self.afters.append(after)
        self.scan_starts.append(scan_started_at)
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeStopEvent:
    def __init__(self, *, stop_on_wait: bool = False) -> None:
        self._set = False
        self._stop_on_wait = stop_on_wait
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        if self._stop_on_wait:
            self._set = True
        return self._set


def test_settings_require_a_safe_origin_and_sequential_lease_budget() -> None:
    settings = RunnerSettings.from_config(config())

    assert settings.upstream_url == "http://127.0.0.1:5000"
    assert settings.lease_for.total_seconds() >= (
        settings.batch_limit * settings.timeout_seconds
        + MUTATION_GRACE_SECONDS
    )
    assert settings.worker_id.startswith("reconciler-")

    with pytest.raises(RunnerConfigurationError, match="upstream_url"):
        RunnerSettings.from_config(config(upstream_url=None))
    with pytest.raises(RunnerConfigurationError, match="explicit fixture"):
        RunnerSettings.from_config(config(allow_insecure_http=False))
    with pytest.raises(RunnerConfigurationError, match="loopback"):
        RunnerSettings.from_config(
            config(upstream_url="http://registry.internal:5000")
        )
    with pytest.raises(RunnerConfigurationError, match="credential-free"):
        RunnerSettings.from_config(
            config(upstream_url="https://user:secret@registry.internal/v2")
        )
    with pytest.raises(RunnerConfigurationError, match="sequential batch"):
        RunnerSettings.from_config(config(lease_seconds=109))
    with pytest.raises(RunnerConfigurationError, match="retry_initial"):
        RunnerSettings.from_config(
            config(retry_initial_seconds=61.0, retry_max_seconds=60.0)
        )


def test_new_config_instances_do_not_share_reconciliation_overrides() -> None:
    first = new_config()
    first(args=[])
    first.set_override("lease_seconds", 109, group="reconciliation")
    second = new_config()
    second(args=[])

    assert first.reconciliation.lease_seconds == 109
    assert second.reconciliation.lease_seconds == 120


def test_one_shot_has_fixed_summary_and_stable_exit_codes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    reconciler = FakeReconciler(
        iter([result(scanned=3, present=1, absent=1, indeterminate=1)])
    )

    exit_code = run_with_config(
        config(worker_id="worker-a"),
        reconciler_factory=lambda _conf, _settings, _metrics: reconciler,
    )

    assert exit_code == EXIT_OK
    assert reconciler.calls == 1
    assert (
        "reconciliation completed scanned=3 present=1 absent=1 "
        "indeterminate=1 stale=0" in caplog.text
    )
    for forbidden in (
        "worker-a",
        "project-a",
        "repository-a",
        "sha256:",
        "claim-token",
        "credential-secret",
    ):
        assert forbidden not in caplog.text

    failure = FakeReconciler(iter([RuntimeError("credential-secret")]))
    assert run_with_config(
        config(),
        reconciler_factory=lambda _conf, _settings, _metrics: failure,
    ) == EXIT_TEMPFAIL
    assert "credential-secret" not in caplog.text


def test_cycle_drains_pages_and_persists_cursor_at_the_bound() -> None:
    first_cursor = ReconciliationCursor(
        updated_at=datetime(2026, 7, 23, tzinfo=UTC),
        reservation_id="reservation-a",
    )
    second_cursor = ReconciliationCursor(
        updated_at=datetime(2026, 7, 23, 0, 0, 1, tzinfo=UTC),
        reservation_id="reservation-b",
    )
    reconciler = FakeReconciler(
        iter(
            (
                ReconciliationRun(2, 1, 0, 1, 0, first_cursor),
                ReconciliationRun(2, 0, 1, 0, 1, second_cursor),
                ReconciliationRun(1, 1, 0, 0, 0, None),
            )
        )
    )
    scan_started_at = datetime(2026, 7, 23, 0, 0, 2, tzinfo=UTC)
    cycle = ReconciliationCycle(
        reconciler,
        max_pages=2,
        now=lambda: scan_started_at,
    )

    bounded = cycle.run_once()
    completed = cycle.run_once()

    assert bounded == ReconciliationRun(4, 1, 1, 1, 1, second_cursor)
    assert completed == ReconciliationRun(1, 1, 0, 0, 0, None)
    assert reconciler.afters == [None, first_cursor, second_cursor]
    assert reconciler.scan_starts == [
        scan_started_at,
        scan_started_at,
        scan_started_at,
    ]


def test_cycle_stops_after_active_page_and_preserves_cursor() -> None:
    cursor = ReconciliationCursor(
        updated_at=datetime(2026, 7, 23, tzinfo=UTC),
        reservation_id="reservation-a",
    )
    event = FakeStopEvent()

    class StoppingReconciler(FakeReconciler):
        def run_once(
            self,
            *,
            after: ReconciliationCursor | None = None,
            scan_started_at: datetime | None = None,
        ) -> ReconciliationRun:
            page = super().run_once(
                after=after, scan_started_at=scan_started_at
            )
            event.set()
            return page

    reconciler = StoppingReconciler(
        iter((ReconciliationRun(1, 0, 0, 1, 0, cursor),))
    )
    cycle = ReconciliationCycle(
        reconciler,
        max_pages=100,
        stop_event=event,
    )

    stopped = cycle.run_once()

    assert stopped.next_cursor == cursor
    assert reconciler.calls == 1


def test_startup_distinguishes_invalid_config_from_dependency_failure() -> None:
    assert run_with_config(config(upstream_url=None)) == EXIT_CONFIG
    assert run_with_config(
        config(),
        reconciler_factory=lambda _conf, _settings, _metrics: (_ for _ in ()).throw(
            RuntimeError("database unavailable")
        ),
    ) == EXIT_TEMPFAIL


def test_periodic_runner_applies_capped_backoff_and_resets_after_success() -> None:
    reconciler = FakeReconciler(
        iter(
            [
                RuntimeError("first"),
                RuntimeError("second"),
                result(),
                RuntimeError("reset"),
                result(),
            ]
        )
    )
    event = FakeStopEvent()
    runner = PeriodicRunner(
        reconciler.run_once,
        event,
        interval_seconds=60.0,
        jitter_fraction=0.0,
        retry_initial_seconds=5.0,
        retry_max_seconds=8.0,
        random_value=lambda: 0.5,
        monotonic=lambda: 0.0,
    )

    assert runner.run(max_runs=5) == EXIT_OK
    assert reconciler.calls == 5
    assert event.waits == [5.0, 8.0, 60.0, 5.0]


def test_periodic_runner_jitter_is_bounded_and_wait_is_interruptible() -> None:
    random_values = iter((0.0, 1.0))
    reconciler = FakeReconciler(iter((result(), result(), result())))
    event = FakeStopEvent()
    runner = PeriodicRunner(
        reconciler.run_once,
        event,
        interval_seconds=20.0,
        jitter_fraction=0.5,
        retry_initial_seconds=2.0,
        retry_max_seconds=10.0,
        random_value=lambda: next(random_values),
        monotonic=lambda: 0.0,
    )

    assert runner.run(max_runs=3) == EXIT_OK
    assert event.waits == [10.0, 30.0]

    stopping_event = FakeStopEvent(stop_on_wait=True)
    stopping = PeriodicRunner(
        lambda: result(),
        stopping_event,
        interval_seconds=20.0,
        jitter_fraction=0.0,
        retry_initial_seconds=2.0,
        retry_max_seconds=10.0,
        monotonic=lambda: 0.0,
    )
    assert stopping.run() == EXIT_OK
    assert stopping_event.waits == [20.0]


def test_periodic_runner_never_overlaps_local_runs() -> None:
    active = False
    maximum_depth = 0

    def serial_run() -> ReconciliationRun:
        nonlocal active, maximum_depth
        assert not active
        active = True
        maximum_depth = max(maximum_depth, int(active))
        active = False
        return result()

    runner = PeriodicRunner(
        serial_run,
        FakeStopEvent(),
        interval_seconds=1.0,
        jitter_fraction=0.0,
        retry_initial_seconds=1.0,
        retry_max_seconds=2.0,
        random_value=lambda: 0.5,
        monotonic=lambda: 0.0,
    )

    assert runner.run(max_runs=3) == EXIT_OK
    assert maximum_depth == 1


def test_signal_context_sets_stop_event_and_restores_handlers() -> None:
    event = FakeStopEvent()
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)

    with installed_stop_signals(event):
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        assert event.is_set()

    assert signal.getsignal(signal.SIGTERM) == previous_term
    assert signal.getsignal(signal.SIGINT) == previous_int


def test_real_one_shot_starts_against_migrated_empty_sqlite(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'runner.sqlite'}"
    migration = Config(str(ROOT / "alembic.ini"))
    migration.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration, "head")
    conf = config()
    conf.set_override("connection", database_url, group="database")

    assert run_with_config(conf) == EXIT_OK


def test_missing_quota_schema_fails_before_repository_schema_mutation(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing.sqlite'}"
    conf = config()
    conf.set_override("connection", database_url, group="database")

    assert run_with_config(conf) == EXIT_CONFIG
    assert inspect(create_engine(database_url)).get_table_names() == []


def test_installed_console_missing_config_has_stable_secret_free_exit(
    tmp_path: Path,
) -> None:
    missing_config = tmp_path / "missing.conf"

    completed = subprocess.run(
        ["coffer-reconcile", "--config-file", str(missing_config)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == EXIT_CONFIG
    assert "result=invalid_configuration" in output
    assert "Traceback" not in output
    assert str(missing_config) not in output


def test_installed_console_entry_point_runs_one_shot_fixture(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "console.sqlite"
    database_url = f"sqlite:///{database_path}"
    migration = Config(str(ROOT / "alembic.ini"))
    migration.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration, "head")
    project_id = "11111111-1111-4111-8111-111111111111"
    repository = RepositoryStore(database_url).create(project_id, "absent")
    manifest_digest = (
        f"sha256:{hashlib.sha256(b'console-manifest').hexdigest()}"
    )
    quotas = QuotaStore(database_url)
    quotas.set_limit(project_id, 1000)
    reservation = quotas.reserve(
        project_id=project_id,
        repository_id=repository.id,
        manifest_digest=manifest_digest,
        request_id="console-request",
        descriptors=(Descriptor(manifest_digest, 10),),
    )

    class AbsentHandler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:  # noqa: N802
            assert self.path == (
                f"/v2/p/{project_id}/absent/manifests/{manifest_digest}"
            )
            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), AbsentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config_path = tmp_path / "coffer.conf"
    config_path.write_text(
        "\n".join(
            (
                "[database]",
                f"connection = {database_url}",
                "[reconciliation]",
                "mode = once",
                f"upstream_url = http://127.0.0.1:{server.server_port}",
                "allow_insecure_http = true",
                "stale_after_seconds = 0",
            )
        )
    )

    try:
        completed = subprocess.run(
            ["coffer-reconcile", "--config-file", str(config_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert completed.returncode == EXIT_OK
    output = completed.stdout + completed.stderr
    assert "reconciliation completed scanned=1" in output
    assert str(tmp_path) not in output
    assert project_id not in output
    assert manifest_digest not in output
    assert quotas.get_reservation(reservation.id).state == "released"
