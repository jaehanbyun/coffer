from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TARGET_MODULE = load(
    "python_target",
    ROOT / "poc" / "ui-images" / "python_target.py",
)
TRIAL = load(
    "coffer_ui_python_overlay_trial",
    ROOT / "poc" / "ui-images" / "python_trial.py",
)
COLLECTOR = load(
    "coffer_ui_python_overlay_collector",
    ROOT / "poc" / "ui-images" / "collect_python_trial.py",
)
RUNTIME = load(
    "coffer_ui_python_overlay_runtime",
    ROOT / "poc" / "ui-images" / "collect_python_runtime.py",
)
TARGET_MANIFEST = ROOT / "poc" / "ui-images" / "python_targets.json"
BASE_TARGETS = TARGET_MODULE.load_targets(TARGET_MANIFEST)


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def wheel(
    path: Path,
    surface: str,
    target: Any,
) -> tuple[Path, dict[str, str]]:
    if surface == "horizon":
        files = {member: member.encode() for member in TRIAL.HORIZON_MEMBERS}
    elif surface == "skyline":
        files = {"skyline_console/static/coffer.bundle.123.js": b"bundle"}
    else:
        files = {
            f"{target.package_prefix}__init__.py": b"version = 'fixture'\n",
            f"{target.package_prefix}client.py": b"class Client: pass\n",
        }
    with ZipFile(path, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    return path, {
        member: hashlib.sha256(content).hexdigest()
        for member, content in files.items()
    }


def write_trivy(path: Path, identifiers: list[str], target: Any) -> None:
    def component_for(identifier: str) -> Any | None:
        return next(
            (
                component
                for component in target.components
                if identifier in component.finding_ids_for("trivy")
            ),
            None,
        )

    path.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "CreatedAt": "fixture",
                "Results": [
                    {
                        "Class": "lang-pkgs",
                        "Type": "python-pkg",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": identifier,
                                "PkgName": (
                                    component_for(identifier).display_name
                                    if component_for(identifier) is not None
                                    else "remaining"
                                ),
                                "InstalledVersion": (
                                    component_for(identifier).from_version
                                    if component_for(identifier) is not None
                                    else "1"
                                ),
                                "FixedVersion": (
                                    component_for(identifier).to_version
                                    if component_for(identifier) is not None
                                    else ""
                                ),
                                "Severity": "HIGH",
                            }
                            for identifier in identifiers
                        ],
                    }
                ],
            }
        )
    )


def write_scout(path: Path, identifiers: list[str], target: Any) -> None:
    def component_for(identifier: str) -> Any | None:
        return next(
            (
                component
                for component in target.components
                if identifier in component.finding_ids_for("scout")
            ),
            None,
        )

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
                                "rules": [
                                    {
                                        "id": identifier,
                                        "properties": {
                                            "cvssV3_severity": "HIGH",
                                            "purls": [
                                                (
                                                    "pkg:pypi/"
                                                    f"{component_for(identifier).normalized_name}"
                                                    "@"
                                                    f"{component_for(identifier).from_version}"
                                                    if component_for(identifier)
                                                    is not None
                                                    else "pkg:pypi/remaining@1"
                                                )
                                            ],
                                            "affected_version": "1",
                                            "fixed_version": (
                                                component_for(
                                                    identifier
                                                ).to_version
                                                if component_for(identifier)
                                                is not None
                                                else "not fixed"
                                            ),
                                        },
                                    }
                                    for identifier in identifiers
                                ],
                            }
                        }
                    }
                ],
            }
        )
    )


def os_inventory() -> dict[str, object]:
    return {
        "schema": TRIAL.PACKAGE_INVENTORY_SCHEMA,
        "architecture": "arm64",
        "os": {"id": "ubuntu", "version_id": "24.04"},
        "packages": [
            {
                "name": "base-runtime",
                "version": "1",
                "status": "ii ",
                "manual": True,
                "automatic": False,
            }
        ],
        "package_database": {
            "dpkg_audit_clean": True,
            "apt_dependency_check_clean": True,
        },
    }


