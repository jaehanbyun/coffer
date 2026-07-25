from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import rsa
from falcon import testing
from keystoneauth1 import fixture as keystone_fixture
from keystonemiddleware.fixture import AuthTokenFixture

from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.maintenance_token import (
    AuthorizedRepositoryRead,
    INTERNAL_TOKEN_PATH,
    MaintenancePolicy,
    MaintenanceTokenBroker,
    MaintenanceTokenResource,
)
from coffer.tokens import TokenIssuer
from coffer.wsgi import build_application


SERVICE_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MAINTENANCE_USER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TENANT_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "22222222-2222-4222-8222-222222222222"
RESERVATION_ID = "33333333-3333-4333-8333-333333333333"
CLAIM_TOKEN = "44444444-4444-4444-8444-444444444444"
WORKLOAD_ID = "reconciler-a"
SERVICE = "coffer-registry"
ACCESS_RULE = {
    "id": "maintenance-rule",
    "service": "oci-registry",
    "method": "POST",
    "path": INTERNAL_TOKEN_PATH,
}


class FixedAuthority:
    def __init__(self, expires_at: datetime) -> None:
        self._expires_at = expires_at

    def authorize(self, _request, *, workload_id: str, checked_at: datetime):
        assert workload_id == WORKLOAD_ID
        assert checked_at.tzinfo is not None
        return AuthorizedRepositoryRead(
            project_id=TENANT_PROJECT_ID,
            repository_name="server-route",
            authority_id=RESERVATION_ID,
            expires_at=self._expires_at,
        )


def _token(
    *,
    expires_at: datetime,
    application_credential: bool,
    restricted: bool = True,
) -> keystone_fixture.V3Token:
    token = keystone_fixture.V3Token(
        expires=expires_at,
        user_id=MAINTENANCE_USER_ID,
        user_domain_id="service-domain",
        project_id=SERVICE_PROJECT_ID,
        project_domain_id="service-domain",
        methods=["application_credential"] if application_credential else ["password"],
    )
    token.add_role(name="service")
    token.add_role(name="registry_maintenance")
    token.add_service("oci-registry", name="coffer")
    if application_credential:
        token.set_application_credential(
            "maintenance-credential",
            access_rules=[ACCESS_RULE] if restricted else None,
        )
    return token


def _client(
    tmp_path: Path,
    *,
    inject_workload: bool = True,
) -> tuple[testing.TestClient, AuthTokenFixture]:
    now = datetime.now(UTC).replace(microsecond=0)
    auth_fixture = AuthTokenFixture()
    auth_fixture.setUp()
    auth_fixture.add_token(
        _token(
            expires_at=now + timedelta(hours=1),
            application_credential=True,
        ),
        token_id="maintenance-app-credential",
    )
    auth_fixture.add_token(
        _token(
            expires_at=now + timedelta(hours=1),
            application_credential=False,
        ),
        token_id="maintenance-password-token",
    )
    auth_fixture.add_token(
        _token(
            expires_at=now + timedelta(hours=1),
            application_credential=True,
            restricted=False,
        ),
        token_id="maintenance-unrestricted-credential",
    )
    conf = new_config()
    conf(args=[])
    store = RepositoryStore(
        f"sqlite:///{tmp_path / 'maintenance-api.sqlite'}",
        bootstrap_schema=True,
    )
    issuer = TokenIssuer(
        private_key=rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        ),
        issuer="https://coffer.internal/auth/token",
        service=SERVICE,
        clock=lambda: now,
    )
    broker = MaintenanceTokenBroker(
        policy=MaintenancePolicy(
            service_project_id=SERVICE_PROJECT_ID,
            maintenance_user_id=MAINTENANCE_USER_ID,
            workload_ids=frozenset({WORKLOAD_ID}),
        ),
        authority=FixedAuthority(now + timedelta(minutes=2)),
        issuer=issuer,
        clock=lambda: now,
    )
    application = build_application(
        conf,
        store=store,
        auth_config={
            "www_authenticate_uri": "https://keystone.invalid/v3",
            "delay_auth_decision": "false",
            "service_token_roles_required": "true",
            "service_token_roles": "service",
            "service_type": "oci-registry",
            "token_cache_time": "-1",
        },
        maintenance_resource=MaintenanceTokenResource(broker),
    )

    def wsgi_app(environ: dict[str, Any], start_response: Any) -> Any:
        if inject_workload:
            environ["coffer.maintenance_workload_id"] = WORKLOAD_ID
        return application(environ, start_response)

    return testing.TestClient(wsgi_app), auth_fixture


