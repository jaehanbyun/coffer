from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "ui-images"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("python_target", HARNESS / "python_target.py")
load("collect_python_trial", HARNESS / "collect_python_trial.py")
PROBE = load(
    "coffer_ui_setuptools_backport_probe",
    HARNESS / "probe_setuptools_backport.py",
)
COLLECTOR = load(
    "coffer_ui_setuptools_backport_collector",
    HARNESS / "collect_setuptools_backport.py",
)
load("residual_finding", HARNESS / "residual_finding.py")
OPENVEX = load(
    "generate_setuptools_openvex",
    HARNESS / "generate_setuptools_openvex.py",
)
load("qualification", HARNESS / "qualification.py")
RESIDUAL_TRIAL = load(
    "coffer_ui_residual_trial",
    HARNESS / "residual_trial.py",
)


def fake_package_index() -> ModuleType:
    module = ModuleType("setuptools.package_index")
    module.__file__ = "/usr/lib/python3/dist-packages/setuptools/package_index.py"
    module.subprocess = SimpleNamespace(check_call=lambda argv: 0)
    module.os = SimpleNamespace(system=lambda command: 0)

    class PackageIndex:
        @staticmethod
        def _download_vcs(url: str, destination: str):
            clean_url = url.removeprefix("git+").split("@", 1)[0]
            revision = url.split("@", 1)[1].split("#", 1)[0]
            module.subprocess.check_call(
                ["git", "clone", "--quiet", clean_url, destination]
            )
            module.subprocess.check_call(
                [
                    "git",
                    "-C",
                    destination,
                    "checkout",
                    "--quiet",
                    revision,
                ]
            )
            return destination

        @staticmethod
        def _resolve_download_filename(url: str, root: Path) -> str:
            if "%2fhome%2f" in url:
                raise ValueError("Invalid filename /home/user/.ssh/authorized_keys")
            return str(root / url.rsplit("/", 1)[1])

    module.PackageIndex = PackageIndex
    return module


def test_vcs_source_requires_two_no_shell_check_calls() -> None:
    safe = """
def _download_vcs():
    subprocess.check_call(["git", "clone"])
    subprocess.check_call(commands["git"])
"""
    assert PROBE.verify_vcs_source(safe) == {
        "check_call_sites": 2,
        "os_system_sites": 0,
        "shell_true_sites": 0,
    }
    with pytest.raises(PROBE.ProbeError, match="safe backport"):
        PROBE.verify_vcs_source(
            """
def _download_vcs():
    os.system("git clone")
"""
        )
    with pytest.raises(PROBE.ProbeError, match="enables a shell"):
        PROBE.verify_vcs_source(
            """
def _download_vcs():
    subprocess.check_call(["git", "clone"], shell=True)
    subprocess.check_call(["git", "checkout"])
"""
        )


def test_vcs_runtime_preserves_metacharacters_as_argv() -> None:
    result = PROBE.verify_vcs_runtime(fake_package_index())

    assert result["argv_is_list"] is True
    assert result["subprocess_count"] == 2
    assert result["calls"][0][3] == "<url-with-metacharacters>"
    assert result["calls"][1][-1] == "<revision-with-metacharacters>"


def test_path_containment_rejects_encoded_absolute_path() -> None:
    assert PROBE.verify_path_containment(fake_package_index()) == {
        "benign_relative_path": "setuptools-78.1.0.tar.gz",
        "encoded_absolute_path_rejected": True,
    }


def test_dpkg_revision_is_exact() -> None:
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout="68.1.2-2ubuntu1.2\n",
            stderr="",
        )

    assert PROBE.dpkg_version(run) == "68.1.2-2ubuntu1.2"

    def wrong(*args, **kwargs):
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout="68.1.2-2ubuntu1.1\n",
            stderr="",
        )

    with pytest.raises(PROBE.ProbeError, match="revision"):
        PROBE.dpkg_version(wrong)


