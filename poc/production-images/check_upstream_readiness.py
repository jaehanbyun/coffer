from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.request


SCHEMA = "coffer.upstream-readiness/v1"
QUALIFICATION_SCHEMA = "coffer.stage6-upstream-qualification/v1"
DISTRIBUTION_BASELINE = "v3.1.1"
CEPH_BASELINE = "v20.2.2"
CEPH_FIX_MERGE_SHA = "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e"
CEPH_FIX_PR = 69277
GITHUB_API = "https://api.github.com"
STATUS_ORDER = {
    "blocked": 0,
    "candidate-released": 1,
    "candidate-qualified": 2,
}
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ReadinessError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: object) -> Version:
        match = VERSION_PATTERN.fullmatch(str(value))
        if match is None:
            raise ReadinessError(f"invalid release version: {value!r}")
        return cls(*(int(part) for part in match.groups()))

    @property
    def tag(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"


def fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "coffer-stage6-readiness",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise ReadinessError(f"unable to read official metadata from {url}") from error


def require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReadinessError(f"{label} must be a JSON object")
    return value


def require_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ReadinessError(f"{label} must be a JSON array")
    return value


def require_revision(value: object, label: str) -> str:
    revision = str(value)
    if REVISION_PATTERN.fullmatch(revision) is None:
        raise ReadinessError(f"{label} must be a full lowercase SHA-1")
    return revision


def latest_tentacle_stable(tags: Sequence[object]) -> Version:
    versions: list[Version] = []
    for item in tags:
        tag = require_mapping(item, "Ceph tag").get("name")
        try:
            version = Version.parse(tag)
        except ReadinessError:
            continue
        if version.major == 20 and version.minor == 2:
            versions.append(version)
    if not versions:
        raise ReadinessError("Ceph metadata has no Tentacle v20.2.z release tag")
    return max(versions)


def exact_qualification(
    qualification: Mapping[str, Any] | None,
    component: str,
    version: str,
    revision: str,
) -> bool:
    if qualification is None:
        return False
    if qualification.get("schema") != QUALIFICATION_SCHEMA:
        raise ReadinessError("qualification evidence has an unsupported schema")
    evidence = require_mapping(
        qualification.get(component),
        f"qualification {component}",
    )
    return (
        evidence.get("version") == version
        and evidence.get("revision") == revision
        and evidence.get("qualified") is True
    )


def distribution_readiness(
    release_value: object,
    commit_value: object,
    qualification: Mapping[str, Any] | None,
) -> dict[str, object]:
    release = require_mapping(release_value, "Distribution release")
    commit = require_mapping(commit_value, "Distribution commit")
    version = Version.parse(release.get("tag_name"))
    baseline = Version.parse(DISTRIBUTION_BASELINE)
    verification = require_mapping(
        require_mapping(commit.get("commit"), "Distribution commit payload").get(
            "verification"
        ),
        "Distribution commit verification",
    )
    verified = verification.get("verified") is True
    revision = require_revision(
        commit.get("sha"),
        "Distribution release revision",
    )
    stable = release.get("draft") is False and release.get("prerelease") is False

    reasons: list[str] = []
    if not stable:
        reasons.append("latest Distribution input is draft or prerelease")
    if not verified:
        reasons.append("latest Distribution release commit is not verified")
    if version <= baseline:
        reasons.append(
            f"no stable Distribution release newer than {DISTRIBUTION_BASELINE}"
        )

    status = "blocked"
    if not reasons:
        status = "candidate-released"
        if exact_qualification(
            qualification,
            "distribution",
            version.tag,
            revision,
        ):
            status = "candidate-qualified"

    return {
        "status": status,
        "baseline": DISTRIBUTION_BASELINE,
        "latest_stable": version.tag,
        "revision": revision,
        "verified_release_commit": verified,
        "published_at": release.get("published_at"),
        "url": release.get("html_url"),
        "reasons": reasons,
    }


def ceph_readiness(
    tags_value: object,
    release_commit_value: object,
    compare_value: object,
    pull_value: object,
    qualification: Mapping[str, Any] | None,
) -> dict[str, object]:
    tags = require_sequence(tags_value, "Ceph tags")
    release_commit = require_mapping(
        release_commit_value,
        "Ceph release commit",
    )
    compare = require_mapping(compare_value, "Ceph fix comparison")
    pull = require_mapping(pull_value, "Ceph fix pull request")
    version = latest_tentacle_stable(tags)
    baseline = Version.parse(CEPH_BASELINE)
    revision = require_revision(
        release_commit.get("sha"),
        "Ceph release revision",
    )
    merged_to_tentacle = (
        pull.get("number") == CEPH_FIX_PR
        and pull.get("merged") is True
        and require_mapping(pull.get("base"), "Ceph fix base").get("ref")
        == "tentacle"
        and pull.get("merge_commit_sha") == CEPH_FIX_MERGE_SHA
    )
    fix_in_release = (
        compare.get("status") in {"ahead", "identical"}
        and require_mapping(compare.get("merge_base_commit"), "Ceph merge base").get(
            "sha"
        )
        == CEPH_FIX_MERGE_SHA
    )

    reasons: list[str] = []
    if not merged_to_tentacle:
        reasons.append("encrypted CopyObject fix is not merged to tentacle")
    if version <= baseline:
        reasons.append(f"no stable Ceph release newer than {CEPH_BASELINE}")
    if not fix_in_release:
        reasons.append("latest stable Ceph release does not contain the fix")

    status = "blocked"
    if not reasons:
        status = "candidate-released"
        if exact_qualification(
            qualification,
            "ceph",
            version.tag,
            revision,
        ):
            status = "candidate-qualified"

    return {
        "status": status,
        "baseline": CEPH_BASELINE,
        "latest_stable": version.tag,
        "revision": revision,
        "fix_pull_request": CEPH_FIX_PR,
        "fix_merge_revision": CEPH_FIX_MERGE_SHA,
        "fix_merged_to_tentacle": merged_to_tentacle,
        "fix_in_latest_stable": fix_in_release,
        "reasons": reasons,
    }


def classify(
    fixture: Mapping[str, Any],
    qualification: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    distribution = distribution_readiness(
        fixture.get("distribution_release"),
        fixture.get("distribution_commit"),
        qualification,
    )
    ceph = ceph_readiness(
        fixture.get("ceph_tags"),
        fixture.get("ceph_release_commit"),
        fixture.get("ceph_fix_compare"),
        fixture.get("ceph_fix_pull"),
        qualification,
    )
    overall_status = min(
        (str(distribution["status"]), str(ceph["status"])),
        key=STATUS_ORDER.__getitem__,
    )
    return {
        "schema": SCHEMA,
        "status": overall_status,
        "distribution": distribution,
        "ceph": ceph,
    }


def live_fixture() -> dict[str, object]:
    distribution_release = fetch_json(
        f"{GITHUB_API}/repos/distribution/distribution/releases/latest"
    )
    distribution_tag = require_mapping(
        distribution_release,
        "Distribution release",
    ).get("tag_name")
    distribution_commit = fetch_json(
        f"{GITHUB_API}/repos/distribution/distribution/commits/{distribution_tag}"
    )
    ceph_tags = fetch_json(f"{GITHUB_API}/repos/ceph/ceph/tags?per_page=100")
    ceph_version = latest_tentacle_stable(
        require_sequence(ceph_tags, "Ceph tags")
    )
    ceph_release_commit = fetch_json(
        f"{GITHUB_API}/repos/ceph/ceph/commits/{ceph_version.tag}"
    )
    ceph_fix_compare = fetch_json(
        f"{GITHUB_API}/repos/ceph/ceph/compare/"
        f"{CEPH_FIX_MERGE_SHA}...{ceph_version.tag}"
    )
    ceph_fix_pull = fetch_json(
        f"{GITHUB_API}/repos/ceph/ceph/pulls/{CEPH_FIX_PR}"
    )
    return {
        "distribution_release": distribution_release,
        "distribution_commit": distribution_commit,
        "ceph_tags": ceph_tags,
        "ceph_release_commit": ceph_release_commit,
        "ceph_fix_compare": ceph_fix_compare,
        "ceph_fix_pull": ceph_fix_pull,
    }


def read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReadinessError(f"unable to read {label} from {path}") from error
    return require_mapping(value, label)


def write_output(path: Path, result: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify released upstream readiness without building artifacts."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="read captured GitHub response objects instead of the network",
    )
    parser.add_argument(
        "--qualification",
        type=Path,
        help="optional exact Stage 6 qualification evidence",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require",
        choices=tuple(STATUS_ORDER),
        default="blocked",
        help="return 3 unless the overall status reaches this level",
    )
    arguments = parser.parse_args(argv)

    try:
        fixture = (
            read_json(arguments.fixture, "upstream fixture")
            if arguments.fixture
            else live_fixture()
        )
        qualification = (
            read_json(arguments.qualification, "qualification evidence")
            if arguments.qualification
            else None
        )
        result = classify(fixture, qualification)
        if arguments.output:
            write_output(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return (
            0
            if STATUS_ORDER[str(result["status"])]
            >= STATUS_ORDER[arguments.require]
            else 3
        )
    except ReadinessError as error:
        print(f"upstream readiness error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
