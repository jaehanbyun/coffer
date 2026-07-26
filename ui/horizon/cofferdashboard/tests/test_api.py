from __future__ import annotations

from types import SimpleNamespace

import pytest

from cofferdashboard.api import coffer

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "22222222-2222-4222-8222-222222222222"
NEXT_ID = "33333333-3333-4333-8333-333333333333"
ENDPOINT = "https://registry.example.test/v1"


def request() -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(
            project_id=PROJECT_ID,
            token=SimpleNamespace(id="test-token-value"),
        )
    )


def repository(
    *,
    repository_id: str = REPOSITORY_ID,
    project_id: str = PROJECT_ID,
    name: str = "team/application",
) -> dict[str, object]:
    return {
        "id": repository_id,
        "project_id": project_id,
        "name": name,
        "immutable_tags": True,
        "created_at": "2026-07-26T00:00:00Z",
    }


class Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


class Client:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, url: str, method: str, **kwargs: object) -> Response:
        self.calls.append((url, method, kwargs))
        return Response(self.payload)


def install_client(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> Client:
    client = Client(payload)
    monkeypatch.setattr(coffer.base, "url_for", lambda *_args: ENDPOINT)
    monkeypatch.setattr(coffer, "_new_adapter", lambda *_args: client)
    return client


def test_list_uses_versioned_catalog_endpoint_and_bounded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "repositories": [repository()],
        "next_marker": REPOSITORY_ID,
    }
    client = install_client(monkeypatch, payload)

    page = coffer.list_repositories(request(), limit=1)

    assert page.repositories[0].name == "team/application"
    assert page.next_marker == REPOSITORY_ID
    assert len(client.calls) == 1
    url, method, kwargs = client.calls[0]
    assert url == f"{ENDPOINT}/repositories"
    assert method == "GET"
    assert kwargs["params"] == {"limit": 1}
    assert kwargs["timeout"] == (5, 30)
    assert kwargs["connect_retries"] == 0
    assert kwargs["status_code_retries"] == 0
    assert kwargs["raise_exc"] is True
    headers = kwargs["headers"]
    assert isinstance(headers, dict)
    assert headers["X-Openstack-Request-Id"].startswith("req-")
    assert "test-token-value" not in str(client.calls)


def test_create_get_and_quota_validate_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = install_client(
        monkeypatch,
        {"repository": repository()},
    )
    created = coffer.create_repository(
        request(),
        name="team/application",
        immutable_tags=True,
    )
    assert created.id == REPOSITORY_ID
    assert client.calls[-1][2]["json"] == {
        "name": "team/application",
        "immutable_tags": True,
    }

    client.payload = {"repository": repository()}
    assert coffer.get_repository(request(), REPOSITORY_ID) == created

    client.payload = {
        "quota": {
            "project_id": PROJECT_ID,
            "limit_bytes": 100,
            "used_bytes": 50,
            "reserved_bytes": 10,
        }
    }
    quota = coffer.get_quota(request())
    assert quota.available_bytes == 40
    assert quota.charged_bytes == 60
    assert quota.usage_percent == 60.0

    client.payload = {"repository": repository(project_id="other-project")}
    with pytest.raises(coffer.CofferAPIError, match="invalid_response"):
        coffer.get_repository(request(), REPOSITORY_ID)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://registry.example.test",
        "https://registry.example.test/v1?token=value",
        "https://user@example.test/v1",
        "ftp://registry.example.test/v1",
        "/v1",
    ],
)
def test_endpoint_must_be_a_safe_versioned_catalog_url(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    monkeypatch.setattr(coffer.base, "url_for", lambda *_args: endpoint)

    with pytest.raises(coffer.CofferAPIError, match="unavailable"):
        coffer.list_repositories(request())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"repositories": [], "next_marker": NEXT_ID},
        {
            "repositories": [repository(name="INVALID")],
            "next_marker": None,
        },
        {
            "repositories": [repository(), repository(repository_id=NEXT_ID)],
            "next_marker": NEXT_ID,
        },
        {
            "repositories": [repository()],
            "next_marker": NEXT_ID,
        },
    ],
)
def test_list_refuses_malformed_or_oversized_responses(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    install_client(monkeypatch, payload)

    with pytest.raises(coffer.CofferAPIError, match="invalid_response"):
        coffer.list_repositories(request(), limit=1)


def test_adapter_construction_uses_token_auth_and_horizon_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Auth:
        def __init__(self, **kwargs: object) -> None:
            captured["auth"] = kwargs

    class Session:
        def __init__(self, **kwargs: object) -> None:
            captured["session"] = kwargs

    class Adapter:
        def __init__(self, **kwargs: object) -> None:
            captured["adapter"] = kwargs

    monkeypatch.setattr(coffer.token_endpoint, "Token", Auth)
    monkeypatch.setattr(coffer.session, "Session", Session)
    monkeypatch.setattr(coffer.adapter, "Adapter", Adapter)
    monkeypatch.setattr(coffer.settings, "OPENSTACK_SSL_NO_VERIFY", False)
    monkeypatch.setattr(
        coffer.settings,
        "OPENSTACK_SSL_CACERT",
        "/etc/ssl/certs/openstack-ca.pem",
    )

    result = coffer._new_adapter(request(), ENDPOINT)

    assert isinstance(result, Adapter)
    assert captured["auth"] == {
        "endpoint": ENDPOINT,
        "token": "test-token-value",
    }
    assert captured["session"]["verify"] == "/etc/ssl/certs/openstack-ca.pem"
    assert captured["adapter"]["service_type"] == "oci-registry"
    assert captured["adapter"]["endpoint_override"] == ENDPOINT


def test_invalid_inputs_fail_before_an_adapter_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        coffer,
        "_new_adapter",
        lambda *_args: calls.append(object()),
    )

    with pytest.raises(ValueError, match="repository limit"):
        coffer.list_repositories(request(), limit=0)
    with pytest.raises(ValueError, match="repository input"):
        coffer.create_repository(request(), name="INVALID")
    with pytest.raises(coffer.CofferAPIError, match="invalid_response"):
        coffer.get_repository(request(), "not-a-uuid")

    assert calls == []


