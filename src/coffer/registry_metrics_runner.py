from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import http.client
import ipaddress
import logging
import sys
from typing import Any
from urllib.parse import urlsplit

import falcon
from oslo_config import cfg
from prometheus_client.exposition import CONTENT_TYPE_LATEST

from coffer.config import parse_config, setup_logging
from coffer.observability import HealthResource
from coffer.runtime import (
    RuntimeConfigurationError,
    WSGIServerSettings,
    run_wsgi,
)


LOG = logging.getLogger(__name__)
EXIT_OK = 0
EXIT_TEMPFAIL = 75
EXIT_CONFIG = 78
MAX_METRICS_BYTES = 16 * 1024 * 1024


class RegistryMetricsConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RegistryMetricsSettings:
    server: WSGIServerSettings
    upstream_host: str
    upstream_port: int
    upstream_timeout_seconds: float

    @classmethod
    def from_config(cls, conf: cfg.ConfigOpts) -> RegistryMetricsSettings:
        options = conf.registry_metrics
        if not options.upstream_url:
            raise RegistryMetricsConfigurationError(
                "registry metrics upstream URL is required"
            )
        parsed = urlsplit(options.upstream_url)
        try:
            port = parsed.port
        except ValueError as error:
            raise RegistryMetricsConfigurationError(
                "registry metrics upstream port is invalid"
            ) from error
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/metrics"
            or parsed.query
            or parsed.fragment
        ):
            raise RegistryMetricsConfigurationError(
                "registry metrics upstream must be one loopback HTTP metrics URL"
            )
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = parsed.hostname == "localhost"
        if not loopback:
            raise RegistryMetricsConfigurationError(
                "registry metrics upstream must use loopback"
            )
        server = WSGIServerSettings.from_options(
            options,
            process_name="coffer-registry-metrics",
        )
        if server.workers != 1:
            raise RegistryMetricsConfigurationError(
                "registry metrics proxy requires one worker"
            )
        return cls(
            server=server,
            upstream_host=parsed.hostname,
            upstream_port=port,
            upstream_timeout_seconds=options.upstream_timeout_seconds,
        )


class RegistryMetricsResource:
    def __init__(self, settings: RegistryMetricsSettings) -> None:
        self._settings = settings

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        resp.set_header("Cache-Control", "no-store")
        if req.query_string:
            raise falcon.HTTPNotFound()
        connection = http.client.HTTPConnection(
            self._settings.upstream_host,
            self._settings.upstream_port,
            timeout=self._settings.upstream_timeout_seconds,
        )
        try:
            connection.request("GET", "/metrics")
            upstream = connection.getresponse()
            try:
                body = upstream.read(MAX_METRICS_BYTES + 1)
                if upstream.status != 200 or len(body) > MAX_METRICS_BYTES:
                    raise OSError("registry metrics response is invalid")
            finally:
                upstream.close()
        except Exception:
            resp.status = falcon.HTTP_503
            resp.media = {"status": "unavailable"}
            return
        finally:
            connection.close()
        resp.content_type = CONTENT_TYPE_LATEST
        resp.data = body


def build_application(settings: RegistryMetricsSettings) -> falcon.App:
    application = falcon.App()
    application.add_route("/healthz", HealthResource())
    application.add_route("/metrics", RegistryMetricsResource(settings))
    return application


def run_with_config(
    conf: cfg.ConfigOpts,
    *,
    application_factory: Callable[[RegistryMetricsSettings], Any] = build_application,
    server_runner: Callable[[Any, WSGIServerSettings], None] = run_wsgi,
) -> int:
    try:
        settings = RegistryMetricsSettings.from_config(conf)
        application = application_factory(settings)
    except (
        RegistryMetricsConfigurationError,
        RuntimeConfigurationError,
        OSError,
        ValueError,
    ):
        LOG.error("registry metrics startup failed result=invalid_configuration")
        return EXIT_CONFIG
    except Exception:
        LOG.error("registry metrics startup failed result=dependency_unavailable")
        return EXIT_TEMPFAIL
    try:
        server_runner(application, settings.server)
    except (OSError, RuntimeError):
        LOG.error("registry metrics stopped result=dependency_unavailable")
        return EXIT_TEMPFAIL
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        conf = parse_config(args=argv)
    except SystemExit as exc:
        if exc.code in (None, EXIT_OK):
            raise
        print(
            "registry metrics startup failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    except cfg.Error:
        print(
            "registry metrics startup failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    try:
        setup_logging(conf)
    except (cfg.Error, OSError, ValueError):
        print(
            "registry metrics startup failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    return run_with_config(conf)
