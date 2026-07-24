from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re


def scout_counts(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"vulnerabilities\s+│\s+(\d+)C\s+(\d+)H\s+(\d+)M\s+(\d+)L",
        text,
    )
    if not match:
        raise RuntimeError(f"Scout overview is missing from {path}")
    return dict(zip(("critical", "high", "medium", "low"), map(int, match.groups())))


def trivy_counts(path: Path) -> dict[str, int]:
    document = json.loads(path.read_text(encoding="utf-8"))
    severities: Counter[str] = Counter()
    for result in document.get("Results", []):
        for finding in result.get("Vulnerabilities") or []:
            severities[str(finding.get("Severity", "UNKNOWN")).lower()] += 1
    return {
        severity: severities[severity]
        for severity in ("critical", "high", "medium", "low", "unknown")
    }


def trivy_secret_count(path: Path) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        len(result.get("Secrets") or []) for result in document.get("Results", [])
    )


def sbom_package_count(path: Path) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not str(document.get("spdxVersion", "")).startswith("SPDX-"):
        raise RuntimeError(f"SPDX metadata is missing from {path}")
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RuntimeError(f"SPDX package inventory is empty in {path}")
    return len(packages)


def image_contract(path: Path) -> dict[str, object]:
    images = json.loads(path.read_text(encoding="utf-8"))
    expected_users = {"coffer", "registry"}
    actual_users = {str(image.get("user", "")) for image in images}
    architectures = {str(image.get("architecture", "")) for image in images}
    operating_systems = {str(image.get("os", "")) for image in images}
    revisions = {
        str((image.get("labels") or {}).get("org.opencontainers.image.revision", ""))
        for image in images
    }
    valid = (
        len(images) == 2
        and actual_users == expected_users
        and len(architectures) == 1
        and architectures <= {"amd64", "arm64"}
        and operating_systems == {"linux"}
        and len(revisions) == 1
        and "" not in revisions
    )
    return {
        "valid": valid,
        "users": sorted(actual_users),
        "architectures": sorted(architectures),
        "operating_systems": sorted(operating_systems),
        "revisions": sorted(revisions),
    }


def vulnerability_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"Your code is affected by (\d+) vulnerabilities?", text)
    if not match:
        raise RuntimeError(f"govulncheck result is missing from {path}")
    return int(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    arguments = parser.parse_args()
    evidence = arguments.evidence

    report = {
        "schema": "coffer.production-image-qualification.v1",
        "runtime_contract": (evidence / "runtime-contract.passed").is_file(),
        "release_provenance": (evidence / "release-provenance.passed").is_file(),
        "image_contract": image_contract(evidence / "images.json"),
        "sbom": {
            image: {
                "format": "SPDX",
                "packages": sbom_package_count(evidence / f"{image}.spdx.json"),
            }
            for image in ("coffer", "registry")
        },
        "scout": {
            "coffer": scout_counts(evidence / "coffer-critical-high.txt"),
            "registry": scout_counts(evidence / "registry-critical-high.txt"),
        },
        "trivy": {
            "coffer": trivy_counts(evidence / "coffer.trivy.json"),
            "registry": trivy_counts(evidence / "registry.trivy.json"),
        },
        "secrets": {
            image: trivy_secret_count(evidence / f"{image}.trivy.json")
            for image in ("coffer", "registry")
        },
        "govulncheck": {
            "source_reachable": vulnerability_count(
                evidence / "distribution-source.govulncheck.txt"
            ),
            "release_binary_symbols": vulnerability_count(
                evidence / "distribution-binary.govulncheck.txt"
            ),
        },
    }

    blockers: list[str] = []
    if not report["runtime_contract"]:
        blockers.append("runtime contract did not pass")
    if not report["release_provenance"]:
        blockers.append("release provenance did not pass")
    if not report["image_contract"]["valid"]:
        blockers.append("image architecture/non-root/provenance contract did not pass")
    for image in ("coffer", "registry"):
        if not report["sbom"][image]["packages"]:
            blockers.append(f"{image} SBOM package inventory is empty")
        if report["secrets"][image]:
            blockers.append(
                f"Trivy found {report['secrets'][image]} secrets in {image}"
            )
    for scanner in ("scout", "trivy"):
        for image in ("coffer", "registry"):
            counts = report[scanner][image]
            if counts["critical"] or counts["high"]:
                blockers.append(
                    f"{scanner} {image} has "
                    f"{counts['critical']} Critical/{counts['high']} High"
                )
    if report["govulncheck"]["source_reachable"]:
        blockers.append(
            "signed Distribution source has "
            f"{report['govulncheck']['source_reachable']} reachable vulnerabilities"
        )
    if report["govulncheck"]["release_binary_symbols"]:
        blockers.append(
            "signed Distribution binary has "
            f"{report['govulncheck']['release_binary_symbols']} vulnerable symbol groups"
        )

    report["production_candidate"] = not blockers
    report["blockers"] = blockers
    output = evidence / "qualification.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not blockers else 3


if __name__ == "__main__":
    raise SystemExit(main())
