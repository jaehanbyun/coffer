from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZipFile

MANIFEST_SCHEMA = "coffer.ui-python-overlay-evidence/v1"
IMAGE_SCHEMA = "coffer.ui-python-overlay-images/v1"
INVENTORY_SCHEMA = "coffer.ui-python-overlay-os-inventories/v1"
RUNTIME_SCHEMA = "coffer.ui-python-overlay-runtimes/v1"
PYTHON_RUNTIME_SCHEMA = "coffer.ui-python-overlay-runtime/v1"
PACKAGE_INVENTORY_SCHEMA = "coffer.ui-package-inventory/v1"
RESULT_SCHEMA = "coffer.ui-python-overlay-trial/v1"
OS_CLEANUP_RESULT_SCHEMA = "coffer.ui-os-cleanup-trial/v1"
REMEDIATION_SCHEMA = "coffer.ui-parent-remediation/v1"
KOLLA_REVISION = "686c6d13dc1c31092b22c6c481e16a7329e935ea"
HORIZON_REVISION = "0a4439556517cf67be0aa949b6551a14e409af75"
SKYLINE_REVISION = "c9000cb1be332a213009793598f17a80ce59671e"
TARGET_NAME = "mako"
TARGET_FROM_VERSION = "1.3.10"
TARGET_TO_VERSION = "1.3.12"
TARGET_WHEEL_NAME = "mako-1.3.12-py3-none-any.whl"
TARGET_WHEEL_SHA256 = (
    "8f61569480282dbf557145ce441e4ba888be453c30989f879f0d652e39f53ea9"
)
TARGET_FINDINGS = frozenset({"CVE-2026-41205", "CVE-2026-44307"})
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


def _target_wheel_members(path: Path) -> dict[str, str]:
    if path.name != TARGET_WHEEL_NAME or sha256_file(path) != TARGET_WHEEL_SHA256:
        raise EvidenceError("target wheel identity is invalid")
    try:
        with ZipFile(path) as archive:
            members = tuple(
                name
                for name in archive.namelist()
                if name.startswith("mako/") and not name.endswith("/")
            )
            if not members:
                raise EvidenceError("target wheel package is empty")
            return {
                member: hashlib.sha256(archive.read(member)).hexdigest()
                for member in members
            }
    except OSError as error:
        raise EvidenceError("target wheel is invalid") from error


def validate_baselines(
    *,
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
    for surface in SURFACES:
        packages = _array(
            _object(
                _object(remediation.get("surfaces"), "remediation surfaces").get(
                    surface
                ),
                f"{surface} remediation",
            ).get("packages"),
            f"{surface} remediation packages",
        )
        candidates = [
            _object(value, f"{surface} candidate")
            for value in packages
            if _object(value, f"{surface} package").get("package") == TARGET_NAME
        ]
        if len(candidates) != 1:
            raise EvidenceError(f"{surface} target candidate is ambiguous")
        candidate = candidates[0]
        if (
            candidate.get("classification")
            != "constraint-bound-all-findings-have-fix"
            or candidate.get("eligible_for_compatibility_trial") is not True
            or candidate.get("constraint_match") is not True
            or candidate.get("installed_version") != TARGET_FROM_VERSION
            or candidate.get("constraint_version") != TARGET_FROM_VERSION
            or TARGET_TO_VERSION
            not in _array(candidate.get("fixed_versions"), "target fixed versions")
            or frozenset(candidate.get("finding_ids") or ()) != TARGET_FINDINGS
        ):
            raise EvidenceError(f"{surface} target candidate is invalid")
    inventories = _load(baseline_inventories_path, "OS cleanup inventories")
    if inventories.get("schema") != "coffer.ui-os-cleanup-inventories/v1":
        raise EvidenceError("OS cleanup inventory schema is invalid")


def validate_manifest(
    evidence: Path,
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheel: Path,
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
) -> dict[str, Any]:
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
            "name": "Mako",
            "from_version": TARGET_FROM_VERSION,
            "to_version": TARGET_TO_VERSION,
            "filename": TARGET_WHEEL_NAME,
            "sha256": sha256_file(target_wheel),
        },
    }
    if artifacts != expected_artifacts:
        raise EvidenceError("trial artifacts do not match exact inputs")
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
        f"{surface}-{kind}" for surface in SURFACES for kind in KINDS
    }
    if set(images) != expected_keys:
        raise EvidenceError("trial manifest image set is invalid")
    if any(
        not DIGEST.fullmatch(str(_object(images[key], key).get("id", "")))
        for key in expected_keys
    ):
        raise EvidenceError("trial manifest image ID is invalid")
    return manifest


