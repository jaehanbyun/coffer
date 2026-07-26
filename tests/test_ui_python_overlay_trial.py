from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
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


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def wheel(path: Path, surface: str) -> tuple[Path, dict[str, str]]:
    if surface == "horizon":
        files = {member: member.encode() for member in TRIAL.HORIZON_MEMBERS}
    elif surface == "skyline":
        files = {"skyline_console/static/coffer.bundle.123.js": b"bundle"}
    else:
        files = {
            "mako/__init__.py": b"version = 'fixture'\n",
            "mako/template.py": b"class Template: pass\n",
        }
    with ZipFile(path, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    return path, {
        member: hashlib.sha256(content).hexdigest()
        for member, content in files.items()
    }


def write_trivy(path: Path, identifiers: list[str]) -> None:
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
                                    "Mako"
                                    if identifier in TRIAL.TARGET_FINDINGS
                                    else "remaining"
                                ),
                                "InstalledVersion": (
                                    TRIAL.TARGET_FROM_VERSION
                                    if identifier in TRIAL.TARGET_FINDINGS
                                    else "1"
                                ),
                                "FixedVersion": (
                                    TRIAL.TARGET_TO_VERSION
                                    if identifier in TRIAL.TARGET_FINDINGS
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


def write_scout(path: Path, identifiers: list[str]) -> None:
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
                                                    "pkg:pypi/mako@1.3.10"
                                                    if identifier
                                                    in TRIAL.TARGET_FINDINGS
                                                    else "pkg:pypi/remaining@1"
                                                )
                                            ],
                                            "affected_version": "1",
                                            "fixed_version": (
                                                TRIAL.TARGET_TO_VERSION
                                                if identifier
                                                in TRIAL.TARGET_FINDINGS
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
    version: str,
    target_files: dict[str, str],
) -> dict[str, object]:
    return {
        "schema": TRIAL.PYTHON_RUNTIME_SCHEMA,
        "architecture": "arm64",
        "packages": {"base": ["1"], "mako": [version]},
        "target": {
            "name": TRIAL.TARGET_NAME,
            "version": version,
            "files": target_files,
            "rendered": "coffer",
        },
        "pip_check": {
            "clean": True,
            "message": "No broken requirements found.",
        },
        "absent": [f"/tmp/{TRIAL.TARGET_WHEEL_NAME}"],
    }


def fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, Path]]:
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True)
    artifacts: dict[str, Path] = {}
    wheel_files: dict[str, dict[str, str]] = {}
    for surface in (*TRIAL.SURFACES, "target"):
        filename = (
            TRIAL.TARGET_WHEEL_NAME if surface == "target" else f"{surface}.whl"
        )
        artifacts[surface], wheel_files[surface] = wheel(
            tmp_path / filename,
            surface,
        )
    monkeypatch.setattr(
        TRIAL,
        "TARGET_WHEEL_SHA256",
        TRIAL.sha256_file(artifacts["target"]),
    )

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
        "package": TRIAL.TARGET_NAME,
        "classification": "constraint-bound-all-findings-have-fix",
        "eligible_for_compatibility_trial": True,
        "constraint_match": True,
        "installed_version": TRIAL.TARGET_FROM_VERSION,
        "constraint_version": TRIAL.TARGET_FROM_VERSION,
        "fixed_versions": [TRIAL.TARGET_TO_VERSION],
        "finding_ids": sorted(TRIAL.TARGET_FINDINGS),
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
                "name": "Mako",
                "from_version": TRIAL.TARGET_FROM_VERSION,
                "to_version": TRIAL.TARGET_TO_VERSION,
                "filename": TRIAL.TARGET_WHEEL_NAME,
                "sha256": TRIAL.sha256_file(artifacts["target"]),
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
                    "2026.1-mako-1.3.12"
                ),
                "id": digest(f"{surface}-{kind}"),
            }
            for surface in TRIAL.SURFACES
            for kind in TRIAL.KINDS
        },
        "scanners": {"docker_scout": "fixture", "trivy": "fixture"},
    }
    (evidence / "manifest.json").write_text(json.dumps(manifest))

    images = {}
    for surface in TRIAL.SURFACES:
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
                "io.coffer.ui.python-overlay-trial": (
                    "coffer-ui-mako-1.3.12-v1"
                ),
            },
            "layers": before_layers + [digest(f"{surface}-overlay")],
        }
    (evidence / "images.json").write_text(
        json.dumps({"schema": TRIAL.IMAGE_SCHEMA, "images": images})
    )
    inventories = {
        f"{surface}-{kind}": os_inventory()
        for surface in TRIAL.SURFACES
        for kind in TRIAL.KINDS
    }
    (evidence / "os-inventories.json").write_text(
        json.dumps({"schema": TRIAL.INVENTORY_SCHEMA, "images": inventories})
    )
    python = {
        f"{surface}-{kind}": python_runtime(
            version=(
                TRIAL.TARGET_FROM_VERSION
                if kind == "before"
                else TRIAL.TARGET_TO_VERSION
            ),
            target_files=(
                {"mako/old.py": digest("old").removeprefix("sha256:")}
                if kind == "before"
                else wheel_files["target"]
            ),
        )
        for surface in TRIAL.SURFACES
        for kind in TRIAL.KINDS
    }
    ui = {
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
    before_findings = [*sorted(TRIAL.TARGET_FINDINGS), "CVE-remaining"]
    for surface in TRIAL.SURFACES:
        write_trivy(
            evidence / f"{surface}-before.trivy.json",
            before_findings,
        )
        write_trivy(
            evidence / f"{surface}-after.trivy.json",
            ["CVE-remaining"],
        )
        write_scout(
            evidence / f"{surface}-before.scout.sarif.json",
            before_findings,
        )
        write_scout(
            evidence / f"{surface}-after.scout.sarif.json",
            ["CVE-remaining"],
        )
    return evidence, artifacts


def build(evidence: Path, artifacts: dict[str, Path]) -> dict[str, object]:
    return TRIAL.build_report(
        evidence,
        baseline_result_path=artifacts["baseline"],
        baseline_inventories_path=artifacts["baseline_inventories"],
        remediation_result_path=artifacts["remediation"],
        horizon_wheel=artifacts["horizon"],
        skyline_wheel=artifacts["skyline"],
        target_wheel=artifacts["target"],
    )


def test_valid_mako_overlay_is_accepted_but_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, artifacts = fixture(tmp_path, monkeypatch)

    report = build(evidence, artifacts)

    assert report["decision"]["status"] == "blocked"
    assert report["decision"]["production_candidate"] is False
    assert report["decision"]["python_overlay_trial_accepted"] is True
    assert report["decision"]["target"] == "Mako==1.3.12"
    assert report["decision"]["private_constraint_override_accepted"] is False
    for surface in TRIAL.SURFACES:
        for scanner in TRIAL.SCANNERS:
            result = report["surfaces"][surface]["scanners"][scanner]
            assert result["removed_finding_ids"] == sorted(TRIAL.TARGET_FINDINGS)
            assert result["introduced_critical_high"] == 0


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
    assert RUNTIME.package_versions() == {
        "horizon": ["0.0.0", "25.7.3"],
        "mako": ["1.3.12"],
    }
    monkeypatch.undo()
    linked = tmp_path / "linked.py"
    linked.symlink_to(package_file)
    with pytest.raises(RUNTIME.RuntimeCollectionError, match="invalid"):
        RUNTIME.file_sha256(linked)


def test_trial_containerfile_is_narrow_and_runner_target_is_fixed() -> None:
    containerfile = (
        ROOT / "poc" / "ui-images" / "python_overlay.Containerfile"
    ).read_text()

    assert "--no-deps" in containerfile
    assert "--no-index" in containerfile
    assert "--force-reinstall" in containerfile
    assert "mako-1.3.12-py3-none-any.whl" in containerfile
    assert "pip check" in containerfile
    assert "coffer-ui-mako-1.3.12-v1" in containerfile

    runner = (
        ROOT / "poc" / "ui-images" / "trial_python_overlay.sh"
    ).read_text()
    assert 'WORK="${ROOT}/work/ui-python-overlay-trial-mako"' in runner
    assert "refusing existing UI Python overlay trial work directory" in runner
    assert 'TARGET_WHEEL_SHA256="8f615694' in runner
    assert "--network none" in runner
    assert "--no-deps" in containerfile
    assert 'rm -rf -- \\' in runner
    assert "podman image rm --force" in runner
    assert ".decision.production_candidate == false" in runner