def python_runtime(
    *,
    target: Any,
    kind: str,
    target_files: dict[str, dict[str, str]],
    probe_mode: str,
) -> dict[str, object]:
    if kind not in {"before", "after"}:
        raise ValueError("invalid fixture runtime kind")
    return {
        "schema": TRIAL.PYTHON_RUNTIME_SCHEMA,
        "architecture": "arm64",
        "packages": {
            "base": ["1"],
            **{
                component.normalized_name: [
                    component.from_version
                    if kind == "before"
                    else component.to_version
                ]
                for component in target.components
            },
        },
        "components": [
            {
                "name": component.normalized_name,
                "version": (
                    component.from_version
                    if kind == "before"
                    else component.to_version
                ),
                "files": target_files[component.normalized_name],
            }
            for component in target.components
        ],
        "probe": {
            "name": target.probe,
            "mode": probe_mode,
            "result": target.expected_probe_result,
        },
        "pip_check": {
            "clean": True,
            "message": "No broken requirements found.",
        },
        "absent": [
            "/tmp/target-wheels",
            "/tmp/python_target.py",
            "/tmp/python_targets.json",
        ],
    }


def fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_key: str = "mako",
    surfaces: tuple[str, ...] | None = None,
    finding_ids_by_scanner: dict[str, list[str]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True)
    artifacts: dict[str, Any] = {}
    wheel_files: dict[str, dict[str, str]] = {}
    base_target = BASE_TARGETS[target_key]
    for surface in TRIAL.SURFACES:
        artifacts[surface], wheel_files[surface] = wheel(
            tmp_path / f"{surface}.whl",
            surface,
            base_target,
        )
    target_wheels: list[Path] = []
    target_wheel_files: dict[str, dict[str, str]] = {}
    for component in base_target.components:
        target_wheel, files = wheel(
            tmp_path / component.wheel_filename,
            "target",
            component,
        )
        target_wheels.append(target_wheel)
        target_wheel_files[component.normalized_name] = files
    target_document = json.loads(TARGET_MANIFEST.read_text())
    target_document["targets"] = {
        target_key: target_document["targets"][target_key]
    }
    if surfaces is not None:
        target_document["targets"][target_key]["surfaces"] = list(surfaces)
    if finding_ids_by_scanner is not None:
        target_document["targets"][target_key][
            "finding_ids_by_scanner"
        ] = finding_ids_by_scanner
    target_entry = target_document["targets"][target_key]
    target_entry["wheel_sha256"] = TRIAL.sha256_file(target_wheels[0])
    for companion, target_wheel in zip(
        target_entry.get("companions", []),
        target_wheels[1:],
        strict=True,
    ):
        companion["wheel_sha256"] = TRIAL.sha256_file(target_wheel)
    target_manifest = tmp_path / "python_targets.json"
    target_manifest.write_text(json.dumps(target_document, sort_keys=True))
    target = TARGET_MODULE.load_target(target_manifest, target_key)
    artifacts["target_manifest"] = target_manifest
    artifacts["target_spec"] = target
    artifacts["target_wheels"] = tuple(target_wheels)

    baseline = tmp_path / "cleanup-trial.json"
    baseline.write_text(
        json.dumps(
            {
                "schema": TRIAL.OS_CLEANUP_RESULT_SCHEMA,
                "decision": {
                    "status": "blocked",
                    "production_candidate": False,
                    "os_cleanup_trial_accepted": True,
                },
            }
        )
    )
    remediation = tmp_path / "remediation.json"
    candidates = [
        {
            "package": component.normalized_name,
            "classification": "constraint-bound-all-findings-have-fix",
            "eligible_for_compatibility_trial": True,
            "constraint_match": True,
            "installed_version": component.from_version,
            "constraint_version": component.from_version,
            "fixed_versions": [component.to_version],
            "finding_ids": list(component.finding_ids),
        }
        for component in target.components
    ]
    remediation.write_text(
        json.dumps(
            {
                "schema": TRIAL.REMEDIATION_SCHEMA,
                "surfaces": {
                    surface: {"packages": candidates}
                    for surface in TRIAL.SURFACES
                },
            }
        )
    )
    monkeypatch.setattr(
        TRIAL,
        "OS_CLEANUP_RESULT_SHA256",
        TRIAL.sha256_file(baseline),
    )
    baseline_inventories = tmp_path / "cleanup-inventories.json"
    baseline_inventories.write_text(
        json.dumps(
            {
                "schema": "coffer.ui-os-cleanup-inventories/v1",
                "images": {
                    f"{surface}-after": os_inventory()
                    for surface in TRIAL.SURFACES
                },
            }
        )
    )
    monkeypatch.setattr(
        TRIAL,
        "OS_CLEANUP_INVENTORIES_SHA256",
        TRIAL.sha256_file(baseline_inventories),
    )
    monkeypatch.setattr(
        TRIAL,
        "REMEDIATION_RESULT_SHA256",
        TRIAL.sha256_file(remediation),
    )
    artifacts["baseline"] = baseline
    artifacts["baseline_inventories"] = baseline_inventories
    artifacts["remediation"] = remediation

    manifest = {
        "schema": TRIAL.MANIFEST_SCHEMA,
        "architecture": "arm64",
        "platform": "linux/arm64",
        "sources": {
            "ubuntu_sha256": "a" * 64,
            "kolla": TRIAL.KOLLA_REVISION,
            "horizon": TRIAL.HORIZON_REVISION,
            "skyline": TRIAL.SKYLINE_REVISION,
        },
        "artifacts": {
            "horizon": {
                "name": "coffer-horizon",
                "version": "0.1.0",
                "sha256": TRIAL.sha256_file(artifacts["horizon"]),
            },
            "skyline": {
                "name": "skyline-console",
                "version": "8.0.0+coffer.1",
                "sha256": TRIAL.sha256_file(artifacts["skyline"]),
            },
            "target": {
                "key": target.key,
                "manifest_sha256": TRIAL.sha256_file(target_manifest),
                "probe": target.probe,
                "trial_label": target.trial_label,
                "finding_ids": list(target.finding_ids),
                "finding_ids_by_scanner": target.scanner_finding_ids,
                "surfaces": list(target.surfaces),
                "components": [
                    TRIAL._component_artifact(component)
                    for component in target.components
                ],
            },
        },
        "baseline": {
            "os_cleanup_result_sha256": TRIAL.sha256_file(baseline),
            "os_cleanup_inventories_sha256": TRIAL.sha256_file(
                baseline_inventories
            ),
            "remediation_result_sha256": TRIAL.sha256_file(remediation),
        },
        "images": {
            f"{surface}-{kind}": {
                "name": (
                    f"localhost/coffer-ui-python-trial-{surface}-{kind}:"
                    "2026.1-python-overlay"
                ),
                "id": digest(f"{surface}-{kind}"),
            }
            for surface in target.surfaces
            for kind in TRIAL.KINDS
        },
        "scanners": {"docker_scout": "fixture", "trivy": "fixture"},
    }
    (evidence / "manifest.json").write_text(json.dumps(manifest))

    images = {}
    for surface in target.surfaces:
        before_layers = [digest(f"{surface}-coffer"), digest(f"{surface}-cleanup")]
        common = {
            "architecture": "arm64",
            "os": "linux",
            "user": "root",
            "entrypoint": ["/usr/local/bin/kolla_start"],
            "cmd": [],
        }
        base_labels = {
            "io.coffer.ui.contract": "coffer-ui-image-v1",
            "io.coffer.ui.surface": surface,
            "io.coffer.ui.os-cleanup-trial": "coffer-ui-os-cleanup-v1",
            "org.opencontainers.image.revision": (
                TRIAL.HORIZON_REVISION
                if surface == "horizon"
                else TRIAL.SKYLINE_REVISION
            ),
        }
        images[f"{surface}-before"] = {
            **common,
            "id": manifest["images"][f"{surface}-before"]["id"],
            "labels": base_labels,
            "layers": before_layers,
        }
        images[f"{surface}-after"] = {
            **common,
            "id": manifest["images"][f"{surface}-after"]["id"],
            "labels": {
                **base_labels,
                "io.coffer.ui.python-overlay-trial": target.trial_label,
            },
            "layers": before_layers + [digest(f"{surface}-overlay")],
        }
    (evidence / "images.json").write_text(
        json.dumps({"schema": TRIAL.IMAGE_SCHEMA, "images": images})
    )
    inventories = {
        f"{surface}-{kind}": os_inventory()
        for surface in target.surfaces
        for kind in TRIAL.KINDS
    }
    (evidence / "os-inventories.json").write_text(
        json.dumps({"schema": TRIAL.INVENTORY_SCHEMA, "images": inventories})
    )
    python = {
        f"{surface}-{kind}": python_runtime(
            target=target,
            kind=kind,
            target_files=(
                {
                    component.normalized_name: {
                        f"{component.package_prefix}old.py": digest(
                            f"{component.normalized_name}-old"
                        ).removeprefix("sha256:")
                    }
                    for component in target.components
                }
                if kind == "before"
                else target_wheel_files
            ),
            probe_mode="baseline" if kind == "before" else "candidate",
        )
        for surface in target.surfaces
        for kind in TRIAL.KINDS
    }
    ui_all = {
        "horizon": {
            "package": {"name": "coffer-horizon", "version": "0.1.0"},
            "files": wheel_files["horizon"],
            "absent": list(TRIAL.HORIZON_ABSENT),
        },
        "skyline": {
            "package": {
                "name": "skyline-console",
                "version": "8.0.0+coffer.1",
            },
            "files": wheel_files["skyline"],
            "absent": list(TRIAL.SKYLINE_ABSENT),
        },
    }
    ui = {surface: ui_all[surface] for surface in target.surfaces}
    (evidence / "runtimes.json").write_text(
        json.dumps(
            {
                "schema": TRIAL.RUNTIME_SCHEMA,
                "architecture": "arm64",
                "python": python,
                "ui": ui,
            }
        )
    )
    for surface in target.surfaces:
        trivy_before = [*target.finding_ids_for("trivy"), "CVE-remaining"]
        scout_before = [*target.finding_ids_for("scout"), "CVE-remaining"]
        write_trivy(
            evidence / f"{surface}-before.trivy.json",
            trivy_before,
            target,
        )
        write_trivy(
            evidence / f"{surface}-after.trivy.json",
            ["CVE-remaining"],
            target,
        )
        write_scout(
            evidence / f"{surface}-before.scout.sarif.json",
            scout_before,
            target,
        )
        write_scout(
            evidence / f"{surface}-after.scout.sarif.json",
            ["CVE-remaining"],
            target,
        )
    return evidence, artifacts


