from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from falcon import testing
import jwt
import pytest

from coffer.keystone import (
    ApplicationCredentialPrincipal,
    InvalidApplicationCredential,
    KeystoneUnavailable,
)
from coffer.authorization import RegistryScopeAuthorizer
from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.policy import create_enforcer
from coffer.observability import CofferMetrics, build_operational_application
from coffer.token_api import BASIC_CHALLENGE, build_token_application
from coffer.tokens import TokenIssuer
from coffer.wsgi import build_application


NOW = datetime(2026, 7, 21, 11, 0, tzinfo=UTC)
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
SERVICE = "coffer-registry"
SECRET = "request-only-secret"
APPLICATION_CREDENTIAL_ID = "33333333-3333-4333-8333-333333333333"


class FakeAuthenticator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.seen: tuple[str, bool] | None = None

    def authenticate(
        self, application_credential_id: str, application_credential_secret: str
    ) -> ApplicationCredentialPrincipal:
        self.seen = (
            application_credential_id,
            application_credential_secret == SECRET,
        )
        if self.error is not None:
            raise self.error
        return ApplicationCredentialPrincipal(
            application_credential_id=application_credential_id,
            user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            project_id=PROJECT_ID,
            roles=("member",),
            expires_at=NOW + timedelta(hours=1),
            audit_ids=("audit-id",),
        )


def _authorization(
    identifier: str = APPLICATION_CREDENTIAL_ID, secret: str = SECRET
) -> str:
    encoded = base64.b64encode(f"{identifier}:{secret}".encode()).decode()
    return f"Basic {encoded}"


@pytest.fixture
def issuer() -> TokenIssuer:
    return TokenIssuer(
        private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
        issuer="https://coffer.example.test/auth/token",
        service=SERVICE,
        clock=lambda: NOW,
    )


def _client(
    issuer: TokenIssuer,
    authenticator: FakeAuthenticator,
    metrics: CofferMetrics | None = None,
) -> testing.TestClient:
    conf = new_config()
    conf(args=[])
    store = RepositoryStore("sqlite://", bootstrap_schema=True)
    store.create(PROJECT_ID, "demo")
    scope_authorizer = RegistryScopeAuthorizer(store, create_enforcer(conf))
    return testing.TestClient(
        build_token_application(authenticator, scope_authorizer, issuer, metrics)
    )


def _verification_key(issuer: TokenIssuer) -> object:
    return jwt.PyJWK.from_dict(issuer.jwks()["keys"][0]).key


