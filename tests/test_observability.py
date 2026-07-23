from __future__ import annotations

import warnings

import falcon
from falcon import testing
import pytest

from coffer.db import RepositoryStore
from coffer.observability import (
    CofferMetrics,
    HTTPMetricsMiddleware,
    build_operational_application,
)


class FailingStore:
    def ping(self) -> None:
        raise RuntimeError("database unavailable")


class ItemResource:
    def on_get(
        self, req: falcon.Request, resp: falcon.Response, item_id: str
    ) -> None:
        resp.media = {"id": item_id}


def test_health_readiness_and_metrics_have_bounded_output() -> None:
    store = RepositoryStore("sqlite://")
    metrics = CofferMetrics()
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
        'coffer_readiness_checks_total{result="ready"} 1.0'
        in rendered.text
    )


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
            RepositoryStore("sqlite://"), metrics, metrics_enabled=False
        )
    )

    assert client.simulate_get("/metrics").status_code == 404


def test_http_metrics_use_route_templates_not_resource_identifiers() -> None:
    metrics = CofferMetrics()
    application = falcon.App(
        middleware=[HTTPMetricsMiddleware(metrics, "control")]
    )
    application.add_route("/items/{item_id}", ItemResource())
    client = testing.TestClient(application)
    item_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    assert client.simulate_get(f"/items/{item_id}").status_code == 200
    rendered = metrics.render().decode()

    assert item_id not in rendered
    assert 'route="/items/{item_id}"' in rendered
    assert 'component="control"' in rendered
    assert 'method="GET"' in rendered
    assert 'status="200"' in rendered


def test_http_metrics_collapse_unknown_methods() -> None:
    metrics = CofferMetrics()
    application = falcon.App(
        middleware=[HTTPMetricsMiddleware(metrics, "control")]
    )
    application.add_route("/items/{item_id}", ItemResource())
    client = testing.TestClient(application)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unknown REQUEST_METHOD.*")
        client.simulate_request(path="/items/example", method="UNBOUNDED-ONE")
        client.simulate_request(path="/items/example", method="UNBOUNDED-TWO")
    rendered = metrics.render().decode()

    assert "UNBOUNDED-ONE" not in rendered
    assert "UNBOUNDED-TWO" not in rendered
    assert 'method="OTHER"' in rendered


def test_reconciliation_metrics_accept_only_fixed_result_classes() -> None:
    metrics = CofferMetrics()
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
