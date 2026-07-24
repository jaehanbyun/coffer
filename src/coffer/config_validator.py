from __future__ import annotations

import argparse
from collections.abc import Sequence
import ssl
import sys
from urllib.parse import urlsplit

from oslo_config import cfg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from coffer.config import parse_config
from coffer.edge_runner import EdgeSettings, load_jwks
from coffer.quota_admission import RegistryTokenVerifier
from coffer.reconciliation_runner import RunnerSettings
from coffer.runtime import WSGIServerSettings
from coffer.tokens import TokenIssuer


EXIT_OK = 0
EXIT_CONFIG = 78
COMPONENTS = ("api", "edge", "reconcile", "bootstrap")


class ConfigValidationError(ValueError):
    pass


def _validate_database(connection: str) -> None:
    if not connection or not connection.strip():
        raise ConfigValidationError("database connection is required")
    try:
        url = make_url(connection)
    except (ArgumentError, ValueError) as exc:
        raise ConfigValidationError("database connection is invalid") from exc
    if not url.drivername:
        raise ConfigValidationError("database driver is required")
    if url.drivername != "sqlite" and (not url.database or not url.username):
        raise ConfigValidationError("network database identity is incomplete")


def _validate_https_url(value: str, *, label: str) -> None:
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ConfigValidationError(f"{label} has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigValidationError(
            f"{label} must be one credential-free HTTPS URL"
        )


def _validate_server_tls(settings: WSGIServerSettings) -> None:
    if settings.tls_certfile is None or settings.tls_keyfile is None:
        raise ConfigValidationError("server TLS certificate and key are required")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(settings.tls_certfile, settings.tls_keyfile)


def validate_component(conf: cfg.ConfigOpts, component: str) -> None:
    if component not in COMPONENTS:
        raise ConfigValidationError("unsupported Coffer component")
    _validate_database(conf.database.connection)

    if component == "bootstrap":
        return

    if component == "api":
        settings = WSGIServerSettings.from_options(
            conf.api,
            process_name="coffer-api",
        )
        _validate_server_tls(settings)
        if not conf.token.enabled:
            raise ConfigValidationError("API token service must be enabled")
        if not conf.token.key_id:
            raise ConfigValidationError("API token key_id is required")
        TokenIssuer.from_pem_file(
            conf.token.private_key_file,
            issuer=conf.token.issuer,
            service=conf.token.service,
            lifetime_seconds=conf.token.lifetime_seconds,
            key_id=conf.token.key_id,
        )
        _validate_https_url(conf.keystone.auth_url, label="Keystone auth_url")
        if conf.keystone.insecure:
            raise ConfigValidationError("Keystone TLS verification cannot be disabled")
        if conf.keystone.cafile:
            ssl.create_default_context(cafile=conf.keystone.cafile)
        return

    if component == "edge":
        settings = EdgeSettings.from_config(conf)
        _validate_server_tls(settings.server)
        RegistryTokenVerifier(
            load_jwks(settings.jwks_file),
            issuer=settings.issuer,
            service=settings.service,
        )
        return

    settings = RunnerSettings.from_config(conf)
    if not settings.upstream_url.startswith("https://"):
        raise ConfigValidationError(
            "reconciliation upstream must use verified HTTPS"
        )
    ssl.create_default_context(cafile=settings.cafile)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coffer-config-validate",
        description="Validate one rendered Coffer process configuration.",
    )
    parser.add_argument("--component", choices=COMPONENTS, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    options, config_args = parser.parse_known_args(argv)
    try:
        conf = parse_config(args=config_args)
        validate_component(conf, options.component)
    except (
        ConfigValidationError,
        cfg.Error,
        OSError,
        UnicodeError,
        ValueError,
    ):
        print(
            "configuration validation failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    print(f"configuration validation passed component={options.component}")
    return EXIT_OK
