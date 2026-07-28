from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "artifacts.py"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_artifacts",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
artifacts = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = artifacts
SPEC.loader.exec_module(artifacts)

KOLLA_REVISION = "686c6d13dc1c31092b22c6c481e16a7329e935ea"
HORIZON_REVISION = "0a4439556517cf67be0aa949b6551a14e409af75"
SKYLINE_REVISION = "c9000cb1be332a213009793598f17a80ce59671e"


def release(qualified: bool = True) -> dict[str, object]:
    status = "candidate-qualified" if qualified else "blocked"
    reasons = [] if qualified else ["not qualified"]
    components = {
        "distribution": {
            "reasons": list(reasons),
            "revision": "a" * 40,
            "status": status,
            "version": "v3.2.0",
        },
        "ceph": {
            "reasons": list(reasons),
            "revision": "b" * 40,
            "status": status,
            "version": "v20.2.3",
        },
        "oslo_messaging": {
            "reasons": list(reasons),
            "revision": "c" * 40,
            "status": status,
            "version": "17.3.1",
        },
    }
    return {
        "blockers": [] if qualified else ["distribution: not qualified"],
        "components": components,
        "next_action": "fixture",
        "production_candidate": False,
        "release_inputs_qualified": qualified,
        "schema": artifacts.RELEASE_SCHEMA,
        "source": {
            "upstream_classifier_sha256": artifacts._sha256(
                ROOT
                / "poc"
                / "production-images"
                / "check_upstream_readiness.py"
            ),
            "ui_classifier_sha256": artifacts._sha256(
                ROOT
                / "poc"
                / "ui-images"
                / "oslo_messaging_release_gate.py"
            ),
            "ui_contract_sha256": artifacts._sha256(
                ROOT
                / "poc"
                / "ui-images"
                / "oslo_messaging_release_gate.json"
            ),
        },
        "status": status,
        "ui_observed_on": "2026-07-28",
    }


def core_result(architecture: str) -> dict[str, object]:
    counts = {"critical": 0, "high": 0, "medium": 1}
    return {
        "blockers": [],
        "govulncheck": {
            "release_binary_symbols": 0,
            "source_reachable": 0,
        },
        "image_contract": {
            "architectures": [architecture],
            "operating_systems": ["linux"],
            "revisions": [KOLLA_REVISION],
            "users": ["coffer", "registry"],
            "valid": True,
        },
        "production_candidate": True,
        "release_provenance": True,
        "runtime_contract": True,
        "sbom": {
            "coffer": {"format": "SPDX", "packages": 300},
            "registry": {"format": "SPDX", "packages": 330},
        },
        "schema": artifacts.CORE_SCHEMA,
        "scout": {
            "coffer": dict(counts),
            "registry": dict(counts),
        },
        "secrets": {"coffer": 0, "registry": 0},
        "trivy": {
            "coffer": dict(counts),
            "registry": dict(counts),
        },
    }


def core_images(architecture: str) -> list[dict[str, object]]:
    return [
        {
            "architecture": architecture,
            "id": digit * 64,
            "labels": {
                "org.opencontainers.image.revision": KOLLA_REVISION,
            },
            "os": "linux",
            "user": user,
        }
        for digit, user in (("1", "coffer"), ("2", "registry"))
    ]


def ui_image_result() -> dict[str, object]:
    counts = {"critical": 0, "high": 0, "medium": 1}
    return {
        "delta": {
            scanner: {
                "introduced_critical_high": 0,
                "missing_parent_critical_high": 0,
            }
            for scanner in ("scout", "trivy")
        },
        "images": {
            kind: {
                "sbom_packages": 500,
                "scout": dict(counts),
                "secrets": 0,
                "trivy": dict(counts),
            }
            for kind in ("parent", "custom")
        },
    }


def ui_result(architecture: str) -> dict[str, object]:
    return {
        "architecture": architecture,
        "artifacts": {
            "horizon": {
                "name": "coffer-horizon",
                "sha256": "3" * 64,
                "version": "0.1.0",
            },
            "skyline": {
                "name": "skyline-console",
                "sha256": "4" * 64,
                "version": "8.0.0+coffer.1",
            },
        },
        "blockers": [],
        "images": {
            surface: {
                "custom": {
                    "id": f"sha256:{digit * 64}",
                    "name": f"fixture-{surface}-custom",
                },
                "parent": {
                    "id": f"sha256:{(str(int(digit) + 2)) * 64}",
                    "name": f"fixture-{surface}-parent",
                },
            }
            for surface, digit in (("horizon", "5"), ("skyline", "6"))
        },
        "platform": f"linux/{architecture}",
        "production_candidate": True,
        "scanners": {"docker_scout": "1.21.0", "trivy": "0.72.0"},
        "schema": artifacts.UI_SCHEMA,
        "sources": {
            "horizon": HORIZON_REVISION,
            "kolla": KOLLA_REVISION,
            "skyline": SKYLINE_REVISION,
        },
        "status": "qualified",
        "surfaces": {
            "horizon": ui_image_result(),
            "skyline": ui_image_result(),
        },
    }