def build(
    evidence: Path,
    artifacts: dict[str, Any],
    *,
    target_wheels: tuple[Path, ...] | None = None,
) -> dict[str, object]:
    return TRIAL.build_report(
        evidence,
        target=artifacts["target_spec"],
        target_manifest_path=artifacts["target_manifest"],
        baseline_result_path=artifacts["baseline"],
        baseline_inventories_path=artifacts["baseline_inventories"],
        remediation_result_path=artifacts["remediation"],
        horizon_wheel=artifacts["horizon"],
        skyline_wheel=artifacts["skyline"],
        target_wheels=target_wheels or artifacts["target_wheels"],
    )


@pytest.mark.parametrize(
    "target_key",
    [
        "click",
        "cryptography-pyopenssl",
        "django",
        "mako",
        "httplib2",
        "lxml",
        "msgpack",
        "pillow",
        "pyjwt",
        "ujson",
        "urllib3",
    ],
)
def test_valid_overlay_is_accepted_but_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_key: str,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch, target_key)
    target = artifacts["target_spec"]

    report = build(evidence, artifacts)

    assert report["decision"]["status"] == "blocked"
    assert report["decision"]["production_candidate"] is False
    assert report["decision"]["python_overlay_trial_accepted"] is True
    assert report["decision"]["target"] == target.result_name
    assert report["decision"]["private_constraint_override_accepted"] is False
    for surface in target.surfaces:
        for scanner in TRIAL.SCANNERS:
            result = report["surfaces"][surface]["scanners"][scanner]
            assert result["removed_finding_ids"] == list(
                target.finding_ids_for(scanner)
            )
            assert result["introduced_critical_high"] == 0


