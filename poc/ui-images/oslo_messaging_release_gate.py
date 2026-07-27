from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from collect_python_trial import CollectionError, atomic_json

SCHEMA = "coffer.ui-oslo-messaging-release-gate/v1"
QUALIFICATION_SCHEMA = "coffer.ui-oslo-messaging-qualification/v1"
RESULT_SCHEMA = "coffer.ui-oslo-messaging-release-readiness/v1"
SURFACES = ("horizon", "skyline")
SECURITY_REVISION = "9546853cc8f3da604085fd75eb05d2fbb289533c"
STABLE_PATCH_REVISION = "399f96e8044419ea16929a39174617ba59644052"
MAINLINE_PATCH_REVISION = "73dc887a9caf7540685bdcb148f63d1a91f34bc0"
MAINLINE_TAGS = (
    (
        "18.0.0",
        "7c54081476db457ac66f82df377347c6eb413b614801158181adee11a138e30e",
        False,
    ),
    (
        "18.1.0",
        "73fa9af464e7ad4d4bf030461b7900eaa47202f7a861cd9de39ee393c58199b3",
        True,
    ),
    (
        "18.2.0",
        "0d5e4ad2de8c204c248cc4f98b7ecde06a32dc9d166de078f9ad79988a84712e",
        True,
    ),
)
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
DATE = re.compile(r"^20[0-9]{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])$")


class ReleaseGateError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: object) -> Version:
        if not isinstance(value, str):
            raise ReleaseGateError("oslo.messaging version is invalid")
        match = VERSION.fullmatch(value)
        if match is None:
            raise ReleaseGateError("oslo.messaging version is invalid")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseGateError(f"{label} is invalid")
    return value


def _exact_keys(
    value: object,
    keys: set[str],
    label: str,
) -> Mapping[str, Any]:
    result = _mapping(value, label)
    if set(result) != keys:
        raise ReleaseGateError(f"{label} is invalid")
    return result


