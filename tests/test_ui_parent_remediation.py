from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "poc" / "ui-images" / "remediation.py"
)
SPEC = importlib.util.spec_from_file_location(
    "coffer_ui_parent_remediation",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
REMEDIATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REMEDIATION
SPEC.loader.exec_module(REMEDIATION)


def trivy_findings() -> list[dict[str, str]]:
    return [
        {
            "VulnerabilityID": "CVE-python",
            "PkgName": "Django",
            "InstalledVersion": "4.2.28",
            "FixedVersion": "4.2.29",
            "Severity": "HIGH",
        },
        {
            "VulnerabilityID": "CVE-linux",
            "PkgName": "linux-libc-dev",
            "InstalledVersion": "6.8.0",
            "FixedVersion": "",
            "Severity": "CRITICAL",
        },
    ]


def scout_rules() -> list[dict[str, object]]:
    return [
        {
            "id": "CVE-python",
            "name": "PythonPackageVulnerability",
            "properties": {
                "cvssV3_severity": "HIGH",
                "purls": ["pkg:pypi/Django@4.2.28"],
                "fixed_version": "4.2.29",
            },
        },
        {
            "id": "CVE-linux",
            "name": "OsPackageVulnerability",
            "properties": {
                "cvssV3_severity": "CRITICAL",
                "purls": [
                    "pkg:deb/ubuntu/linux@6.8.0"
                    "?os_distro=noble&os_name=ubuntu"
                ],
                "fixed_version": "not fixed",
            },
        },
    ]


def write_trivy(path: Path, findings: list[dict[str, str]]) -> None:
    python = [finding for finding in findings if finding["PkgName"] == "Django"]
    os_packages = [
        finding for finding in findings if finding["PkgName"] == "linux-libc-dev"
    ]
    path.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "Results": [
                    {
                        "Class": "os-pkgs",
                        "Type": "ubuntu",
                        "Vulnerabilities": os_packages,
                    },
                    {
                        "Class": "lang-pkgs",
                        "Type": "python-pkg",
                        "Vulnerabilities": python,
                    },
                ],
            }
        )
    )


def write_scout(path: Path, rules: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "name": "docker scout",
                                "version": "fixture",
                                "rules": rules,
                            }
                        }
                    }
                ],
            }
        )
    )


def source_archive(path: Path, constraints: bytes | None = None) -> Path:
    payload = constraints or b"Django===4.2.28\nurllib3===2.6.3\n"
    with tarfile.open(path, "w") as archive:
        root = tarfile.TarInfo("openstack_requirements-fixture/upper-constraints.txt")
        root.size = len(payload)
        archive.addfile(root, io.BytesIO(payload))
        nested_payload = b"not-the-build-input===1\n"
        nested = tarfile.TarInfo(
            "openstack_requirements-fixture/tests/files/upper-constraints.txt"
        )
        nested.size = len(nested_payload)
        archive.addfile(nested, io.BytesIO(nested_payload))
    return path


def evidence(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "evidence"
    root.mkdir()
    qualification = {
        "schema": REMEDIATION.QUALIFICATION_SCHEMA,
        "architecture": "arm64",
        "status": "blocked",
        "production_candidate": False,
        "surfaces": {
            surface: {
                "images": {
                    kind: {
                        "trivy": {"critical": 1, "high": 1},
                        "scout": {"critical": 1, "high": 1},
                    }
                    for kind in ("parent", "custom")
                }
            }
            for surface in REMEDIATION.SURFACES
        },
    }
    (root / "qualification.json").write_text(json.dumps(qualification))
    for surface in REMEDIATION.SURFACES:
        for kind in ("parent", "custom"):
            write_trivy(root / f"{surface}-{kind}.trivy.json", trivy_findings())
            write_scout(root / f"{surface}-{kind}.scout.sarif.json", scout_rules())
    return root, source_archive(tmp_path / "openstack-base.tar")


def build(root: Path, archive: Path) -> dict[str, object]:
    return REMEDIATION.build_report(
        root,
        openstack_base_archive=archive,
        requirements_revision="a" * 40,
    )


def test_report_binds_constraints_and_preserves_absolute_block(
    tmp_path: Path,
) -> None:
    root, archive = evidence(tmp_path)

    report = build(root, archive)

    assert report["decision"]["status"] == "blocked"
    assert report["decision"]["production_candidate"] is False
    assert report["decision"]["waivers_applied"] is False
    assert report["requirements"]["revision"] == "a" * 40
    assert report["requirements"]["constraints_member"].endswith(
        "/upper-constraints.txt"
    )
    horizon = report["surfaces"]["horizon"]
    django = next(
        package for package in horizon["packages"] if package["package"] == "django"
    )
    assert django == {
        "ecosystem": "pypi",
        "package": "django",
        "installed_version": "4.2.28",
        "constraint_version": "4.2.28",
        "constraint_match": True,
        "scanners": ["scout", "trivy"],
        "finding_ids": ["CVE-python"],
        "severity_counts": {"high": 2},
        "fixed_versions": ["4.2.29"],
        "unfixed_finding_ids": [],
        "classification": "constraint-bound-all-findings-have-fix",
        "eligible_for_compatibility_trial": True,
    }
    assert horizon["compatibility_trial_candidates"] == ["django"]
    assert any(
        package["classification"] == "os-no-fixed-version"
        for package in horizon["packages"]
    )


def test_parent_custom_divergence_is_rejected(tmp_path: Path) -> None:
    root, archive = evidence(tmp_path)
    changed = scout_rules()
    changed[0] = {
        **changed[0],
        "id": "CVE-custom-only",
    }
    write_scout(root / "horizon-custom.scout.sarif.json", changed)

    with pytest.raises(REMEDIATION.EvidenceError, match="findings diverge"):
        build(root, archive)


def test_qualification_count_mismatch_is_rejected(tmp_path: Path) -> None:
    root, archive = evidence(tmp_path)
    qualification_path = root / "qualification.json"
    qualification = json.loads(qualification_path.read_text())
    qualification["surfaces"]["skyline"]["images"]["parent"]["trivy"]["high"] = 0
    qualification_path.write_text(json.dumps(qualification))

    with pytest.raises(REMEDIATION.EvidenceError, match="do not match"):
        build(root, archive)


def test_revision_and_archive_contracts_fail_closed(tmp_path: Path) -> None:
    root, archive = evidence(tmp_path)
    with pytest.raises(REMEDIATION.EvidenceError, match="lowercase commit SHA"):
        REMEDIATION.build_report(
            root,
            openstack_base_archive=archive,
            requirements_revision="latest",
        )

    empty_archive = source_archive(tmp_path / "empty.tar", b"# no pins\n")
    with pytest.raises(REMEDIATION.EvidenceError, match="no pinned packages"):
        build(root, empty_archive)


def test_atomic_result_refuses_different_evidence(tmp_path: Path) -> None:
    root, archive = evidence(tmp_path)
    report = build(root, archive)
    output = root / "remediation.json"

    REMEDIATION.write_result(output, report)
    inode = output.stat().st_ino
    REMEDIATION.write_result(output, report)
    assert output.stat().st_ino == inode
    assert output.stat().st_mode & 0o777 == 0o640

    changed = dict(report)
    changed["architecture"] = "amd64"
    with pytest.raises(REMEDIATION.EvidenceError, match="refusing to replace"):
        REMEDIATION.write_result(output, changed)