@pytest.mark.parametrize("wheel_set", ["missing", "reversed", "duplicate"])
def test_coupled_overlay_rejects_inexact_wheel_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wheel_set: str,
) -> None:
    evidence, artifacts = fixture(
        tmp_path,
        monkeypatch,
        "cryptography-pyopenssl",
    )
    target_wheels = artifacts["target_wheels"]
    candidates = {
        "missing": target_wheels[:1],
        "reversed": tuple(reversed(target_wheels)),
        "duplicate": (target_wheels[0], target_wheels[0]),
    }

    with pytest.raises(TRIAL.EvidenceError, match="target wheel set"):
        build(
            evidence,
            artifacts,
            target_wheels=candidates[wheel_set],
        )


def test_coupled_overlay_rejects_missing_runtime_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(
        tmp_path,
        monkeypatch,
        "cryptography-pyopenssl",
    )
    runtimes_path = evidence / "runtimes.json"
    runtimes = json.loads(runtimes_path.read_text())
    runtimes["python"]["horizon-after"]["components"].pop()
    runtimes_path.write_text(json.dumps(runtimes))

    with pytest.raises(TRIAL.EvidenceError, match="component count"):
        build(evidence, artifacts)


def test_surface_scoped_overlay_excludes_unselected_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(
        tmp_path,
        monkeypatch,
        surfaces=("horizon",),
    )

    report = build(evidence, artifacts)

    assert set(report["surfaces"]) == {"horizon"}
    assert artifacts["target_spec"].surfaces == ("horizon",)
    assert not list(evidence.glob("skyline-*.json"))


def test_scanner_specific_empty_expected_delta_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scout_findings = list(BASE_TARGETS["mako"].finding_ids)
    evidence, artifacts = fixture(
        tmp_path,
        monkeypatch,
        finding_ids_by_scanner={
            "trivy": [],
            "scout": scout_findings,
        },
    )

    report = build(evidence, artifacts)

    horizon = report["surfaces"]["horizon"]["scanners"]
    assert horizon["trivy"]["removed_finding_ids"] == []
    assert horizon["scout"]["removed_finding_ids"] == scout_findings
    assert artifacts["target_spec"].finding_ids == tuple(scout_findings)


