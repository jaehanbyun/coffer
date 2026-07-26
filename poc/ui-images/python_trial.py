from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
from itertools import zip_longest
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from python_target import PackageComponent, Target, TargetError, load_target

MANIFEST_SCHEMA = "coffer.ui-python-overlay-evidence/v4"
IMAGE_SCHEMA = "coffer.ui-python-overlay-images/v1"
INVENTORY_SCHEMA = "coffer.ui-python-overlay-os-inventories/v1"
RUNTIME_SCHEMA = "coffer.ui-python-overlay-runtimes/v1"
PYTHON_RUNTIME_SCHEMA = "coffer.ui-python-overlay-runtime/v3"
PACKAGE_INVENTORY_SCHEMA = "coffer.ui-package-inventory/v1"
RESULT_SCHEMA = "coffer.ui-python-overlay-trial/v4"
OS_CLEANUP_RESULT_SCHEMA = "coffer.ui-os-cleanup-trial/v1"
REMEDIATION_SCHEMA = "coffer.ui-parent-remediation/v1"
KOLLA_REVISION = "686c6d13dc1c31092b22c6c481e16a7329e935ea"
HORIZON_REVISION = "0a4439556517cf67be0aa949b6551a14e409af75"
SKYLINE_REVISION = "c9000cb1be332a213009793598f17a80ce59671e"
OS_CLEANUP_RESULT_SHA256 = (
    "a8da7856f955f25866a0b9fbe9214d34863a502714a1624ac2ae66ce6caac2d3"
)
OS_CLEANUP_INVENTORIES_SHA256 = (
    "cce5364a6a2202ae822b8510cb0b4339afef1133d3f8f0affacb75e28cf721db"
)
REMEDIATION_RESULT_SHA256 = (
    "9ecde6e3b6e2d484bd27fa05cf6c1b26e81077a3e3154a64ebf4902863fa0941"
)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SURFACES = ("horizon", "skyline")
KINDS = ("before", "after")
SCANNERS = ("trivy", "scout")
PURGED_PACKAGES = frozenset(
    {
        "build-essential",
        "g++",
        "g++-13",
        "g++-13-aarch64-linux-gnu",
        "g++-aarch64-linux-gnu",
        "libc6-dev",
        "libexpat1-dev",
        "libicu-dev",
        "libpcre2-dev",
        "libpython3-dev",
        "libpython3.12-dev",
        "libstdc++-13-dev",
        "libxml2-dev",
        "libxslt1-dev",
        "linux-libc-dev",
        "python3-dev",
        "python3.12-dev",
        "zlib1g-dev",
    }
)
HORIZON_MEMBERS = (
    "cofferdashboard/enabled/_1910_project_registry_panel_group.py",
    "cofferdashboard/enabled/_1920_project_registry_repositories_panel.py",
    "cofferdashboard/local_settings.d/_1930_coffer_policy.py",
    "cofferdashboard/conf/coffer_policy.yaml",
)
HORIZON_ABSENT = (
    "/tmp/coffer_horizon-0.1.0-py3-none-any.whl",
    "/tmp/install-coffer-horizon.py",
)
SKYLINE_ABSENT = (
    "/tmp/skyline_console-8.0.0+coffer.1-py3-none-any.whl",
)


class EvidenceError(RuntimeError):
    pass


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceError(f"{label} must be an array")
    return value


def _load(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"{label} is missing or linked")
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is not valid JSON") from error


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"artifact is missing or linked: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _numeric_release(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
        raise EvidenceError(f"{label} is not a numeric release")
    return tuple(int(part) for part in value.split("."))


def _release_at_least(candidate: object, floor: object, label: str) -> bool:
    candidate_parts = _numeric_release(candidate, f"{label} candidate")
    floor_parts = _numeric_release(floor, f"{label} floor")
    for candidate_part, floor_part in zip_longest(
        candidate_parts,
        floor_parts,
        fillvalue=0,
    ):
        if candidate_part != floor_part:
            return candidate_part > floor_part
    return True


