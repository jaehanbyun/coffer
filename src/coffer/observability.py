from __future__ import annotations

import time
from typing import Any, Protocol

import falcon
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import CONTENT_TYPE_LATEST, generate_latest


BOUNDED_HTTP_METHODS = frozenset(
    {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}
)


class ReadinessStore(Protocol):
    def ping(self) -> None: ...


class CofferMetrics:
    """Process-local metrics with bounded label sets."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self._build = Gauge(
            "coffer_build_info",
            "Coffer process build information.",
            ["version"],
            registry=self.registry,
        )
        self._build.labels(version="0.1.0").set(1)
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

    def observe_http(
        self,
        *,
        component: str,
        route: str,
        method: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        self._http_requests.labels(
            component=component,
            route=route,
            method=method,
            status=status,
        ).inc()
        self._http_duration.labels(
            component=component,
            route=route,
            method=method,
        ).observe(duration_seconds)

    def observe_token_decision(
        self, result: str, duration_seconds: float
    ) -> None:
        self._token_decisions.labels(result=result).inc()
        self._token_duration.observe(duration_seconds)

    def observe_readiness(self, result: str) -> None:
        self._readiness.labels(result=result).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)


class HTTPMetricsMiddleware:
    def __init__(self, metrics: CofferMetrics, component: str) -> None:
        self._metrics = metrics
        self._component = component

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
            component=self._component,
            route=route,
            method=method,
            status=status,
            duration_seconds=max(0.0, time.monotonic() - started),
        )


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