def validate_images(evidence: Path, manifest: dict[str, Any]) -> None:
    document = _load(evidence / "images.json", "trial image inspection")
    if document.get("schema") != IMAGE_SCHEMA:
        raise EvidenceError("trial image inspection schema is unsupported")
    images = _object(document.get("images"), "trial inspected images")
    if set(images) != set(manifest["images"]):
        raise EvidenceError("trial inspected image set is invalid")
    for surface in SURFACES:
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
            "io.coffer.ui.python-overlay-trial": "coffer-ui-mako-1.3.12-v1",
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
    for surface in SURFACES:
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
    target_wheel: Path,
) -> None:
    python = _object(document.get("python"), "trial Python runtimes")
    if set(python) != set(manifest["images"]):
        raise EvidenceError("trial Python runtime set is invalid")
    expected_files = _target_wheel_members(target_wheel)
    expected_absent = [f"/tmp/{TARGET_WHEEL_NAME}"]
    for surface in SURFACES:
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
            target = _object(
                runtime.get("target"),
                f"{surface} {kind} target runtime",
            )
            expected_version = (
                TARGET_FROM_VERSION if kind == "before" else TARGET_TO_VERSION
            )
            if (
                target.get("name") != TARGET_NAME
                or target.get("version") != expected_version
                or target.get("rendered") != "coffer"
                or runtime.get("absent") != expected_absent
            ):
                raise EvidenceError(f"{surface} {kind} target runtime is invalid")
        installed_files = _object(
            _object(after_document["target"], "after target").get("files"),
            f"{surface} installed target files",
        )
        installed_source = {
            name: digest
            for name, digest in installed_files.items()
            if "/__pycache__/" not in name
        }
        generated_files = set(installed_files) - set(installed_source)
        if (
            installed_source != expected_files
            or any(
                not re.fullmatch(
                    r"mako/(?:[^/]+/)*__pycache__/[^/]+\.pyc",
                    name,
                )
                for name in generated_files
            )
        ):
            raise EvidenceError(f"{surface} target wheel files are invalid")
        before = _python_packages(before_document, f"{surface} before")
        after = _python_packages(after_document, f"{surface} after")
        changed = {
            name
            for name in set(before) & set(after)
            if before[name] != after[name]
        }
        if (
            set(before) != set(after)
            or changed != {TARGET_NAME}
            or before.get(TARGET_NAME) != [TARGET_FROM_VERSION]
            or after.get(TARGET_NAME) != [TARGET_TO_VERSION]
        ):
            raise EvidenceError(f"{surface} Python package delta is not exact")


def validate_ui_runtimes(
    document: dict[str, Any],
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
) -> None:
    ui = _object(document.get("ui"), "trial UI runtimes")
    if set(ui) != set(SURFACES):
        raise EvidenceError("trial UI runtime set is invalid")
    wheels = {"horizon": horizon_wheel, "skyline": skyline_wheel}
    versions = {"horizon": "0.1.0", "skyline": "8.0.0+coffer.1"}
    names = {"horizon": "coffer-horizon", "skyline": "skyline-console"}
    absent = {"horizon": HORIZON_ABSENT, "skyline": SKYLINE_ABSENT}
    for surface in SURFACES:
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
    target_wheel: Path,
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
        target_wheel=target_wheel,
    )
    validate_ui_runtimes(
        document,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
    )


def _scanner_suffix(scanner: str) -> str:
    return "trivy.json" if scanner == "trivy" else "scout.sarif.json"


def scanner_result(evidence: Path, surface: str, scanner: str) -> dict[str, Any]:
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
    if removed_ids != TARGET_FINDINGS or TARGET_FINDINGS & after_ids:
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
    baseline_result_path: Path,
    baseline_inventories_path: Path,
    remediation_result_path: Path,
    horizon_wheel: Path,
    skyline_wheel: Path,
    target_wheel: Path,
) -> dict[str, Any]:
    validate_baselines(
        baseline_result_path=baseline_result_path,
        baseline_inventories_path=baseline_inventories_path,
        remediation_result_path=remediation_result_path,
    )
    manifest = validate_manifest(
        evidence,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        target_wheel=target_wheel,
        baseline_result_path=baseline_result_path,
        baseline_inventories_path=baseline_inventories_path,
        remediation_result_path=remediation_result_path,
    )
    validate_images(evidence, manifest)
    validate_os_inventories(
        evidence,
        manifest,
        baseline_inventories_path=baseline_inventories_path,
    )
    validate_runtimes(
        evidence,
        manifest=manifest,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
        target_wheel=target_wheel,
    )
    surfaces: dict[str, Any] = {}
    blockers: list[str] = []
    for surface in SURFACES:
        scanners = {
            scanner: scanner_result(evidence, surface, scanner)
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
            "target": f"Mako=={TARGET_TO_VERSION}",
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
    parser.add_argument("--target-wheel", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = build_report(
            arguments.evidence,
            baseline_result_path=arguments.baseline_result,
            baseline_inventories_path=arguments.baseline_inventories,
            remediation_result_path=arguments.remediation_result,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
            target_wheel=arguments.target_wheel,
        )
        write_result(arguments.evidence / "python-trial.json", report)
    except EvidenceError as error:
        print(f"coffer-ui-python-overlay-trial: {error}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
