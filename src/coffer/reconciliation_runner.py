from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import ipaddress
import logging
import os
import random
import signal
import ssl
import sys
import threading
import time
from types import FrameType
from typing import Protocol
from urllib.parse import urlsplit
import uuid

from oslo_config import cfg

from coffer.config import parse_config, setup_logging
from coffer.db import RepositoryStore
from coffer.observability import CofferMetrics
from coffer.quota import QuotaStore
from coffer.quota_reconciliation import (
    HTTPDistributionManifestProbe,
    QuotaReconciler,
    ReconciliationCursor,
    ReconciliationRun,
    RepositoryStoreResolver,
)
from coffer.schema import SchemaNotReady


LOG = logging.getLogger(__name__)
EXIT_OK = 0
EXIT_TEMPFAIL = 75
EXIT_CONFIG = 78
MUTATION_GRACE_SECONDS = 10.0


class RunnerConfigurationError(ValueError):
    pass


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def set(self) -> None: ...

    def wait(self, timeout: float) -> bool: ...


class Reconciler(Protocol):
    def run_once(
        self,
        *,
        after: ReconciliationCursor | None = None,
        scan_started_at: datetime | None = None,
    ) -> ReconciliationRun: ...


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    mode: str
    upstream_url: str
    cafile: str | None
    allow_insecure_http: bool
    timeout_seconds: float
    worker_id: str
    stale_after: timedelta
    lease_for: timedelta
    batch_limit: int
    max_pages_per_cycle: int
    interval_seconds: float
    jitter_fraction: float
    retry_initial_seconds: float
    retry_max_seconds: float

    @classmethod
    def from_config(cls, conf: cfg.ConfigOpts) -> RunnerSettings:
        options = conf.reconciliation
        upstream_url = options.upstream_url
        if not upstream_url:
            raise RunnerConfigurationError(
                "reconciliation upstream_url is required"
            )
        parsed = urlsplit(upstream_url)
        try:
            parsed.port
        except ValueError as exc:
            raise RunnerConfigurationError(
                "reconciliation upstream_url has an invalid port"
            ) from exc
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RunnerConfigurationError(
                "reconciliation upstream_url must be one credential-free origin"
            )
        if parsed.scheme == "http":
            if not options.allow_insecure_http:
                raise RunnerConfigurationError(
                    "plaintext reconciliation requires the explicit fixture switch"
                )
            if not _is_loopback_host(parsed.hostname):
                raise RunnerConfigurationError(
                    "plaintext reconciliation is restricted to loopback fixtures"
                )
            if options.cafile:
                raise RunnerConfigurationError(
                    "a reconciliation CA file requires an HTTPS origin"
                )
        elif parsed.scheme != "https":
            raise RunnerConfigurationError(
                "reconciliation upstream_url must use HTTP(S)"
            )

        worker_id = options.worker_id or (
            f"reconciler-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
        if (
            not worker_id
            or worker_id.strip() != worker_id
            or len(worker_id) > 128
        ):
            raise RunnerConfigurationError(
                "reconciliation worker_id must contain 1 to 128 characters"
            )
        required_lease = (
            options.batch_limit * options.timeout_seconds
            + MUTATION_GRACE_SECONDS
        )
        if options.lease_seconds < required_lease:
            raise RunnerConfigurationError(
                "reconciliation lease is shorter than the sequential batch budget"
            )
        if options.retry_initial_seconds > options.retry_max_seconds:
            raise RunnerConfigurationError(
                "reconciliation retry_initial_seconds exceeds retry_max_seconds"
            )
        return cls(
            mode=options.mode,
            upstream_url=upstream_url,
            cafile=options.cafile,
            allow_insecure_http=options.allow_insecure_http,
            timeout_seconds=options.timeout_seconds,
            worker_id=worker_id,
            stale_after=timedelta(seconds=options.stale_after_seconds),
            lease_for=timedelta(seconds=options.lease_seconds),
            batch_limit=options.batch_limit,
            max_pages_per_cycle=options.max_pages_per_cycle,
            interval_seconds=options.interval_seconds,
            jitter_fraction=options.jitter_fraction,
            retry_initial_seconds=options.retry_initial_seconds,
            retry_max_seconds=options.retry_max_seconds,
        )


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def build_reconciler(
    conf: cfg.ConfigOpts,
    settings: RunnerSettings,
    metrics: CofferMetrics,
) -> QuotaReconciler:
    quotas = QuotaStore(conf.database.connection)
    repositories = RepositoryStore(conf.database.connection)
    tls_context = (
        ssl.create_default_context(cafile=settings.cafile)
        if settings.upstream_url.startswith("https://")
        else None
    )
    probe = HTTPDistributionManifestProbe(
        settings.upstream_url,
        timeout_seconds=settings.timeout_seconds,
        ssl_context=tls_context,
    )
    return QuotaReconciler(
        quotas,
        RepositoryStoreResolver(repositories),
        probe,
        worker_id=settings.worker_id,
        stale_after=settings.stale_after,
        lease_for=settings.lease_for,
        batch_limit=settings.batch_limit,
        metrics=metrics,
    )


def log_run_summary(run: ReconciliationRun) -> None:
    LOG.info(
        "reconciliation completed scanned=%d present=%d absent=%d "
        "indeterminate=%d stale=%d",
        run.scanned,
        run.present,
        run.absent,
        run.indeterminate,
        run.stale,
    )


class ReconciliationCycle:
    def __init__(
        self,
        reconciler: Reconciler,
        *,
        max_pages: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        stop_event: StopEvent | None = None,
    ) -> None:
        self._reconciler = reconciler
        self._max_pages = max_pages
        self._now = now
        self._stop_event = stop_event
        self._cursor: ReconciliationCursor | None = None
        self._scan_started_at: datetime | None = None

    def run_once(self) -> ReconciliationRun:
        scanned = 0
        present = 0
        absent = 0
        indeterminate = 0
        stale = 0
        if self._scan_started_at is None:
            self._scan_started_at = self._now()
        for _page_number in range(self._max_pages):
            page = self._reconciler.run_once(
                after=self._cursor,
                scan_started_at=self._scan_started_at,
            )
            scanned += page.scanned
            present += page.present
            absent += page.absent
            indeterminate += page.indeterminate
            stale += page.stale
            self._cursor = page.next_cursor
            if self._cursor is None:
                self._scan_started_at = None
                break
            if self._stop_event is not None and self._stop_event.is_set():
                break
        return ReconciliationRun(
            scanned=scanned,
            present=present,
            absent=absent,
            indeterminate=indeterminate,
            stale=stale,
            next_cursor=self._cursor,
        )


class PeriodicRunner:
    def __init__(
        self,
        run_once: Callable[[], ReconciliationRun],
        stop_event: StopEvent,
        *,
        interval_seconds: float,
        jitter_fraction: float,
        retry_initial_seconds: float,
        retry_max_seconds: float,
        random_value: Callable[[], float] = random.random,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._run_once = run_once
        self._stop_event = stop_event
        self._interval = interval_seconds
        self._jitter = jitter_fraction
        self._retry_initial = retry_initial_seconds
        self._retry_max = retry_max_seconds
        self._random_value = random_value
        self._monotonic = monotonic

    def _jittered(self, seconds: float) -> float:
        value = self._random_value()
        if not 0.0 <= value <= 1.0:
            raise ValueError("reconciliation random source returned an invalid value")
        factor = 1.0 + self._jitter * (2.0 * value - 1.0)
        return seconds * factor

    def run(self, *, max_runs: int | None = None) -> int:
        backoff = self._retry_initial
        completed = 0
        while not self._stop_event.is_set():
            try:
                result = self._run_once()
            except Exception:
                LOG.error("reconciliation failed result=dependency_unavailable")
                base_delay = backoff
                backoff = min(self._retry_max, backoff * 2.0)
            else:
                backoff = self._retry_initial
                log_run_summary(result)
                base_delay = self._interval
            completed += 1
            if max_runs is not None and completed >= max_runs:
                break
            deadline = self._monotonic() + self._jittered(base_delay)
            remaining = max(0.0, deadline - self._monotonic())
            if self._stop_event.wait(remaining):
                break
        return EXIT_OK


@contextmanager
def installed_stop_signals(stop_event: StopEvent) -> Iterator[None]:
    previous: dict[signal.Signals, signal.Handlers] = {}

    def stop(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_with_config(
    conf: cfg.ConfigOpts,
    *,
    reconciler_factory: Callable[
        [cfg.ConfigOpts, RunnerSettings, CofferMetrics], Reconciler
    ] = build_reconciler,
    stop_event: StopEvent | None = None,
) -> int:
    try:
        settings = RunnerSettings.from_config(conf)
        metrics = CofferMetrics()
    except RunnerConfigurationError:
        LOG.error("reconciliation startup failed result=invalid_configuration")
        return EXIT_CONFIG
    try:
        reconciler = reconciler_factory(conf, settings, metrics)
    except (SchemaNotReady, ValueError, OSError, ssl.SSLError):
        LOG.error("reconciliation startup failed result=invalid_configuration")
        return EXIT_CONFIG
    except Exception:
        LOG.error("reconciliation startup failed result=dependency_unavailable")
        return EXIT_TEMPFAIL
    if settings.mode == "once":
        cycle = ReconciliationCycle(
            reconciler, max_pages=settings.max_pages_per_cycle
        )
        try:
            result = cycle.run_once()
        except Exception:
            LOG.error("reconciliation failed result=dependency_unavailable")
            return EXIT_TEMPFAIL
        log_run_summary(result)
        return EXIT_OK

    event = stop_event or threading.Event()
    cycle = ReconciliationCycle(
        reconciler,
        max_pages=settings.max_pages_per_cycle,
        stop_event=event,
    )
    runner = PeriodicRunner(
        cycle.run_once,
        event,
        interval_seconds=settings.interval_seconds,
        jitter_fraction=settings.jitter_fraction,
        retry_initial_seconds=settings.retry_initial_seconds,
        retry_max_seconds=settings.retry_max_seconds,
    )
    with installed_stop_signals(event):
        return runner.run()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        conf = parse_config(args=argv)
    except SystemExit as exc:
        if exc.code in (None, EXIT_OK):
            raise
        print(
            "reconciliation startup failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    except cfg.Error:
        print(
            "reconciliation startup failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    try:
        setup_logging(conf)
    except (cfg.Error, OSError, ValueError):
        print(
            "reconciliation startup failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    return run_with_config(conf)
