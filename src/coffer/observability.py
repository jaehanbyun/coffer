from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
import threading
import time
from typing import Any, Protocol

import falcon
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest


BOUNDED_HTTP_METHODS = frozenset(
    {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}
)
BOUNDED_COMPONENTS = frozenset({"api", "edge", "reconcile"})
BOUNDED_ROUTES = frozenset(
    {
        "/auth/token",
        "/healthz",
        "/metrics",
        "/readyz",
        "/v1/internal/maintenance/registry-token",
        "/v1/repositories",
        "/v1/repositories/{repository_id}",
        "edge-auth",
        "edge-blob",
        "edge-manifest",
        "edge-other",
        "edge-upload",
        "unmatched",
    }
)
BOUNDED_STATUS_CLASSES = frozenset(
    {"1xx", "2xx", "3xx", "4xx", "5xx", "OTHER"}
)
TOKEN_RESULTS = frozenset(
    {
        "credential_expires_too_soon",
        "identity_unavailable",
        "invalid_credential",
        "invalid_request",
        "issued",
    }
)
READINESS_RESULTS = frozenset({"database_unavailable", "ready"})
ADMISSION_RESULTS = frozenset(
    {
        "accepted",
        "internal_error",
        "invalid_manifest",
        "missing_quota",
        "over_quota",
        "unauthorized",
        "upstream_unavailable",
    }
)
RECONCILIATION_RESULTS = frozenset(
    {"absent", "indeterminate", "present", "stale_claim", "stale_version"}
)
RECONCILIATION_CYCLE_RESULTS = frozenset(
    {"dependency_unavailable", "success"}
)
BOUNDED_DEPENDENCIES = frozenset(
    {"database", "haproxy", "keystone", "kms", "registry", "rgw"}
)
EDGE_ROUTE_CLASSES = frozenset(
    {"edge-auth", "edge-blob", "edge-manifest", "edge-other", "edge-upload"}
)
QUOTA_TRANSACTION_OPERATIONS = frozenset(
    {"claim", "commit", "limit", "reconcile", "release", "reserve"}
)
QUOTA_TRANSACTION_RESULTS = frozenset(
    {"conflict_exhausted", "database_error", "rejected", "success"}
)


class ReadinessStore(Protocol):
    def ping(self) -> None: ...


