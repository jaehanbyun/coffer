from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import python_trial as common
from collect_python_matrix_trial import (
    MANIFEST_SCHEMA,
    RUNTIME_SCHEMA,
    CollectionError,
    component_projection,
    surface_projection,
    wheel_map,
)
from python_matrix import Matrix, MatrixError, MatrixSurface, load_matrix
from python_target import SCANNERS, TargetError

RESULT_SCHEMA = "coffer.ui-python-matrix-trial/v1"
SURFACES = ("horizon", "skyline")
KINDS = ("before", "after")


def validate_baselines(
    *,
    matrix: Matrix,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
) -> None:
    for surface in matrix.surfaces:
        common.validate_baselines(
            target=SimpleNamespace(
                surfaces=(surface.name,),
                components=surface.components,
            ),
            baseline_result_path=baseline_result_path,
            baseline_inventories_path=baseline_inventories_path,
            remediation_result_path=remediation_result_path,
        )


def validate_manifest(
    evidence: Path,
    *,
    matrix: Matrix,
    matrix_manifest_path: Path,
    target_manifest_path: Path,
    target_wheels: tuple[Path, ...],
    horizon_wheel: Path,
    skyline_wheel: Path,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
) -> dict[str, Any]:
    wheel_map(target_wheels, matrix)
    manifest = common._load(evidence / "manifest.json", "matrix manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise common.EvidenceError("matrix manifest schema is unsupported")
    architecture = manifest.get("architecture")
    if (
        architecture not in {"arm64", "amd64"}
        or manifest.get("platform") != f"linux/{architecture}"
    ):
        raise common.EvidenceError("matrix manifest platform is invalid")
    sources = common._object(manifest.get("sources"), "matrix sources")
    if sources != {
        "ubuntu_sha256": sources.get("ubuntu_sha256"),
        "kolla": common.KOLLA_REVISION,
        "horizon": common.HORIZON_REVISION,
        "skyline": common.SKYLINE_REVISION,
    } or not re.fullmatch(
        r"[0-9a-f]{64}",
        str(sources.get("ubuntu_sha256", "")),
    ):
        raise common.EvidenceError("matrix source revisions are invalid")
    artifacts = common._object(manifest.get("artifacts"), "matrix artifacts")
    expected_artifacts = {
        "horizon": {
            "name": "coffer-horizon",
            "version": "0.1.0",
            "sha256": common.sha256_file(horizon_wheel),
        },
        "skyline": {
            "name": "skyline-console",
            "version": "8.0.0+coffer.1",
            "sha256": common.sha256_file(skyline_wheel),
        },
        "matrix": {
            "key": matrix.key,
            "manifest_sha256": common.sha256_file(matrix_manifest_path),
            "target_manifest_sha256": common.sha256_file(target_manifest_path),
            "trial_label": matrix.trial_label,
            "surfaces": {
                surface: surface_projection(matrix, surface) for surface in SURFACES
            },
            "wheels": [
                component_projection(component) for component in matrix.components
            ],
        },
    }
    if artifacts != expected_artifacts:
        raise common.EvidenceError("matrix artifacts do not match exact inputs")
    if any(
        component.wheel_architecture not in {"any", architecture}
        for component in matrix.components
    ):
        raise common.EvidenceError("matrix wheel architecture is incompatible")
    baseline = common._object(manifest.get("baseline"), "matrix baseline")
    if baseline != {
        "os_cleanup_result_sha256": common.sha256_file(baseline_result_path),
        "os_cleanup_inventories_sha256": common.sha256_file(baseline_inventories_path),
        "remediation_result_sha256": common.sha256_file(remediation_result_path),
    }:
        raise common.EvidenceError("matrix baseline hashes are inconsistent")
    images = common._object(manifest.get("images"), "matrix images")
    expected_keys = {f"{surface}-{kind}" for surface in SURFACES for kind in KINDS}
    if set(images) != expected_keys or any(
        not common.DIGEST.fullmatch(str(common._object(images[key], key).get("id", "")))
        for key in expected_keys
    ):
        raise common.EvidenceError("matrix image set is invalid")
    scanners = common._object(manifest.get("scanners"), "matrix scanners")
    if set(scanners) != {"docker_scout", "trivy"} or any(
        not isinstance(value, str) or not value for value in scanners.values()
    ):
        raise common.EvidenceError("matrix scanner versions are invalid")
    return manifest


def validate_images(
    evidence: Path,
    manifest: dict[str, Any],
    *,
    matrix: Matrix,
) -> None:
    document = common._load(
        evidence / "images.json",
        "matrix image inspection",
    )
    if document.get("schema") != common.IMAGE_SCHEMA:
        raise common.EvidenceError("matrix image inspection schema is unsupported")
    images = common._object(document.get("images"), "matrix inspected images")
    if set(images) != set(manifest["images"]):
        raise common.EvidenceError("matrix inspected image set is invalid")
    for surface in SURFACES:
        before = common._object(
            images[f"{surface}-before"],
            f"{surface} before image",
        )
        after = common._object(
            images[f"{surface}-after"],
            f"{surface} after image",
        )
        for kind, image in (("before", before), ("after", after)):
            if (
                image.get("id") != manifest["images"][f"{surface}-{kind}"]["id"]
                or image.get("architecture") != manifest["architecture"]
                or image.get("os") != "linux"
            ):
                raise common.EvidenceError(
                    f"{surface} {kind} matrix image is inconsistent"
                )
        for field in ("user", "entrypoint", "cmd"):
            if after.get(field) != before.get(field):
                raise common.EvidenceError(f"{surface} matrix changed Kolla {field}")
        before_layers = common._array(
            before.get("layers"),
            f"{surface} before layers",
        )
        after_layers = common._array(
            after.get("layers"),
            f"{surface} after layers",
        )
        if (
            len(after_layers) <= len(before_layers)
            or after_layers[: len(before_layers)] != before_layers
        ):
            raise common.EvidenceError(f"{surface} matrix does not inherit exact input")
        labels = common._object(after.get("labels"), f"{surface} labels")
        expected_labels = {
            "io.coffer.ui.contract": "coffer-ui-image-v1",
            "io.coffer.ui.surface": surface,
            "io.coffer.ui.os-cleanup-trial": "coffer-ui-os-cleanup-v1",
            "io.coffer.ui.python-matrix-trial": matrix.trial_label,
            "org.opencontainers.image.revision": (
                common.HORIZON_REVISION
                if surface == "horizon"
                else common.SKYLINE_REVISION
            ),
        }
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            raise common.EvidenceError(f"{surface} matrix labels are invalid")


def validate_os_inventories(
    evidence: Path,
    manifest: dict[str, Any],
    *,
    baseline_inventories_path: Path,
) -> None:
    common.validate_os_inventories(
        evidence,
        manifest,
        baseline_inventories_path=baseline_inventories_path,
        target=SimpleNamespace(surfaces=SURFACES),
    )


def _target_wheel_map(
    paths: tuple[Path, ...],
    matrix: Matrix,
) -> dict[str, Path]:
    try:
        return wheel_map(paths, matrix)
    except CollectionError as error:
        raise common.EvidenceError("matrix wheel set is invalid") from error


def validate_python_runtimes(
    document: dict[str, Any],
    *,
    manifest: dict[str, Any],
    target_wheels: tuple[Path, ...],
    matrix: Matrix,
) -> None:
    python = common._object(document.get("python"), "matrix Python runtimes")
    if set(python) != set(manifest["images"]):
        raise common.EvidenceError("matrix Python runtime set is invalid")
    wheels = _target_wheel_map(target_wheels, matrix)
    expected_absent = [
        "/tmp/target-wheels",
        "/tmp/python_matrix.py",
        "/tmp/python_matrices.json",
        "/tmp/python_target.py",
        "/tmp/python_targets.json",
    ]
    for surface_name in SURFACES:
        surface = matrix.for_surface(surface_name)
        expected_files = {
            component.normalized_name: common._target_wheel_members(
                wheels[component.wheel_filename],
                component,
            )
            for component in surface.components
        }
        before_document = common._object(
            python[f"{surface_name}-before"],
            f"{surface_name} before Python runtime",
        )
        after_document = common._object(
            python[f"{surface_name}-after"],
            f"{surface_name} after Python runtime",
        )
        for kind, runtime in (
            ("before", before_document),
            ("after", after_document),
        ):
            if (
                runtime.get("schema") != "coffer.ui-python-matrix-runtime/v1"
                or runtime.get("architecture") != manifest["architecture"]
                or runtime.get("surface") != surface_name
            ):
                raise common.EvidenceError(
                    f"{surface_name} {kind} matrix runtime is invalid"
                )
            if runtime.get("pip_check") != {
                "clean": True,
                "message": "No broken requirements found.",
            }:
                raise common.EvidenceError(
                    f"{surface_name} {kind} matrix pip check failed"
                )
            components = common._array(
                runtime.get("components"),
                f"{surface_name} {kind} matrix components",
            )
            expected_components = [
                {
                    "name": component.normalized_name,
                    "version": (
                        component.from_version
                        if kind == "before"
                        else component.to_version
                    ),
                }
                for component in surface.components
            ]
            actual_components = [
                {
                    "name": common._object(value, "matrix component").get("name"),
                    "version": common._object(
                        value,
                        "matrix component",
                    ).get("version"),
                }
                for value in components
            ]
            expected_probes = [
                {
                    "target": target.key,
                    "name": target.probe,
                    "mode": ("baseline" if kind == "before" else "candidate"),
                    "result": target.expected_probe_result,
                }
                for target in surface.targets
            ]
            if (
                actual_components != expected_components
                or runtime.get("probes") != expected_probes
                or runtime.get("absent") != expected_absent
            ):
                raise common.EvidenceError(
                    f"{surface_name} {kind} matrix contract is invalid"
                )
        after_components = common._array(
            after_document.get("components"),
            f"{surface_name} after matrix components",
        )
        for component, value in zip(
            surface.components,
            after_components,
            strict=True,
        ):
            installed_files = common._object(
                common._object(value, "matrix component").get("files"),
                "installed matrix files",
            )
            installed_source = {
                name: digest
                for name, digest in installed_files.items()
                if "/__pycache__/" not in name
            }
            generated_files = set(installed_files) - set(installed_source)
            if installed_source != expected_files[component.normalized_name] or any(
                not re.fullmatch(
                    rf"{re.escape(component.package_prefix)}"
                    r"(?:[^/]+/)*__pycache__/[^/]+\.pyc",
                    name,
                )
                for name in generated_files
            ):
                raise common.EvidenceError(
                    f"{surface_name} matrix wheel files are invalid"
                )
        before = common._python_packages(
            before_document,
            f"{surface_name} before",
        )
        after = common._python_packages(
            after_document,
            f"{surface_name} after",
        )
        changed = {
            name for name in set(before) & set(after) if before[name] != after[name]
        }
        if (
            set(before) != set(after)
            or changed
            != {component.normalized_name for component in surface.components}
            or any(
                before.get(component.normalized_name) != [component.from_version]
                or after.get(component.normalized_name) != [component.to_version]
                for component in surface.components
            )
        ):
            raise common.EvidenceError(
                f"{surface_name} matrix package delta is not exact"
            )


def validate_runtimes(
    evidence: Path,
    *,
    manifest: dict[str, Any],
    matrix: Matrix,
    target_wheels: tuple[Path, ...],
    horizon_wheel: Path,
    skyline_wheel: Path,
) -> None:
    document = common._load(evidence / "runtimes.json", "matrix runtimes")
    if (
        document.get("schema") != RUNTIME_SCHEMA
        or document.get("architecture") != manifest["architecture"]
    ):
        raise common.EvidenceError("matrix runtime identity is invalid")
    validate_python_runtimes(
        document,
        manifest=manifest,
        target_wheels=target_wheels,
        matrix=matrix,
    )
    common.validate_ui_runtimes(
        document,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        target=SimpleNamespace(surfaces=SURFACES),
    )


def scanner_result(
    evidence: Path,
    surface: MatrixSurface,
    scanner: str,
) -> dict[str, Any]:
    qualification = common._load_sibling("qualification")
    parser = (
        qualification.trivy_report if scanner == "trivy" else qualification.scout_report
    )
    before = parser(
        evidence / f"{surface.name}-before.{common._scanner_suffix(scanner)}"
    )
    after = parser(evidence / f"{surface.name}-after.{common._scanner_suffix(scanner)}")
    introduced = after.critical_high - before.critical_high
    removed = before.critical_high - after.critical_high
    removed_ids = frozenset(item[0] for item in removed)
    after_ids = frozenset(item[0] for item in after.critical_high)
    expected = frozenset(surface.finding_ids_for(scanner))
    if introduced:
        raise common.EvidenceError(
            f"{scanner} {surface.name} matrix introduced findings"
        )
    if removed_ids != expected or len(removed) != len(expected) or expected & after_ids:
        raise common.EvidenceError(
            f"{scanner} {surface.name} matrix finding delta is invalid"
        )
    if scanner == "trivy" and (before.secrets or after.secrets):
        raise common.EvidenceError(f"{surface.name} matrix contains a Trivy secret")
    return {
        "before": before.counts,
        "after": after.counts,
        "removed_critical_high": len(removed),
        "removed_finding_ids": sorted(removed_ids),
        "introduced_critical_high": 0,
        "after_secrets": after.secrets,
    }


def build_report(
    evidence: Path,
    *,
    matrix: Matrix,
    matrix_manifest_path: Path,
    target_manifest_path: Path,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheels: tuple[Path, ...],
) -> dict[str, Any]:
    validate_baselines(
        matrix=matrix,
        baseline_result_path=baseline_result_path,
        baseline_inventories_path=baseline_inventories_path,
        remediation_result_path=remediation_result_path,
    )
    manifest = validate_manifest(
        evidence,
        matrix=matrix,
        matrix_manifest_path=matrix_manifest_path,
        target_manifest_path=target_manifest_path,
        target_wheels=target_wheels,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        baseline_result_path=baseline_result_path,
        baseline_inventories_path=baseline_inventories_path,
        remediation_result_path=remediation_result_path,
    )
    validate_images(evidence, manifest, matrix=matrix)
    validate_os_inventories(
        evidence,
        manifest,
        baseline_inventories_path=baseline_inventories_path,
    )
    validate_runtimes(
        evidence,
        manifest=manifest,
        matrix=matrix,
        target_wheels=target_wheels,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
    )
    surfaces: dict[str, Any] = {}
    blockers: list[str] = []
    for surface in matrix.surfaces:
        scanners = {
            scanner: scanner_result(evidence, surface, scanner) for scanner in SCANNERS
        }
        for scanner, result in scanners.items():
            after = result["after"]
            if after["critical"] or after["high"]:
                blockers.append(
                    f"{scanner} {surface.name} matrix remains at "
                    f"{after['critical']} Critical/{after['high']} High"
                )
        surfaces[surface.name] = {"scanners": scanners}
    if not blockers:
        blockers.append(
            "native AMD64, Distribution/Ceph, signing, publication, and live "
            "Kolla/UI gates remain independent"
        )
    return {
        "schema": RESULT_SCHEMA,
        "architecture": manifest["architecture"],
        "sources": manifest["sources"],
        "artifacts": manifest["artifacts"],
        "baseline": manifest["baseline"],
        "evidence": {
            f"{name}_sha256": common.sha256_file(evidence / f"{name}.json")
            for name in (
                "manifest",
                "images",
                "os-inventories",
                "runtimes",
            )
        },
        "surfaces": surfaces,
        "decision": {
            "status": "blocked",
            "production_candidate": False,
            "python_matrix_trial_accepted": True,
            "matrix": matrix.key,
            "production_containerfile_changed": False,
            "private_constraint_override_accepted": False,
            "waivers_applied": False,
            "blockers": blockers,
            "next_action": (
                "translate the accepted cumulative matrix into a separately "
                "reviewed immutable image contract without weakening the "
                "remaining production gates"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--baseline-result", type=Path, required=True)
    parser.add_argument("--baseline-inventories", type=Path, required=True)
    parser.add_argument("--remediation-result", type=Path, required=True)
    parser.add_argument("--horizon-wheel", type=Path, required=True)
    parser.add_argument("--skyline-wheel", type=Path, required=True)
    parser.add_argument(
        "--target-wheel",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--matrix-manifest", type=Path, required=True)
    parser.add_argument("--matrix", required=True)
    arguments = parser.parse_args()
    try:
        matrix = load_matrix(
            arguments.matrix_manifest,
            arguments.target_manifest,
            arguments.matrix,
        )
        report = build_report(
            arguments.evidence,
            matrix=matrix,
            matrix_manifest_path=arguments.matrix_manifest,
            target_manifest_path=arguments.target_manifest,
            baseline_result_path=arguments.baseline_result,
            baseline_inventories_path=arguments.baseline_inventories,
            remediation_result_path=arguments.remediation_result,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
            target_wheels=tuple(arguments.target_wheel),
        )
        common.write_result(
            arguments.evidence / "python-matrix-trial.json",
            report,
        )
    except (common.EvidenceError, CollectionError, MatrixError, TargetError) as error:
        print(f"coffer-ui-python-matrix-trial: {error}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