def _revision(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ReleaseGateError(f"{label} is invalid")
    return value


def _release_artifacts(value: object, version: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or len(value) != 2:
        raise ReleaseGateError("fixed stable release artifacts are invalid")
    artifacts: list[dict[str, Any]] = []
    for raw in value:
        artifact = _exact_keys(
            raw,
            {"filename", "packagetype", "sha256", "yanked"},
            "fixed stable release artifact",
        )
        package_type = artifact.get("packagetype")
        filename = artifact.get("filename")
        expected_filename = {
            "bdist_wheel": f"oslo_messaging-{version}-py3-none-any.whl",
            "sdist": f"oslo_messaging-{version}.tar.gz",
        }.get(package_type)
        if filename != expected_filename or artifact.get("yanked") is not False:
            raise ReleaseGateError("fixed stable release artifact is invalid")
        artifacts.append(
            {
                "filename": filename,
                "packagetype": package_type,
                "sha256": _revision(
                    artifact.get("sha256"),
                    SHA256,
                    "fixed stable release artifact SHA-256",
                ),
                "yanked": False,
            }
        )
    if [item["packagetype"] for item in artifacts] != ["bdist_wheel", "sdist"]:
        raise ReleaseGateError("fixed stable release artifacts are unsorted")
    return tuple(artifacts)


def _fixed_release(
    value: object,
    *,
    minimum: Version,
    series: tuple[int, int],
) -> dict[str, Any] | None:
    if value is None:
        return None
    release = _exact_keys(
        value,
        {
            "artifacts",
            "contains_stable_patch",
            "source_probe_present",
            "source_sha256",
            "tag_revision",
            "version",
        },
        "fixed stable release",
    )
    version = Version.parse(release.get("version"))
    if (
        (version.major, version.minor) != series
        or version < minimum
        or release.get("contains_stable_patch") is not True
        or release.get("source_probe_present") is not True
    ):
        raise ReleaseGateError("fixed stable release is outside policy")
    version_text = str(version)
    return {
        "artifacts": list(_release_artifacts(release.get("artifacts"), version_text)),
        "contains_stable_patch": True,
        "source_probe_present": True,
        "source_sha256": _revision(
            release.get("source_sha256"),
            SHA256,
            "fixed stable release source SHA-256",
        ),
        "tag_revision": _revision(
            release.get("tag_revision"),
            SHA1,
            "fixed stable release tag revision",
        ),
        "version": version_text,
    }


def _qualification(
    value: object,
    release: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if release is None:
        raise ReleaseGateError("qualification exists without a fixed release")
    qualification = _exact_keys(
        value,
        {"artifacts_sha256", "schema", "surfaces", "tag_revision", "version"},
        "oslo.messaging qualification",
    )
    if qualification.get("schema") != QUALIFICATION_SCHEMA:
        raise ReleaseGateError("oslo.messaging qualification schema is invalid")
    expected_artifacts = {
        item["filename"]: item["sha256"] for item in release["artifacts"]
    }
    if qualification.get("artifacts_sha256") != expected_artifacts:
        raise ReleaseGateError("qualification artifact identity is invalid")
    if (
        qualification.get("version") != release["version"]
        or qualification.get("tag_revision") != release["tag_revision"]
    ):
        raise ReleaseGateError("qualification release identity is invalid")
    surfaces = _exact_keys(
        qualification.get("surfaces"),
        set(SURFACES),
        "qualification surfaces",
    )
    normalized: dict[str, Any] = {}
    for surface in SURFACES:
        item = _exact_keys(
            surfaces[surface],
            {
                "finding_absent",
                "installed_version",
                "runtime_hostname_verification",
            },
            "qualification surface",
        )
        if (
            item.get("installed_version") != release["version"]
            or item.get("finding_absent") is not True
            or item.get("runtime_hostname_verification") is not True
        ):
            raise ReleaseGateError("qualification surface is not accepted")
        normalized[surface] = dict(item)
    return {
        "artifacts_sha256": expected_artifacts,
        "schema": QUALIFICATION_SCHEMA,
        "surfaces": normalized,
        "tag_revision": release["tag_revision"],
        "version": release["version"],
    }


def classify(value: object) -> dict[str, Any]:
    contract = _exact_keys(
        value,
        {
            "advisory",
            "candidate_policy",
            "current_observation",
            "mainline_observation",
            "package",
            "qualification",
            "schema",
            "stable_series",
            "upstream_metadata",
        },
        "oslo.messaging release gate",
    )
    if contract.get("schema") != SCHEMA or contract.get("package") != "oslo.messaging":
        raise ReleaseGateError("oslo.messaging release gate identity is invalid")
    advisory = _exact_keys(
        contract.get("advisory"),
        {
            "affected_below",
            "finding_id",
            "ossn",
            "security_change",
            "security_revision",
            "source",
        },
        "oslo.messaging advisory",
    )
    if (
        advisory.get("affected_below") != "17.3.1"
        or advisory.get("finding_id") != "CVE-2026-44393"
        or advisory.get("ossn") != "OSSN-0096"
        or advisory.get("security_change") != 989478
        or advisory.get("security_revision") != SECURITY_REVISION
        or advisory.get("source")
        != "https://review.opendev.org/c/openstack/security-doc/+/989478"
    ):
        raise ReleaseGateError("oslo.messaging advisory identity is invalid")

    policy = _exact_keys(
        contract.get("candidate_policy"),
        {
            "minimum_version",
            "required_artifact_types",
            "series",
            "source_probe",
        },
        "oslo.messaging candidate policy",
    )
    minimum = Version.parse(policy.get("minimum_version"))
    if (
        policy.get("series") != "17.3"
        or policy.get("required_artifact_types") != ["bdist_wheel", "sdist"]
        or policy.get("source_probe") != "ssl_enforce_hostname_verification"
        or minimum != Version(17, 3, 1)
    ):
        raise ReleaseGateError("oslo.messaging candidate policy is invalid")

    stable = _exact_keys(
        contract.get("stable_series"),
        {
            "installed_version",
            "name",
            "patch_change",
            "patch_revision",
            "release_notes",
            "upper_constraints",
        },
        "oslo.messaging stable series",
    )
    if (
        stable.get("installed_version") != "17.3.0"
        or stable.get("name") != "stable/2026.1"
        or stable.get("patch_change") != 988979
        or stable.get("patch_revision") != STABLE_PATCH_REVISION
        or stable.get("release_notes")
        != "https://docs.openstack.org/releasenotes/oslo.messaging/2026.1.html"
        or stable.get("upper_constraints")
        != "https://opendev.org/openstack/requirements/raw/branch/stable/2026.1/upper-constraints.txt"
    ):
        raise ReleaseGateError("oslo.messaging stable series is invalid")

    observation = _exact_keys(
        contract.get("current_observation"),
        {
            "as_of",
            "fixed_stable_release",
            "pypi_latest",
            "stable_releases",
            "upper_constraint",
        },
        "oslo.messaging observation",
    )
    if (
        not isinstance(observation.get("as_of"), str)
        or DATE.fullmatch(observation["as_of"]) is None
    ):
        raise ReleaseGateError("oslo.messaging observation date is invalid")
    Version.parse(observation.get("pypi_latest"))
    releases = observation.get("stable_releases")
    if not isinstance(releases, list) or not releases:
        raise ReleaseGateError("oslo.messaging stable releases are invalid")
    parsed_releases = [Version.parse(version) for version in releases]
    if any(
        (version.major, version.minor) != (17, 3) for version in parsed_releases
    ) or parsed_releases != sorted(set(parsed_releases)):
        raise ReleaseGateError("oslo.messaging stable releases are invalid")
    release = _fixed_release(
        observation.get("fixed_stable_release"),
        minimum=minimum,
        series=(17, 3),
    )
    expected_constraint = (
        f"oslo.messaging==={release['version']}"
        if release is not None
        else "oslo.messaging===17.3.0"
    )
    if observation.get("upper_constraint") != expected_constraint:
        raise ReleaseGateError("oslo.messaging upper constraint is not exact")
    if release is not None and Version.parse(release["version"]) not in parsed_releases:
        raise ReleaseGateError("fixed stable release is absent from PyPI releases")

    mainline = _exact_keys(
        contract.get("mainline_observation"),
        {"patch_change", "patch_revision", "tags"},
        "oslo.messaging mainline observation",
    )
    if (
        mainline.get("patch_change") != 988095
        or mainline.get("patch_revision") != MAINLINE_PATCH_REVISION
    ):
        raise ReleaseGateError("oslo.messaging mainline change is invalid")
    tags = mainline.get("tags")
    if (
        not isinstance(tags, list)
        or len(tags) != len(MAINLINE_TAGS)
        or any(not isinstance(item, Mapping) for item in tags)
    ):
        raise ReleaseGateError("oslo.messaging mainline tags are invalid")
    for raw, expected in zip(tags, MAINLINE_TAGS, strict=True):
        tag = _exact_keys(
            raw,
            {"source_probe_present", "source_sha256", "version"},
            "oslo.messaging mainline tag",
        )
        if (
            tag.get("version"),
            tag.get("source_sha256"),
            tag.get("source_probe_present"),
        ) != expected:
            raise ReleaseGateError("oslo.messaging mainline source observation drifted")

    metadata = _exact_keys(
        contract.get("upstream_metadata"),
        {"pypi", "source_template"},
        "oslo.messaging upstream metadata",
    )
    if (
        metadata.get("pypi") != "https://pypi.org/pypi/oslo.messaging/json"
        or metadata.get("source_template")
        != "https://opendev.org/openstack/oslo.messaging/raw/tag/{version}/oslo_messaging/_drivers/impl_rabbit.py"
    ):
        raise ReleaseGateError("oslo.messaging upstream metadata is invalid")

    qualification = _qualification(contract.get("qualification"), release)
    status = "blocked"
    reasons = [
        "stable/2026.1 has no official fixed oslo.messaging release",
        "stable/2026.1 upper constraints remain at oslo.messaging 17.3.0",
    ]
    if release is not None:
        status = "candidate-released"
        reasons = ["fixed release still requires exact two-surface image qualification"]
        if qualification is not None:
            status = "candidate-qualified"
            reasons = []
    return {
        "schema": RESULT_SCHEMA,
        "status": status,
        "production_candidate": False,
        "finding_id": advisory["finding_id"],
        "installed_version": stable["installed_version"],
        "stable_patch_merged": True,
        "fixed_stable_release": release,
        "qualification_accepted": qualification is not None,
        "mainline_advisory_discrepancy": {
            "claimed_version": "18.0.0",
            "first_verified_source_version": "18.1.0",
        },
        "reasons": reasons,
        "next_action": (
            "wait for an official stable/2026.1 fixed release and matching "
            "upper-constraints update"
            if release is None
            else "run exact Horizon and Skyline runtime and scanner qualification"
        ),
    }


def load_contract(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReleaseGateError("oslo.messaging release gate is missing or linked")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseGateError("oslo.messaging release gate is unreadable") from error
    return dict(_mapping(value, "oslo.messaging release gate"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).with_name("oslo_messaging_release_gate.json"),
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="return success after validating a blocked fail-closed result",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        report = classify(load_contract(arguments.contract))
        if arguments.output is not None:
            atomic_json(arguments.output, report)
    except (CollectionError, ReleaseGateError) as error:
        print(f"coffer-ui-oslo-messaging-release-gate: {error}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        0 if report["status"] == "candidate-qualified" or arguments.allow_blocked else 3
    )


if __name__ == "__main__":
    raise SystemExit(main())