def _request() -> dict[str, object]:
    return {
        "mode": "reconciliation",
        "repository_id": REPOSITORY_ID,
        "reservation_id": RESERVATION_ID,
        "claim_token": CLAIM_TOKEN,
        "expected_version": 1,
    }


def test_internal_route_uses_middleware_app_credential_and_no_store(
    tmp_path: Path,
) -> None:
    client, auth_fixture = _client(tmp_path)
    try:
        result = client.simulate_post(
            INTERNAL_TOKEN_PATH,
            headers={"X-Auth-Token": "maintenance-app-credential"},
            json=_request(),
        )
    finally:
        auth_fixture.cleanUp()

    assert result.status_code == 200
    assert result.json["expires_in"] == 120
    assert set(result.json) == {"token", "expires_in", "issued_at"}
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["pragma"] == "no-cache"


def test_password_token_cannot_impersonate_maintenance_identity(
    tmp_path: Path,
) -> None:
    client, auth_fixture = _client(tmp_path)
    try:
        result = client.simulate_post(
            INTERNAL_TOKEN_PATH,
            headers={"X-Auth-Token": "maintenance-password-token"},
            json=_request(),
        )
    finally:
        auth_fixture.cleanUp()

    assert result.status_code == 403
    assert result.json == {"title": "Maintenance token denied"}


def test_unrestricted_application_credential_is_rejected(
    tmp_path: Path,
) -> None:
    client, auth_fixture = _client(tmp_path)
    try:
        result = client.simulate_post(
            INTERNAL_TOKEN_PATH,
            headers={"X-Auth-Token": "maintenance-unrestricted-credential"},
            json=_request(),
        )
    finally:
        auth_fixture.cleanUp()

    assert result.status_code == 403
    assert result.json == {"title": "Maintenance token denied"}


def test_access_rule_rejects_other_control_path(tmp_path: Path) -> None:
    client, auth_fixture = _client(tmp_path)
    try:
        result = client.simulate_get(
            "/v1/repositories",
            headers={"X-Auth-Token": "maintenance-app-credential"},
        )
    finally:
        auth_fixture.cleanUp()

    assert result.status_code == 401


def test_http_header_cannot_replace_trusted_mtls_workload_context(
    tmp_path: Path,
) -> None:
    client, auth_fixture = _client(tmp_path, inject_workload=False)
    try:
        result = client.simulate_post(
            INTERNAL_TOKEN_PATH,
            headers={
                "X-Auth-Token": "maintenance-app-credential",
                "X-Coffer-Maintenance-Workload": WORKLOAD_ID,
            },
            json=_request(),
        )
    finally:
        auth_fixture.cleanUp()

    assert result.status_code == 403


def test_invalid_request_and_logs_do_not_retain_caller_authority(
    tmp_path: Path,
    caplog,
) -> None:
    client, auth_fixture = _client(tmp_path)
    caplog.set_level(logging.INFO)
    try:
        result = client.simulate_post(
            INTERNAL_TOKEN_PATH,
            headers={"X-Auth-Token": "maintenance-app-credential"},
            json={
                **_request(),
                "repository": "credential-secret/repository",
            },
        )
    finally:
        auth_fixture.cleanUp()

    assert result.status_code == 403
    assert "credential-secret" not in result.text
    assert "credential-secret" not in caplog.text
    assert CLAIM_TOKEN not in caplog.text
