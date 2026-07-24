from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import sys
from typing import Any

from oslo_config import cfg

from coffer.config import parse_config, setup_logging
from coffer.runtime import (
    RuntimeConfigurationError,
    WSGIServerSettings,
    run_wsgi,
)
from coffer.schema import SchemaNotReady
from coffer.wsgi import build_product_application


LOG = logging.getLogger(__name__)
EXIT_OK = 0
EXIT_TEMPFAIL = 75
EXIT_CONFIG = 78


def run_with_config(
    conf: cfg.ConfigOpts,
    *,
    application_factory: Callable[[cfg.ConfigOpts], Any] = build_product_application,
    server_runner: Callable[[Any, WSGIServerSettings], None] = run_wsgi,
) -> int:
    try:
        settings = WSGIServerSettings.from_options(conf.api)
        application = application_factory(conf)
    except (RuntimeConfigurationError, SchemaNotReady, OSError, ValueError):
        LOG.error("api startup failed result=invalid_configuration")
        return EXIT_CONFIG
    except Exception:
        LOG.error("api startup failed result=dependency_unavailable")
        return EXIT_TEMPFAIL
    try:
        server_runner(application, settings)
    except (OSError, RuntimeError):
        LOG.error("api stopped result=dependency_unavailable")
        return EXIT_TEMPFAIL
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        conf = parse_config(args=argv)
    except SystemExit as exc:
        if exc.code in (None, EXIT_OK):
            raise
        print("api startup failed result=invalid_configuration", file=sys.stderr)
        return EXIT_CONFIG
    except cfg.Error:
        print("api startup failed result=invalid_configuration", file=sys.stderr)
        return EXIT_CONFIG
    try:
        setup_logging(conf)
    except (cfg.Error, OSError, ValueError):
        print("api startup failed result=invalid_configuration", file=sys.stderr)
        return EXIT_CONFIG
    return run_with_config(conf)