def test_scanner_specific_unexpected_delta_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scout_findings = list(BASE_TARGETS["mako"].finding_ids)
    evidence, artifacts = fixture(
        tmp_path,
        monkeypatch,
        finding_ids_by_scanner={
            "trivy": [],
            "scout": scout_findings,
        },
    )
    write_trivy(
        evidence / "horizon-before.trivy.json",
        [scout_findings[0], "CVE-remaining"],
        artifacts["target_spec"],
    )

    with pytest.raises(TRIAL.EvidenceError, match="target finding delta"):
        build(evidence, artifacts)


def test_canonical_ghsa_finding_contract_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finding = "GHSA-6v7p-g79w-8964"
    evidence, artifacts = fixture(
        tmp_path,
        monkeypatch,
        finding_ids_by_scanner={
            "trivy": [finding],
            "scout": [finding],
        },
    )

    report = build(evidence, artifacts)

    for surface in TRIAL.SURFACES:
        for scanner in TRIAL.SCANNERS:
            assert report["surfaces"][surface]["scanners"][scanner][
                "removed_finding_ids"
            ] == [finding]


def test_python_and_os_package_delta_tamper_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch)
    runtimes_path = evidence / "runtimes.json"
    runtimes = json.loads(runtimes_path.read_text())
    runtimes["python"]["horizon-after"]["packages"]["base"] = ["2"]
    runtimes_path.write_text(json.dumps(runtimes))
    with pytest.raises(TRIAL.EvidenceError, match="Python package delta"):
        build(evidence, artifacts)

    evidence, artifacts = fixture(tmp_path / "second", monkeypatch)
    inventories_path = evidence / "os-inventories.json"
    inventories = json.loads(inventories_path.read_text())
    inventories["images"]["skyline-after"]["packages"][0]["version"] = "2"
    inventories_path.write_text(json.dumps(inventories))
    with pytest.raises(TRIAL.EvidenceError, match="changed OS packages"):
        build(evidence, artifacts)


def test_lineage_runtime_and_target_finding_tamper_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch)
    images_path = evidence / "images.json"
    images = json.loads(images_path.read_text())
    images["images"]["horizon-after"]["entrypoint"] = ["/bin/false"]
    images_path.write_text(json.dumps(images))
    with pytest.raises(TRIAL.EvidenceError, match="Kolla entrypoint"):
        build(evidence, artifacts)

    evidence, artifacts = fixture(tmp_path / "second", monkeypatch)
    runtimes_path = evidence / "runtimes.json"
    runtimes = json.loads(runtimes_path.read_text())
    runtimes["python"]["skyline-after"]["components"][0]["files"] = {}
    runtimes_path.write_text(json.dumps(runtimes))
    with pytest.raises(TRIAL.EvidenceError, match="target wheel files"):
        build(evidence, artifacts)

    evidence, artifacts = fixture(tmp_path / "third", monkeypatch)
    write_trivy(
        evidence / "horizon-after.trivy.json",
        ["CVE-2026-44307", "CVE-remaining"],
        artifacts["target_spec"],
    )
    with pytest.raises(TRIAL.EvidenceError, match="target finding delta"):
        build(evidence, artifacts)


def test_baseline_and_candidate_tamper_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch)
    baseline = json.loads(artifacts["baseline"].read_text())
    baseline["decision"]["os_cleanup_trial_accepted"] = False
    artifacts["baseline"].write_text(json.dumps(baseline))
    monkeypatch.setattr(
        TRIAL,
        "OS_CLEANUP_RESULT_SHA256",
        TRIAL.sha256_file(artifacts["baseline"]),
    )
    with pytest.raises(TRIAL.EvidenceError, match="not accepted"):
        build(evidence, artifacts)

    evidence, artifacts = fixture(tmp_path / "second", monkeypatch)
    remediation = json.loads(artifacts["remediation"].read_text())
    remediation["surfaces"]["horizon"]["packages"][0][
        "eligible_for_compatibility_trial"
    ] = False
    artifacts["remediation"].write_text(json.dumps(remediation))
    monkeypatch.setattr(
        TRIAL,
        "REMEDIATION_RESULT_SHA256",
        TRIAL.sha256_file(artifacts["remediation"]),
    )
    with pytest.raises(TRIAL.EvidenceError, match="target candidate"):
        build(evidence, artifacts)


