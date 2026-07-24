from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from typing import Any

import falcon
from keystonemiddleware import auth_token
from oslo_config import cfg

from coffer.api import RepositoryCollectionResource, RepositoryResource
from coffer.authorization import RegistryScopeAuthorizer
from coffer.config import parse_config, setup_logging
from coffer.db import RepositoryStore
from coffer.keystone import create_authenticator
from coffer.observability import (
    CofferMetrics,
    HTTPMetricsMiddleware,
    build_operational_application,
)
from coffer.policy import create_enforcer
from coffer.token_api import build_token_application
from coffer.tokens import TokenIssuer


class PathDispatcher:
    def __init__(
        self,
        control_application: Any,
        token_application: Any | None = None,
        operational_application: Any | None = None,
    ) -> None:
        self._control_application = control_application
        self._token_application = token_application
        self._operational_application = operational_application

    def __call__(self, environ: dict[str, Any], start_response: Any) -> Any:
        path = environ.get("PATH_INFO")
        if path == "/auth/token" and self._token_application is not None:
            return self._token_application(environ, start_response)
        if path in {"/healthz", "/readyz", "/metrics"} and (
            self._operational_application is not None
        ):
            return self._operational_application(environ, start_response)
        return self._control_application(environ, start_response)


def build_application(
    conf: cfg.ConfigOpts,
    *,
    store: RepositoryStore | None = None,
    auth_config: Mapping[str, Any] | None = None,
    token_application: Any | None = None,
    operational_application: Any | None = None,
    enforcer: Any | None = None,
    metrics: CofferMetrics | None = None,
) -> Any:
    store = store or RepositoryStore(conf.database.connection)
    enforcer = enforcer or create_enforcer(conf)

    middleware = [HTTPMetricsMiddleware(metrics, "control")] if metrics else None
    application = falcon.App(middleware=middleware)
    collection = RepositoryCollectionResource(store, enforcer)
    repository = RepositoryResource(store, enforcer)
    application.add_route("/v1/repositories", collection)
    application.add_route("/v1/repositories/{repository_id}", repository)

    middleware_config: dict[str, Any]
    if auth_config is None:
        middleware_config = {"oslo_config_config": conf}
    else:
        middleware_config = dict(auth_config)
    control_application = auth_token.AuthProtocol(application, middleware_config)
    if token_application is None and operational_application is None:
        return control_application
    return PathDispatcher(
        control_application,
        token_application,
        operational_application,
    )


def build_product_application(conf: cfg.ConfigOpts) -> Any:
    store = RepositoryStore(conf.database.connection)
    enforcer = create_enforcer(conf)
    metrics = CofferMetrics()
    operational_application = build_operational_application(
        store,
        metrics,
        metrics_enabled=conf.observability.metrics_enabled,
    )
    token_application = None
    if conf.token.enabled:
        authenticator = create_authenticator(conf)
        issuer = TokenIssuer.from_pem_file(
            conf.token.private_key_file,
            issuer=conf.token.issuer,
            service=conf.token.service,
            lifetime_seconds=conf.token.lifetime_seconds,
            key_id=conf.token.key_id,
        )
        scope_authorizer = RegistryScopeAuthorizer(store, enforcer)
        token_application = build_token_application(
            authenticator, scope_authorizer, issuer, metrics
        )
    return build_application(
        conf,
        store=store,
        token_application=token_application,
        operational_application=operational_application,
        enforcer=enforcer,
        metrics=metrics,
    )


def create_application() -> Any:
    config_file = os.environ.get("COFFER_CONFIG_FILE")
    config_files: Sequence[str] | None = [config_file] if config_file else None
    conf = parse_config(args=[], default_config_files=config_files)
    setup_logging(conf)
    return build_product_application(conf)
