from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import ssl
from typing import Any

import pytest

from coffer.maintenance_probe import (
    AuthenticatedReconciliationManifestProbe,
    KeystoneApplicationCredentialTokenSource,
    MaintenanceProbeUnavailable,
    read_owner_only_credential,
)
from coffer.maintenance_token import (
    INTERNAL_SERVICE_TYPE,
    INTERNAL_TOKEN_PATH,
)
from coffer.quota_reconciliation import ManifestPresence


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
CREDENTIAL_ID = "33333333-3333-4333-8333-333333333333"
REPOSITORY_ID = "44444444-4444-4444-8444-444444444444"
RESERVATION_ID = "55555555-5555-4555-8555-555555555555"
CLAIM_TOKEN = "claim-token-a"
DIGEST = "sha256:" + "a" * 64
REPOSITORY = f"p/{PROJECT_ID}/example"


def private_file(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_owner_only_credential_reader_refuses_aliases_modes_and_multiline(
    tmp_path: Path,
) -> None:
    credential = private_file(tmp_path / "credential", "credential-value\n")
    assert read_owner_only_credential(str(credential.resolve())) == "credential-value"

    credential.chmod(0o644)
    with pytest.raises(MaintenanceProbeUnavailable) as mode_error:
        read_owner_only_credential(str(credential.resolve()))
    assert "credential-value" not in str(mode_error.value)
    credential.chmod(0o600)

    alias = tmp_path / "alias"
    alias.symlink_to(credential)
    with pytest.raises(MaintenanceProbeUnavailable):
        read_owner_only_credential(str(alias.absolute()))

    hardlink = tmp_path / "hardlink"
    os.link(credential, hardlink)
    with pytest.raises(MaintenanceProbeUnavailable):
        read_owner_only_credential(str(credential.resolve()))
    hardlink.unlink()

    private_file(credential, "first\nsecond")
    with pytest.raises(MaintenanceProbeUnavailable):
        read_owner_only_credential(str(credential.resolve()))
    with pytest.raises(MaintenanceProbeUnavailable):
        read_owner_only_credential("relative")


class FakeAccess:
    application_credential_id = CREDENTIAL_ID
    project_scoped = True
    project_id = PROJECT_ID
    user_id = USER_ID
    role_names = ("service", "registry_maintenance")
    application_credential_access_rules = (
        {
            "id": "access-rule-id",
            "service": INTERNAL_SERVICE_TYPE,
            "method": "POST",
            "path": INTERNAL_TOKEN_PATH,
        },
    )
    expires = datetime(2026, 7, 28, 1, tzinfo=UTC)
    auth_token = "identity-token-value"


class FakePlugin:
    def __init__(self, access: Any) -> None:
        self.access = access
        self.sessions: list[Any] = []

    def get_access(self, session: Any) -> Any:
        self.sessions.append(session)
        return self.access


def test_keystone_token_source_checks_exact_access_rule_and_identity(
    tmp_path: Path,
) -> None:
    credential_id = private_file(
        tmp_path / "credential-id",
        CREDENTIAL_ID,
    )
    credential_secret = private_file(
        tmp_path / "credential-secret",
        "credential-secret-value",
    )
    cafile = tmp_path / "ca.crt"
    cafile.write_text("public-ca-placeholder", encoding="utf-8")
    cafile.chmod(0o644)
    calls: list[dict[str, Any]] = []
    plugin = FakePlugin(FakeAccess())

    def plugin_factory(**kwargs: Any) -> FakePlugin:
        calls.append(kwargs)
        return plugin

    sessions: list[dict[str, Any]] = []

    def session_factory(**kwargs: Any) -> dict[str, Any]:
        sessions.append(kwargs)
        return kwargs

    source = KeystoneApplicationCredentialTokenSource(
        auth_url="https://keystone.internal/v3",
        cafile=str(cafile.resolve()),
        timeout_seconds=10,
        credential_id_file=str(credential_id.resolve()),
        credential_secret_file=str(credential_secret.resolve()),
        expected_project_id=PROJECT_ID,
        expected_user_id=USER_ID,
        plugin_factory=plugin_factory,
        session_factory=session_factory,
        clock=lambda: datetime(2026, 7, 28, tzinfo=UTC),
    )

    assert source.issue_token() == "identity-token-value"
    assert calls == [
        {
            "auth_url": "https://keystone.internal/v3",
            "application_credential_id": CREDENTIAL_ID,
            "application_credential_secret": "credential-secret-value",
            "include_catalog": False,
        }
    ]
    assert sessions[0]["verify"] == str(cafile.resolve())
    assert sessions[0]["timeout"] == 10

    bad_access = FakeAccess()
    bad_access.role_names = ("admin",)
    denied = KeystoneApplicationCredentialTokenSource(
        auth_url="https://keystone.internal/v3",
        cafile=str(cafile.resolve()),
        timeout_seconds=10,
        credential_id_file=str(credential_id.resolve()),
        credential_secret_file=str(credential_secret.resolve()),
        expected_project_id=PROJECT_ID,
        expected_user_id=USER_ID,
        plugin_factory=lambda **_kwargs: FakePlugin(bad_access),
        session_factory=session_factory,
        clock=lambda: datetime(2026, 7, 28, tzinfo=UTC),
    )
    with pytest.raises(MaintenanceProbeUnavailable) as error:
        denied.issue_token()
    assert "credential-secret-value" not in str(error.value)
    assert "identity-token-value" not in str(error.value)


class FakeIdentityTokenSource:
    def __init__(self, outcome: str | Exception = "identity-token") -> None:
        self.outcome = outcome
        self.calls = 0

    def issue_token(self) -> str:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeResponse:
    def __init__(
        self,
        *,
        status: int,
        body: bytes = b"",
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.status = status
        self._body = body
        self._headers = headers

    def getheader(self, name: str, default: str | None = None) -> str | None:
        values = [
            value
            for header, value in self._headers
            if header.lower() == name.lower()
        ]
        return values[-1] if values else default

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers)

    def read(self, amount: int | None = None) -> bytes:
        if amount is None:
            return self._body
        return self._body[:amount]


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[
            tuple[str, str, bytes | None, Mapping[str, str]]
        ] = []
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.requests.append((method, url, body, dict(headers or {})))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class ConnectionQueue:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.connections: list[FakeConnection] = []
        self.calls: list[tuple[str, int, float, object]] = []

    def __call__(
        self,
        host: str,
        port: int,
        timeout_seconds: float,
        context: ssl.SSLContext,
    ) -> FakeConnection:
        self.calls.append((host, port, timeout_seconds, context))
        connection = FakeConnection(self.responses.pop(0))
        self.connections.append(connection)
        return connection


def maintenance_response(token: str = "distribution-token") -> FakeResponse:
    body = json.dumps(
        {
            "token": token,
            "expires_in": 60,
            "issued_at": "2026-07-28T00:00:00Z",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return FakeResponse(
        status=200,
        body=body,
        headers=(
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ),
    )


def build_probe(
    queue: ConnectionQueue,
    source: FakeIdentityTokenSource | None = None,
) -> AuthenticatedReconciliationManifestProbe:
    context = ssl.create_default_context()
    return AuthenticatedReconciliationManifestProbe(
        registry_url="https://registry.internal:8789",
        maintenance_token_url=(
            "https://registry.internal:8790"
            "/v1/internal/maintenance/registry-token"
        ),
        identity_token_source=source or FakeIdentityTokenSource(),
        registry_ssl_context=context,
        maintenance_ssl_context_factory=lambda: context,
        registry_timeout_seconds=11,
        maintenance_timeout_seconds=7,
        connection_factory=queue,
    )


def probe_once(
    probe: AuthenticatedReconciliationManifestProbe,
):
    return probe.probe(
        repository=REPOSITORY,
        digest=DIGEST,
        repository_id=REPOSITORY_ID,
        reservation_id=RESERVATION_ID,
        claim_token=CLAIM_TOKEN,
        expected_version=3,
    )


def test_authenticated_probe_exchanges_exact_claim_then_uses_pull_token() -> None:
    queue = ConnectionQueue(
        [
            maintenance_response(),
            FakeResponse(
                status=200,
                headers=(("Docker-Content-Digest", DIGEST),),
            ),
        ]
    )
    observation = probe_once(build_probe(queue))

    assert observation.presence == ManifestPresence.PRESENT
    assert observation.status_code == 200
    assert [(host, port, timeout) for host, port, timeout, _ in queue.calls] == [
        ("registry.internal", 8790, 7),
        ("registry.internal", 8789, 11),
    ]
    maintenance_request = queue.connections[0].requests[0]
    assert maintenance_request[0:2] == ("POST", INTERNAL_TOKEN_PATH)
    assert json.loads(maintenance_request[2]) == {
        "claim_token": CLAIM_TOKEN,
        "expected_version": 3,
        "mode": "reconciliation",
        "repository_id": REPOSITORY_ID,
        "reservation_id": RESERVATION_ID,
    }
    assert maintenance_request[3]["X-Auth-Token"] == "identity-token"
    assert "X-Coffer-Maintenance-Workload" not in maintenance_request[3]
    head_request = queue.connections[1].requests[0]
    assert head_request[0:2] == (
        "HEAD",
        f"/v2/{REPOSITORY}/manifests/{DIGEST}",
    )
    assert head_request[3]["Authorization"] == "Bearer distribution-token"
    assert all(connection.closed for connection in queue.connections)


def test_authenticated_probe_distinguishes_authorized_absence_from_outage() -> None:
    absent = probe_once(
        build_probe(
            ConnectionQueue(
                [maintenance_response(), FakeResponse(status=404)]
            )
        )
    )
    assert absent.presence == ManifestPresence.ABSENT
    assert absent.status_code == 404

    denied_queue = ConnectionQueue(
        [
            FakeResponse(
                status=403,
                body=b'{"title":"denied"}',
                headers=(("Content-Type", "application/json"),),
            )
        ]
    )
    denied = probe_once(build_probe(denied_queue))
    assert denied.presence == ManifestPresence.INDETERMINATE
    assert denied.status_code is None
    assert len(denied_queue.connections) == 1

    registry_denied = probe_once(
        build_probe(
            ConnectionQueue(
                [maintenance_response(), FakeResponse(status=401)]
            )
        )
    )
    assert registry_denied.presence == ManifestPresence.INDETERMINATE
    assert registry_denied.status_code == 401

    source = FakeIdentityTokenSource(RuntimeError("credential-secret-value"))
    source_queue = ConnectionQueue([])
    unavailable = probe_once(build_probe(source_queue, source))
    assert unavailable.presence == ManifestPresence.INDETERMINATE
    assert source.calls == 1
    assert source_queue.connections == []


@pytest.mark.parametrize(
    "response",
    (
        FakeResponse(
            status=200,
            body=b"not-json",
            headers=(("Content-Type", "application/json"),),
        ),
        FakeResponse(
            status=200,
            body=b'{"expires_in":60,"issued_at":"2026-07-28T00:00:00Z"}',
            headers=(("Content-Type", "application/json"),),
        ),
        FakeResponse(
            status=200,
            body=(
                b'{"expires_in":301,"issued_at":"2026-07-28T00:00:00Z",'
                b'"token":"distribution-token"}'
            ),
            headers=(("Content-Type", "application/json"),),
        ),
        FakeResponse(
            status=200,
            body=(
                b'{"expires_in":60,"issued_at":"2026-07-28T00:00:00Z",'
                b'"token":"distribution-token"}'
            ),
            headers=(("Content-Type", "text/plain"),),
        ),
        FakeResponse(
            status=503,
            body=b'{"title":"unavailable"}',
            headers=(("Content-Type", "application/json"),),
        ),
    ),
)
def test_authenticated_probe_rejects_malformed_or_failed_broker_response(
    response: FakeResponse,
) -> None:
    queue = ConnectionQueue([response])

    observation = probe_once(build_probe(queue))

    assert observation.presence == ManifestPresence.INDETERMINATE
    assert observation.status_code is None
    assert len(queue.connections) == 1
    assert queue.connections[0].closed


def test_authenticated_probe_requires_exact_distribution_digest_header() -> None:
    queue = ConnectionQueue(
        [
            maintenance_response(),
            FakeResponse(
                status=200,
                headers=(("Docker-Content-Digest", "sha256:" + "b" * 64),),
            ),
        ]
    )

    observation = probe_once(build_probe(queue))

    assert observation.presence == ManifestPresence.INDETERMINATE
    assert observation.status_code == 200


@pytest.mark.parametrize(
    "overrides",
    (
        {"repository": "not-canonical"},
        {"digest": "sha256:bad"},
        {"repository_id": ""},
        {"reservation_id": ""},
        {"claim_token": ""},
        {"expected_version": 0},
        {"expected_version": True},
    ),
)
def test_authenticated_probe_rejects_invalid_authority_before_network(
    overrides: dict[str, object],
) -> None:
    source = FakeIdentityTokenSource()
    queue = ConnectionQueue([])
    arguments: dict[str, object] = {
        "repository": REPOSITORY,
        "digest": DIGEST,
        "repository_id": REPOSITORY_ID,
        "reservation_id": RESERVATION_ID,
        "claim_token": CLAIM_TOKEN,
        "expected_version": 3,
    }
    arguments.update(overrides)

    observation = build_probe(queue, source).probe(
        **arguments  # type: ignore[arg-type]
    )

    assert observation.presence == ManifestPresence.INDETERMINATE
    assert source.calls == 0
    assert queue.connections == []