def test_selected_release_may_be_newer_than_reported_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch, "ujson")
    remediation = json.loads(artifacts["remediation"].read_text())
    for surface in TRIAL.SURFACES:
        remediation["surfaces"][surface]["packages"][0]["fixed_versions"] = [
            "5.12.0",
            "5.12.1",
        ]
    artifacts["remediation"].write_text(json.dumps(remediation))
    monkeypatch.setattr(
        TRIAL,
        "REMEDIATION_RESULT_SHA256",
        TRIAL.sha256_file(artifacts["remediation"]),
    )
    manifest_path = evidence / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["baseline"]["remediation_result_sha256"] = TRIAL.sha256_file(
        artifacts["remediation"]
    )
    manifest_path.write_text(json.dumps(manifest))

    report = build(evidence, artifacts)

    assert report["decision"]["target"] == "ujson==5.13.0"


@pytest.mark.parametrize("fixed_version", ["5.14.0", "not-a-release"])
def test_selected_release_must_reach_a_numeric_reported_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixed_version: str,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch, "ujson")
    remediation = json.loads(artifacts["remediation"].read_text())
    for surface in TRIAL.SURFACES:
        remediation["surfaces"][surface]["packages"][0]["fixed_versions"] = [
            fixed_version
        ]
    artifacts["remediation"].write_text(json.dumps(remediation))
    monkeypatch.setattr(
        TRIAL,
        "REMEDIATION_RESULT_SHA256",
        TRIAL.sha256_file(artifacts["remediation"]),
    )

    with pytest.raises(
        TRIAL.EvidenceError,
        match="target (candidate|fixed version)",
    ):
        build(evidence, artifacts)


def test_collector_projection_and_runtime_helpers_are_bounded(
    tmp_path: Path,
) -> None:
    projection = COLLECTOR.image_projection(
        {
            "Id": "a" * 64,
            "Architecture": "arm64",
            "Os": "linux",
            "RootFS": {"Layers": [digest("layer")]},
            "Config": {
                "User": "root",
                "Entrypoint": ["/usr/local/bin/kolla_start"],
                "Cmd": [],
                "Labels": {"safe": "yes"},
            },
        }
    )
    assert projection["id"] == f"sha256:{'a' * 64}"
    assert projection["layers"] == [digest("layer")]
    with pytest.raises(COLLECTOR.CollectionError, match="immutable"):
        COLLECTOR.image_projection(
            {
                "Id": "latest",
                "RootFS": {"Layers": [digest("layer")]},
                "Config": {},
            }
        )

    package_file = tmp_path / "module.py"
    package_file.write_text("safe\n")
    assert RUNTIME.normalized_name("Mako_Name.test") == "mako-name-test"
    assert RUNTIME.file_sha256(package_file) == hashlib.sha256(b"safe\n").hexdigest()
    monkeypatch = pytest.MonkeyPatch()
    distributions = [
        SimpleNamespace(metadata={"Name": "Horizon"}, version="25.7.3"),
        SimpleNamespace(metadata={"Name": "horizon"}, version="0.0.0"),
        SimpleNamespace(metadata={"Name": "Mako"}, version="1.3.12"),
    ]
    monkeypatch.setattr(RUNTIME.metadata, "distributions", lambda: distributions)
    assert RUNTIME.package_versions(BASE_TARGETS["mako"]) == {
        "horizon": ["0.0.0", "25.7.3"],
        "mako": ["1.3.12"],
    }
    monkeypatch.undo()
    linked = tmp_path / "linked.py"
    linked.symlink_to(package_file)
    with pytest.raises(RUNTIME.RuntimeCollectionError, match="invalid"):
        RUNTIME.file_sha256(linked)


