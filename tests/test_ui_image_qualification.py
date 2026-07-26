from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "poc" / "ui-images" / "qualification.py"
)
SPEC = importlib.util.spec_from_file_location(
    "coffer_ui_image_qualification", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
QUALIFICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFICATION)


def digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def wheel(path: Path, surface: str) -> tuple[Path, dict[str, str]]:
    if surface == "horizon":
        name = "coffer-horizon"
        version = "0.1.0"
        files = {
            "cofferdashboard/enabled/_1910_project_registry_panel_group.py": b"group",
            "cofferdashboard/enabled/"
            "_1920_project_registry_repositories_panel.py": b"panel",
            "cofferdashboard/local_settings.d/_1930_coffer_policy.py": b"settings",
            "cofferdashboard/conf/coffer_policy.yaml": b"policy",
        }
    else:
        name = "skyline-console"
        version = "8.0.0+coffer.1"
        files = {"skyline_console/static/coffer.bundle.123.js": b"bundle"}
    with ZipFile(path, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
        archive.writestr(
            f"{name.replace('-', '_')}-{version}.dist-info/METADATA",
            f"Name: {name}\nVersion: {version}\n",
        )
    return path, {
        member: hashlib.sha256(content).hexdigest() for member, content in files.items()
    }


def finding(identifier: str, severity: str = "HIGH") -> dict[str, str]:
    return {
        "VulnerabilityID": identifier,
        "PkgName": "example",
        "InstalledVersion": "1",
        "FixedVersion": "2",
        "Severity": severity,
    }


def write_trivy(
    path: Path,
    findings: list[dict[str, str]] | None = None,
    *,
    secrets: int = 0,
) -> None:
    path.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "CreatedAt": "fixture",
                "Results": [
                    {
                        "Target": "fixture",
                        "Vulnerabilities": findings or [],
                        "Secrets": [{"RuleID": "fixture"}] * secrets,
                    }
                ],
            }
        )
    )


def write_scout(
    path: Path,
    identifiers: list[tuple[str, str]] | None = None,
) -> None:
    rules = []
    for identifier, severity in identifiers or []:
        rules.append(
            {
                "id": identifier,
                "properties": {
                    "cvssV3_severity": severity,
                    "purls": ["pkg:pypi/example@1"],
                    "affected_version": "1",
                    "fixed_version": "2",
                },
            }
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
                                "rules": rules,
                            }
                        }
                    }
                ],
            }
        )
    )


