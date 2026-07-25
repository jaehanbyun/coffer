from __future__ import annotations

import warnings

import falcon
from falcon import testing
import pytest

from coffer.db import RepositoryStore
from coffer.observability import (
    CofferMetrics,
    HTTPMetricsMiddleware,
    WSGIHTTPMetricsMiddleware,
    build_operational_application,
    edge_route_class,
)


class FailingStore:
    def ping(self) -> None:
        raise RuntimeError("database unavailable")


class ItemResource:
    def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        repository_id: str,
    ) -> None:
        resp.media = {"id": repository_id}


def test_health_readiness_and_metrics_have_bounded_output() -> None:
    store = RepositoryStore("sqlite://", bootstrap_schema=True)
    metrics = CofferMetrics(wall_clock=lambda: 123.0)
    client = testing.TestClient(
        build_operational_application(store, metrics, metrics_enabled=True)
    )

    health = client.simulate_get("/healthz")
    readiness = client.simulate_get("/readyz")
    rendered = client.simulate_get("/metrics")

    assert health.status_code == 200
    assert health.json == {"status": "ok", "checks": {"process": "alive"}}
    assert readiness.status_code == 200
    assert readiness.json == {"status": "ok", "checks": {"database": "ready"}}
    assert health.headers["cache-control"] == "no-store"
    assert readiness.headers["cache-control"] == "no-store"
    assert rendered.status_code == 200
    assert rendered.headers["cache-control"] == "no-store"
    assert rendered.content_type.startswith("text/plain")
    assert "coffer_build_info{version=\"0.1.0\"} 1.0" in rendered.text
    assert (
        'coffer_process_start_time_seconds{component="api",version="0.1.0"} '
        "123.0"
    ) in rendered.text
    assert (
        'coffer_readiness_checks_total{result="ready"} 1.0'
        in rendered.text
    )


def test_process_start_is_refreshed_after_the_worker_fork() -> None:
    starts = iter((123.0, 456.0))
    metrics = CofferMetrics(wall_clock=lambda: next(starts))

    metrics.mark_process_started()
    rendered = metrics.render().decode()

    assert (
        'coffer_process_start_time_seconds{component="api",version="0.1.0"} '
        "456.0"
    ) in rendered
    assert " 123.0" not in rendered


def test_readiness_failure_is_neutral_and_counted() -> None:
    metrics = CofferMetrics()
    client = testing.TestClient(
        build_operational_application(
            FailingStore(), metrics, metrics_enabled=True
        )
    )

    readiness = client.simulate_get("/readyz")
    rendered = client.simulate_get("/metrics")

    assert readiness.status_code == 503
    assert readiness.json == {
        "status": "unavailable",
        "checks": {"database": "unavailable"},
    }
    assert "RuntimeError" not in readiness.text
    assert (
        'coffer_readiness_checks_total{result="database_unavailable"} 1.0'
        in rendered.text
    )


def test_metrics_route_is_absent_when_disabled() -> None:
    metrics = CofferMetrics()
    client = testing.TestClient(
        build_operational_application(
            RepositoryStore("sqlite://", bootstrap_schema=True),
            metrics,
            metrics_enabled=False,
        )
    )

    assert client.simulate_get("/metrics").status_code == 404


def test_http_metrics_use_route_templates_not_resource_identifiers() -> None:
    metrics = CofferMetrics(component="api")
    application = falcon.App(middleware=[HTTPMetricsMiddleware(metrics)])
    application.add_route(
        "/v1/repositories/{repository_id}",
        ItemResource(),
    )
    client = testing.TestClient(application)
    item_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    assert (
        client.simulate_get(f"/v1/repositories/{item_id}").status_code
        == 200
    )
    rendered = metrics.render().decode()

    assert item_id not in rendered
    assert 'route="/v1/repositories/{repository_id}"' in rendered
    assert 'component="api"' in rendered
    assert 'method="GET"' in rendered
    assert 'status="2xx"' in rendered


def test_http_metrics_collapse_unknown_methods() -> None:
    metrics = CofferMetrics(component="api")
    application = falcon.App(middleware=[HTTPMetricsMiddleware(metrics)])
    application.add_route(
        "/v1/repositories/{repository_id}",
        ItemResource(),
    )
    client = testing.TestClient(application)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unknown REQUEST_METHOD.*")
        client.simulate_request(
            path="/v1/repositories/example",
            method="UNBOUNDED-ONE",
        )
        client.simulate_request(
            path="/v1/repositories/example",
            method="UNBOUNDED-TWO",
        )
    rendered = metrics.render().decode()

    assert "UNBOUNDED-ONE" not in rendered
    assert "UNBOUNDED-TWO" not in rendered
    assert 'method="OTHER"' in rendered


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/auth/token", "GET", "edge-auth"),
        ("/v2/p/project/repo/manifests/latest", "PUT", "edge-manifest"),
        ("/v2/p/project/repo/blobs/uploads/id", "PATCH", "edge-upload"),
        ("/v2/p/project/repo/blobs/sha256:abc", "GET", "edge-blob"),
        ("/v1/repositories", "GET", "edge-other"),
    ],
)
def test_edge_routes_collapse_resource_identifiers(path, method, expected) -> None:
    assert (
        edge_route_class({"PATH_INFO": path, "REQUEST_METHOD": method})
        == expected
    )


