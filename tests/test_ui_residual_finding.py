from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "ui-images"
MANIFEST = HARNESS / "residual_findings.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("python_target", HARNESS / "python_target.py")
MODULE = load("coffer_ui_residual_finding", HARNESS / "residual_finding.py")


def write_manifest(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "residual_findings.json"
    path.write_text(json.dumps(document))
    return path


def test_checked_in_residual_contract_is_exact() -> None:
    contract = MODULE.load_contract(MANIFEST)

    assert (
        contract.result_sha256
        == "a920ce2076908469c06103fbd0f19953cbf6e67a4dead964faaf85d20ed21e0a"
    )
    assert tuple(package.key for package in contract.packages) == (
        "oslo-messaging",
        "ubuntu-setuptools",
    )
    assert contract.finding_ids_for("horizon", "trivy") == ("CVE-2026-44393",)
    assert contract.finding_ids_for("skyline", "scout") == (
        "CVE-2024-6345",
        "CVE-2025-47273",
        "CVE-2026-44393",
    )
    setuptools = contract.package("ubuntu-setuptools")
    assert setuptools.installed_version == "68.1.2-2ubuntu1.2"
    assert setuptools.disposition == "vendor-backport-to-prove"
    assert tuple(
        evidence.fixed_package_version for evidence in setuptools.vendor_evidence
    ) == (
        "68.1.2-2ubuntu1.1",
        "68.1.2-2ubuntu1.2",
    )
    assert contract.package("oslo-messaging").disposition == "affected-no-fixed-release"
    assert len(contract.sources) == 4


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("schema", "schema"),
        ("baseline-field", "baseline"),
        ("result-hash", "baseline"),
        ("missing-source", "source set"),
        ("duplicate-source", "source set"),
        ("source-order", "source set"),
        ("source-path", "path"),
        ("source-hash", "source"),
        ("package-order", "unsorted"),
        ("package-field", "package"),
        ("package-key", "package"),
        ("package-version", "value"),
        ("package-path", "installed path"),
        ("purl", "value"),
        ("surfaces", "value"),
        ("disposition", "value"),
        ("scanner", "scanner"),
        ("finding", "scanner"),
        ("duplicate-finding", "scanner"),
        ("empty-findings", "empty"),
        ("vendor-field", "vendor"),
        ("vendor-source", "source"),
        ("vendor-order", "unsorted"),
        ("vendor-mismatch", "not exact"),
        ("affected-fixed", "affected disposition"),
        ("backport-unfixed", "backport disposition"),
        ("package-overlap", "overlap packages"),
    ],
)
def test_residual_contract_rejects_invalid_input(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    document = json.loads(MANIFEST.read_text())
    baseline = document["baseline"]
    sources = baseline["sources"]
    packages = document["packages"]
    oslo = packages["oslo-messaging"]
    setuptools = packages["ubuntu-setuptools"]
    if mutation == "schema":
        document["schema"] = "unsupported"
    elif mutation == "baseline-field":
        baseline["mutable"] = True
    elif mutation == "result-hash":
        baseline["result_sha256"] = "0"
    elif mutation == "missing-source":
        sources.pop()
    elif mutation == "duplicate-source":
        sources.append(sources[0])
    elif mutation == "source-order":
        sources.reverse()
    elif mutation == "source-path":
        sources[0]["path"] = "../report.json"
    elif mutation == "source-hash":
        sources[0]["sha256"] = "0"
    elif mutation == "package-order":
        document["packages"] = {
            "ubuntu-setuptools": setuptools,
            "oslo-messaging": oslo,
        }
    elif mutation == "package-field":
        oslo["mutable"] = True
    elif mutation == "package-key":
        packages["UNKNOWN"] = packages.pop("oslo-messaging")
    elif mutation == "package-version":
        oslo["installed_version"] = "latest"
    elif mutation == "package-path":
        oslo["installed_path"] = "/absolute"
    elif mutation == "purl":
        oslo["purl"] = "https://example.invalid/package"
    elif mutation == "surfaces":
        oslo["surfaces"] = ["horizon"]
    elif mutation == "disposition":
        oslo["disposition"] = "waived"
    elif mutation == "scanner":
        oslo["findings_by_scanner"]["unknown"] = []
    elif mutation == "finding":
        oslo["findings_by_scanner"]["trivy"] = ["free-form"]
    elif mutation == "duplicate-finding":
        oslo["findings_by_scanner"]["trivy"].append("CVE-2026-44393")
    elif mutation == "empty-findings":
        for scanner in ("scout", "trivy"):
            oslo["findings_by_scanner"][scanner] = []
    elif mutation == "vendor-field":
        oslo["vendor_evidence"][0]["mutable"] = True
    elif mutation == "vendor-source":
        oslo["vendor_evidence"][0]["source"] = "http://example.invalid"
    elif mutation == "vendor-order":
        setuptools["vendor_evidence"].reverse()
    elif mutation == "vendor-mismatch":
        oslo["vendor_evidence"][0]["finding_id"] = "CVE-2026-44394"
    elif mutation == "affected-fixed":
        oslo["vendor_evidence"][0]["fixed_package_version"] = "17.3.1"
    elif mutation == "backport-unfixed":
        setuptools["vendor_evidence"][0]["fixed_package_version"] = "none-published"
    elif mutation == "package-overlap":
        setuptools["findings_by_scanner"]["scout"].append("CVE-2026-44393")
        setuptools["findings_by_scanner"]["scout"].sort()
        setuptools["vendor_evidence"].append(
            {
                "finding_id": "CVE-2026-44393",
                "fixed_package_version": "68.1.2-2ubuntu1.2",
                "source": "https://ubuntu.com/security/notices/USN-7544-1",
            }
        )
        setuptools["vendor_evidence"].sort(key=lambda item: item["finding_id"])

    with pytest.raises(MODULE.ResidualError, match=message):
        MODULE.load_contract(write_manifest(tmp_path, document))


def test_residual_contract_refuses_linked_or_unknown_inputs(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "residual_findings.json"
    linked.symlink_to(MANIFEST)
    with pytest.raises(MODULE.ResidualError, match="missing or linked"):
        MODULE.load_contract(linked)

    contract = MODULE.load_contract(MANIFEST)
    with pytest.raises(MODULE.ResidualError, match="package is unsupported"):
        contract.package("unknown")
    with pytest.raises(MODULE.ResidualError, match="source is unsupported"):
        contract.source("horizon", "unknown")
    with pytest.raises(MODULE.ResidualError, match="projection is unsupported"):
        contract.finding_ids_for("unknown", "trivy")
