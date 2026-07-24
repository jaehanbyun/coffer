from __future__ import annotations

import logging

from coffer.api_runner import EXIT_CONFIG, EXIT_OK, EXIT_TEMPFAIL, run_with_config
from coffer.config import new_config
from coffer.runtime import WSGIServerSettings


def config(**overrides: object):
    conf = new_config()
    conf(args=[])
    for name, value in overrides.items():
        conf.set_override(name, value, group="api")
    return conf


def test_api_uses_the_product_port_and_fixed_gunicorn_contract() -> None:
    application = object()
    captured: list[tuple[object, WSGIServerSettings]] = []

    exit_code = run_with_config(
        config(),
        application_factory=lambda _conf: application,
        server_runner=lambda app, settings: captured.append((app, settings)),
    )

    assert exit_code == EXIT_OK
    assert captured == [
        (
            application,
            WSGIServerSettings(
                process_name="coffer-api",
                host="127.0.0.1",
                port=8787,
                workers=2,
                threads=4,
                timeout_seconds=30,
                graceful_timeout_seconds=30,
                keepalive_seconds=5,
                tls_certfile=None,
                tls_keyfile=None,
            ),
        )
    ]
    assert captured[0][1].gunicorn_options() == {
        "proc_name": "coffer-api",
        "bind": "127.0.0.1:8787",
        "workers": 2,
        "worker_class": "gthread",
        "threads": 4,
        "preload_app": False,
        "timeout": 30,
        "graceful_timeout": 30,
        "keepalive": 5,
        "accesslog": None,
        "errorlog": "-",
        "capture_output": False,
        "umask": 0o027,
    }


def test_api_rejects_invalid_bind_and_has_secret_safe_failures(
    caplog,
) -> None:
    caplog.set_level(logging.INFO)

    assert run_with_config(
        config(bind_host=" invalid"),
        application_factory=lambda _conf: object(),
        server_runner=lambda _app, _settings: None,
    ) == EXIT_CONFIG
    assert run_with_config(
        config(tls_certfile="/etc/coffer/api.crt"),
        application_factory=lambda _conf: object(),
        server_runner=lambda _app, _settings: None,
    ) == EXIT_CONFIG
    assert run_with_config(
        config(),
        application_factory=lambda _conf: (_ for _ in ()).throw(
            RuntimeError("credential-secret")
        ),
        server_runner=lambda _app, _settings: None,
    ) == EXIT_TEMPFAIL
    assert run_with_config(
        config(),
        application_factory=lambda _conf: object(),
        server_runner=lambda _app, _settings: (_ for _ in ()).throw(
            OSError("credential-secret")
        ),
    ) == EXIT_TEMPFAIL
    assert "credential-secret" not in caplog.text
