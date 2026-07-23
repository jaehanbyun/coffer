from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import os
import secrets
from typing import Any

from coffer.authorization import RegistryScopeAuthorizer
from coffer.config import new_config
from coffer.db import RepositoryAlreadyExists, RepositoryStore
from coffer.keystone import ApplicationCredentialPrincipal, InvalidApplicationCredential
from coffer.policy import create_enforcer
from coffer.quota import QuotaStore
from coffer.quota_admission import (
    ManifestAdmissionService,
    RegistryTokenVerifier,
    build_manifest_admission_application,
)
from coffer.registry_proxy import HTTPManifestUpstream, RegistryEdgeProxy
from coffer.token_api import build_token_application
from coffer.tokens import TokenIssuer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)

PROJECT_A_REPOSITORIES = (
    "docker-proof",
    "podman-proof",
    "skopeo-proof",
    "concurrent-a",
    "concurrent-b",
    "staging",
)
PROJECT_B_REPOSITORIES = ("unavailable",)


class FixtureAuthenticator:
    def authenticate(
        self, application_credential_id: str, application_credential_secret: str
    ) -> ApplicationCredentialPrincipal:
        credentials = {
            os.environ["COFFER_QUOTA_MEMBER_ID"]: (
                os.environ["COFFER_QUOTA_MEMBER_SECRET"],
                os.environ["COFFER_QUOTA_PROJECT_A"],
            ),
            os.environ["COFFER_QUOTA_PROJECT_B_MEMBER_ID"]: (
                os.environ["COFFER_QUOTA_PROJECT_B_MEMBER_SECRET"],
                os.environ["COFFER_QUOTA_PROJECT_B"],
            ),
        }
        expected = credentials.get(application_credential_id)
        if expected is None or not secrets.compare_digest(
            application_credential_secret, expected[0]
        ):
            raise InvalidApplicationCredential("fixture credential rejected")
        return ApplicationCredentialPrincipal(
            application_credential_id=application_credential_id,
            user_id="00000000-0000-4000-8000-000000000001",
            project_id=expected[1],
            roles=("member",),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            audit_ids=("coffer-quota-fixture",),
        )


database = os.environ["COFFER_QUOTA_DATABASE"]
repositories = RepositoryStore(database, bootstrap_schema=True)
for project_id, names in (
    (os.environ["COFFER_QUOTA_PROJECT_A"], PROJECT_A_REPOSITORIES),
    (os.environ["COFFER_QUOTA_PROJECT_B"], PROJECT_B_REPOSITORIES),
):
    for name in names:
        try:
            repositories.create(project_id, name)
        except RepositoryAlreadyExists:
            pass

quotas = QuotaStore(database, bootstrap_schema=True)
quotas.set_limit(os.environ["COFFER_QUOTA_PROJECT_A"], 16 * 1024 * 1024)

issuer = TokenIssuer.from_pem_file(
    os.environ["COFFER_QUOTA_PRIVATE_KEY"],
    issuer="coffer-quota-poc",
    service="coffer-quota-registry",
)
conf = new_config()
conf(args=[])
authorizer = RegistryScopeAuthorizer(repositories, create_enforcer(conf))
token_application = build_token_application(
    FixtureAuthenticator(), authorizer, issuer
)
manifest_application = build_manifest_admission_application(
    RegistryTokenVerifier(
        issuer.jwks(), issuer=issuer.issuer, service=issuer.service
    ),
    ManifestAdmissionService(repositories, quotas),
    HTTPManifestUpstream(os.environ["COFFER_QUOTA_UPSTREAM"]),
    token_realm="http://edge:5000/auth/token",
)
registry_application = RegistryEdgeProxy(
    manifest_application, os.environ["COFFER_QUOTA_UPSTREAM"]
)


class FixtureApplication:
    def __call__(self, environ: dict[str, Any], start_response: Any) -> Any:
        if environ.get("PATH_INFO") == "/auth/token":
            return token_application(environ, start_response)
        return registry_application(environ, start_response)


application = FixtureApplication()
