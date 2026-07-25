from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "coffer_upstream_readiness",
    ROOT
    / "poc"
    / "production-images"
    / "check_upstream_readiness.py",
)
assert SPEC is not None and SPEC.loader is not None
READINESS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = READINESS
SPEC.loader.exec_module(READINESS)


def current_fixture() -> dict[str, object]:
    return {
        "distribution_release": {
            "tag_name": "v3.1.1",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-05-01T15:51:50Z",
            "html_url": (
                "https://github.com/distribution/distribution/releases/tag/v3.1.1"
            ),
        },
        "distribution_commit": {
            "sha": "9a8d98b679740cd514aa7e7d84d23d442a5ef54c",
            "commit": {"verification": {"verified": True}},
        },
        "ceph_tags": [
            {"name": "v21.3.0"},
            {"name": "v21.1.0"},
            {"name": "v20.3.0"},
            {"name": "v20.2.2"},
        ],
        "ceph_release_commit": {
            "sha": "0fcffee29411e3a38036764817b6e1afc59741cc"
        },
        "ceph_fix_compare": {
            "status": "behind",
            "merge_base_commit": {
                "sha": "0fcffee29411e3a38036764817b6e1afc59741cc"
            },
        },
        "ceph_fix_pull": {
            "number": 69277,
            "merged": True,
            "base": {"ref": "tentacle"},
            "merge_commit_sha": (
                "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e"
            ),
        },
    }


def released_fixture() -> dict[str, object]:
    fixture = current_fixture()
    fixture["distribution_release"] = {
        "tag_name": "v3.1.2",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-01T00:00:00Z",
        "html_url": (
            "https://github.com/distribution/distribution/releases/tag/v3.1.2"
        ),
    }
    fixture["distribution_commit"] = {
        "sha": "d" * 40,
        "commit": {"verification": {"verified": True}},
    }
    fixture["ceph_tags"] = [
        {"name": "v21.1.0"},
        {"name": "v20.3.0"},
        {"name": "v20.2.3"},
        {"name": "v20.2.2"},
    ]
    fixture["ceph_release_commit"] = {"sha": "e" * 40}
    fixture["ceph_fix_compare"] = {
        "status": "ahead",
        "merge_base_commit": {
            "sha": "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e"
        },
    }
    return fixture


def test_current_releases_are_blocked_without_confusing_branch_merge() -> None:
    result = READINESS.classify(current_fixture())

    assert result["status"] == "blocked"
    assert result["distribution"]["status"] == "blocked"
    assert result["distribution"]["latest_stable"] == "v3.1.1"
    assert result["ceph"]["status"] == "blocked"
    assert result["ceph"]["latest_stable"] == "v20.2.2"
    assert result["ceph"]["fix_merged_to_tentacle"] is True
    assert result["ceph"]["fix_in_latest_stable"] is False


def test_new_verified_distribution_and_fixed_ceph_are_candidates_only() -> None:
    result = READINESS.classify(released_fixture())

    assert result["status"] == "candidate-released"
    assert result["distribution"]["status"] == "candidate-released"
    assert result["ceph"]["status"] == "candidate-released"
    assert result["ceph"]["fix_in_latest_stable"] is True


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("draft", True, "draft or prerelease"),
        ("prerelease", True, "draft or prerelease"),
    ],
)
def test_distribution_draft_or_prerelease_never_becomes_candidate(
    field: str,
    value: bool,
    reason: str,
) -> None:
    fixture = released_fixture()
    fixture["distribution_release"][field] = value

    result = READINESS.classify(fixture)

    assert result["status"] == "blocked"
    assert result["distribution"]["status"] == "blocked"
    assert any(
        reason in item for item in result["distribution"]["reasons"]
    )


def test_unverified_distribution_release_never_becomes_candidate() -> None:
    fixture = released_fixture()
    fixture["distribution_commit"]["commit"]["verification"]["verified"] = False

    result = READINESS.classify(fixture)

    assert result["status"] == "blocked"
    assert "not verified" in result["distribution"]["reasons"][0]


def test_qualification_requires_exact_release_versions_and_revisions() -> None:
    fixture = released_fixture()
    exact = {
        "schema": "coffer.stage6-upstream-qualification/v1",
        "distribution": {
            "version": "v3.1.2",
            "revision": "d" * 40,
            "qualified": True,
        },
        "ceph": {
            "version": "v20.2.3",
            "revision": "e" * 40,
            "qualified": True,
        },
    }

    qualified = READINESS.classify(fixture, exact)

    assert qualified["status"] == "candidate-qualified"
    assert qualified["distribution"]["status"] == "candidate-qualified"
    assert qualified["ceph"]["status"] == "candidate-qualified"

    exact["ceph"]["revision"] = "f" * 40
    mismatched = READINESS.classify(fixture, exact)
    assert mismatched["status"] == "candidate-released"
    assert mismatched["distribution"]["status"] == "candidate-qualified"
    assert mismatched["ceph"]["status"] == "candidate-released"


def test_invalid_qualification_schema_fails_closed() -> None:
    with pytest.raises(READINESS.ReadinessError, match="unsupported schema"):
        READINESS.classify(
            released_fixture(),
            {
                "schema": "coffer.stage6-upstream-qualification/v0",
                "distribution": {},
                "ceph": {},
            },
        )


def test_latest_tentacle_stable_rejects_other_release_series() -> None:
    version = READINESS.latest_tentacle_stable(
        [
            {"name": "v21.2.0"},
            {"name": "v21.3.0"},
            {"name": "v21.1.0"},
            {"name": "v20.3.0"},
            {"name": "v20.2.3"},
            {"name": "not-a-version"},
        ]
    )

    assert version.tag == "v20.2.3"


def test_invalid_release_revision_fails_closed() -> None:
    fixture = released_fixture()
    fixture["distribution_commit"]["sha"] = "not-a-revision"

    with pytest.raises(READINESS.ReadinessError, match="full lowercase SHA-1"):
        READINESS.classify(fixture)


def test_output_is_atomic_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    output = tmp_path / "readiness.json"
    result = READINESS.classify(current_fixture())

    READINESS.write_output(output, result)

    assert output.read_text(encoding="utf-8").endswith("\n")
    assert list(tmp_path.iterdir()) == [output]
