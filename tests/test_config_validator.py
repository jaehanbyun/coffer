from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from coffer.config import new_config
from coffer.config_validator import (
    ConfigValidationError,
    EXIT_CONFIG,
    EXIT_OK,
    _validate_database,
    _validate_endpoint_set,
    _validate_https_url,
    main,
    validate_component,
)


def test_bootstrap_component_accepts_a_static_database_url() -> None:
    conf = new_config()
    conf.set_override("connection", "sqlite:////tmp/coffer.db", group="database")

    validate_component(conf, "bootstrap")


@pytest.mark.parametrize(
    "connection",
    (
        "",
        "not a database URL",
        "mysql+pymysql://localhost/coffer",
    ),
)
def test_database_validation_rejects_incomplete_connections(
    connection: str,
) -> None:
    with pytest.raises(ConfigValidationError):
        _validate_database(connection)


@pytest.mark.parametrize(
    "value",
    (
        "http://keystone.example/v3",
        "https://user@keystone.example/v3",
        "https://keystone.example/v3?secret=value",
        "https://keystone.example:invalid/v3",
    ),
)
def test_https_url_validation_rejects_unsafe_origins(value: str) -> None:
    with pytest.raises(ConfigValidationError):
        _validate_https_url(value, label="dependency")


def test_public_endpoint_set_requires_one_https_origin_and_exact_paths() -> None:
    conf = new_config()
    conf(args=[])
    conf.set_override(
        "control_url", "https://registry.example:18788/v1", group="endpoint"
    )
    conf.set_override(
        "registry_url", "https://registry.example:18788/v2/", group="endpoint"
    )
    conf.set_override(
        "token_url",
        "https://registry.example:18788/auth/token",
        group="endpoint",
    )

    _validate_endpoint_set(conf)

    conf.set_override(
        "token_url",
        "https://other.example:18788/auth/token",
        group="endpoint",
    )
    with pytest.raises(ConfigValidationError, match="share one origin"):
        _validate_endpoint_set(conf)

    conf.set_override(
        "token_url",
        "https://registry.example:18788/token",
        group="endpoint",
    )
    with pytest.raises(ConfigValidationError, match="endpoint paths"):
        _validate_endpoint_set(conf)


def test_cli_returns_fixed_secret_safe_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "coffer.conf"
    config.write_text("[database]\nconnection = \n", encoding="utf-8")

    result = main(
        [
            "--component",
            "bootstrap",
            "--config-file",
            str(config),
        ]
    )

    captured = capsys.readouterr()
    assert result == EXIT_CONFIG
    assert captured.out == ""
    assert captured.err == (
        "configuration validation failed result=invalid_configuration\n"
    )
    assert str(config) not in captured.err


def test_cli_accepts_static_bootstrap_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "coffer.conf"
    config.write_text(
        "[database]\nconnection = sqlite:////tmp/coffer.db\n",
        encoding="utf-8",
    )

    result = main(
        [
            "--component",
            "bootstrap",
            "--config-file",
            str(config),
        ]
    )

    captured = capsys.readouterr()
    assert result == EXIT_OK
    assert captured.out == (
        "configuration validation passed component=bootstrap\n"
    )
    assert captured.err == ""


def test_registry_metrics_validation_requires_server_tls_without_database(
    tmp_path: Path,
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "metrics")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .sign(key, hashes.SHA256())
    )
    certificate_path = tmp_path / "metrics.crt"
    key_path = tmp_path / "metrics.key"
    certificate_path.write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    conf = new_config()
    conf(args=[])
    conf.set_override(
        "upstream_url",
        "http://127.0.0.1:8792/metrics",
        group="registry_metrics",
    )
    conf.set_override(
        "tls_certfile",
        str(certificate_path),
        group="registry_metrics",
    )
    conf.set_override(
        "tls_keyfile",
        str(key_path),
        group="registry_metrics",
    )

    validate_component(conf, "registry-metrics")


def test_periodic_reconciliation_validation_requires_management_tls(
    tmp_path: Path,
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reconcile")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(2)
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .sign(key, hashes.SHA256())
    )
    certificate_path = tmp_path / "reconcile.crt"
    key_path = tmp_path / "reconcile.key"
    certificate_path.write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    credential_id_path = tmp_path / "credential-id"
    credential_secret_path = tmp_path / "credential-secret"
    credential_id_path.write_text(
        "33333333-3333-4333-8333-333333333333",
        encoding="utf-8",
    )
    credential_secret_path.write_text(
        "credential-secret-value",
        encoding="utf-8",
    )
    credential_id_path.chmod(0o600)
    credential_secret_path.chmod(0o600)
    conf = new_config()
    conf(args=[])
    conf.set_override(
        "connection",
        f"sqlite:///{tmp_path / 'coffer.sqlite'}",
        group="database",
    )
    conf.set_override("mode", "periodic", group="reconciliation")
    conf.set_override(
        "upstream_url",
        "https://registry.internal.example",
        group="reconciliation",
    )
    conf.set_override(
        "cafile",
        str(certificate_path),
        group="reconciliation",
    )
    conf.set_override(
        "authentication_mode",
        "maintenance",
        group="reconciliation",
    )
    conf.set_override(
        "worker_id",
        "reconciler-controller-1",
        group="reconciliation",
    )
    conf.set_override(
        "lease_seconds",
        310,
        group="reconciliation",
    )
    conf.set_override(
        "maintenance_token_url",
        (
            "https://registry.internal.example:8790"
            "/v1/internal/maintenance/registry-token"
        ),
        group="reconciliation",
    )
    conf.set_override(
        "application_credential_id_file",
        str(credential_id_path),
        group="reconciliation",
    )
    conf.set_override(
        "application_credential_secret_file",
        str(credential_secret_path),
        group="reconciliation",
    )
    conf.set_override(
        "maintenance_client_certfile",
        str(certificate_path),
        group="reconciliation",
    )
    conf.set_override(
        "maintenance_client_keyfile",
        str(key_path),
        group="reconciliation",
    )
    conf.set_override(
        "maintenance_service_project_id",
        "11111111-1111-4111-8111-111111111111",
        group="reconciliation",
    )
    conf.set_override(
        "maintenance_user_id",
        "22222222-2222-4222-8222-222222222222",
        group="reconciliation",
    )
    conf.set_override(
        "auth_url",
        "https://keystone.internal.example/v3",
        group="keystone",
    )
    conf.set_override(
        "cafile",
        str(certificate_path),
        group="keystone",
    )
    conf.set_override(
        "management_tls_certfile",
        str(certificate_path),
        group="reconciliation",
    )
    conf.set_override(
        "management_tls_keyfile",
        str(key_path),
        group="reconciliation",
    )

    validate_component(conf, "reconcile")
    conf.clear_override(
        "management_tls_keyfile",
        group="reconciliation",
    )
    with pytest.raises(ValueError, match="management TLS"):
        validate_component(conf, "reconcile")
