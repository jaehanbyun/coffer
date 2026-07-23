from __future__ import annotations

import logging
import os

from coffer.authorization import RegistryScopeAuthorizer
from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.keystone import ApplicationCredentialAuthenticator
from coffer.observability import CofferMetrics, build_operational_application
from coffer.policy import create_enforcer
from coffer.token_api import build_token_application
from coffer.tokens import TokenIssuer
from coffer.wsgi import PathDispatcher


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)

authenticator = ApplicationCredentialAuthenticator(
    auth_url=os.environ["COFFER_INTEGRATION_AUTH_URL"],
    verify=os.environ["COFFER_INTEGRATION_KEYSTONE_CA"],
    timeout=10.0,
)
store = RepositoryStore(
    f"sqlite:///{os.environ['COFFER_INTEGRATION_DATABASE_FILE']}",
    bootstrap_schema=True,
)
conf = new_config()
conf(args=[])
authorizer = RegistryScopeAuthorizer(store, create_enforcer(conf))
metrics = CofferMetrics()
issuer = TokenIssuer.from_pem_file(
    os.environ["COFFER_INTEGRATION_SIGNING_KEY"],
    issuer="coffer-real-poc",
    service="coffer-registry-poc",
    lifetime_seconds=300,
)
token_application = build_token_application(
    authenticator, authorizer, issuer, metrics
)
operational_application = build_operational_application(
    store, metrics, metrics_enabled=True
)
application = PathDispatcher(
    token_application,
    token_application,
    operational_application,
)