def test_transport_and_json_failures_are_bounded_without_secret_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(coffer.base, "url_for", lambda *_args: ENDPOINT)

    class FailingClient:
        def request(self, *_args: object, **_kwargs: object) -> object:
            raise OSError("test-token-value database-password")

    monkeypatch.setattr(coffer, "_new_adapter", lambda *_args: FailingClient())
    with pytest.raises(coffer.CofferAPIError) as failure:
        coffer.list_repositories(request())
    assert failure.value.result == "unavailable"
    assert "test-token-value" not in str(failure.value)
    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None

    class InvalidJSONClient:
        def request(self, *_args: object, **_kwargs: object) -> object:
            return ResponseWithInvalidJSON()

    class ResponseWithInvalidJSON:
        def json(self) -> object:
            raise ValueError("test-token-value database-password")

    monkeypatch.setattr(coffer, "_new_adapter", lambda *_args: InvalidJSONClient())
    with pytest.raises(coffer.CofferAPIError) as invalid:
        coffer.list_repositories(request())
    assert invalid.value.result == "invalid_response"
    assert "test-token-value" not in str(invalid.value)
    assert invalid.value.__cause__ is None
    assert invalid.value.__context__ is None


@pytest.mark.parametrize(
    ("status", "result"),
    [
        (400, "invalid_request"),
        (401, "authentication_required"),
        (403, "forbidden"),
        (404, "not_found"),
        (409, "conflict"),
        (503, "unavailable"),
        (500, "unavailable"),
    ],
)
def test_http_failures_map_only_to_bounded_results(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    result: str,
) -> None:
    monkeypatch.setattr(coffer.base, "url_for", lambda *_args: ENDPOINT)

    class FailingClient:
        def request(self, *_args: object, **_kwargs: object) -> object:
            raise coffer.ksa_exceptions.http.HttpError(
                message="test-token-value database-password",
                http_status=status,
            )

    monkeypatch.setattr(coffer, "_new_adapter", lambda *_args: FailingClient())

    with pytest.raises(coffer.CofferAPIError) as failure:
        coffer.list_repositories(request())

    assert failure.value.result == result
    assert "test-token-value" not in str(failure.value)
    assert failure.value.__cause__ is None
    assert failure.value.__context__ is None
