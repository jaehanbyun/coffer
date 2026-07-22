from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from keystoneauth1 import exceptions as keystone_exceptions
import pytest

from coffer.keystone import (
    ApplicationCredentialAuthenticator,
    InvalidApplicationCredential,
    KeystoneUnavailable,
)


APPLICATION_CREDENTIAL_ID = "33333333-3333-4333-8333-333333333333"
APPLICATION_CREDENTIAL_SECRET = "request-local-secret-value"
PROJECT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@dataclass
class FakeAccess:
    application_credential_id: str = APPLICATION_CREDENTIAL_ID
    user_id: str = USER_ID
    project_id: str | None = PROJECT_ID
    project_scoped: bool = True
    role_names: tuple[str, ...] = ("reader", "member")
    expires: datetime | None = datetime.now(UTC) + timedelta(minutes=30)
    audit_id: str | None = "audit-current"
    audit_chain_id: str | None = "audit-chain"
    application_credential_access_rules: list[dict[str, str]] | None = None


def _authenticator(
    access: FakeAccess | None = None,
    *,
    error: Exception | None = None,
    observed: dict[str, Any] | None = None,
) -> ApplicationCredentialAuthenticator:
    observed = observed if observed is not None else {}

    class FakePlugin:
        def get_access(self, session: object) -> FakeAccess:
            observed["session_used"] = session is observed["session"]
            if error is not None:
                raise error
            return access or FakeAccess()

    def plugin_factory(**kwargs: Any) -> FakePlugin:
        supplied_secret = kwargs.pop("application_credential_secret")
        observed["secret_matched"] = supplied_secret == APPLICATION_CREDENTIAL_SECRET
        observed["plugin_options"] = kwargs
        return FakePlugin()

    def session_factory(**kwargs: Any) -> object:
        observed["session_options"] = {
            key: value for key, value in kwargs.items() if key != "auth"
        }
        observed["session"] = object()
        return observed["session"]

    return ApplicationCredentialAuthenticator(
        auth_url="https://keystone.example.test/v3",
        verify="/etc/ssl/certs/ca.pem",
        timeout=7.5,
        plugin_factory=plugin_factory,
        session_factory=session_factory,
    )


def test_authenticate_returns_only_nonsecret_audit_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed: dict[str, Any] = {}
    authenticator = _authenticator(observed=observed)

    with caplog.at_level(logging.INFO):
        principal = authenticator.authenticate(
            APPLICATION_CREDENTIAL_ID, APPLICATION_CREDENTIAL_SECRET
        )

    assert principal.application_credential_id == APPLICATION_CREDENTIAL_ID
    assert principal.project_id == PROJECT_ID
    assert principal.user_id == USER_ID
    assert principal.roles == ("reader", "member")
    assert principal.audit_ids == ("audit-current", "audit-chain")
    assert observed["secret_matched"] is True
    assert observed["plugin_options"] == {
        "auth_url": "https://keystone.example.test/v3",
        "application_credential_id": APPLICATION_CREDENTIAL_ID,
        "include_catalog": False,
    }
    assert observed["session_options"] == {
        "verify": "/etc/ssl/certs/ca.pem",
        "timeout": 7.5,
        "app_name": "coffer",
        "app_version": "0.1.0",
    }
    assert observed["session_used"] is True

    retained_state = repr(authenticator) + repr(principal) + caplog.text
    assert APPLICATION_CREDENTIAL_SECRET not in retained_state


@pytest.mark.parametrize(
    "access",
    [
        FakeAccess(project_id=None, project_scoped=False),
        FakeAccess(application_credential_id="different-credential"),
        FakeAccess(user_id="", expires=None),
    ],
)
def test_incomplete_or_mismatched_identity_is_rejected(access: FakeAccess) -> None:
    authenticator = _authenticator(access)

    with pytest.raises(InvalidApplicationCredential):
        authenticator.authenticate(
            APPLICATION_CREDENTIAL_ID, APPLICATION_CREDENTIAL_SECRET
        )


@pytest.mark.parametrize(
    "access_rules",
    [[], [{"service": "compute", "method": "GET", "path": "/v2.1/**"}]],
)
def test_application_credential_access_rules_fail_closed(
    access_rules: list[dict[str, str]],
) -> None:
    authenticator = _authenticator(
        FakeAccess(application_credential_access_rules=access_rules)
    )

    with pytest.raises(InvalidApplicationCredential):
        authenticator.authenticate(
            APPLICATION_CREDENTIAL_ID, APPLICATION_CREDENTIAL_SECRET
        )


def test_invalid_secret_is_redacted_from_exception_and_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dependency_error = keystone_exceptions.Unauthorized(
        message="credential rejected"
    )
    dependency_error.request_body = APPLICATION_CREDENTIAL_SECRET
    authenticator = _authenticator(error=dependency_error)

    with caplog.at_level(logging.WARNING), pytest.raises(
        InvalidApplicationCredential
    ) as raised:
        authenticator.authenticate(
            APPLICATION_CREDENTIAL_ID, APPLICATION_CREDENTIAL_SECRET
        )

    assert APPLICATION_CREDENTIAL_SECRET not in str(raised.value)
    assert APPLICATION_CREDENTIAL_SECRET not in caplog.text
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    traceback = raised.value.__traceback__
    while traceback is not None:
        assert APPLICATION_CREDENTIAL_SECRET not in repr(
            traceback.tb_frame.f_locals
        )
        traceback = traceback.tb_next


def test_deleted_credential_not_found_is_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dependency_error = keystone_exceptions.NotFound(
        message="application credential not found"
    )
    dependency_error.request_body = APPLICATION_CREDENTIAL_SECRET
    authenticator = _authenticator(error=dependency_error)

    with caplog.at_level(logging.WARNING), pytest.raises(
        InvalidApplicationCredential
    ) as raised:
        authenticator.authenticate(
            APPLICATION_CREDENTIAL_ID, APPLICATION_CREDENTIAL_SECRET
        )

    assert APPLICATION_CREDENTIAL_SECRET not in str(raised.value)
    assert APPLICATION_CREDENTIAL_SECRET not in caplog.text
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_keystone_outage_fails_closed_without_secret_disclosure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    authenticator = _authenticator(
        error=keystone_exceptions.ConnectFailure("connection failed")
    )

    with caplog.at_level(logging.ERROR), pytest.raises(KeystoneUnavailable) as raised:
        authenticator.authenticate(
            APPLICATION_CREDENTIAL_ID, APPLICATION_CREDENTIAL_SECRET
        )

    assert APPLICATION_CREDENTIAL_SECRET not in str(raised.value)
    assert APPLICATION_CREDENTIAL_SECRET not in caplog.text


def test_missing_id_or_secret_is_rejected_before_keystone() -> None:
    authenticator = _authenticator()

    with pytest.raises(InvalidApplicationCredential):
        authenticator.authenticate("", APPLICATION_CREDENTIAL_SECRET)
    with pytest.raises(InvalidApplicationCredential):
        authenticator.authenticate(APPLICATION_CREDENTIAL_ID, "")