def test_token_realm_authenticates_basic_and_returns_reduced_distribution_token(
    issuer: TokenIssuer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    authenticator = FakeAuthenticator()
    client = _client(issuer, authenticator)

    with caplog.at_level(logging.INFO):
        result = client.simulate_get(
            "/auth/token",
            params={
                "service": SERVICE,
                "scope": f"repository:p/{PROJECT_ID}/demo:pull,push,delete",
                "account": "ignored-client-account",
            },
            headers={"Authorization": _authorization()},
        )

    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["pragma"] == "no-cache"
    assert result.json["expires_in"] == 300
    assert authenticator.seen == (APPLICATION_CREDENTIAL_ID, True)

    claims = jwt.decode(
        result.json["token"],
        _verification_key(issuer),
        algorithms=["RS256"],
        audience=SERVICE,
        issuer="https://coffer.example.test/auth/token",
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )
    assert claims["access"] == [
        {
            "type": "repository",
            "name": f"p/{PROJECT_ID}/demo",
            "actions": ["pull", "push"],
        }
    ]
    assert SECRET not in caplog.text
    assert result.json["token"] not in caplog.text
    assert "audit-id" in caplog.text
    assert result.headers["x-openstack-request-id"].startswith("req-")


def test_login_without_scope_returns_token_with_empty_access(
    issuer: TokenIssuer,
) -> None:
    client = _client(issuer, FakeAuthenticator())

    result = client.simulate_get(
        "/auth/token",
        params={"service": SERVICE, "offline_token": "true"},
        headers={"Authorization": _authorization()},
    )

    claims = jwt.decode(
        result.json["token"],
        _verification_key(issuer),
        algorithms=["RS256"],
        audience=SERVICE,
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )
    assert claims["access"] == []
    assert "refresh_token" not in result.json


def test_nonexistent_repository_returns_empty_access_token(
    issuer: TokenIssuer,
) -> None:
    client = _client(issuer, FakeAuthenticator())

    result = client.simulate_get(
        "/auth/token",
        params={
            "service": SERVICE,
            "scope": f"repository:p/{PROJECT_ID}/missing:pull,push",
        },
        headers={"Authorization": _authorization()},
    )

    claims = jwt.decode(
        result.json["token"],
        _verification_key(issuer),
        algorithms=["RS256"],
        audience=SERVICE,
        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
    )
    assert claims["access"] == []


def test_token_decision_metrics_use_bounded_result_labels(
    issuer: TokenIssuer,
) -> None:
    metrics = CofferMetrics()
    client = _client(issuer, FakeAuthenticator(), metrics)

    success = client.simulate_get(
        "/auth/token",
        params={"service": SERVICE},
        headers={"Authorization": _authorization()},
    )
    invalid = client.simulate_get(
        "/auth/token",
        params={"service": "wrong-service"},
        headers={"Authorization": _authorization()},
    )
    rendered = metrics.render().decode()

    assert success.status_code == 200
    assert invalid.status_code == 400
    assert 'coffer_token_decisions_total{result="issued"} 1.0' in rendered
    assert (
        'coffer_token_decisions_total{result="invalid_request"} 1.0'
        in rendered
    )
    assert SECRET not in rendered


@pytest.mark.parametrize(
    "authorization",
    [None, "Bearer token", "Basic invalid"],
)
def test_missing_or_malformed_basic_auth_receives_neutral_challenge(
    issuer: TokenIssuer, authorization: str | None
) -> None:
    client = _client(issuer, FakeAuthenticator())
    headers = {"Authorization": authorization} if authorization else None

    result = client.simulate_get(
        "/auth/token",
        params={"service": SERVICE},
        headers=headers,
    )

    assert result.status_code == 401
    assert result.headers["www-authenticate"] == BASIC_CHALLENGE
    assert SECRET not in result.text


def test_invalid_credential_and_keystone_outage_are_distinct(
    issuer: TokenIssuer,
) -> None:
    invalid = _client(
        issuer, FakeAuthenticator(InvalidApplicationCredential("rejected"))
    ).simulate_get(
        "/auth/token",
        params={"service": SERVICE},
        headers={"Authorization": _authorization()},
    )
    unavailable = _client(
        issuer, FakeAuthenticator(KeystoneUnavailable("down"))
    ).simulate_get(
        "/auth/token",
        params={"service": SERVICE},
        headers={"Authorization": _authorization()},
    )

    assert invalid.status_code == 401
    assert unavailable.status_code == 503
    assert SECRET not in invalid.text + unavailable.text


@pytest.mark.parametrize(
    "params",
    [
        {"service": "wrong-service"},
        {"service": SERVICE, "offline_token": "yes"},
        {
            "service": SERVICE,
            "scope": f"repository:p/{PROJECT_ID}/../demo:pull",
        },
    ],
)
def test_invalid_query_is_rejected_before_authentication(
    issuer: TokenIssuer, params: dict[str, str]
) -> None:
    authenticator = FakeAuthenticator()
    client = _client(issuer, authenticator)

    result = client.simulate_get(
        "/auth/token",
        params=params,
        headers={"Authorization": _authorization()},
    )

    assert result.status_code == 400
    assert authenticator.seen is None


def test_token_realm_bypasses_control_api_keystone_middleware(
    issuer: TokenIssuer, tmp_path: Path
) -> None:
    conf = new_config()
    conf(args=[])
    store = RepositoryStore(
        f"sqlite:///{tmp_path / 'coffer.sqlite'}", bootstrap_schema=True
    )
    store.create(PROJECT_ID, "demo")
    token_application = build_token_application(
        FakeAuthenticator(),
        RegistryScopeAuthorizer(store, create_enforcer(conf)),
        issuer,
    )
    metrics = CofferMetrics()
    operational_application = build_operational_application(
        store, metrics, metrics_enabled=True
    )
    composite = build_application(
        conf,
        store=store,
        auth_config={
            "www_authenticate_uri": "https://keystone.invalid/v3",
            "delay_auth_decision": "false",
            "token_cache_time": "-1",
            "service_token_roles_required": "true",
        },
        token_application=token_application,
        operational_application=operational_application,
        metrics=metrics,
    )
    client = testing.TestClient(composite)

    token_result = client.simulate_get(
        "/auth/token",
        params={"service": SERVICE},
        headers={"Authorization": _authorization()},
    )
    control_result = client.simulate_get("/v1/repositories")
    health_result = client.simulate_get("/healthz")
    readiness_result = client.simulate_get("/readyz")
    metrics_result = client.simulate_get("/metrics")

    assert token_result.status_code == 200
    assert control_result.status_code == 401
    assert health_result.status_code == 200
    assert readiness_result.status_code == 200
    assert metrics_result.status_code == 200
