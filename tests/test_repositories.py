from __future__ import annotations

import re
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


def test_reader_discovers_the_exact_single_registry_origin(
    client: testing.TestClient,
) -> None:
    result = client.simulate_get("/v1", headers=_headers("project-a-reader"))
    slash = client.simulate_get("/v1/", headers=_headers("project-a-member"))

    assert result.status_code == 200
    assert slash.status_code == 200
    assert result.json == slash.json == {
        "version": {
            "id": "v1",
            "status": "CURRENT",
            "service_type": "oci-registry",
            "endpoints": {
                "control": "https://registry.invalid/v1",
                "registry": "https://registry.invalid/v2/",
                "token": "https://registry.invalid/auth/token",
            },
        }
    }


def test_endpoint_discovery_requires_a_project_scoped_registry_role(
    client: testing.TestClient,
) -> None:
    assert client.simulate_get("/v1").status_code == 401
    assert (
        client.simulate_get(
            "/v1", headers=_headers("unscoped-reader")
        ).status_code
        == 403
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
    assert listed.json["next_marker"] is None


def test_repository_listing_uses_project_scoped_keyset_pagination(
    client: testing.TestClient,
) -> None:
    created = {
        name: _create(client, "project-a-member", name).json["repository"]
        for name in ("charlie", "alpha", "bravo")
    }
    other_project = _create(
        client,
        "project-b-member",
        "between",
    ).json["repository"]

    first = client.simulate_get(
        "/v1/repositories",
        headers=_headers("project-a-reader"),
        params={"limit": "2"},
    )
    assert first.status_code == 200
    assert first.json == {
        "repositories": [created["alpha"], created["bravo"]],
        "next_marker": created["bravo"]["id"],
    }

    second = client.simulate_get(
        "/v1/repositories",
        headers=_headers("project-a-reader"),
        params={"limit": "2", "marker": first.json["next_marker"]},
    )
    assert second.status_code == 200
    assert second.json == {
        "repositories": [created["charlie"]],
        "next_marker": None,
    }
    assert all(
        repository["id"] != other_project["id"]
        for result in (first, second)
        for repository in result.json["repositories"]
    )


def test_repository_listing_rejects_invalid_or_cross_project_page_inputs(
    client: testing.TestClient,
) -> None:
    other = _create(client, "project-b-member", "other").json["repository"]

    for params in (
        {"limit": "0"},
        {"limit": "1001"},
        {"limit": "not-an-integer"},
        {"marker": ""},
        {"marker": "not-a-repository-id"},
        {"marker": other["id"]},
    ):
        result = client.simulate_get(
            "/v1/repositories",
            headers=_headers("project-a-reader"),
            params=params,
        )
        assert result.status_code == 400


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
    too_long = _create(client, "project-a-member", "a" * 256)

    assert result.status_code == 400
    assert too_long.status_code == 400


def test_reader_gets_only_the_current_project_quota(
    client: testing.TestClient,
) -> None:
    result = client.simulate_get(
        "/v1/quota",
        headers=_headers("project-a-reader"),
    )

    assert result.status_code == 200
    assert result.json == {
        "quota": {
            "project_id": PROJECT_A_ID,
            "limit_bytes": 10 * 1024 * 1024 * 1024,
            "used_bytes": 0,
            "reserved_bytes": 0,
        }
    }


def test_missing_project_quota_is_not_created_or_borrowed(
    client: testing.TestClient,
) -> None:
    result = client.simulate_get(
        "/v1/quota",
        headers=_headers("project-b-member"),
    )

    assert result.status_code == 404
    assert result.json["title"] == "Quota not configured"


def test_quota_requires_a_valid_project_scoped_reader(
    client: testing.TestClient,
) -> None:
    for token, status in (
        ("invalid-token", 401),
        ("unscoped-reader", 403),
        ("domain-reader", 403),
        ("system-admin", 403),
    ):
        result = client.simulate_get(
            "/v1/quota",
            headers=_headers(token),
        )
        assert result.status_code == status


def test_control_api_preserves_only_bounded_request_ids(
    client: testing.TestClient,
) -> None:
    preserved = client.simulate_get(
        "/v1/repositories",
        headers={
            **_headers("project-a-reader"),
            "X-Openstack-Request-Id": "req-ui-123",
        },
    )
    generated = client.simulate_get(
        "/v1/repositories",
        headers={
            **_headers("project-a-reader"),
            "X-Openstack-Request-Id": "not a request id",
        },
    )
    resource_error = client.simulate_get(
        "/v1/quota",
        headers=_headers("project-b-member"),
    )

    assert preserved.headers["x-openstack-request-id"] == "req-ui-123"
    assert re.fullmatch(
        r"req-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        generated.headers["x-openstack-request-id"],
    )
    assert resource_error.status_code == 404
    assert resource_error.headers["x-openstack-request-id"].startswith("req-")


def test_keystone_owned_outer_authentication_error_is_unchanged(
    client: testing.TestClient,
) -> None:
    result = client.simulate_get(
        "/v1/repositories",
        headers={"X-Openstack-Request-Id": "req-ui-unauthenticated"},
    )

    assert result.status_code == 401
    assert result.headers["www-authenticate"] == (
        'Keystone uri="https://keystone.invalid/v3"'
    )
