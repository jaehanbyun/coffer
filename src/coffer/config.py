from __future__ import annotations

from collections.abc import Sequence

from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_db import options as db_options
from oslo_log import log as oslo_log
from oslo_policy import opts as policy_opts


API_GROUP = cfg.OptGroup("api")
API_OPTS = [
    cfg.StrOpt("bind_host", default="127.0.0.1"),
    cfg.PortOpt("bind_port", default=8080),
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


def new_config() -> cfg.ConfigOpts:
    conf = cfg.ConfigOpts()
    conf.register_group(API_GROUP)
    conf.register_opts(API_OPTS, group=API_GROUP)
    conf.register_group(KEYSTONE_GROUP)
    conf.register_opts(KEYSTONE_OPTS, group=KEYSTONE_GROUP)
    conf.register_group(TOKEN_GROUP)
    conf.register_opts(TOKEN_OPTS, group=TOKEN_GROUP)
    conf.register_group(OBSERVABILITY_GROUP)
    conf.register_opts(OBSERVABILITY_OPTS, group=OBSERVABILITY_GROUP)
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
