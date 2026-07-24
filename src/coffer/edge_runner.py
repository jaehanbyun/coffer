from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

from oslo_config import cfg

from coffer.config import parse_config, setup_logging
from coffer.db import RepositoryStore
from coffer.quota import QuotaStore
from coffer.quota_admission import (
    ManifestAdmissionService,
    RegistryTokenVerifier,
    build_manifest_admission_application,
)
from coffer.registry_proxy import (
    HTTPManifestUpstream,
    RegistryEdgeProxy,
    UpstreamOrigin,
)
from coffer.runtime import (
    RuntimeConfigurationError,
    WSGIServerSettings,
    run_wsgi,
)
from coffer.schema import SchemaNotReady


LOG = logging.getLogger(__name__)
EXIT_OK = 0
EXIT_TEMPFAIL = 75
EXIT_CONFIG = 78
MAX_JWKS_BYTES = 1024 * 1024


class EdgeConfigurationError(ValueError):
    pass


def _safe_header_value(value: str, *, name: str) -> str:
    if (
        not value
        or len(value) > 512
        or any(character in value for character in ('"', "\\", "\r", "\n"))
        or any(ord(character) < 0x20 for character in value)
    ):
        raise EdgeConfigurationError(f"edge {name} is not header-safe")
    return value


@dataclass(frozen=True, slots=True)
class EdgeSettings:
    server: WSGIServerSettings
    api_origin: UpstreamOrigin
    registry_origin: UpstreamOrigin
    jwks_file: str
    token_realm: str
    issuer: str
    service: str

    @classmethod
    def from_config(cls, conf: cfg.ConfigOpts) -> EdgeSettings:
        options = conf.edge
        required = {
            "api_upstream_url": options.api_upstream_url,
            "registry_upstream_url": options.registry_upstream_url,
            "jwks_file": options.jwks_file,
            "token_realm": options.token_realm,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise EdgeConfigurationError(
                "edge configuration is missing required values"
            )
        if not conf.token.issuer or not conf.token.service:
            raise EdgeConfigurationError("edge token issuer and service are required")
        issuer = _safe_header_value(conf.token.issuer, name="token issuer")
        service = _safe_header_value(conf.token.service, name="token service")
        token_realm = _safe_header_value(options.token_realm, name="token realm")
        realm = urlsplit(token_realm)
        if (
            realm.scheme != "https"
            or not realm.hostname
            or realm.username is not None
            or realm.password is not None
            or not realm.path
            or realm.query
            or realm.fragment
        ):
            raise EdgeConfigurationError(
                "edge token_realm must be one credential-free HTTPS URL"
            )
        api_origin = UpstreamOrigin.from_url(
            options.api_upstream_url,
            label="edge API upstream",
            timeout_seconds=options.api_upstream_timeout_seconds,
            cafile=options.api_cafile,
            allow_insecure_http=options.allow_insecure_http,
        )
        registry_origin = UpstreamOrigin.from_url(
            options.registry_upstream_url,
            label="edge registry upstream",
            timeout_seconds=options.registry_upstream_timeout_seconds,
            cafile=options.registry_cafile,
            allow_insecure_http=options.allow_insecure_http,
        )
        return cls(
            server=WSGIServerSettings.from_options(
                options,
                process_name="coffer-edge",
            ),
            api_origin=api_origin,
            registry_origin=registry_origin,
            jwks_file=options.jwks_file,
            token_realm=token_realm,
            issuer=issuer,
            service=service,
        )


def load_jwks(path: str) -> Mapping[str, object]:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JWKS_BYTES + 1)
    if len(raw) > MAX_JWKS_BYTES:
        raise EdgeConfigurationError("edge JWKS exceeds the maximum size")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise EdgeConfigurationError("edge JWKS must be a JSON object")
    return value


def build_product_application(
    conf: cfg.ConfigOpts,
    settings: EdgeSettings,
) -> RegistryEdgeProxy:
    repositories = RepositoryStore(conf.database.connection)
    quotas = QuotaStore(conf.database.connection)
    registry = HTTPManifestUpstream(settings.registry_origin)
    manifest_application = build_manifest_admission_application(
        RegistryTokenVerifier(
            load_jwks(settings.jwks_file),
            issuer=settings.issuer,
            service=settings.service,
        ),
        ManifestAdmissionService(repositories, quotas),
        registry,
        token_realm=settings.token_realm,
    )
    return RegistryEdgeProxy(
        manifest_application,
        settings.registry_origin,
        api_origin=settings.api_origin,
    )


def run_with_config(
    conf: cfg.ConfigOpts,
    *,
    application_factory: Callable[
        [cfg.ConfigOpts, EdgeSettings], Any
    ] = build_product_application,
    server_runner: Callable[[Any, WSGIServerSettings], None] = run_wsgi,
) -> int:
    try:
        settings = EdgeSettings.from_config(conf)
        application = application_factory(conf, settings)
    except (
        EdgeConfigurationError,
        RuntimeConfigurationError,
        SchemaNotReady,
        OSError,
        UnicodeError,
        ValueError,
    ):
        LOG.error("edge startup failed result=invalid_configuration")
        return EXIT_CONFIG
    except Exception:
        LOG.error("edge startup failed result=dependency_unavailable")
        return EXIT_TEMPFAIL
    try:
        server_runner(application, settings.server)
    except (OSError, RuntimeError):
        LOG.error("edge stopped result=dependency_unavailable")
        return EXIT_TEMPFAIL
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        conf = parse_config(args=argv)
    except SystemExit as exc:
        if exc.code in (None, EXIT_OK):
            raise
        print("edge startup failed result=invalid_configuration", file=sys.stderr)
        return EXIT_CONFIG
    except cfg.Error:
        print("edge startup failed result=invalid_configuration", file=sys.stderr)
        return EXIT_CONFIG
    try:
        setup_logging(conf)
    except (cfg.Error, OSError, ValueError):
        print("edge startup failed result=invalid_configuration", file=sys.stderr)
        return EXIT_CONFIG
    return run_with_config(conf)
