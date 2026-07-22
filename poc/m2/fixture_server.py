from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import os
import secrets

from coffer.keystone import (
    ApplicationCredentialPrincipal,
    InvalidApplicationCredential,
)
from coffer.authorization import RegistryScopeAuthorizer
from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.policy import create_enforcer
from coffer.token_api import build_token_application
from coffer.tokens import TokenIssuer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)


class FixtureAuthenticator:
    """Isolated M2 protocol fixture; never use this in a deployed service."""

    def __init__(self) -> None:
        self._credentials = {
            os.environ["COFFER_M2_MEMBER_CREDENTIAL_ID"]: (
                os.environ["COFFER_M2_MEMBER_CREDENTIAL_SECRET"],
                ("member",),
                os.environ["COFFER_M2_PROJECT_ID"],
            ),
            os.environ["COFFER_M2_READER_CREDENTIAL_ID"]: (
                os.environ["COFFER_M2_READER_CREDENTIAL_SECRET"],
                ("reader",),
                os.environ["COFFER_M2_PROJECT_ID"],
            ),
            os.environ["COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_ID"]: (
                os.environ["COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_SECRET"],
                ("member",),
                os.environ["COFFER_M2_PROJECT_B_ID"],
            ),
        }

    def authenticate(
        self, application_credential_id: str, application_credential_secret: str
    ) -> ApplicationCredentialPrincipal:
        expected = self._credentials.get(application_credential_id)
        if expected is None or not secrets.compare_digest(
            application_credential_secret, expected[0]
        ):
            raise InvalidApplicationCredential("fixture credential rejected")
        return ApplicationCredentialPrincipal(
            application_credential_id=application_credential_id,
            user_id="00000000-0000-4000-8000-000000000001",
            project_id=expected[2],
            roles=expected[1],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            audit_ids=("coffer-m2-fixture",),
        )


issuer = TokenIssuer.from_pem_file(
    os.environ["COFFER_M2_PRIVATE_KEY_FILE"],
    issuer="coffer-m2",
    service="coffer-m2-registry",
)
conf = new_config()
conf(args=[])
store = RepositoryStore(f"sqlite:///{os.environ['COFFER_M2_DATABASE_FILE']}")
for project_id, repository_names in (
    (
        os.environ["COFFER_M2_PROJECT_ID"],
        ("demo", "mount-target", "reader-denied"),
    ),
    (
        os.environ["COFFER_M2_PROJECT_B_ID"],
        ("demo", "mount-source", "mount-target"),
    ),
):
    for repository_name in repository_names:
        store.create(project_id, repository_name)
scope_authorizer = RegistryScopeAuthorizer(store, create_enforcer(conf))
application = build_token_application(
    FixtureAuthenticator(), scope_authorizer, issuer
)