def test_target_manifest_containerfile_and_runner_are_bounded() -> None:
    containerfile = (
        ROOT / "poc" / "ui-images" / "python_overlay.Containerfile"
    ).read_text()

    assert "--no-deps" in containerfile
    assert "--no-index" in containerfile
    assert "--force-reinstall" in containerfile
    assert "target-wheels/*.whl" in containerfile
    assert "python_targets.json" in containerfile
    assert "pip check" in containerfile
    assert "TARGET_LABEL" in containerfile
    assert "TARGET_WHEEL_FILENAME" not in containerfile

    targets = TARGET_MODULE.load_targets(TARGET_MANIFEST)
    assert set(targets) == {
        "click",
        "cryptography-pyopenssl",
        "django",
        "mako",
        "httplib2",
        "lxml",
        "pillow",
        "pyjwt",
        "msgpack",
        "urllib3",
        "ujson",
    }
    assert targets["django"].surfaces == ("horizon",)
    assert targets["click"].scanner_finding_ids == {
        "trivy": [],
        "scout": ["CVE-2026-7246"],
    }
    assert targets["click"].requires_dist == (
        'colorama; platform_system == "Windows"',
    )
    assert targets["click"].wheel_sha256 == (
        "a2bf429bb3033c89fa4936ffb35d5cb471e3719e1f3c8a7c3fff0b8314305613"
    )
    crypto_target = targets["cryptography-pyopenssl"]
    assert tuple(
        component.normalized_name for component in crypto_target.components
    ) == ("cryptography", "pyopenssl")
    assert crypto_target.result_name == (
        "cryptography==49.0.0 + pyOpenSSL==26.3.0"
    )
    assert crypto_target.finding_ids == (
        "CVE-2026-26007",
        "CVE-2026-27459",
        "GHSA-537c-gmf6-5ccf",
    )
    assert crypto_target.components[0].wheel_architecture == "arm64"
    assert crypto_target.components[1].wheel_architecture == "any"
    assert targets["msgpack"].wheel_architecture == "arm64"
    assert targets["msgpack"].requires_dist == ()
    assert targets["msgpack"].finding_ids == ("GHSA-6v7p-g79w-8964",)
    assert targets["msgpack"].wheel_sha256 == (
        "60926b75d00c8e816ef98f3034f484a8bc64242d66839cef4cf7e503142316a0"
    )
    assert targets["lxml"].package_prefix == "lxml/"
    assert targets["lxml"].module_name == "lxml"
    assert targets["lxml"].wheel_architecture == "arm64"
    assert targets["lxml"].finding_ids == ("CVE-2026-41066",)
    assert targets["lxml"].wheel_sha256 == (
        "c921ba5c51e4e9f63b8b00267d06566e1f63407408a0496da2d1d0bfc819c7fc"
    )
    assert targets["pillow"].display_name == "Pillow"
    assert targets["pillow"].package_prefix == "PIL/"
    assert targets["pillow"].module_name == "PIL"
    assert targets["pillow"].surfaces == ("horizon",)
    assert targets["pillow"].wheel_architecture == "arm64"
    assert len(targets["pillow"].finding_ids) == 12
    assert targets["pillow"].wheel_sha256 == (
        "d9c7f76c0673154f044e9d78c8655fb4213f6ca31a836df48b40fe5d187717b9"
    )
    assert targets["ujson"].package_prefix == "ujson."
    assert targets["ujson"].module_name == "ujson"
    assert targets["ujson"].wheel_architecture == "arm64"
    assert targets["ujson"].requires_dist == ()
    assert targets["ujson"].finding_ids == (
        "CVE-2026-32874",
        "CVE-2026-32875",
        "CVE-2026-44660",
    )
    assert targets["ujson"].wheel_sha256 == (
        "fdde6341d213b29f413b5fa9fad1392d5408074c75f0900ed949e97e546fa5df"
    )
    assert targets["django"].finding_ids == (
        "CVE-2026-25673",
        "CVE-2026-33034",
        "CVE-2026-3902",
    )
    assert targets["mako"].finding_ids == (
        "CVE-2026-41205",
        "CVE-2026-44307",
    )
    assert targets["httplib2"].wheel_sha256 == (
        "dc6705cacdf3fb0a2aba7629fa33c90fd93e30035db0c157325826be177e4816"
    )
    assert targets["urllib3"].finding_ids == (
        "CVE-2026-44431",
        "CVE-2026-44432",
    )
    assert targets["pyjwt"].module_name == "jwt"
    assert targets["pyjwt"].wheel_sha256 == (
        "66adcc2aff09b3f1bbd95fc1e1577df8ac8723c978552fd43304c8a290ac5728"
    )
    assert targets["pyjwt"].scanner_finding_ids == {
        "trivy": ["CVE-2026-32597", "CVE-2026-48526"],
        "scout": ["CVE-2026-32597", "CVE-2026-48526"],
    }
    assert all(
        target.surfaces == ("horizon", "skyline")
        for key, target in targets.items()
        if key not in {"django", "pillow"}
    )

    runner = (
        ROOT / "poc" / "ui-images" / "trial_python_overlay.sh"
    ).read_text()
    assert 'WORK="${ROOT}/work/ui-python-overlay-trial-${TARGET_KEY}"' in runner
    assert "refusing existing UI Python overlay trial work directory" in runner
    assert "TARGET_WHEEL_SHA256S" in runner
    assert "TARGET_WHEEL_ARCHITECTURES" in runner
    assert "($entry.companions // [])" in runner
    assert "target wheel is incompatible with runtime architecture" in runner
    assert "--network none" in runner
    assert "--no-deps" in containerfile
    assert 'rm -rf -- \\' in runner
    assert "podman image rm --force" in runner
    assert ".decision.production_candidate == false" in runner


