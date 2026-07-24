from __future__ import annotations

from pathlib import Path

import pytest

from coffer.config import new_config
from coffer.config_validator import (
    ConfigValidationError,
    EXIT_CONFIG,
    EXIT_OK,
    _validate_database,
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
