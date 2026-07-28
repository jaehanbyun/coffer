from __future__ import annotations

from datetime import UTC, datetime, timedelta

from falcon import testing

from conftest import PROJECT_A_ID


DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
IMAGE_CONFIG = "application/vnd.oci.image.config.v1+json"


def _headers(token: str) -> dict[str, str]:
    return {"X-Auth-Token": token}


def _repository(client: testing.TestClient) -> dict[str, object]:
    result = client.simulate_post(
        "/v1/repositories",
        headers=_headers("project-a-member"),
        json={"name": "team/application"},
    )
    assert result.status_code == 201
    return result.json["repository"]


def _artifact(
    client: testing.TestClient,
    repository_id: str,
    *,
    digest: str,
    tag: str,
    pushed_at: datetime,
) -> dict[str, object]:
    store = client.artifact_store  # type: ignore[attr-defined]
    claim = store.claim_tag(
        project_id=PROJECT_A_ID,
        repository_id=repository_id,
        reference=tag,
        digest=digest,
        request_id=f"req-{tag}",
        immutable=False,
        claimed_at=pushed_at,
    )
    return store.commit_artifact(
        project_id=PROJECT_A_ID,
        repository_id=repository_id,
        digest=digest,
        media_type=MEDIA_TYPE,
        artifact_type=IMAGE_CONFIG,
        kind="image",
        size_bytes=4096,
        claim=claim,
        pushed_at=pushed_at,
    ).to_dict()


def test_reader_lists_searches_and_gets_repository_artifacts(
    client: testing.TestClient,
) -> None:
    repository = _repository(client)
    repository_id = repository["id"]
    assert isinstance(repository_id, str)
    now = datetime(2026, 7, 28, tzinfo=UTC)
    first = _artifact(
        client,
        repository_id,
        digest=DIGEST_A,
        tag="stable",
        pushed_at=now,
    )
    second = _artifact(
        client,
        repository_id,
        digest=DIGEST_B,
        tag="nightly",
        pushed_at=now + timedelta(seconds=1),
    )

    listed = client.simulate_get(
        f"/v1/repositories/{repository_id}/artifacts",
        headers=_headers("project-a-reader"),
        params={"limit": "1"},
    )
    assert listed.status_code == 200
    assert listed.json == {
        "artifacts": [second],
        "next_marker": DIGEST_B,
    }

    searched = client.simulate_get(
        f"/v1/repositories/{repository_id}/artifacts",
        headers=_headers("project-a-reader"),
        params={"query": "stable"},
    )
    assert searched.status_code == 200
    assert searched.json == {"artifacts": [first], "next_marker": None}

    shown = client.simulate_get(
        f"/v1/repositories/{repository_id}/artifacts/{DIGEST_A}",
        headers=_headers("project-a-reader"),
    )
    assert shown.status_code == 200
    assert shown.json == {"artifact": first}


def test_artifact_api_is_project_scoped_and_requires_repository(
    client: testing.TestClient,
) -> None:
    repository = _repository(client)
    repository_id = repository["id"]
    assert isinstance(repository_id, str)
    _artifact(
        client,
        repository_id,
        digest=DIGEST_A,
        tag="latest",
        pushed_at=datetime.now(UTC),
    )

    for path in (
        f"/v1/repositories/{repository_id}/artifacts",
        f"/v1/repositories/{repository_id}/artifacts/{DIGEST_A}",
    ):
        assert client.simulate_get(path).status_code == 401
        assert (
            client.simulate_get(
                path,
                headers=_headers("unscoped-reader"),
            ).status_code
            == 403
        )
        assert (
            client.simulate_get(
                path,
                headers=_headers("project-b-member"),
            ).status_code
            == 404
        )


def test_artifact_api_rejects_unbounded_or_cross_query_markers(
    client: testing.TestClient,
) -> None:
    repository = _repository(client)
    repository_id = repository["id"]
    assert isinstance(repository_id, str)
    _artifact(
        client,
        repository_id,
        digest=DIGEST_A,
        tag="stable",
        pushed_at=datetime.now(UTC),
    )

    for params in (
        {"limit": "0"},
        {"limit": "101"},
        {"marker": "not-a-digest"},
        {"marker": DIGEST_A, "query": "does-not-match"},
        {"query": ""},
        {"query": "x" * 129},
    ):
        result = client.simulate_get(
            f"/v1/repositories/{repository_id}/artifacts",
            headers=_headers("project-a-reader"),
            params=params,
        )
        assert result.status_code == 400

    invalid_digest = client.simulate_get(
        f"/v1/repositories/{repository_id}/artifacts/not-a-digest",
        headers=_headers("project-a-reader"),
    )
    assert invalid_digest.status_code == 400
