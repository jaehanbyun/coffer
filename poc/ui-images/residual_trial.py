from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import qualification
from collect_python_trial import CollectionError, atomic_json
from generate_setuptools_openvex import (
    INDEX_SCHEMA,
    VexError,
    load_json,
    scout_projection,
    sha256_file,
    vex_document,
)
from residual_finding import ResidualError, load_contract

SCHEMA = "coffer.ui-residual-trial/v1"
SURFACES = ("horizon", "skyline")


class ResidualTrialError(RuntimeError):
    pass


def validate_baseline(contract, root: Path) -> None:
    result = (
        root
        / "work/ui-python-overlay-trial-matrix-accepted/evidence/python-matrix-trial.json"
    )
    if sha256_file(result) != contract.result_sha256:
        raise ResidualTrialError("Plan 0025 result identity is invalid")
    for source in contract.sources:
        path = root / source.path
        if sha256_file(path) != source.sha256:
            raise ResidualTrialError("Plan 0025 residual source identity is invalid")


def scan_projection(
    evidence: Path,
    *,
    surface: str,
    expected_raw: tuple[str, ...],
    expected_vex: tuple[str, ...],
) -> dict[str, Any]:
    raw_path = evidence / f"{surface}-after.scout.sarif.json"
    vex_path = evidence / f"{surface}-after.scout.vex.sarif.json"
    try:
        raw = qualification.scout_report(raw_path)
        vex = qualification.scout_report(vex_path)
    except qualification.EvidenceError as error:
        raise ResidualTrialError("Scout residual evidence is invalid") from error
    raw_ids = tuple(sorted(item[0] for item in raw.critical_high))
    vex_ids = tuple(sorted(item[0] for item in vex.critical_high))
    removed = tuple(sorted(set(raw_ids) - set(vex_ids)))
    if (
        raw_ids != expected_raw
        or vex_ids != expected_vex
        or removed != ("CVE-2024-6345", "CVE-2025-47273")
        or raw.counts["critical"] != 0
        or raw.counts["high"] != 3
        or vex.counts["critical"] != 0
        or vex.counts["high"] != 1
        or any(
            raw.counts[severity] != vex.counts[severity]
            for severity in ("medium", "low", "unknown")
        )
    ):
        raise ResidualTrialError("Scout OpenVEX finding delta is invalid")
    return {
        "raw": raw.counts,
        "vex_aware": vex.counts,
        "removed_finding_ids": list(removed),
        "remaining_finding_ids": list(vex_ids),
        "raw_sha256": sha256_file(raw_path),
        "vex_aware_sha256": sha256_file(vex_path),
    }


def validate_openvex(
    evidence: Path,
    *,
    manifest_path: Path,
    source_path: Path,
    baseline_result_path: Path,
) -> dict[str, Any]:
    index_path = evidence / "vex/index.json"
    index = load_json(index_path, "OpenVEX index")
    if index.get("schema") != INDEX_SCHEMA:
        raise ResidualTrialError("OpenVEX index schema is invalid")
    expected_inputs = {
        "baseline_result_sha256": sha256_file(baseline_result_path),
        "images_sha256": sha256_file(evidence / "images.json"),
        "residual_manifest_sha256": sha256_file(manifest_path),
        "runtime_evidence_sha256": sha256_file(evidence / "setuptools-runtimes.json"),
        "scout_sbom_sha256": {
            surface: sha256_file(evidence / f"{surface}-after.scout.sbom.json")
            for surface in SURFACES
        },
        "source_evidence_sha256": sha256_file(source_path),
    }
    if index.get("inputs") != expected_inputs:
        raise ResidualTrialError("OpenVEX input binding is invalid")
    runtime = load_json(
        evidence / "setuptools-runtimes.json",
        "setuptools runtime evidence",
    )
    images = load_json(evidence / "images.json", "matrix images")
    entries = index.get("openvex")
    if not isinstance(entries, dict) or set(entries) != set(SURFACES):
        raise ResidualTrialError("OpenVEX surface set is invalid")
    for surface in SURFACES:
        entry = entries[surface]
        if not isinstance(entry, dict):
            raise ResidualTrialError("OpenVEX index entry is invalid")
        path = evidence / "vex" / f"{surface}.vex.json"
        image = images["images"][f"{surface}-after"]
        image_id = image["id"]
        archive_name = (
            "work/ui-python-overlay-trial-matrix-accepted-residual/evidence/"
            f"{surface}-after.tar"
        )
        scout = scout_projection(
            load_json(
                evidence / f"{surface}-after.scout.sbom.json",
                f"{surface} Docker Scout SBOM",
            ),
            expected_archive_name=archive_name,
            expected_config_digest=image_id,
        )
        expected_product = f"pkg:docker/{archive_name}@{scout['image_manifest_digest']}"
        if entry != {
            "archive_name": archive_name,
            "filename": f"{surface}.vex.json",
            "image_config_digest": image_id,
            "image_manifest_digest": scout["image_manifest_digest"],
            "product": expected_product,
            "sha256": sha256_file(path),
        }:
            raise ResidualTrialError("OpenVEX product binding is invalid")
        document = load_json(path, f"{surface} OpenVEX")
        expected_document = vex_document(
            surface=surface,
            product=expected_product,
            timestamp=image["labels"]["org.opencontainers.image.created"],
            subcomponent="pkg:pypi/setuptools@68.1.2",
            findings=("CVE-2024-6345", "CVE-2025-47273"),
        )
        if document != expected_document:
            raise ResidualTrialError("OpenVEX document is not exact")
        runtime_decision = runtime["runtimes"][surface]["decision"]
        if runtime_decision.get("vex_generation_allowed") is not True:
            raise ResidualTrialError("OpenVEX runtime decision is invalid")
    return {
        "index_sha256": sha256_file(index_path),
        "runtime_sha256": sha256_file(evidence / "setuptools-runtimes.json"),
    }