class CofferMetrics:
    """Process-local metrics with bounded label sets."""

    def __init__(
        self,
        *,
        component: str = "api",
        version: str = "0.1.0",
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if component not in BOUNDED_COMPONENTS:
            raise ValueError("metric component is not bounded")
        if (
            not version
            or len(version) > 64
            or not all(
                character.isascii()
                and (character.isalnum() or character in ".+-")
                for character in version
            )
        ):
            raise ValueError("metric version is invalid")
        try:
            process_start = _duration(float(wall_clock()))
        except (TypeError, ValueError) as error:
            raise ValueError("metric process start is invalid") from error
        self.component = component
        self._version = version
        self._wall_clock = wall_clock
        self.registry = CollectorRegistry()
        self._build = Gauge(
            "coffer_build_info",
            "Coffer process build information.",
            ["version"],
            registry=self.registry,
        )
        self._build.labels(version=version).set(1)
        self._process_start = Gauge(
            "coffer_process_start_time_seconds",
            "Unix time when the Coffer process started.",
            ["component", "version"],
            registry=self.registry,
        )
        self._process_start.labels(
            component=self.component,
            version=version,
        ).set(process_start)
        self._http_requests = Counter(
            "coffer_http_requests_total",
            "Completed Coffer HTTP requests.",
            ["component", "route", "method", "status"],
            registry=self.registry,
        )
        self._http_duration = Histogram(
            "coffer_http_request_duration_seconds",
            "Coffer HTTP request duration.",
            ["component", "route", "method"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self._token_decisions = Counter(
            "coffer_token_decisions_total",
            "Registry token decisions by bounded result class.",
            ["result"],
            registry=self.registry,
        )
        self._token_duration = Histogram(
            "coffer_token_decision_duration_seconds",
            "Registry token decision duration.",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self._readiness = Counter(
            "coffer_readiness_checks_total",
            "Readiness checks by bounded result class.",
            ["result"],
            registry=self.registry,
        )
        self._quota_admission = Counter(
            "coffer_quota_admission_total",
            "Manifest quota admission decisions by bounded result class.",
            ["result"],
            registry=self.registry,
        )
        self._quota_admission_duration = Histogram(
            "coffer_quota_admission_duration_seconds",
            "Manifest quota admission duration.",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self._quota_transaction_attempts = Histogram(
            "coffer_quota_transaction_attempts",
            "Observed attempts for one completed quota write.",
            ["operation", "result"],
            buckets=(1, 2, 3),
            registry=self.registry,
        )
        self._reconciliation = Counter(
            "coffer_quota_reconciliation_outcomes_total",
            "Quota reconciliation candidates by bounded result class.",
            ["result"],
            registry=self.registry,
        )
        self._reconciliation_lock = threading.RLock()
        self._reconciliation_cycles: Counter | None = None
        self._reconciliation_cycle_duration: Histogram | None = None
        self._reconciliation_last_success: Gauge | None = None
        self._reconciliation_last_scanned: Gauge | None = None
        self._reconciliation_backlog: Gauge | None = None
        self._reconciliation_active_claims: Gauge | None = None
        self._reconciliation_stale_claims: Gauge | None = None
        self._reconciliation_oldest_pending: Gauge | None = None
        self._dependency_up: Gauge | None = None
        if component == "reconcile":
            self._reconciliation_cycles = Counter(
                "coffer_reconciliation_cycles_total",
                "Periodic reconciliation cycles by bounded result class.",
                ["result"],
                registry=self.registry,
            )
            self._reconciliation_cycle_duration = Histogram(
                "coffer_reconciliation_cycle_duration_seconds",
                "Periodic reconciliation cycle duration.",
                buckets=(0.01, 0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
                registry=self.registry,
            )
            self._reconciliation_last_success = Gauge(
                "coffer_reconciliation_last_success_timestamp_seconds",
                "Unix time of the last successful periodic cycle.",
                registry=self.registry,
            )
            self._reconciliation_last_scanned = Gauge(
                "coffer_reconciliation_last_scanned",
                "Candidates scanned by the last successful periodic cycle.",
                registry=self.registry,
            )
            self._reconciliation_backlog = Gauge(
                "coffer_reconciliation_backlog",
                "Current SQL-derived eligible reconciliation backlog.",
                registry=self.registry,
            )
            self._reconciliation_active_claims = Gauge(
                "coffer_reconciliation_active_claims",
                "Current SQL-derived unexpired reconciliation claims.",
                registry=self.registry,
            )
            self._reconciliation_stale_claims = Gauge(
                "coffer_reconciliation_stale_claims",
                "Current SQL-derived expired reconciliation claims.",
                registry=self.registry,
            )
            self._reconciliation_oldest_pending = Gauge(
                "coffer_reconciliation_oldest_pending_seconds",
                "Age of the oldest SQL-derived eligible reconciliation item.",
                registry=self.registry,
            )
            self._dependency_up = Gauge(
                "coffer_dependency_up",
                "Bounded dependency availability observed by Coffer.",
                ["component", "dependency"],
                registry=self.registry,
            )

    def observe_http(
        self,
        *,
        route: str,
        method: str,
        status: int | str,
        duration_seconds: float,
    ) -> None:
        if route not in BOUNDED_ROUTES:
            raise ValueError("HTTP metric route is not bounded")
        method = method if method in BOUNDED_HTTP_METHODS else "OTHER"
        status_class = _status_class(status)
        duration = _duration(duration_seconds)
        self._http_requests.labels(
            component=self.component,
            route=route,
            method=method,
            status=status_class,
        ).inc()
        self._http_duration.labels(
            component=self.component,
            route=route,
            method=method,
        ).observe(duration)

    def observe_token_decision(
        self, result: str, duration_seconds: float
    ) -> None:
        if result not in TOKEN_RESULTS:
            raise ValueError("token metric result is not bounded")
        self._token_decisions.labels(result=result).inc()
        self._token_duration.observe(_duration(duration_seconds))

    def observe_readiness(self, result: str) -> None:
        if result not in READINESS_RESULTS:
            raise ValueError("readiness metric result is not bounded")
        self._readiness.labels(result=result).inc()

    def observe_quota_admission(
        self,
        result: str,
        duration_seconds: float,
    ) -> None:
        if result not in ADMISSION_RESULTS:
            raise ValueError("quota admission metric result is not bounded")
        self._quota_admission.labels(result=result).inc()
        self._quota_admission_duration.observe(_duration(duration_seconds))

    def observe_quota_transaction(
        self,
        operation: str,
        attempts: int,
        result: str,
    ) -> None:
        if operation not in QUOTA_TRANSACTION_OPERATIONS:
            raise ValueError("quota transaction operation is not bounded")
        if result not in QUOTA_TRANSACTION_RESULTS:
            raise ValueError("quota transaction result is not bounded")
        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or not 1 <= attempts <= 3
        ):
            raise ValueError("quota transaction attempts are invalid")
        self._quota_transaction_attempts.labels(
            operation=operation,
            result=result,
        ).observe(attempts)

    def observe_reconciliation(self, result: str) -> None:
        if result not in RECONCILIATION_RESULTS:
            raise ValueError("quota reconciliation metric result is not bounded")
        self._reconciliation.labels(result=result).inc()

    def observe_reconciliation_cycle(
        self,
        result: str,
        duration_seconds: float,
        *,
        scanned: int,
        completed_at: float | None = None,
    ) -> None:
        if self.component != "reconcile":
            raise ValueError("reconciliation cycle metrics require the reconcile component")
        if result not in RECONCILIATION_CYCLE_RESULTS:
            raise ValueError("reconciliation cycle metric result is not bounded")
        if isinstance(scanned, bool) or not isinstance(scanned, int) or scanned < 0:
            raise ValueError("reconciliation scanned count is invalid")
        assert self._reconciliation_cycles is not None
        assert self._reconciliation_cycle_duration is not None
        assert self._reconciliation_last_success is not None
        assert self._reconciliation_last_scanned is not None
        with self._reconciliation_lock:
            self._reconciliation_cycles.labels(result=result).inc()
            self._reconciliation_cycle_duration.observe(
                _duration(duration_seconds)
            )
            if result == "success":
                timestamp = (
                    self._wall_clock()
                    if completed_at is None
                    else completed_at
                )
                self._reconciliation_last_success.set(
                    _duration(float(timestamp))
                )
                self._reconciliation_last_scanned.set(scanned)

    def set_reconciliation_snapshot(
        self,
        *,
        backlog: int,
        active_claims: int,
        stale_claims: int,
        oldest_pending_seconds: float,
    ) -> None:
        if self.component != "reconcile":
            raise ValueError("reconciliation state metrics require the reconcile component")
        counts = (backlog, active_claims, stale_claims)
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in counts
        ):
            raise ValueError("reconciliation state count is invalid")
        oldest = _duration(oldest_pending_seconds)
        assert self._reconciliation_backlog is not None
        assert self._reconciliation_active_claims is not None
        assert self._reconciliation_stale_claims is not None
        assert self._reconciliation_oldest_pending is not None
        with self._reconciliation_lock:
            self._reconciliation_backlog.set(backlog)
            self._reconciliation_active_claims.set(active_claims)
            self._reconciliation_stale_claims.set(stale_claims)
            self._reconciliation_oldest_pending.set(oldest)

    def set_dependency_up(self, dependency: str, up: bool) -> None:
        if self.component != "reconcile":
            raise ValueError("dependency metrics require the reconcile component")
        if dependency not in BOUNDED_DEPENDENCIES:
            raise ValueError("dependency metric label is not bounded")
        if not isinstance(up, bool):
            raise ValueError("dependency metric state is invalid")
        assert self._dependency_up is not None
        with self._reconciliation_lock:
            self._dependency_up.labels(
                component=self.component,
                dependency=dependency,
            ).set(1 if up else 0)

    def mark_process_started(self) -> None:
        try:
            process_start = _duration(float(self._wall_clock()))
        except (TypeError, ValueError) as error:
            raise ValueError("metric process start is invalid") from error
        self._process_start.labels(
            component=self.component,
            version=self._version,
        ).set(process_start)

    def render(self) -> bytes:
        with self._reconciliation_lock:
            return generate_latest(self.registry)


def _duration(value: float) -> float:
    result = float(value)
    if result < 0 or result == float("inf") or result != result:
        raise ValueError("metric duration is invalid")
    return result


def _status_class(value: int | str) -> str:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return "OTHER"
    if 100 <= status <= 599:
        result = f"{status // 100}xx"
        if result in BOUNDED_STATUS_CLASSES:
            return result
    return "OTHER"


class HTTPMetricsMiddleware:
    def __init__(self, metrics: CofferMetrics) -> None:
        self._metrics = metrics

    def process_request(self, req: falcon.Request, resp: falcon.Response) -> None:
        req.context.coffer_metrics_started = time.monotonic()

    def process_response(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        resource: Any,
        req_succeeded: bool,
    ) -> None:
        started = getattr(req.context, "coffer_metrics_started", time.monotonic())
        route = req.uri_template or "unmatched"
        status = str(resp.status_code)
        method = req.method if req.method in BOUNDED_HTTP_METHODS else "OTHER"
        self._metrics.observe_http(
            route=route,
            method=method,
            status=status,
            duration_seconds=max(0.0, time.monotonic() - started),
        )


def edge_route_class(environ: Mapping[str, Any]) -> str:
    path = environ.get("PATH_INFO")
    method = environ.get("REQUEST_METHOD")
    if not isinstance(path, str) or not path.startswith("/"):
        return "edge-other"
    if path == "/auth/token":
        return "edge-auth"
    if path == "/v2" or path.startswith("/v2/"):
        if method == "PUT" and "/manifests/" in path:
            return "edge-manifest"
        if "/blobs/uploads" in path:
            return "edge-upload"
        if "/blobs/" in path:
            return "edge-blob"
    return "edge-other"


class _ObservedIterable:
    def __init__(
        self,
        iterable: Iterable[bytes],
        complete: Callable[[], None],
    ) -> None:
        self._iterable = iterable
        self._complete = complete
        self._completed = False

    def _finish(self) -> None:
        if not self._completed:
            self._completed = True
            self._complete()

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self._iterable
        finally:
            self._finish()

    def close(self) -> None:
        close = getattr(self._iterable, "close", None)
        try:
            if close is not None:
                close()
        finally:
            self._finish()


class WSGIHTTPMetricsMiddleware:
    def __init__(self, application: Any, metrics: CofferMetrics) -> None:
        if metrics.component != "edge":
            raise ValueError("WSGI metrics middleware requires the edge component")
        self.application = application
        self.metrics = metrics

    def mark_process_started(self) -> None:
        self.metrics.mark_process_started()

    def __call__(
        self,
        environ: dict[str, Any],
        start_response: Callable[..., Any],
    ) -> Iterable[bytes]:
        started = time.monotonic()
        status: int | str = "OTHER"

        def observed_start_response(
            response_status: str,
            headers: Sequence[tuple[str, str]],
            exc_info: object | None = None,
        ) -> Any:
            nonlocal status
            status = response_status.partition(" ")[0]
            if exc_info is None:
                return start_response(response_status, headers)
            return start_response(response_status, headers, exc_info)

        route = edge_route_class(environ)
        method = str(environ.get("REQUEST_METHOD", "OTHER"))

        def complete() -> None:
            self.metrics.observe_http(
                route=route,
                method=method,
                status=status,
                duration_seconds=max(0.0, time.monotonic() - started),
            )

        try:
            iterable = self.application(environ, observed_start_response)
        except Exception:
            status = 500
            complete()
            raise
        return _ObservedIterable(iterable, complete)


class HealthResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.set_header("Cache-Control", "no-store")
        resp.media = {
            "status": "ok",
            "checks": {"process": "alive"},
        }


class ReadinessResource:
    def __init__(self, store: ReadinessStore, metrics: CofferMetrics) -> None:
        self._store = store
        self._metrics = metrics

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.set_header("Cache-Control", "no-store")
        try:
            self._store.ping()
        except Exception:
            self._metrics.observe_readiness("database_unavailable")
            resp.status = falcon.HTTP_503
            resp.media = {
                "status": "unavailable",
                "checks": {"database": "unavailable"},
            }
            return
        self._metrics.observe_readiness("ready")
        resp.media = {
            "status": "ok",
            "checks": {"database": "ready"},
        }


class MetricsResource:
    def __init__(self, metrics: CofferMetrics) -> None:
        self._metrics = metrics

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.set_header("Cache-Control", "no-store")
        resp.content_type = CONTENT_TYPE_LATEST
        resp.data = self._metrics.render()


def build_operational_application(
    store: ReadinessStore,
    metrics: CofferMetrics,
    *,
    metrics_enabled: bool,
) -> falcon.App:
    application = falcon.App()
    application.add_route("/healthz", HealthResource())
    application.add_route("/readyz", ReadinessResource(store, metrics))
    if metrics_enabled:
        application.add_route("/metrics", MetricsResource(metrics))
    return application
