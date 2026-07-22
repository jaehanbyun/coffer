from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from falcon import testing
import pytest
from keystoneauth1 import fixture as keystone_fixture
from keystonemiddleware.fixture import AuthTokenFixture

from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.wsgi import build_application


PROJECT_A_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_B_ID = "22222222-2222-4222-8222-222222222222"
USER_A_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.fixture
def auth_fixture() -> Iterator[AuthTokenFixture]:
    fixture = AuthTokenFixture()
    fixture.setUp()
    for token_id, project_id, user_id, roles in [
        ("project-a-reader", PROJECT_A_ID, USER_A_ID, ["reader"]),
        ("project-a-member", PROJECT_A_ID, USER_A_ID, ["member"]),
        (
            "project-b-member",
            PROJECT_B_ID,
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            ["member"],
        ),
    ]:
        fixture.add_token_data(
            token_id=token_id,
            user_id=user_id,
            user_name="same-name",
            user_domain_id=f"domain-{project_id[0]}",
            project_id=project_id,
            project_name="same-name",
            project_domain_id=f"domain-{project_id[0]}",
            role_list=roles,
        )
    fixture.add_token_data(
        token_id="unscoped-reader",
        user_id=USER_A_ID,
        user_name="same-name",
        user_domain_id="domain-a",
        role_list=["reader"],
    )
    fixture.add_token_data(
        token_id="expired-reader",
        expires=datetime.now(UTC) - timedelta(seconds=1),
        user_id=USER_A_ID,
        user_domain_id="domain-a",
        project_id=PROJECT_A_ID,
        project_domain_id="domain-a",
        role_list=["reader"],
    )
    domain_token = keystone_fixture.V3Token(
        user_id=USER_A_ID,
        user_domain_id="domain-a",
        domain_id="domain-a",
    )
    domain_token.add_role(name="reader")
    fixture.add_token(domain_token, token_id="domain-reader")

    system_token = keystone_fixture.V3Token(
        user_id=USER_A_ID,
        user_domain_id="domain-a",
    )
    system_token.set_system_scope()
    system_token.add_role(name="admin")
    fixture.add_token(system_token, token_id="system-admin")
    yield fixture
    fixture.cleanUp()


@pytest.fixture
def client(tmp_path: Any, auth_fixture: AuthTokenFixture) -> testing.TestClient:
    conf = new_config()
    conf(args=[])
    store = RepositoryStore(f"sqlite:///{tmp_path / 'coffer.sqlite'}")
    middleware = build_application(
        conf,
        store=store,
        auth_config={
            "www_authenticate_uri": "https://keystone.invalid/v3",
            "delay_auth_decision": "false",
            "service_token_roles_required": "true",
            "service_token_roles": "service",
            "token_cache_time": "-1",
        },
    )

    # Falcon's test client introspects a callable to distinguish WSGI from
    # ASGI. WebOb's wsgify descriptor hides AuthProtocol's signature.
    def wsgi_app(environ: dict[str, Any], start_response: Any) -> Any:
        return middleware(environ, start_response)

    return testing.TestClient(wsgi_app)