def runtime_document() -> dict[str, object]:
    return {
        "architecture": "arm64",
        "decision": {
            "backported_behaviors_verified": True,
            "findings": {
                "CVE-2024-6345": "not_affected",
                "CVE-2025-47273": "not_affected",
            },
            "vex_generation_allowed": True,
        },
        "package": {
            "dpkg_name": "python3-setuptools",
            "dpkg_version": "68.1.2-2ubuntu1.2",
            "metadata_name": "setuptools",
            "metadata_version": "68.1.2",
            "module_path": (
                "/usr/lib/python3/dist-packages/setuptools/package_index.py"
            ),
            "python": "/usr/bin/python3",
        },
        "path_containment": {
            "benign_relative_path": "setuptools-78.1.0.tar.gz",
            "encoded_absolute_path_rejected": True,
        },
        "schema": "coffer.ui-setuptools-backport-runtime/v1",
        "vcs": {
            "runtime": {
                "argv_is_list": True,
                "calls": [
                    [
                        "git",
                        "clone",
                        "--quiet",
                        "<url-with-metacharacters>",
                        "<destination>",
                    ],
                    [
                        "git",
                        "-C",
                        "<destination>",
                        "checkout",
                        "--quiet",
                        "<revision-with-metacharacters>",
                    ],
                ],
                "subprocess_count": 2,
            },
            "source": {
                "check_call_sites": 2,
                "os_system_sites": 0,
                "shell_true_sites": 0,
            },
        },
    }


def test_runtime_validator_is_fail_closed() -> None:
    document = runtime_document()
    COLLECTOR.validate_runtime(document, "arm64")
    document["decision"]["vex_generation_allowed"] = False
    with pytest.raises(
        COLLECTOR.CollectionError,
        match="runtime decision",
    ):
        COLLECTOR.validate_runtime(document, "arm64")


def test_collector_binds_exact_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    images = {
        surface: (
            f"localhost/coffer-ui-python-trial-{surface}-after:2026.1-python-overlay"
        )
        for surface in ("horizon", "skyline")
    }

    def inspection(name: str):
        digit = "1" if "horizon" in name else "2"
        return {
            "architecture": "arm64",
            "id": f"sha256:{digit * 64}",
        }

    monkeypatch.setattr(COLLECTOR, "inspect_image", inspection)
    monkeypatch.setattr(
        COLLECTOR,
        "container_json",
        lambda **kwargs: runtime_document(),
    )
    output = tmp_path / "evidence" / "setuptools-runtimes.json"

    result = COLLECTOR.collect(output=output, images=images)

    assert result["schema"] == "coffer.ui-setuptools-backport-evidence/v1"
    assert result["architecture"] == "arm64"
    assert result["images"]["horizon"]["id"] == f"sha256:{'1' * 64}"
    assert output.stat().st_mode & 0o777 == 0o640
    assert json.loads(output.read_text()) == result


def test_matrix_runner_collects_system_python_proof() -> None:
    runner = (HARNESS / "trial_python_overlay.sh").read_text()
    makefile = (HARNESS / "Makefile").read_text()

    assert "--matrix-residual" in runner
    assert "collect_setuptools_backport.py" in runner
    assert "setuptools-runtimes.json" in runner
    assert "generate_setuptools_openvex.py" in runner
    assert "residual_trial.py" in runner
    assert "--vex-location" in runner
    assert "--ignore-suppressed" in runner
    assert "./trial_python_overlay.sh --matrix-residual accepted" in makefile


def test_openvex_document_is_exact_and_deterministic() -> None:
    document = OPENVEX.vex_document(
        surface="horizon",
        product=f"pkg:docker/localhost/coffer-horizon@sha256:{'1' * 64}",
        timestamp="2026-07-27T00:00:00Z",
        subcomponent="pkg:pypi/setuptools@68.1.2",
        findings=("CVE-2024-6345", "CVE-2025-47273"),
    )

    assert document["@context"] == "https://openvex.dev/ns/v0.2.0"
    assert document["@id"].startswith("urn:uuid:")
    assert document["author"] == "Coffer Security Working Group"
    assert [item["vulnerability"]["name"] for item in document["statements"]] == [
        "CVE-2024-6345",
        "CVE-2025-47273",
    ]
    assert all(item["status"] == "not_affected" for item in document["statements"])
    assert all(
        item["justification"] == "vulnerable_code_not_present"
        for item in document["statements"]
    )
    assert document == OPENVEX.vex_document(
        surface="horizon",
        product=f"pkg:docker/localhost/coffer-horizon@sha256:{'1' * 64}",
        timestamp="2026-07-27T00:00:00Z",
        subcomponent="pkg:pypi/setuptools@68.1.2",
        findings=("CVE-2024-6345", "CVE-2025-47273"),
    )


