from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from falcon import testing
import pytest

from coffer.config import new_config
from coffer.registry_metrics_runner import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_TEMPFAIL,
    RegistryMetricsConfigurationError,
    RegistryMetricsSettings,
    build_application,
    run_with_config,
)


def config(**overrides: object):
    conf = new_config()
    conf(args=[])
    baseline = {
        "bind_host": "127.0.0.1",
        "bind_port": 8791,
        "workers": 1,
        "threads": 2,
        "timeout_seconds": 10,
        "graceful_timeout_seconds": 10,
        "keepalive_seconds": 5,
        "upstream_url": "http://127.0.0.1:8792/metrics",
        "upstream_timeout_seconds": 1.0,
    }
    baseline.update(overrides)
    for name, value in baseline.items():
        conf.set_override(name, value, group="registry_metrics")
    return conf


@contextmanager
def metrics_backend(body: bytes) -> Iterator[tuple[int, list[str]]]:
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "upstream_url",
    [
        None,
        "https://127.0.0.1:8792/metrics",
        "http://registry.internal:8792/metrics",
        "http://127.0.0.1:8792/debug/metrics",
        "http://user:secret@127.0.0.1:8792/metrics",
        "http://127.0.0.1:8792/metrics?secret=value",
    ],
)
def test_settings_accept_only_an_exact_loopback_metrics_upstream(
    upstream_url,
) -> None:
    with pytest.raises(
        RegistryMetricsConfigurationError,
        match="upstream",
    ):
        RegistryMetricsSettings.from_config(config(upstream_url=upstream_url))


def test_proxy_exposes_only_bounded_health_and_metrics_paths() -> None:
    payload = b"# HELP registry_test bounded\nregistry_test 1\n"
    with metrics_backend(payload) as (port, paths):
        settings = RegistryMetricsSettings.from_config(
            config(upstream_url=f"http://127.0.0.1:{port}/metrics")
        )
        client = testing.TestClient(build_application(settings))

        assert client.simulate_get("/healthz").status_code == 200
        metrics = client.simulate_get("/metrics")
        assert client.simulate_get("/debug/pprof/").status_code == 404
        assert client.simulate_get("/debug/vars").status_code == 404
        assert client.simulate_get("/metrics", params={"raw": "1"}).status_code == 404

    assert metrics.status_code == 200
    assert metrics.content == payload
    assert metrics.headers["cache-control"] == "no-store"
    assert paths == ["/metrics"]


def test_proxy_maps_outage_and_oversized_payload_to_a_fixed_503(
    monkeypatch,
) -> None:
    unavailable = testing.TestClient(
        build_application(
            RegistryMetricsSettings.from_config(
                config(upstream_url="http://127.0.0.1:1/metrics")
            )
        )
    ).simulate_get("/metrics")
    assert unavailable.status_code == 503
    assert unavailable.json == {"status": "unavailable"}

    monkeypatch.setattr(
        "coffer.registry_metrics_runner.MAX_METRICS_BYTES",
        16,
    )
    with metrics_backend(b"x" * 17) as (port, _paths):
        oversized = testing.TestClient(
            build_application(
                RegistryMetricsSettings.from_config(
                    config(upstream_url=f"http://127.0.0.1:{port}/metrics")
                )
            )
        ).simulate_get("/metrics")
    assert oversized.status_code == 503
    assert "xxxx" not in oversized.text


def test_runner_has_one_worker_and_secret_safe_exit_contracts(caplog) -> None:
    captured = []
    assert run_with_config(
        config(),
        application_factory=lambda settings: settings,
        server_runner=lambda application, server: captured.append(
            (application, server)
        ),
    ) == EXIT_OK
    assert captured[0][1].workers == 1
    assert captured[0][1].port == 8791

    assert run_with_config(config(workers=2)) == EXIT_CONFIG
    assert run_with_config(
        config(),
        application_factory=lambda _settings: (_ for _ in ()).throw(
            RuntimeError("credential-secret")
        ),
    ) == EXIT_TEMPFAIL
    assert run_with_config(
        config(),
        application_factory=lambda _settings: object(),
        server_runner=lambda _application, _server: (_ for _ in ()).throw(
            OSError("credential-secret")
        ),
    ) == EXIT_TEMPFAIL
    assert "credential-secret" not in caplog.text