def build_report(
    evidence: Path,
    *,
    root: Path,
    manifest_path: Path,
    source_path: Path,
    baseline_result_path: Path,
) -> dict[str, Any]:
    try:
        contract = load_contract(manifest_path)
    except ResidualError as error:
        raise ResidualTrialError("residual contract is invalid") from error
    validate_baseline(contract, root)
    if sha256_file(baseline_result_path) != contract.result_sha256:
        raise ResidualTrialError("residual baseline result is invalid")
    openvex = validate_openvex(
        evidence,
        manifest_path=manifest_path,
        source_path=source_path,
        baseline_result_path=baseline_result_path,
    )
    setuptools = contract.package("ubuntu-setuptools")
    oslo = contract.package("oslo-messaging")
    surfaces = {
        surface: scan_projection(
            evidence,
            surface=surface,
            expected_raw=contract.finding_ids_for(surface, "scout"),
            expected_vex=oslo.finding_ids_for("scout"),
        )
        for surface in SURFACES
    }
    return {
        "architecture": "arm64",
        "evidence": {
            **openvex,
            "manifest_sha256": sha256_file(manifest_path),
            "source_sha256": sha256_file(source_path),
        },
        "packages": {
            "oslo-messaging": {
                "disposition": "affected-no-fixed-release",
                "finding_ids": list(oslo.finding_ids),
                "release_qualified": False,
            },
            "ubuntu-setuptools": {
                "disposition": "not_affected",
                "finding_ids": list(setuptools.finding_ids),
                "justification": "vulnerable_code_not_present",
                "openvex_accepted": True,
            },
        },
        "schema": SCHEMA,
        "surfaces": surfaces,
        "decision": {
            "status": "blocked",
            "production_candidate": False,
            "setuptools_openvex_accepted": True,
            "waivers_applied": False,
            "raw_scanner_evidence_retained": True,
            "blockers": [
                (
                    "oslo.messaging 17.3.0 remains affected by "
                    "CVE-2026-44393 without a qualified fixed release"
                ),
                (
                    "native AMD64, Distribution/Ceph, signing, publication, "
                    "and live Kolla/UI gates remain independent"
                ),
            ],
            "next_action": (
                "resolve the upstream oslo.messaging patch and release state, "
                "then qualify the first official fixed release"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--baseline-result", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = build_report(
            arguments.evidence,
            root=arguments.root,
            manifest_path=arguments.manifest,
            source_path=arguments.source_evidence,
            baseline_result_path=arguments.baseline_result,
        )
        atomic_json(arguments.evidence / "residual-trial.json", report)
    except (
        CollectionError,
        ResidualTrialError,
        VexError,
        qualification.EvidenceError,
    ) as error:
        print(f"coffer-ui-residual-trial: {error}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