def test_wsgi_edge_metrics_never_retain_the_raw_path() -> None:
    item_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    def application(environ, start_response):
        start_response("503 Service Unavailable", [("Content-Length", "0")])
        return []

    metrics = CofferMetrics(component="edge", wall_clock=lambda: 123.0)
    middleware = WSGIHTTPMetricsMiddleware(application, metrics)
    environ = {
        "PATH_INFO": f"/v2/p/project/{item_id}/blobs/uploads/id",
        "REQUEST_METHOD": "PATCH",
    }
    iterable = middleware(environ, lambda _status, _headers: None)
    list(iterable)
    rendered = metrics.render().decode()

    assert item_id not in rendered
    assert 'component="edge"' in rendered
    assert 'route="edge-upload"' in rendered
    assert 'method="PATCH"' in rendered
    assert 'status="5xx"' in rendered


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda: CofferMetrics(component="project-a"), "component"),
        (
            lambda: CofferMetrics(version="credential secret"),
            "version",
        ),
        (
            lambda: CofferMetrics().observe_http(
                route="/v1/repositories/concrete-id",
                method="GET",
                status=200,
                duration_seconds=0.1,
            ),
            "route",
        ),
        (
            lambda: CofferMetrics().observe_token_decision(
                "project-a",
                0.1,
            ),
            "token",
        ),
        (
            lambda: CofferMetrics().observe_readiness("project-a"),
            "readiness",
        ),
        (
            lambda: CofferMetrics(component="edge").observe_quota_admission(
                "project-a",
                0.1,
            ),
            "admission",
        ),
    ],
)
def test_metric_schema_rejects_unbounded_values(operation, message) -> None:
    with pytest.raises(ValueError, match=message):
        operation()


def test_reconciliation_metrics_accept_only_fixed_result_classes() -> None:
    metrics = CofferMetrics(component="reconcile")
    for result in (
        "absent",
        "indeterminate",
        "present",
        "stale_claim",
        "stale_version",
    ):
        metrics.observe_reconciliation(result)

    rendered = metrics.render().decode()
    assert rendered.count("coffer_quota_reconciliation_outcomes_total{") == 5
    assert 'result="present"' in rendered
    assert 'result="stale_claim"' in rendered
    for forbidden in (
        "worker-a",
        "project-a",
        "repository-a",
        "sha256:",
        "claim-token",
    ):
        assert forbidden not in rendered

    with pytest.raises(ValueError, match="not bounded"):
        metrics.observe_reconciliation("project-a")


def test_periodic_reconciliation_metrics_are_restart_and_snapshot_correct() -> None:
    metrics = CofferMetrics(
        component="reconcile",
        wall_clock=lambda: 1000.0,
    )

    metrics.observe_reconciliation_cycle(
        "success",
        2.5,
        scanned=7,
        completed_at=1234.0,
    )
    metrics.observe_reconciliation_cycle(
        "dependency_unavailable",
        1.0,
        scanned=0,
    )
    metrics.set_reconciliation_snapshot(
        backlog=11,
        active_claims=2,
        stale_claims=1,
        oldest_pending_seconds=305.0,
    )
    metrics.set_dependency_up("database", True)
    rendered = metrics.render().decode()

    assert (
        'coffer_reconciliation_cycles_total{result="success"} 1.0'
        in rendered
    )
    assert (
        'coffer_reconciliation_cycles_total{result="dependency_unavailable"} 1.0'
        in rendered
    )
    assert "coffer_reconciliation_last_success_timestamp_seconds 1234.0" in rendered
    assert "coffer_reconciliation_last_scanned 7.0" in rendered
    assert "coffer_reconciliation_backlog 11.0" in rendered
    assert "coffer_reconciliation_active_claims 2.0" in rendered
    assert "coffer_reconciliation_stale_claims 1.0" in rendered
    assert "coffer_reconciliation_oldest_pending_seconds 305.0" in rendered
    assert (
        'coffer_dependency_up{component="reconcile",dependency="database"} 1.0'
        in rendered
    )


@pytest.mark.parametrize(
    "operation",
    [
        lambda: CofferMetrics().observe_reconciliation_cycle(
            "success", 1.0, scanned=1
        ),
        lambda: CofferMetrics(component="reconcile").observe_reconciliation_cycle(
            "repository-a", 1.0, scanned=1
        ),
        lambda: CofferMetrics(component="reconcile").set_reconciliation_snapshot(
            backlog=-1,
            active_claims=0,
            stale_claims=0,
            oldest_pending_seconds=0,
        ),
        lambda: CofferMetrics(component="reconcile").set_dependency_up(
            "repository-a", True
        ),
    ],
)
def test_periodic_reconciliation_metric_schema_refuses_unbounded_state(
    operation,
) -> None:
    with pytest.raises(ValueError):
        operation()
