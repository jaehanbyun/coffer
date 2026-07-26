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
    target_findings = target.finding_ids_for("trivy")
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
                                    target.display_name
                                    if identifier in target_findings
                                    else "remaining"
                                ),
                                "InstalledVersion": (
                                    target.from_version
                                    if identifier in target_findings
                                    else "1"
                                ),
                                "FixedVersion": (
                                    target.to_version
                                    if identifier in target_findings
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
    target_findings = target.finding_ids_for("scout")
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
                                                    f"pkg:pypi/{target.normalized_name}"
                                                    f"@{target.from_version}"
                                                    if identifier
                                                    in target_findings
                                                    else "pkg:pypi/remaining@1"
                                                )
                                            ],
                                            "affected_version": "1",
                                            "fixed_version": (
                                                target.to_version
                                                if identifier
                                                in target_findings
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
    version: str,
    target_files: dict[str, str],
) -> dict[str, object]:
    return {
        "schema": TRIAL.PYTHON_RUNTIME_SCHEMA,
        "architecture": "arm64",
        "packages": {"base": ["1"], target.normalized_name: [version]},
        "target": {
            "name": target.normalized_name,
            "version": version,
            "files": target_files,
            "probe": target.probe,
            "probe_result": target.expected_probe_result,
        },
        "pip_check": {
            "clean": True,
            "message": "No broken requirements found.",
        },
        "absent": [
            f"/tmp/{target.wheel_filename}",
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
    for surface in (*TRIAL.SURFACES, "target"):
        filename = (
            base_target.wheel_filename if surface == "target" else f"{surface}.whl"
        )
        artifacts[surface], wheel_files[surface] = wheel(
            tmp_path / filename,
            surface,
            base_target,
        )
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
    target_document["targets"][target_key]["wheel_sha256"] = TRIAL.sha256_file(
        artifacts["target"]
    )
    target_manifest = tmp_path / "python_targets.json"
    target_manifest.write_text(json.dumps(target_document, sort_keys=True))
    target = TARGET_MODULE.load_target(target_manifest, target_key)
    artifacts["target_manifest"] = target_manifest
    artifacts["target_spec"] = target

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
    candidate = {
        "package": target.normalized_name,
        "classification": "constraint-bound-all-findings-have-fix",
        "eligible_for_compatibility_trial": True,
        "constraint_match": True,
        "installed_version": target.from_version,
        "constraint_version": target.from_version,
        "fixed_versions": [target.to_version],
        "finding_ids": list(target.finding_ids),
    }
    remediation.write_text(
        json.dumps(
            {
                "schema": TRIAL.REMEDIATION_SCHEMA,
                "surfaces": {
                    surface: {"packages": [candidate]}
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
                "name": target.display_name,
                "normalized_name": target.normalized_name,
                "from_version": target.from_version,
                "to_version": target.to_version,
                "filename": target.wheel_filename,
                "sha256": target.wheel_sha256,
                "manifest_sha256": TRIAL.sha256_file(target_manifest),
                "probe": target.probe,
                "trial_label": target.trial_label,
                "finding_ids": list(target.finding_ids),
                "finding_ids_by_scanner": target.scanner_finding_ids,
                "requires_dist": list(target.requires_dist),
                "surfaces": list(target.surfaces),
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
            version=(
                target.from_version
                if kind == "before"
                else target.to_version
            ),
            target_files=(
                {
                    f"{target.package_prefix}old.py": digest("old").removeprefix(
                        "sha256:"
                    )
                }
                if kind == "before"
                else wheel_files["target"]
            ),
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


def build(evidence: Path, artifacts: dict[str, Any]) -> dict[str, object]:
    return TRIAL.build_report(
        evidence,
        target=artifacts["target_spec"],
        target_manifest_path=artifacts["target_manifest"],
        baseline_result_path=artifacts["baseline"],
        baseline_inventories_path=artifacts["baseline_inventories"],
        remediation_result_path=artifacts["remediation"],
        horizon_wheel=artifacts["horizon"],
        skyline_wheel=artifacts["skyline"],
        target_wheel=artifacts["target"],
    )


@pytest.mark.parametrize(
    "target_key",
    ["django", "mako", "httplib2", "pyjwt", "urllib3"],
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
    runtimes["python"]["skyline-after"]["target"]["files"] = {}
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
    assert "target.whl" in containerfile
    assert "python_targets.json" in containerfile
    assert "pip check" in containerfile
    assert "TARGET_LABEL" in containerfile
    assert "TARGET_WHEEL_FILENAME" in containerfile

    targets = TARGET_MODULE.load_targets(TARGET_MANIFEST)
    assert set(targets) == {
        "django",
        "mako",
        "httplib2",
        "pyjwt",
        "urllib3",
    }
    assert targets["django"].surfaces == ("horizon",)
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
        if key != "django"
    )

    runner = (
        ROOT / "poc" / "ui-images" / "trial_python_overlay.sh"
    ).read_text()
    assert 'WORK="${ROOT}/work/ui-python-overlay-trial-${TARGET_KEY}"' in runner
    assert "refusing existing UI Python overlay trial work directory" in runner
    assert ".targets[$target].wheel_sha256" in runner
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