def _load_sibling(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"coffer_ui_{name}", path)
    if spec is None or spec.loader is None:
        raise EvidenceError(f"{name} parser is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _wheel_members(path: Path, surface: str) -> dict[str, str]:
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if surface == "horizon":
                members = HORIZON_MEMBERS
            else:
                members = tuple(
                    name
                    for name in names
                    if name.startswith("skyline_console/static/coffer.bundle.")
                    and name.endswith(".js")
                )
                if len(members) != 1:
                    raise EvidenceError(
                        "Skyline wheel must contain one Coffer bundle"
                    )
            return {
                member: hashlib.sha256(archive.read(member)).hexdigest()
                for member in members
            }
    except (OSError, KeyError) as error:
        raise EvidenceError(f"{surface} wheel runtime member is missing") from error


def _target_wheel_members(
    path: Path,
    component: PackageComponent,
) -> dict[str, str]:
    if (
        path.name != component.wheel_filename
        or sha256_file(path) != component.wheel_sha256
    ):
        raise EvidenceError("target wheel identity is invalid")
    try:
        with ZipFile(path) as archive:
            members = tuple(
                name
                for name in archive.namelist()
                if name.startswith(component.package_prefix)
                and not name.endswith("/")
            )
            if not members:
                raise EvidenceError("target wheel package is empty")
            return {
                member: hashlib.sha256(archive.read(member)).hexdigest()
                for member in members
            }
    except OSError as error:
        raise EvidenceError("target wheel is invalid") from error


def _target_wheel_map(
    paths: tuple[Path, ...],
    target: Target,
) -> dict[str, Path]:
    expected = tuple(
        component.wheel_filename for component in target.components
    )
    actual = tuple(path.name for path in paths)
    if (
        actual != expected
        or len(set(actual)) != len(actual)
        or len(paths) != len(target.components)
    ):
        raise EvidenceError("target wheel set is invalid")
    result = dict(zip(expected, paths, strict=True))
    for component in target.components:
        _target_wheel_members(result[component.wheel_filename], component)
    return result


def _component_artifact(component: PackageComponent) -> dict[str, Any]:
    return {
        "name": component.display_name,
        "normalized_name": component.normalized_name,
        "from_version": component.from_version,
        "to_version": component.to_version,
        "filename": component.wheel_filename,
        "wheel_architecture": component.wheel_architecture,
        "sha256": component.wheel_sha256,
        "finding_ids": list(component.finding_ids),
        "finding_ids_by_scanner": component.scanner_finding_ids,
        "requires_dist": list(component.requires_dist),
    }


def validate_baselines(
    *,
    target: Target,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
) -> None:
    if sha256_file(baseline_result_path) != OS_CLEANUP_RESULT_SHA256:
        raise EvidenceError("OS cleanup result hash is invalid")
    if sha256_file(remediation_result_path) != REMEDIATION_RESULT_SHA256:
        raise EvidenceError("remediation result hash is invalid")
    if sha256_file(baseline_inventories_path) != OS_CLEANUP_INVENTORIES_SHA256:
        raise EvidenceError("OS cleanup inventory hash is invalid")
    baseline = _load(baseline_result_path, "OS cleanup result")
    decision = _object(baseline.get("decision"), "OS cleanup decision")
    if (
        baseline.get("schema") != OS_CLEANUP_RESULT_SCHEMA
        or decision.get("status") != "blocked"
        or decision.get("production_candidate") is not False
        or decision.get("os_cleanup_trial_accepted") is not True
    ):
        raise EvidenceError("OS cleanup result is not accepted")
    remediation = _load(remediation_result_path, "remediation result")
    if remediation.get("schema") != REMEDIATION_SCHEMA:
        raise EvidenceError("remediation result schema is invalid")
    for surface in target.surfaces:
        packages = _array(
            _object(
                _object(remediation.get("surfaces"), "remediation surfaces").get(
                    surface
                ),
                f"{surface} remediation",
            ).get("packages"),
            f"{surface} remediation packages",
        )
        for component in target.components:
            candidates = [
                _object(value, f"{surface} candidate")
                for value in packages
                if _object(value, f"{surface} package").get("package")
                == component.normalized_name
            ]
            if len(candidates) != 1:
                raise EvidenceError(
                    f"{surface} target candidate is ambiguous"
                )
            candidate = candidates[0]
            fixed_versions = _array(
                candidate.get("fixed_versions"),
                "target fixed versions",
            )
            if (
                candidate.get("classification")
                != "constraint-bound-all-findings-have-fix"
                or candidate.get("eligible_for_compatibility_trial") is not True
                or candidate.get("constraint_match") is not True
                or candidate.get("installed_version") != component.from_version
                or candidate.get("constraint_version") != component.from_version
                or not _release_at_least(
                    component.to_version,
                    component.from_version,
                    "target upgrade",
                )
                or component.to_version == component.from_version
                or not any(
                    _release_at_least(
                        component.to_version,
                        fixed_version,
                        "target fixed version",
                    )
                    for fixed_version in fixed_versions
                )
                or frozenset(candidate.get("finding_ids") or ())
                != frozenset(component.finding_ids)
            ):
                raise EvidenceError(
                    f"{surface} target candidate is invalid"
                )
    inventories = _load(baseline_inventories_path, "OS cleanup inventories")
    if inventories.get("schema") != "coffer.ui-os-cleanup-inventories/v1":
        raise EvidenceError("OS cleanup inventory schema is invalid")


def validate_manifest(
    evidence: Path,
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheels: tuple[Path, ...],
    target_manifest_path: Path,
    target: Target,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
) -> dict[str, Any]:
    _target_wheel_map(target_wheels, target)
    manifest = _load(evidence / "manifest.json", "trial manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise EvidenceError("trial manifest schema is unsupported")
    if manifest.get("architecture") not in {"arm64", "amd64"}:
        raise EvidenceError("trial architecture is unsupported")
    if manifest.get("platform") != f"linux/{manifest['architecture']}":
        raise EvidenceError("trial platform is inconsistent")
    sources = _object(manifest.get("sources"), "trial sources")
    expected_revisions = {
        "kolla": KOLLA_REVISION,
        "horizon": HORIZON_REVISION,
        "skyline": SKYLINE_REVISION,
    }
    if any(sources.get(key) != value for key, value in expected_revisions.items()):
        raise EvidenceError("trial source revisions do not match the baseline")
    if not re.fullmatch(r"[0-9a-f]{64}", str(sources.get("ubuntu_sha256", ""))):
        raise EvidenceError("trial Ubuntu digest is invalid")
    artifacts = _object(manifest.get("artifacts"), "trial artifacts")
    expected_artifacts = {
        "horizon": {
            "name": "coffer-horizon",
            "version": "0.1.0",
            "sha256": sha256_file(horizon_wheel),
        },
        "skyline": {
            "name": "skyline-console",
            "version": "8.0.0+coffer.1",
            "sha256": sha256_file(skyline_wheel),
        },
        "target": {
            "key": target.key,
            "manifest_sha256": sha256_file(target_manifest_path),
            "probe": target.probe,
            "trial_label": target.trial_label,
            "finding_ids": list(target.finding_ids),
            "finding_ids_by_scanner": target.scanner_finding_ids,
            "surfaces": list(target.surfaces),
            "components": [
                _component_artifact(component)
                for component in target.components
            ],
        },
    }
    if artifacts != expected_artifacts:
        raise EvidenceError("trial artifacts do not match exact inputs")
    if any(
        component.wheel_architecture
        not in {"any", manifest["architecture"]}
        for component in target.components
    ):
        raise EvidenceError("target wheel architecture is incompatible")
    baseline = _object(manifest.get("baseline"), "trial baseline")
    if baseline != {
        "os_cleanup_result_sha256": sha256_file(baseline_result_path),
        "os_cleanup_inventories_sha256": sha256_file(
            baseline_inventories_path
        ),
        "remediation_result_sha256": sha256_file(remediation_result_path),
    }:
        raise EvidenceError("trial baseline hashes are inconsistent")
    images = _object(manifest.get("images"), "trial images")
    expected_keys = {
        f"{surface}-{kind}" for surface in target.surfaces for kind in KINDS
    }
    if set(images) != expected_keys:
        raise EvidenceError("trial manifest image set is invalid")
    if any(
        not DIGEST.fullmatch(str(_object(images[key], key).get("id", "")))
        for key in expected_keys
    ):
        raise EvidenceError("trial manifest image ID is invalid")
    return manifest


def validate_images(
    evidence: Path,
    manifest: dict[str, Any],
    *,
    target: Target,
) -> None:
    document = _load(evidence / "images.json", "trial image inspection")
    if document.get("schema") != IMAGE_SCHEMA:
        raise EvidenceError("trial image inspection schema is unsupported")
    images = _object(document.get("images"), "trial inspected images")
    if set(images) != set(manifest["images"]):
        raise EvidenceError("trial inspected image set is invalid")
    for surface in target.surfaces:
        before = _object(images[f"{surface}-before"], f"{surface} before image")
        after = _object(images[f"{surface}-after"], f"{surface} after image")
        for kind, image in (("before", before), ("after", after)):
            if image.get("id") != manifest["images"][f"{surface}-{kind}"]["id"]:
                raise EvidenceError(f"{surface} {kind} image ID is inconsistent")
            if (
                image.get("architecture") != manifest["architecture"]
                or image.get("os") != "linux"
            ):
                raise EvidenceError(f"{surface} {kind} platform is inconsistent")
        for field in ("user", "entrypoint", "cmd"):
            if after.get(field) != before.get(field):
                raise EvidenceError(f"{surface} overlay changed Kolla {field}")
        before_layers = _array(before.get("layers"), f"{surface} before layers")
        after_layers = _array(after.get("layers"), f"{surface} after layers")
        if (
            len(after_layers) <= len(before_layers)
            or after_layers[: len(before_layers)] != before_layers
        ):
            raise EvidenceError(f"{surface} overlay does not inherit exact input")
        labels = _object(after.get("labels"), f"{surface} after labels")
        expected_labels = {
            "io.coffer.ui.contract": "coffer-ui-image-v1",
            "io.coffer.ui.surface": surface,
            "io.coffer.ui.os-cleanup-trial": "coffer-ui-os-cleanup-v1",
            "io.coffer.ui.python-overlay-trial": target.trial_label,
            "org.opencontainers.image.revision": (
                HORIZON_REVISION if surface == "horizon" else SKYLINE_REVISION
            ),
        }
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            raise EvidenceError(f"{surface} overlay labels are invalid")


def _os_package_map(document: dict[str, Any], label: str) -> dict[str, str]:
    if document.get("schema") != PACKAGE_INVENTORY_SCHEMA:
        raise EvidenceError(f"{label} package inventory schema is unsupported")
    package_database = _object(
        document.get("package_database"),
        f"{label} package database",
    )
    if (
        package_database.get("dpkg_audit_clean") is not True
        or package_database.get("apt_dependency_check_clean") is not True
    ):
        raise EvidenceError(f"{label} package database is not clean")
    result: dict[str, str] = {}
    for value in _array(document.get("packages"), f"{label} packages"):
        package = _object(value, f"{label} package")
        name = str(package.get("name", ""))
        version = str(package.get("version", ""))
        if not name or not version or name in result:
            raise EvidenceError(f"{label} package identity is invalid")
        result[name] = version
    if not result:
        raise EvidenceError(f"{label} package inventory is empty")
    return result


def validate_os_inventories(
    evidence: Path,
    manifest: dict[str, Any],
    *,
    baseline_inventories_path: Path,
    target: Target,
) -> None:
    document = _load(evidence / "os-inventories.json", "trial OS inventories")
    if document.get("schema") != INVENTORY_SCHEMA:
        raise EvidenceError("trial OS inventory schema is unsupported")
    images = _object(document.get("images"), "trial OS inventory images")
    if set(images) != set(manifest["images"]):
        raise EvidenceError("trial OS inventory image set is invalid")
    baseline_document = _load(
        baseline_inventories_path,
        "OS cleanup baseline inventories",
    )
    baseline_images = _object(
        baseline_document.get("images"),
        "OS cleanup baseline images",
    )
    for surface in target.surfaces:
        before_document = _object(images[f"{surface}-before"], "before inventory")
        after_document = _object(images[f"{surface}-after"], "after inventory")
        for inventory in (before_document, after_document):
            if inventory.get("architecture") != manifest["architecture"]:
                raise EvidenceError(f"{surface} inventory architecture is invalid")
        before = _os_package_map(before_document, f"{surface} before")
        after = _os_package_map(after_document, f"{surface} after")
        if before != after:
            raise EvidenceError(f"{surface} overlay changed OS packages")
        if PURGED_PACKAGES & set(after):
            raise EvidenceError(f"{surface} overlay lost the OS cleanup baseline")
        baseline = _os_package_map(
            _object(
                baseline_images.get(f"{surface}-after"),
                f"{surface} OS cleanup baseline",
            ),
            f"{surface} OS cleanup baseline",
        )
        if before != baseline:
            raise EvidenceError(f"{surface} OS cleanup baseline drifted")


def _python_packages(
    document: dict[str, Any],
    label: str,
) -> dict[str, list[str]]:
    if document.get("schema") != PYTHON_RUNTIME_SCHEMA:
        raise EvidenceError(f"{label} Python runtime schema is unsupported")
    packages = _object(document.get("packages"), f"{label} Python packages")
    normalized: dict[str, list[str]] = {}
    for name, versions in packages.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(versions, list)
            or not versions
            or any(not isinstance(version, str) or not version for version in versions)
            or versions != sorted(versions)
        ):
            raise EvidenceError(f"{label} Python package inventory is invalid")
        normalized[name] = versions
    if not normalized:
        raise EvidenceError(f"{label} Python package inventory is invalid")
    return normalized


def validate_python_runtimes(
    document: dict[str, Any],
    *,
    manifest: dict[str, Any],
    target_wheels: tuple[Path, ...],
    target: Target,
) -> None:
    python = _object(document.get("python"), "trial Python runtimes")
    if set(python) != set(manifest["images"]):
        raise EvidenceError("trial Python runtime set is invalid")
    wheel_map = _target_wheel_map(target_wheels, target)
    expected_files = {
        component.normalized_name: _target_wheel_members(
            wheel_map[component.wheel_filename],
            component,
        )
        for component in target.components
    }
    expected_absent = [
        "/tmp/target-wheels",
        "/tmp/python_target.py",
        "/tmp/python_targets.json",
    ]
    for surface in target.surfaces:
        before_document = _object(
            python[f"{surface}-before"],
            f"{surface} before Python runtime",
        )
        after_document = _object(
            python[f"{surface}-after"],
            f"{surface} after Python runtime",
        )
        for kind, runtime in (
            ("before", before_document),
            ("after", after_document),
        ):
            if runtime.get("architecture") != manifest["architecture"]:
                raise EvidenceError(f"{surface} {kind} Python architecture is invalid")
            pip_check = _object(
                runtime.get("pip_check"),
                f"{surface} {kind} pip check",
            )
            if pip_check != {
                "clean": True,
                "message": "No broken requirements found.",
            }:
                raise EvidenceError(f"{surface} {kind} pip check failed")
            runtime_components = _array(
                runtime.get("components"),
                f"{surface} {kind} target components",
            )
            if len(runtime_components) != len(target.components):
                raise EvidenceError(
                    f"{surface} {kind} target component count is invalid"
                )
            for component, value in zip(
                target.components,
                runtime_components,
                strict=True,
            ):
                target_runtime = _object(
                    value,
                    f"{surface} {kind} target component",
                )
                expected_version = (
                    component.from_version
                    if kind == "before"
                    else component.to_version
                )
                if (
                    target_runtime.get("name")
                    != component.normalized_name
                    or target_runtime.get("version") != expected_version
                ):
                    raise EvidenceError(
                        f"{surface} {kind} target runtime is invalid"
                    )
            probe = _object(
                runtime.get("probe"),
                f"{surface} {kind} target probe",
            )
            if (
                probe.get("name") != target.probe
                or probe.get("mode")
                != ("baseline" if kind == "before" else "candidate")
                or probe.get("result") != target.expected_probe_result
                or runtime.get("absent") != expected_absent
            ):
                raise EvidenceError(f"{surface} {kind} target runtime is invalid")
        after_components = _array(
            after_document.get("components"),
            f"{surface} after target components",
        )
        for component, value in zip(
            target.components,
            after_components,
            strict=True,
        ):
            installed_files = _object(
                _object(value, "after target component").get("files"),
                f"{surface} installed target files",
            )
            installed_source = {
                name: digest
                for name, digest in installed_files.items()
                if "/__pycache__/" not in name
            }
            generated_files = set(installed_files) - set(installed_source)
            if (
                installed_source
                != expected_files[component.normalized_name]
                or any(
                    not re.fullmatch(
                        rf"{re.escape(component.package_prefix)}"
                        r"(?:[^/]+/)*__pycache__/[^/]+\.pyc",
                        name,
                    )
                    for name in generated_files
                )
            ):
                raise EvidenceError(
                    f"{surface} target wheel files are invalid"
                )
        before = _python_packages(before_document, f"{surface} before")
        after = _python_packages(after_document, f"{surface} after")
        changed = {
            name
            for name in set(before) & set(after)
            if before[name] != after[name]
        }
        if (
            set(before) != set(after)
            or changed
            != {
                component.normalized_name
                for component in target.components
            }
            or any(
                before.get(component.normalized_name)
                != [component.from_version]
                or after.get(component.normalized_name)
                != [component.to_version]
                for component in target.components
            )
        ):
            raise EvidenceError(f"{surface} Python package delta is not exact")


def validate_ui_runtimes(
    document: dict[str, Any],
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
    target: Target,
) -> None:
    ui = _object(document.get("ui"), "trial UI runtimes")
    if set(ui) != set(target.surfaces):
        raise EvidenceError("trial UI runtime set is invalid")
    wheels = {"horizon": horizon_wheel, "skyline": skyline_wheel}
    versions = {"horizon": "0.1.0", "skyline": "8.0.0+coffer.1"}
    names = {"horizon": "coffer-horizon", "skyline": "skyline-console"}
    absent = {"horizon": HORIZON_ABSENT, "skyline": SKYLINE_ABSENT}
    for surface in target.surfaces:
        runtime = _object(ui[surface], f"{surface} UI runtime")
        if runtime.get("package") != {
            "name": names[surface],
            "version": versions[surface],
        }:
            raise EvidenceError(f"{surface} UI package is invalid")
        if runtime.get("files") != _wheel_members(wheels[surface], surface):
            raise EvidenceError(f"{surface} UI runtime files are invalid")
        if tuple(runtime.get("absent") or ()) != absent[surface]:
            raise EvidenceError(f"{surface} UI runtime retained build input")


def validate_runtimes(
    evidence: Path,
    *,
    manifest: dict[str, Any],
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheels: tuple[Path, ...],
    target: Target,
) -> None:
    document = _load(evidence / "runtimes.json", "trial runtimes")
    if (
        document.get("schema") != RUNTIME_SCHEMA
        or document.get("architecture") != manifest["architecture"]
    ):
        raise EvidenceError("trial runtime identity is invalid")
    validate_python_runtimes(
        document,
        manifest=manifest,
        target_wheels=target_wheels,
        target=target,
    )
    validate_ui_runtimes(
        document,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        target=target,
    )


def _scanner_suffix(scanner: str) -> str:
    return "trivy.json" if scanner == "trivy" else "scout.sarif.json"


def scanner_result(
    evidence: Path,
    surface: str,
    scanner: str,
    *,
    target: Target,
) -> dict[str, Any]:
    qualification = _load_sibling("qualification")
    parser = (
        qualification.trivy_report
        if scanner == "trivy"
        else qualification.scout_report
    )
    before = parser(evidence / f"{surface}-before.{_scanner_suffix(scanner)}")
    after = parser(evidence / f"{surface}-after.{_scanner_suffix(scanner)}")
    introduced = after.critical_high - before.critical_high
    removed = before.critical_high - after.critical_high
    removed_ids = frozenset(item[0] for item in removed)
    after_ids = frozenset(item[0] for item in after.critical_high)
    if introduced:
        raise EvidenceError(f"{scanner} {surface} overlay introduced findings")
    target_findings = frozenset(target.finding_ids_for(scanner))
    if removed_ids != target_findings or target_findings & after_ids:
        raise EvidenceError(f"{scanner} {surface} target finding delta is invalid")
    if scanner == "trivy" and (before.secrets or after.secrets):
        raise EvidenceError(f"{surface} trial contains a Trivy secret")
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
    target: Target,
    target_manifest_path: Path,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheels: tuple[Path, ...],
) -> dict[str, Any]:
    validate_baselines(
        target=target,
        baseline_result_path=baseline_result_path,
        baseline_inventories_path=baseline_inventories_path,
        remediation_result_path=remediation_result_path,
    )
    manifest = validate_manifest(
        evidence,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        target_wheels=target_wheels,
        target_manifest_path=target_manifest_path,
        target=target,
        baseline_result_path=baseline_result_path,
        baseline_inventories_path=baseline_inventories_path,
        remediation_result_path=remediation_result_path,
    )
    validate_images(evidence, manifest, target=target)
    validate_os_inventories(
        evidence,
        manifest,
        baseline_inventories_path=baseline_inventories_path,
        target=target,
    )
    validate_runtimes(
        evidence,
        manifest=manifest,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        target_wheels=target_wheels,
        target=target,
    )
    surfaces: dict[str, Any] = {}
    blockers: list[str] = []
    for surface in target.surfaces:
        scanners = {
            scanner: scanner_result(
                evidence,
                surface,
                scanner,
                target=target,
            )
            for scanner in SCANNERS
        }
        for scanner, result in scanners.items():
            after = result["after"]
            if after["critical"] or after["high"]:
                blockers.append(
                    f"{scanner} {surface} overlay remains at "
                    f"{after['critical']} Critical/{after['high']} High"
                )
        surfaces[surface] = {"scanners": scanners}
    if not blockers:
        blockers.append(
            "unfixed oslo.messaging, native AMD64, and Stage 6 release gates "
            "remain independent"
        )
    return {
        "schema": RESULT_SCHEMA,
        "architecture": manifest["architecture"],
        "sources": manifest["sources"],
        "artifacts": manifest["artifacts"],
        "baseline": manifest["baseline"],
        "evidence": {
            f"{name}_sha256": sha256_file(evidence / f"{name}.json")
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
            "python_overlay_trial_accepted": True,
            "target": target.result_name,
            "production_containerfile_changed": False,
            "private_constraint_override_accepted": False,
            "waivers_applied": False,
            "blockers": blockers,
            "next_action": (
                "extend the compatibility matrix only to another independent "
                "constraint-bound Python candidate"
            ),
        },
    }


def write_result(path: Path, report: dict[str, Any]) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("trial output is not a regular file")
        if path.read_text(encoding="utf-8") != payload:
            raise EvidenceError("refusing to replace different trial evidence")
        path.chmod(0o640)
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            stream.write(payload)
            stream.flush()
            temporary = Path(stream.name)
        temporary.chmod(0o640)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


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
    parser.add_argument("--target", required=True)
    arguments = parser.parse_args()
    try:
        target = load_target(arguments.target_manifest, arguments.target)
        report = build_report(
            arguments.evidence,
            target=target,
            target_manifest_path=arguments.target_manifest,
            baseline_result_path=arguments.baseline_result,
            baseline_inventories_path=arguments.baseline_inventories,
            remediation_result_path=arguments.remediation_result,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
            target_wheels=tuple(arguments.target_wheel),
        )
        write_result(arguments.evidence / "python-trial.json", report)
    except (EvidenceError, TargetError) as error:
        print(f"coffer-ui-python-overlay-trial: {error}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
