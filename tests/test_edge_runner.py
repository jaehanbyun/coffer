from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa

from coffer.bootstrap import upgrade_schema
from coffer.config import new_config
from coffer.edge_runner import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_TEMPFAIL,
    EdgeSettings,
    build_product_application,
    run_with_config,
)
from coffer.registry_proxy import RegistryEdgeProxy
from coffer.tokens import TokenIssuer


def config(**overrides: object):
    conf = new_config()
    conf(args=[])
    baseline = {
        "api_upstream_url": "http://127.0.0.1:8787",
        "registry_upstream_url": "http://127.0.0.1:8789",
        "allow_insecure_http": True,
        "jwks_file": "/etc/coffer/jwks.json",
        "token_realm": "https://registry.example/auth/token",
    }
    baseline.update(overrides)
    for name, value in baseline.items():
        conf.set_override(name, value, group="edge")
    return conf


def test_edge_uses_product_port_and_separate_origins() -> None:
    captured = []

    exit_code = run_with_config(
        config(),
        application_factory=lambda _conf, settings: settings,
        server_runner=lambda application, server: captured.append(
            (application, server)
        ),
    )

    assert exit_code == EXIT_OK
    settings: EdgeSettings = captured[0][0]
    assert captured[0][1].bind == "127.0.0.1:8788"
    assert captured[0][1].process_name == "coffer-edge"
    assert settings.api_origin.port == 8787
    assert settings.registry_origin.port == 8789
    assert settings.server.threads == 8
    assert settings.server.timeout_seconds == 300
    assert settings.server.tls_certfile is None


def test_edge_rejects_missing_downgraded_and_malformed_configuration(
    caplog,
) -> None:
    caplog.set_level(logging.INFO)

    assert run_with_config(
        config(api_upstream_url=None),
        application_factory=lambda _conf, settings: settings,
        server_runner=lambda _application, _server: None,
    ) == EXIT_CONFIG
    assert run_with_config(
        config(
            registry_upstream_url="http://registry.internal:8789",
            allow_insecure_http=True,
        ),
        application_factory=lambda _conf, settings: settings,
        server_runner=lambda _application, _server: None,
    ) == EXIT_CONFIG
    assert run_with_config(
        config(token_realm="http://registry.example/auth/token"),
        application_factory=lambda _conf, settings: settings,
        server_runner=lambda _application, _server: None,
    ) == EXIT_CONFIG
    assert run_with_config(
        config(token_realm='https://registry.example/auth/"token'),
        application_factory=lambda _conf, settings: settings,
        server_runner=lambda _application, _server: None,
    ) == EXIT_CONFIG
    assert run_with_config(
        config(tls_keyfile="/etc/coffer/edge.key"),
        application_factory=lambda _conf, settings: settings,
        server_runner=lambda _application, _server: None,
    ) == EXIT_CONFIG
    assert "registry.internal" not in caplog.text


def test_edge_product_factory_validates_schema_and_jwks(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'coffer.sqlite'}"
    upgrade_schema(database_url)
    issuer = TokenIssuer(
        private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        issuer="coffer-edge-test",
        service="coffer-registry",
        clock=lambda: datetime.now(UTC),
    )
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text(json.dumps(issuer.jwks()), encoding="utf-8")
    conf = config(jwks_file=str(jwks_path))
    conf.set_override("connection", database_url, group="database")
    conf.set_override("issuer", issuer.issuer, group="token")
    conf.set_override("service", issuer.service, group="token")
    settings = EdgeSettings.from_config(conf)

    application = build_product_application(conf, settings)

    assert isinstance(application, RegistryEdgeProxy)


def test_edge_failures_have_stable_secret_safe_exit_contracts(
    caplog,
) -> None:
    caplog.set_level(logging.INFO)

    assert run_with_config(
        config(),
        application_factory=lambda _conf, _settings: (_ for _ in ()).throw(
            RuntimeError("credential-secret")
        ),
        server_runner=lambda _application, _server: None,
    ) == EXIT_TEMPFAIL
    assert run_with_config(
        config(),
        application_factory=lambda _conf, _settings: object(),
        server_runner=lambda _application, _server: (_ for _ in ()).throw(
            OSError("credential-secret")
        ),
    ) == EXIT_TEMPFAIL
    assert "credential-secret" not in caplog.text
