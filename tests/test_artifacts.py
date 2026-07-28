from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from coffer.artifacts import (
    ArtifactSchemaNotReady,
    ArtifactStore,
    InvalidArtifactMarker,
    TagClaimConflict,
    TagClaimNotFound,
    TagImmutable,
)


PROJECT = "11111111-1111-4111-8111-111111111111"
REPOSITORY = "22222222-2222-4222-8222-222222222222"
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
IMAGE_CONFIG = "application/vnd.oci.image.config.v1+json"


def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(
        f"sqlite:///{tmp_path / 'artifacts.sqlite'}",
        bootstrap_schema=True,
    )


def claim_and_commit(
    artifacts: ArtifactStore,
    *,
    digest: str,
    tag: str,
    request_id: str,
    pushed_at: datetime,
    immutable: bool = False,
):
    claim = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference=tag,
        digest=digest,
        request_id=request_id,
        immutable=immutable,
        claimed_at=pushed_at,
    )
    return artifacts.commit_artifact(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        digest=digest,
        media_type=MEDIA_TYPE,
        artifact_type=IMAGE_CONFIG,
        kind="image",
        size_bytes=1234,
        claim=claim,
        pushed_at=pushed_at,
    )


def test_production_store_requires_migrated_schema(tmp_path: Path) -> None:
    with pytest.raises(ArtifactSchemaNotReady, match="migration is required"):
        ArtifactStore(f"sqlite:///{tmp_path / 'missing.sqlite'}")


def test_commit_lists_and_gets_digest_centered_artifact(tmp_path: Path) -> None:
    artifacts = store(tmp_path)
    pushed_at = datetime(2026, 7, 28, 10, 30, tzinfo=UTC)

    artifact = claim_and_commit(
        artifacts,
        digest=DIGEST_A,
        tag="latest",
        request_id="req-first",
        pushed_at=pushed_at,
    )
    second_claim = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference="v1.0.0",
        digest=DIGEST_A,
        request_id="req-second",
        immutable=False,
        claimed_at=pushed_at + timedelta(seconds=1),
    )
    artifacts.commit_artifact(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        digest=DIGEST_A,
        media_type=MEDIA_TYPE,
        artifact_type=IMAGE_CONFIG,
        kind="image",
        size_bytes=1234,
        claim=second_claim,
        pushed_at=pushed_at + timedelta(seconds=1),
    )

    assert artifact.digest == DIGEST_A
    page = artifacts.list_page(PROJECT, REPOSITORY, limit=10)
    assert len(page.artifacts) == 1
    assert page.next_marker is None
    assert page.artifacts[0].tags == ("latest", "v1.0.0")
    assert page.artifacts[0].tag_count == 2
    assert not page.artifacts[0].tags_truncated
    assert page.artifacts[0].to_dict()["pushed_at"].endswith("Z")
    assert artifacts.get(PROJECT, REPOSITORY, DIGEST_A) == page.artifacts[0]


def test_digest_reference_commits_an_untagged_artifact(tmp_path: Path) -> None:
    artifacts = store(tmp_path)

    claim = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference=DIGEST_A,
        digest=DIGEST_A,
        request_id="req-digest",
        immutable=True,
    )
    assert claim is None
    artifact = artifacts.commit_artifact(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        digest=DIGEST_A,
        media_type=MEDIA_TYPE,
        artifact_type=IMAGE_CONFIG,
        kind="image",
        size_bytes=5,
        claim=None,
    )

    assert artifact.tags == ()
    assert artifact.tag_count == 0


def test_immutable_tag_refuses_movement_but_allows_idempotent_digest(
    tmp_path: Path,
) -> None:
    artifacts = store(tmp_path)
    now = datetime.now(UTC)
    claim_and_commit(
        artifacts,
        digest=DIGEST_A,
        tag="stable",
        request_id="req-a",
        pushed_at=now,
        immutable=True,
    )

    with pytest.raises(TagImmutable):
        artifacts.claim_tag(
            project_id=PROJECT,
            repository_id=REPOSITORY,
            reference="stable",
            digest=DIGEST_B,
            request_id="req-b",
            immutable=True,
        )

    retry = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference="stable",
        digest=DIGEST_A,
        request_id="req-retry",
        immutable=True,
    )
    assert retry is not None


