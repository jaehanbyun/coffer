from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
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
    "coffer_ui_os_cleanup_trial",
    ROOT / "poc" / "ui-images" / "cleanup_trial.py",
)
COLLECTOR = load(
    "coffer_ui_os_cleanup_collector",
    ROOT / "poc" / "ui-images" / "collect_cleanup_trial.py",
)


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def wheel(path: Path, surface: str) -> tuple[Path, dict[str, str]]:
    if surface == "horizon":
        files = {member: member.encode() for member in TRIAL.HORIZON_MEMBERS}
    else:
        files = {"skyline_console/static/coffer.bundle.123.js": b"bundle"}
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
                        "Class": "os-pkgs",
                        "Type": "ubuntu",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": identifier,
                                "PkgName": identifier.removeprefix("CVE-"),
                                "InstalledVersion": "1",
                                "FixedVersion": "",
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
                                                f"pkg:deb/ubuntu/"
                                                f"{identifier.removeprefix('CVE-')}@1"
                                            ],
                                            "affected_version": "1",
                                            "fixed_version": "not fixed",
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


def inventory(packages: dict[str, str]) -> dict[str, object]:
    return {
        "schema": TRIAL.PACKAGE_INVENTORY_SCHEMA,
        "architecture": "arm64",
        "os": {"id": "ubuntu", "version_id": "24.04"},
        "packages": [
            {
                "name": name,
                "version": version,
                "status": "ii ",
                "manual": False,
                "automatic": True,
            }
            for name, version in sorted(packages.items())
        ],
        "package_database": {
            "dpkg_audit_clean": True,
            "apt_dependency_check_clean": True,
        },
    }


def fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, Path]]:
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True)
    wheels: dict[str, Path] = {}
    wheel_files: dict[str, dict[str, str]] = {}
    for surface in TRIAL.SURFACES:
        wheels[surface], wheel_files[surface] = wheel(
            tmp_path / f"{surface}.whl",
            surface,
        )
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
                "sha256": TRIAL.sha256_file(wheels["horizon"]),
            },
            "skyline": {
                "name": "skyline-console",
                "version": "8.0.0+coffer.1",
                "sha256": TRIAL.sha256_file(wheels["skyline"]),
            },
        },
        "images": {
            f"{surface}-{kind}": {
                "name": (
                    f"localhost/coffer-ui-trial-{surface}-{kind}:"
                    "2026.1-os-cleanup"
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
        before_layers = [digest(f"{surface}-parent"), digest(f"{surface}-coffer")]
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
                "io.coffer.ui.os-cleanup-trial": "coffer-ui-os-cleanup-v1",
            },
            "layers": before_layers + [digest(f"{surface}-cleanup")],
        }
    (evidence / "images.json").write_text(
        json.dumps({"schema": TRIAL.IMAGE_SCHEMA, "images": images})
    )
    before_packages = {
        "base-runtime": "1",
        "libc6-dev": "2.39",
        "linux-libc-dev": "6.8",
    }
    after_packages = {"base-runtime": "1"}
    inventories = {
        f"{surface}-{kind}": inventory(
            before_packages if kind == "before" else after_packages
        )
        for surface in TRIAL.SURFACES
        for kind in TRIAL.KINDS
    }
    (evidence / "inventories.json").write_text(
        json.dumps({"schema": TRIAL.INVENTORY_SCHEMA, "images": inventories})
    )
    (evidence / "runtime.json").write_text(
        json.dumps(
            {
                "schema": TRIAL.RUNTIME_SCHEMA,
                "architecture": "arm64",
                "surfaces": {
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
                },
            }
        )
    )
    for surface in TRIAL.SURFACES:
        write_trivy(
            evidence / f"{surface}-before.trivy.json",
            ["CVE-linux", "CVE-python"],
        )
        write_trivy(
            evidence / f"{surface}-after.trivy.json",
            ["CVE-python"],
        )
        write_scout(
            evidence / f"{surface}-before.scout.sarif.json",
            ["CVE-linux", "CVE-python"],
        )
        write_scout(
            evidence / f"{surface}-after.scout.sarif.json",
            ["CVE-python"],
        )
    probe = tmp_path / "probe-summary.json"
    probe.write_text(
        json.dumps(
            {
                "schema": TRIAL.PROBE_SUMMARY_SCHEMA,
                "decision": {"safe_to_apply": False},
                "purge_simulation": {
                    "removed": [
                        {"name": "libc6-dev", "installed_version": "2.39"},
                        {
                            "name": "linux-libc-dev",
                            "installed_version": "6.8",
                        },
                    ]
                },
            }
        )
    )
    return evidence, probe, wheels


def build(
    evidence: Path,
    probe: Path,
    wheels: dict[str, Path],
) -> dict[str, object]:
    return TRIAL.build_report(
        evidence,
        probe_summary_path=probe,
        horizon_wheel=wheels["horizon"],
        skyline_wheel=wheels["skyline"],
    )


def test_valid_cleanup_trial_is_accepted_but_remains_blocked(
    tmp_path: Path,
) -> None:
    evidence, probe, wheels = fixture(tmp_path)

    report = build(evidence, probe, wheels)

    assert report["decision"] == {
        "status": "blocked",
        "production_candidate": False,
        "os_cleanup_trial_accepted": True,
        "production_containerfile_changed": False,
        "private_constraint_override_accepted": False,
        "waivers_applied": False,
        "blockers": [
            "trivy horizon cleanup remains at 0 Critical/1 High",
            "scout horizon cleanup remains at 0 Critical/1 High",
            "trivy skyline cleanup remains at 0 Critical/1 High",
            "scout skyline cleanup remains at 0 Critical/1 High",
        ],
        "next_action": (
            "evaluate the smallest constraint-bound Python compatibility set "
            "while preserving the absolute scanner gate"
        ),
    }
    assert report["surfaces"]["horizon"]["scanners"]["trivy"][
        "removed_critical_high"
    ] == 1


def test_package_delta_and_image_lineage_tamper_are_rejected(
    tmp_path: Path,
) -> None:
    evidence, probe, wheels = fixture(tmp_path)
    inventories_path = evidence / "inventories.json"
    inventories = json.loads(inventories_path.read_text())
    inventories["images"]["horizon-after"]["packages"].append(
        {
            "name": "unexpected",
            "version": "1",
            "status": "ii ",
            "manual": True,
            "automatic": False,
        }
    )
    inventories_path.write_text(json.dumps(inventories))
    with pytest.raises(TRIAL.EvidenceError, match="package delta"):
        build(evidence, probe, wheels)

    evidence, probe, wheels = fixture(tmp_path / "second")
    images_path = evidence / "images.json"
    images = json.loads(images_path.read_text())
    images["images"]["skyline-after"]["layers"] = [digest("unrelated")]
    images_path.write_text(json.dumps(images))
    with pytest.raises(TRIAL.EvidenceError, match="inherit exact"):
        build(evidence, probe, wheels)


def test_scanner_introduction_or_no_reduction_is_rejected(
    tmp_path: Path,
) -> None:
    evidence, probe, wheels = fixture(tmp_path)
    write_scout(
        evidence / "horizon-after.scout.sarif.json",
        ["CVE-python", "CVE-new"],
    )
    with pytest.raises(TRIAL.EvidenceError, match="introduced"):
        build(evidence, probe, wheels)

    evidence, probe, wheels = fixture(tmp_path / "second")
    write_trivy(
        evidence / "skyline-after.trivy.json",
        ["CVE-linux", "CVE-python"],
    )
    with pytest.raises(TRIAL.EvidenceError, match="removed no"):
        build(evidence, probe, wheels)


def test_collector_projection_and_atomic_output(tmp_path: Path) -> None:
    projection = COLLECTOR.image_projection(
        {
            "Id": "a" * 64,
            "Architecture": "arm64",
            "Os": "linux",
            "Config": {
                "User": "root",
                "Entrypoint": ["kolla_start"],
                "Cmd": [],
                "Labels": {"fixture": "true"},
            },
            "RootFS": {"Layers": [digest("layer")]},
        }
    )
    assert projection["id"] == "sha256:" + "a" * 64
    assert projection["layers"] == [digest("layer")]

    output = tmp_path / "result.json"
    COLLECTOR.atomic_json(output, {"schema": "fixture"})
    assert output.stat().st_mode & 0o777 == 0o640
    with pytest.raises(COLLECTOR.CollectionError, match="refusing existing"):
        COLLECTOR.atomic_json(output, {"schema": "fixture"})


def test_runner_is_disposable_and_production_containerfiles_are_unchanged() -> None:
    runner = (
        ROOT / "poc" / "ui-images" / "trial_os_cleanup.sh"
    ).read_text()
    cleanup = (
        ROOT / "poc" / "ui-images" / "os_cleanup.Containerfile"
    ).read_text()
    production = (
        (ROOT / "ui" / "images" / "horizon.Containerfile").read_text()
        + (ROOT / "ui" / "images" / "skyline-console.Containerfile").read_text()
    )

    assert 'WORK="${ROOT}/work/ui-os-cleanup-trial"' in runner
    assert "Docker Scout" not in runner or "docker scout cves" in runner
    assert "--network none" in runner
    assert '"${CONTEXTS:?}"' in runner
    assert "podman image rm --force" in runner
    assert "production_containerfile_changed == false" in runner
    assert "apt-get -y purge linux-libc-dev" in cleanup
    assert "linux-libc-dev" not in production