def compile_inputs() -> dict[str, object]:
    return {
        "core_digests": {
            "amd64": f"sha256:{'7' * 64}",
            "arm64": f"sha256:{'8' * 64}",
        },
        "core_image_digests": {
            "amd64": f"sha256:{'9' * 64}",
            "arm64": f"sha256:{'a' * 64}",
        },
        "core_images": {
            architecture: core_images(architecture)
            for architecture in artifacts.ARCHITECTURES
        },
        "core_results": {
            architecture: core_result(architecture)
            for architecture in artifacts.ARCHITECTURES
        },
        "release_digest": f"sha256:{'b' * 64}",
        "release_readiness": release(),
        "ui_digests": {
            "amd64": f"sha256:{'c' * 64}",
            "arm64": f"sha256:{'d' * 64}",
        },
        "ui_results": {
            architecture: ui_result(architecture)
            for architecture in artifacts.ARCHITECTURES
        },
    }


def test_compiles_two_native_architectures_only_from_qualified_inputs() -> None:
    result = artifacts.compile_result(**compile_inputs())

    assert result["schema"] == artifacts.SCHEMA
    assert result["production_candidate"] is True
    assert [
        item["architecture"] for item in result["architectures"]
    ] == ["amd64", "arm64"]
    assert artifacts.validate_final_result(result) == result


def test_blocked_release_refuses_before_artifact_validation() -> None:
    value = compile_inputs()
    value["release_readiness"] = release(False)
    value["core_results"] = {}

    with pytest.raises(
        artifacts.ArtifactInputsBlocked,
        match="not candidate-qualified",
    ):
        artifacts.compile_result(**value)


def test_critical_high_or_missing_architecture_fails_closed() -> None:
    finding = compile_inputs()
    finding["core_results"]["arm64"]["trivy"]["registry"]["high"] = 1
    with pytest.raises(artifacts.ArtifactResultError, match="Critical/High"):
        artifacts.compile_result(**finding)

    missing = compile_inputs()
    missing["ui_results"].pop("amd64")
    with pytest.raises(artifacts.ArtifactResultError, match="incomplete"):
        artifacts.compile_result(**missing)


def test_cross_architecture_source_or_artifact_drift_fails() -> None:
    source_drift = compile_inputs()
    source_drift["ui_results"]["arm64"]["sources"]["horizon"] = "f" * 40
    with pytest.raises(artifacts.ArtifactResultError, match="cross-architecture"):
        artifacts.compile_result(**source_drift)

    artifact_drift = compile_inputs()
    artifact_drift["ui_results"]["arm64"]["artifacts"]["horizon"]["sha256"] = (
        "e" * 64
    )
    with pytest.raises(artifacts.ArtifactResultError, match="cross-architecture"):
        artifacts.compile_result(**artifact_drift)


def test_final_result_rejects_manual_source_or_residue_change() -> None:
    result = artifacts.compile_result(**compile_inputs())
    changed_source = deepcopy(result)
    changed_source["source"]["core_verifier_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(artifacts.ArtifactResultError, match="qualified"):
        artifacts.validate_final_result(changed_source)

    changed_architecture = deepcopy(result)
    changed_architecture["architectures"][0]["architecture"] = "ppc64le"
    with pytest.raises(artifacts.ArtifactResultError, match="qualified"):
        artifacts.validate_final_result(changed_architecture)


def test_current_blocked_release_cli_does_not_read_missing_artifacts(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    release_path = private / "release.json"
    release_path.write_text(json.dumps(release(False)), encoding="utf-8")
    release_path.chmod(0o600)
    output = private / "result.json"

    exit_code = artifacts.main(
        [
            "--release-readiness",
            str(release_path),
            "--amd64-core-directory",
            str(private / "missing-amd64"),
            "--amd64-ui-result",
            str(private / "missing-amd64-ui.json"),
            "--arm64-core-directory",
            str(private / "missing-arm64"),
            "--arm64-ui-result",
            str(private / "missing-arm64-ui.json"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 3
    assert not output.exists()


def test_private_writer_refuses_existing_output(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = private / "result.json"
    result = artifacts.compile_result(**compile_inputs())

    artifacts._write_private(output.resolve(), result)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(artifacts.ArtifactResultError, match="already exists"):
        artifacts._write_private(output.resolve(), result)