def test_tag_claim_serializes_conflicting_pushes_and_expires(tmp_path: Path) -> None:
    artifacts = store(tmp_path)
    now = datetime.now(UTC)
    first = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference="latest",
        digest=DIGEST_A,
        request_id="req-a",
        immutable=False,
        claimed_at=now,
        lease_for=timedelta(seconds=10),
    )
    assert first is not None

    with pytest.raises(TagClaimConflict):
        artifacts.claim_tag(
            project_id=PROJECT,
            repository_id=REPOSITORY,
            reference="latest",
            digest=DIGEST_B,
            request_id="req-b",
            immutable=False,
            claimed_at=now + timedelta(seconds=1),
        )

    replacement = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference="latest",
        digest=DIGEST_B,
        request_id="req-b",
        immutable=False,
        claimed_at=now + timedelta(seconds=11),
    )
    assert replacement is not None
    assert replacement.digest == DIGEST_B


def test_commit_requires_the_exact_live_tag_claim(tmp_path: Path) -> None:
    artifacts = store(tmp_path)
    claim = artifacts.claim_tag(
        project_id=PROJECT,
        repository_id=REPOSITORY,
        reference="latest",
        digest=DIGEST_A,
        request_id="req-a",
        immutable=False,
    )
    assert claim is not None
    assert artifacts.release_tag_claim(claim)

    with pytest.raises(TagClaimNotFound):
        artifacts.commit_artifact(
            project_id=PROJECT,
            repository_id=REPOSITORY,
            digest=DIGEST_A,
            media_type=MEDIA_TYPE,
            artifact_type=IMAGE_CONFIG,
            kind="image",
            size_bytes=1,
            claim=claim,
        )


def test_search_pagination_and_project_repository_isolation(tmp_path: Path) -> None:
    artifacts = store(tmp_path)
    now = datetime(2026, 7, 28, tzinfo=UTC)
    claim_and_commit(
        artifacts,
        digest=DIGEST_A,
        tag="release-1",
        request_id="req-a",
        pushed_at=now,
    )
    claim_and_commit(
        artifacts,
        digest=DIGEST_B,
        tag="nightly",
        request_id="req-b",
        pushed_at=now + timedelta(seconds=1),
    )

    first = artifacts.list_page(PROJECT, REPOSITORY, limit=1)
    assert [item.digest for item in first.artifacts] == [DIGEST_B]
    assert first.next_marker == DIGEST_B
    second = artifacts.list_page(
        PROJECT,
        REPOSITORY,
        limit=1,
        marker=first.next_marker,
    )
    assert [item.digest for item in second.artifacts] == [DIGEST_A]
    assert second.next_marker is None
    assert [
        item.digest
        for item in artifacts.list_page(
            PROJECT,
            REPOSITORY,
            limit=10,
            query="release",
        ).artifacts
    ] == [DIGEST_A]
    assert artifacts.list_page(
        "other-project",
        REPOSITORY,
        limit=10,
    ).artifacts == ()
    assert artifacts.list_page(
        PROJECT,
        "other-repository",
        limit=10,
    ).artifacts == ()
    with pytest.raises(InvalidArtifactMarker):
        artifacts.list_page(
            PROJECT,
            REPOSITORY,
            limit=1,
            marker=f"sha256:{'c' * 64}",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("kind", "unknown"),
        ("size_bytes", -1),
        ("media_type", ""),
        ("artifact_type", ""),
    ),
)
def test_artifact_metadata_is_bounded(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    artifacts = store(tmp_path)
    arguments = {
        "project_id": PROJECT,
        "repository_id": REPOSITORY,
        "digest": DIGEST_A,
        "media_type": MEDIA_TYPE,
        "artifact_type": IMAGE_CONFIG,
        "kind": "image",
        "size_bytes": 1,
        "claim": None,
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        artifacts.commit_artifact(**arguments)  # type: ignore[arg-type]