def test_openvex_rejects_unverified_source() -> None:
    document = {
        "decision": {
            "source_backports_verified": True,
            "vex_generation_allowed": False,
        },
        "manifest_sha256": "1" * 64,
        "patches": [
            {
                "filename": "CVE-2024-6345.patch",
                "finding_id": "CVE-2024-6345",
                "sha256": "2" * 64,
            }
        ],
        "schema": "coffer.ui-vendor-source-evidence/v1",
        "source": {
            "package": "setuptools",
            "version": "68.1.2-2ubuntu1.2",
        },
    }
    OPENVEX.validate_source(
        document,
        manifest_sha256="1" * 64,
        expected_patches=document["patches"],
    )
    document["decision"]["source_backports_verified"] = False
    with pytest.raises(OPENVEX.VexError, match="source decision"):
        OPENVEX.validate_source(
            document,
            manifest_sha256="1" * 64,
            expected_patches=document["patches"],
        )


def write_scout(path: Path, findings: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "name": "docker scout",
                                "version": "1.21.0",
                                "rules": [
                                    {
                                        "id": finding,
                                        "properties": {
                                            "affected_version": "fixture",
                                            "cvssV3_severity": "HIGH",
                                            "fixed_version": "not fixed",
                                            "purls": [
                                                (
                                                    "pkg:pypi/setuptools@68.1.2"
                                                    if finding
                                                    in {
                                                        "CVE-2024-6345",
                                                        "CVE-2025-47273",
                                                    }
                                                    else (
                                                        "pkg:pypi/oslo.messaging@17.3.0"
                                                    )
                                                )
                                            ],
                                        },
                                    }
                                    for finding in findings
                                ],
                            }
                        }
                    }
                ],
            }
        )
    )


def test_residual_scan_projection_requires_only_oslo_remaining(
    tmp_path: Path,
) -> None:
    write_scout(
        tmp_path / "horizon-after.scout.sarif.json",
        ["CVE-2024-6345", "CVE-2025-47273", "CVE-2026-44393"],
    )
    write_scout(
        tmp_path / "horizon-after.scout.vex.sarif.json",
        ["CVE-2026-44393"],
    )

    result = RESIDUAL_TRIAL.scan_projection(
        tmp_path,
        surface="horizon",
        expected_raw=("CVE-2024-6345", "CVE-2025-47273", "CVE-2026-44393"),
        expected_vex=("CVE-2026-44393",),
    )

    assert result["removed_finding_ids"] == [
        "CVE-2024-6345",
        "CVE-2025-47273",
    ]
    assert result["remaining_finding_ids"] == ["CVE-2026-44393"]


def test_residual_scan_projection_rejects_oslo_suppression(
    tmp_path: Path,
) -> None:
    write_scout(
        tmp_path / "skyline-after.scout.sarif.json",
        ["CVE-2024-6345", "CVE-2025-47273", "CVE-2026-44393"],
    )
    write_scout(
        tmp_path / "skyline-after.scout.vex.sarif.json",
        [],
    )

    with pytest.raises(
        RESIDUAL_TRIAL.ResidualTrialError,
        match="finding delta",
    ):
        RESIDUAL_TRIAL.scan_projection(
            tmp_path,
            surface="skyline",
            expected_raw=(
                "CVE-2024-6345",
                "CVE-2025-47273",
                "CVE-2026-44393",
            ),
            expected_vex=("CVE-2026-44393",),
        )