@pytest.mark.parametrize(
    "finding_ids_by_scanner",
    [
        {"trivy": ["CVE-2026-41205"]},
        {"trivy": [], "scout": []},
        {
            "trivy": ["CVE-2026-44307", "CVE-2026-41205"],
            "scout": ["CVE-2026-41205"],
        },
        {
            "trivy": ["GHSA-not-accepted"],
            "scout": ["CVE-2026-41205"],
        },
        {
            "trivy": ["GHSA-6V7P-G79W-8964"],
            "scout": ["CVE-2026-41205"],
        },
        {
            "trivy": ["GHSA-6v7p-g79w-896"],
            "scout": ["CVE-2026-41205"],
        },
        {
            "trivy": ["GHSA-6v7p-g79w-abcd"],
            "scout": ["CVE-2026-41205"],
        },
    ],
)
def test_target_manifest_rejects_invalid_scanner_finding_contract(
    tmp_path: Path,
    finding_ids_by_scanner: dict[str, list[str]],
) -> None:
    document = json.loads(TARGET_MANIFEST.read_text())
    document["targets"] = {"mako": document["targets"]["mako"]}
    document["targets"]["mako"][
        "finding_ids_by_scanner"
    ] = finding_ids_by_scanner
    path = tmp_path / "python_targets.json"
    path.write_text(json.dumps(document))

    with pytest.raises(
        TARGET_MODULE.TargetError,
        match="finding_ids_by_scanner",
    ):
        TARGET_MODULE.load_targets(path)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate-name", "duplicate-finding", "unsorted-companions"],
)
def test_target_manifest_rejects_invalid_component_contract(
    tmp_path: Path,
    mutation: str,
) -> None:
    document = json.loads(TARGET_MANIFEST.read_text())
    entry = document["targets"]["cryptography-pyopenssl"]
    if mutation == "duplicate-name":
        entry["companions"][0]["normalized_name"] = "cryptography"
    elif mutation == "duplicate-finding":
        entry["companions"][0]["finding_ids_by_scanner"] = {
            "trivy": ["CVE-2026-26007"],
            "scout": ["CVE-2026-26007"],
        }
    else:
        entry["companions"].append(
            {
                **entry["companions"][0],
                "display_name": "alpha",
                "normalized_name": "alpha",
                "package_prefix": "alpha/",
                "wheel_filename": "alpha-26.3.0-py3-none-any.whl",
                "wheel_sha256": "a" * 64,
            }
        )
    document["targets"] = {"cryptography-pyopenssl": entry}
    path = tmp_path / "python_targets.json"
    path.write_text(json.dumps(document))

    with pytest.raises(TARGET_MODULE.TargetError):
        TARGET_MODULE.load_targets(path)


@pytest.mark.parametrize(
    ("architecture", "filename"),
    [
        ("amd64", "msgpack-1.2.1-cp312-cp312-manylinux_2_28_aarch64.whl"),
        ("arm64", "msgpack-1.2.1-cp312-cp312-manylinux_2_28_x86_64.whl"),
        ("any", "msgpack-1.2.1-cp312-cp312-manylinux_2_28_aarch64.whl"),
        ("arm64", "msgpack-1.2.1-py3-none-any.whl"),
        ("other", "msgpack-1.2.1-py3-none-any.whl"),
        ("arm64", "aarch64pkg-1.2.1-cp312-cp312-any.whl"),
        ("arm64", "msgpack-1.2.1-cp312-cp311-manylinux_2_28_aarch64.whl"),
        (
            "arm64",
            (
                "msgpack-1.2.1-cp312-cp312-"
                "manylinux_2_28_aarch64.manylinux_2_28_x86_64.whl"
            ),
        ),
    ],
)
def test_target_manifest_rejects_incompatible_wheel_architecture(
    tmp_path: Path,
    architecture: str,
    filename: str,
) -> None:
    document = json.loads(TARGET_MANIFEST.read_text())
    document["targets"] = {"msgpack": document["targets"]["msgpack"]}
    document["targets"]["msgpack"]["wheel_architecture"] = architecture
    document["targets"]["msgpack"]["wheel_filename"] = filename
    path = tmp_path / "python_targets.json"
    path.write_text(json.dumps(document))

    with pytest.raises(TARGET_MODULE.TargetError, match="target value"):
        TARGET_MODULE.load_targets(path)
