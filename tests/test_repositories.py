from __future__ import annotations

from urllib.parse import urlsplit

from falcon import testing

from conftest import PROJECT_A_ID, PROJECT_B_ID


def _headers(token: str) -> dict[str, str]:
    return {"X-Auth-Token": token}


def _create(
    client: testing.TestClient,
    token: str,
    name: str = "demo",
) -> object:
    return client.simulate_post(
        "/v1/repositories",
        headers=_headers(token),
        json={"name": name},
    )


def test_member_creates_and_reader_lists_project_repository(
    client: testing.TestClient,
) -> None:
    created = _create(client, "project-a-member")

    assert created.status_code == 201
    repository = created.json["repository"]
    assert repository["project_id"] == PROJECT_A_ID
    assert repository["name"] == "demo"
    assert urlsplit(created.headers["location"]).path == (
        f"/v1/repositories/{repository['id']}"
    )

    listed = client.simulate_get(
        "/v1/repositories", headers=_headers("project-a-reader")
    )
    assert listed.status_code == 200
    assert listed.json["repositories"] == [repository]


def test_reader_cannot_create(client: testing.TestClient) -> None:
    result = _create(client, "project-a-reader")

    assert result.status_code == 403


def test_duplicate_name_conflicts_only_inside_one_project(
    client: testing.TestClient,
) -> None:
    assert _create(client, "project-a-member").status_code == 201
    assert _create(client, "project-a-member").status_code == 409

    other = _create(client, "project-b-member")
    assert other.status_code == 201
    assert other.json["repository"]["project_id"] == PROJECT_B_ID


def test_project_b_cannot_observe_project_a_repository(
    client: testing.TestClient,
) -> None:
    created = _create(client, "project-a-member")
    repository_id = created.json["repository"]["id"]

    result = client.simulate_get(
        f"/v1/repositories/{repository_id}",
        headers=_headers("project-b-member"),
    )

    assert result.status_code == 404


def test_invalid_and_unscoped_tokens_are_rejected(client: testing.TestClient) -> None:
    invalid = client.simulate_get(
        "/v1/repositories", headers=_headers("invalid-token")
    )
    unscoped = client.simulate_get(
        "/v1/repositories", headers=_headers("unscoped-reader")
    )

    assert invalid.status_code == 401
    assert unscoped.status_code == 403


def test_missing_and_expired_tokens_receive_keystone_challenge(
    client: testing.TestClient,
) -> None:
    missing = client.simulate_get("/v1/repositories")
    expired = client.simulate_get(
        "/v1/repositories", headers=_headers("expired-reader")
    )

    assert missing.status_code == 401
    assert expired.status_code == 401
    assert missing.headers["www-authenticate"] == (
        'Keystone uri="https://keystone.invalid/v3"'
    )


def test_domain_and_system_tokens_cannot_enter_project_api(
    client: testing.TestClient,
) -> None:
    domain = client.simulate_get(
        "/v1/repositories", headers=_headers("domain-reader")
    )
    system = client.simulate_get(
        "/v1/repositories", headers=_headers("system-admin")
    )

    assert domain.status_code == 403
    assert system.status_code == 403


def test_spoofed_identity_headers_are_replaced(client: testing.TestClient) -> None:
    result = client.simulate_get(
        "/v1/repositories",
        headers={
            "X-Auth-Token": "project-a-reader",
            "X-Project-Id": PROJECT_B_ID,
            "X-Roles": "admin",
            "OpenStack-System-Scope": "all",
        },
    )

    assert result.status_code == 200
    assert result.json["repositories"] == []


def test_repository_name_is_validated(client: testing.TestClient) -> None:
    result = _create(client, "project-a-member", "INVALID NAME")

    assert result.status_code == 400