def evidence(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "evidence"
    root.mkdir(parents=True)
    wheels: dict[str, Path] = {}
    wheel_files: dict[str, dict[str, str]] = {}
    for surface in ("horizon", "skyline"):
        wheels[surface], wheel_files[surface] = wheel(
            tmp_path / f"{surface}.whl", surface
        )
    manifest = {
        "schema": QUALIFICATION.MANIFEST_SCHEMA,
        "architecture": "arm64",
        "platform": "linux/arm64",
        "sources": {
            "kolla": QUALIFICATION.KOLLA_REVISION,
            "horizon": QUALIFICATION.HORIZON_REVISION,
            "skyline": QUALIFICATION.SKYLINE_REVISION,
        },
        "artifacts": {
            "horizon": {
                "name": "coffer-horizon",
                "version": "0.1.0",
                "sha256": QUALIFICATION.sha256_file(wheels["horizon"]),
            },
            "skyline": {
                "name": "skyline-console",
                "version": "8.0.0+coffer.1",
                "sha256": QUALIFICATION.sha256_file(wheels["skyline"]),
            },
        },
        "images": {
            surface: {
                kind: {
                    "name": f"localhost/coffer-ui-{surface}-{kind}:fixture",
                    "id": digest(f"{surface}-{kind}"),
                }
                for kind in ("parent", "custom")
            }
            for surface in ("horizon", "skyline")
        },
        "scanners": {"docker_scout": "fixture", "trivy": "fixture"},
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    images = {}
    for surface in ("horizon", "skyline"):
        parent_layers = [digest(f"{surface}-base")]
        common = {
            "architecture": "arm64",
            "os": "linux",
            "user": "root",
            "entrypoint": ["/usr/local/bin/kolla_start"],
            "cmd": [],
        }
        images[f"{surface}-parent"] = {
            **common,
            "id": manifest["images"][surface]["parent"]["id"],
            "labels": {"name": surface},
            "layers": parent_layers,
        }
        images[f"{surface}-custom"] = {
            **common,
            "id": manifest["images"][surface]["custom"]["id"],
            "labels": {
                "io.coffer.ui.contract": "coffer-ui-image-v1",
                "io.coffer.ui.surface": surface,
                "org.opencontainers.image.revision": (
                    QUALIFICATION.SURFACES[surface]["revision"]
                ),
            },
            "layers": parent_layers + [digest(f"{surface}-coffer")],
        }
    (root / "images.json").write_text(
        json.dumps({"schema": "coffer.ui-image-inspection/v1", "images": images})
    )
    (root / "runtime.json").write_text(
        json.dumps(
            {
                "schema": QUALIFICATION.RUNTIME_SCHEMA,
                "architecture": "arm64",
                "surfaces": {
                    surface: {
                        "package": {
                            "name": QUALIFICATION.SURFACES[surface]["artifact_name"],
                            "version": QUALIFICATION.SURFACES[surface][
                                "artifact_version"
                            ],
                        },
                        "files": wheel_files[surface],
                        "absent": list(QUALIFICATION.SURFACES[surface]["absent"]),
                    }
                    for surface in ("horizon", "skyline")
                },
            }
        )
    )
    for key in QUALIFICATION.IMAGE_KEYS:
        (root / f"{key}.spdx.json").write_text(
            json.dumps({"spdxVersion": "SPDX-2.3", "packages": [{"name": key}]})
        )
        write_trivy(root / f"{key}.trivy.json")
        write_scout(root / f"{key}.scout.sarif.json")
    return root, wheels


def qualify(root: Path, wheels: dict[str, Path]) -> dict[str, object]:
    return QUALIFICATION.qualify(
        root,
        horizon_wheel=wheels["horizon"],
        skyline_wheel=wheels["skyline"],
    )


def test_clean_complete_evidence_qualifies(tmp_path: Path) -> None:
    root, wheels = evidence(tmp_path)

    result = qualify(root, wheels)

    assert result["status"] == "qualified"
    assert result["production_candidate"] is True
    assert result["blockers"] == []


@pytest.mark.parametrize("scanner", ["trivy", "scout"])
def test_inherited_parent_finding_remains_a_blocker(
    tmp_path: Path,
    scanner: str,
) -> None:
    root, wheels = evidence(tmp_path)
    for kind in ("parent", "custom"):
        if scanner == "trivy":
            write_trivy(
                root / f"horizon-{kind}.trivy.json",
                [finding("CVE-parent", "CRITICAL")],
            )
        else:
            write_scout(
                root / f"horizon-{kind}.scout.sarif.json",
                [("CVE-parent", "CRITICAL")],
            )

    result = qualify(root, wheels)

    assert result["status"] == "blocked"
    assert any(
        "horizon-parent has 1 Critical/0 High" in item for item in result["blockers"]
    )
    assert result["surfaces"]["horizon"]["delta"][scanner] == {
        "introduced_critical_high": 0,
        "missing_parent_critical_high": 0,
    }


@pytest.mark.parametrize("scanner", ["trivy", "scout"])
def test_introduced_or_missing_parent_finding_is_blocked(
    tmp_path: Path,
    scanner: str,
) -> None:
    root, wheels = evidence(tmp_path)
    if scanner == "trivy":
        write_trivy(
            root / "skyline-parent.trivy.json",
            [finding("CVE-parent")],
        )
        write_trivy(
            root / "skyline-custom.trivy.json",
            [finding("CVE-custom")],
        )
    else:
        write_scout(
            root / "skyline-parent.scout.sarif.json",
            [("CVE-parent", "HIGH")],
        )
        write_scout(
            root / "skyline-custom.scout.sarif.json",
            [("CVE-custom", "HIGH")],
        )

    result = qualify(root, wheels)

    delta = result["surfaces"]["skyline"]["delta"][scanner]
    assert delta["introduced_critical_high"] == 1
    assert delta["missing_parent_critical_high"] == 1
    assert any("introduced 1 Critical/High" in item for item in result["blockers"])
    assert any("lost 1 parent Critical/High" in item for item in result["blockers"])


def test_secret_and_runtime_tamper_are_rejected(tmp_path: Path) -> None:
    root, wheels = evidence(tmp_path)
    write_trivy(root / "horizon-custom.trivy.json", secrets=1)
    blocked = qualify(root, wheels)
    assert any("contains 1 Trivy secrets" in item for item in blocked["blockers"])

    runtime = json.loads((root / "runtime.json").read_text())
    runtime["surfaces"]["horizon"]["files"].pop(
        "cofferdashboard/conf/coffer_policy.yaml"
    )
    (root / "runtime.json").write_text(json.dumps(runtime))
    with pytest.raises(QUALIFICATION.EvidenceError, match="do not match the wheel"):
        qualify(root, wheels)


def test_wrong_source_or_actual_wheel_hash_is_rejected(tmp_path: Path) -> None:
    root, wheels = evidence(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["sources"]["kolla"] = "0" * 40
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(QUALIFICATION.EvidenceError, match="source revisions"):
        qualify(root, wheels)

    root, wheels = evidence(tmp_path / "second")
    wheels["horizon"].write_bytes(b"changed")
    with pytest.raises(QUALIFICATION.EvidenceError, match="actual wheel"):
        qualify(root, wheels)


def test_image_parent_and_atomic_result_contracts(tmp_path: Path) -> None:
    root, wheels = evidence(tmp_path)
    images = json.loads((root / "images.json").read_text())
    images["images"]["skyline-custom"]["layers"] = [digest("not-parent")]
    (root / "images.json").write_text(json.dumps(images))
    with pytest.raises(QUALIFICATION.EvidenceError, match="inherit exact parent"):
        qualify(root, wheels)

    root, wheels = evidence(tmp_path / "second")
    result = qualify(root, wheels)
    output = root / "qualification.json"
    QUALIFICATION.write_result(output, result)
    first_inode = output.stat().st_ino
    QUALIFICATION.write_result(output, result)
    assert output.stat().st_ino == first_inode
    assert output.stat().st_mode & 0o777 == 0o640
    changed = dict(result)
    changed["status"] = "blocked"
    with pytest.raises(QUALIFICATION.EvidenceError, match="refusing to replace"):
        QUALIFICATION.write_result(output, changed)
