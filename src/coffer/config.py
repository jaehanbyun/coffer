from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy

from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_db import options as db_options
from oslo_log import log as oslo_log
from oslo_policy import opts as policy_opts


API_GROUP = cfg.OptGroup("api")
API_OPTS = [
    cfg.StrOpt("bind_host", default="127.0.0.1"),
    cfg.PortOpt("bind_port", default=8787),
    cfg.IntOpt("workers", default=2, min=1, max=128),
    cfg.IntOpt("threads", default=4, min=1, max=256),
    cfg.IntOpt("timeout_seconds", default=30, min=1, max=3600),
    cfg.IntOpt("graceful_timeout_seconds", default=30, min=1, max=3600),
    cfg.IntOpt("keepalive_seconds", default=5, min=1, max=300),
    cfg.StrOpt("tls_certfile"),
    cfg.StrOpt("tls_keyfile"),
]
EDGE_GROUP = cfg.OptGroup("edge")
EDGE_OPTS = [
    cfg.StrOpt("bind_host", default="127.0.0.1"),
    cfg.PortOpt("bind_port", default=8788),
    cfg.IntOpt("workers", default=2, min=1, max=128),
    cfg.IntOpt("threads", default=8, min=1, max=256),
    cfg.IntOpt("timeout_seconds", default=300, min=1, max=3600),
    cfg.IntOpt("graceful_timeout_seconds", default=30, min=1, max=3600),
    cfg.IntOpt("keepalive_seconds", default=5, min=1, max=300),
    cfg.StrOpt("tls_certfile"),
    cfg.StrOpt("tls_keyfile"),
    cfg.URIOpt("api_upstream_url"),
    cfg.URIOpt("registry_upstream_url"),
    cfg.StrOpt("api_cafile"),
    cfg.StrOpt("registry_cafile"),
    cfg.BoolOpt("allow_insecure_http", default=False),
    cfg.FloatOpt("api_upstream_timeout_seconds", default=30.0, min=0.1, max=300.0),
    cfg.FloatOpt(
        "registry_upstream_timeout_seconds", default=300.0, min=0.1, max=3600.0
    ),
    cfg.StrOpt("jwks_file"),
    cfg.URIOpt("token_realm"),
]
KEYSTONE_GROUP = cfg.OptGroup("keystone")
KEYSTONE_OPTS = [
    cfg.URIOpt("auth_url"),
    cfg.StrOpt("cafile"),
    cfg.BoolOpt("insecure", default=False),
    cfg.FloatOpt("timeout", default=10.0, min=0.1),
]
TOKEN_GROUP = cfg.OptGroup("token")
TOKEN_OPTS = [
    cfg.BoolOpt("enabled", default=False),
    cfg.StrOpt("issuer", default="coffer"),
    cfg.StrOpt("service", default="coffer-registry"),
    cfg.StrOpt("private_key_file"),
    cfg.StrOpt("key_id"),
    cfg.IntOpt("lifetime_seconds", default=300, min=60, max=300),
]
OBSERVABILITY_GROUP = cfg.OptGroup("observability")
OBSERVABILITY_OPTS = [
    cfg.BoolOpt("metrics_enabled", default=False),
]
RECONCILIATION_GROUP = cfg.OptGroup("reconciliation")
RECONCILIATION_OPTS = [
    cfg.StrOpt("mode", default="once", choices=("once", "periodic")),
    cfg.URIOpt("upstream_url"),
    cfg.StrOpt("cafile"),
    cfg.BoolOpt("allow_insecure_http", default=False),
    cfg.FloatOpt("timeout_seconds", default=10.0, min=0.1, max=60.0),
    cfg.StrOpt("worker_id"),
    cfg.IntOpt("stale_after_seconds", default=300, min=0, max=86400),
    cfg.IntOpt("lease_seconds", default=120, min=1, max=3600),
    cfg.IntOpt("batch_limit", default=10, min=1, max=1000),
    cfg.IntOpt("max_pages_per_cycle", default=100, min=1, max=1000),
    cfg.FloatOpt("interval_seconds", default=60.0, min=1.0, max=3600.0),
    cfg.FloatOpt("jitter_fraction", default=0.1, min=0.0, max=0.5),
    cfg.FloatOpt("retry_initial_seconds", default=5.0, min=0.1, max=3600.0),
    cfg.FloatOpt("retry_max_seconds", default=60.0, min=0.1, max=3600.0),
]


def new_config() -> cfg.ConfigOpts:
    conf = cfg.ConfigOpts()
    api_group = deepcopy(API_GROUP)
    conf.register_group(api_group)
    conf.register_opts(deepcopy(API_OPTS), group=api_group)
    edge_group = deepcopy(EDGE_GROUP)
    conf.register_group(edge_group)
    conf.register_opts(deepcopy(EDGE_OPTS), group=edge_group)
    keystone_group = deepcopy(KEYSTONE_GROUP)
    conf.register_group(keystone_group)
    conf.register_opts(deepcopy(KEYSTONE_OPTS), group=keystone_group)
    token_group = deepcopy(TOKEN_GROUP)
    conf.register_group(token_group)
    conf.register_opts(deepcopy(TOKEN_OPTS), group=token_group)
    observability_group = deepcopy(OBSERVABILITY_GROUP)
    conf.register_group(observability_group)
    conf.register_opts(deepcopy(OBSERVABILITY_OPTS), group=observability_group)
    reconciliation_group = deepcopy(RECONCILIATION_GROUP)
    conf.register_group(reconciliation_group)
    conf.register_opts(
        deepcopy(RECONCILIATION_OPTS), group=reconciliation_group
    )
    conf.register_opts(db_options.database_opts, group="database")
    oslo_log.register_options(conf)
    for group, options in policy_opts.list_opts():
        conf.register_opts(options, group=group)

    for group, options in auth_token.list_opts():
        conf.register_opts(options, group=group)

    conf.set_default("connection", "sqlite://", group="database")
    conf.set_default("delay_auth_decision", False, group="keystone_authtoken")
    conf.set_default("service_type", "oci-registry", group="keystone_authtoken")
    conf.set_default(
        "service_token_roles", ["service"], group="keystone_authtoken"
    )
    conf.set_default(
        "service_token_roles_required", True, group="keystone_authtoken"
    )
    return conf


def parse_config(
    args: Sequence[str] | None = None,
    *,
    default_config_files: Sequence[str] | None = None,
) -> cfg.ConfigOpts:
    conf = new_config()
    conf(
        args=args,
        project="coffer",
        version="0.1.0",
        default_config_files=default_config_files,
        validate_default_values=True,
    )
    return conf


def setup_logging(conf: cfg.ConfigOpts) -> None:
    oslo_log.setup(conf, "coffer", version="0.1.0")
