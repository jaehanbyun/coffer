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

MANIFEST_SCHEMA = "coffer.ui-os-cleanup-evidence/v1"
IMAGE_SCHEMA = "coffer.ui-os-cleanup-images/v1"
INVENTORY_SCHEMA = "coffer.ui-os-cleanup-inventories/v1"
RUNTIME_SCHEMA = "coffer.ui-os-cleanup-runtime/v1"
RESULT_SCHEMA = "coffer.ui-os-cleanup-trial/v1"
PACKAGE_INVENTORY_SCHEMA = "coffer.ui-package-inventory/v1"
PROBE_SUMMARY_SCHEMA = "coffer.ui-parent-package-probe-summary/v1"
KOLLA_REVISION = "686c6d13dc1c31092b22c6c481e16a7329e935ea"
HORIZON_REVISION = "0a4439556517cf67be0aa949b6551a14e409af75"
SKYLINE_REVISION = "c9000cb1be332a213009793598f17a80ce59671e"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SURFACES = ("horizon", "skyline")
KINDS = ("before", "after")
SCANNERS = ("trivy", "scout")
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


def _package_map(inventory: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    if inventory.get("schema") != PACKAGE_INVENTORY_SCHEMA:
        raise EvidenceError(f"{label} package inventory schema is unsupported")
    package_database = _object(
        inventory.get("package_database"),
        f"{label} package database",
    )
    if (
        package_database.get("dpkg_audit_clean") is not True
        or package_database.get("apt_dependency_check_clean") is not True
    ):
        raise EvidenceError(f"{label} package database is not clean")
    packages: dict[str, dict[str, Any]] = {}
    for value in _array(inventory.get("packages"), f"{label} packages"):
        package = _object(value, f"{label} package")
        name = str(package.get("name", ""))
        version = str(package.get("version", ""))
        if not name or not version or name in packages:
            raise EvidenceError(f"{label} package identity is invalid")
        packages[name] = package
    if not packages:
        raise EvidenceError(f"{label} package inventory is empty")
    return packages


def validate_manifest(
    evidence: Path,
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
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
        "horizon": ("coffer-horizon", "0.1.0", horizon_wheel),
        "skyline": ("skyline-console", "8.0.0+coffer.1", skyline_wheel),
    }
    for surface, (name, version, wheel) in expected_artifacts.items():
        artifact = _object(artifacts.get(surface), f"{surface} artifact")
        if artifact != {
            "name": name,
            "version": version,
            "sha256": sha256_file(wheel),
        }:
            raise EvidenceError(f"{surface} artifact does not match the wheel")
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


def validate_images(evidence: Path, manifest: dict[str, Any]) -> dict[str, Any]:
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
                raise EvidenceError(f"{surface} cleanup changed Kolla {field}")
        before_layers = _array(before.get("layers"), f"{surface} before layers")
        after_layers = _array(after.get("layers"), f"{surface} after layers")
        if (
            len(after_layers) <= len(before_layers)
            or after_layers[: len(before_layers)] != before_layers
        ):
            raise EvidenceError(f"{surface} cleanup does not inherit exact input")
        labels = _object(after.get("labels"), f"{surface} after labels")
        expected_labels = {
            "io.coffer.ui.contract": "coffer-ui-image-v1",
            "io.coffer.ui.surface": surface,
            "io.coffer.ui.os-cleanup-trial": "coffer-ui-os-cleanup-v1",
            "org.opencontainers.image.revision": (
                HORIZON_REVISION if surface == "horizon" else SKYLINE_REVISION
            ),
        }
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            raise EvidenceError(f"{surface} cleanup labels are invalid")
    return document


def validate_inventories(
    evidence: Path,
    manifest: dict[str, Any],
    probe_summary: dict[str, Any],
) -> dict[str, Any]:
    document = _load(evidence / "inventories.json", "trial inventories")
    if document.get("schema") != INVENTORY_SCHEMA:
        raise EvidenceError("trial inventory schema is unsupported")
    images = _object(document.get("images"), "trial inventory images")
    if set(images) != set(manifest["images"]):
        raise EvidenceError("trial inventory image set is invalid")
    expected_removed = {
        str(item["name"]): str(item["installed_version"])
        for item in _array(
            _object(
                probe_summary.get("purge_simulation"),
                "probe purge simulation",
            ).get("removed"),
            "probe removed packages",
        )
    }
    if not expected_removed or "linux-libc-dev" not in expected_removed:
        raise EvidenceError("probe purge set is invalid")
    for surface in SURFACES:
        before_document = _object(images[f"{surface}-before"], "before inventory")
        after_document = _object(images[f"{surface}-after"], "after inventory")
        for inventory in (before_document, after_document):
            if inventory.get("architecture") != manifest["architecture"]:
                raise EvidenceError(f"{surface} inventory architecture is invalid")
        before = _package_map(before_document, f"{surface} before")
        after = _package_map(after_document, f"{surface} after")
        added = set(after) - set(before)
        changed = {
            name
            for name in set(before) & set(after)
            if before[name].get("version") != after[name].get("version")
        }
        removed = {
            name: str(before[name].get("version", ""))
            for name in set(before) - set(after)
        }
        if added or changed or removed != expected_removed:
            raise EvidenceError(f"{surface} cleanup package delta is not exact")
    return document


def validate_runtime(
    evidence: Path,
    manifest: dict[str, Any],
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
) -> dict[str, Any]:
    document = _load(evidence / "runtime.json", "trial runtime")
    if (
        document.get("schema") != RUNTIME_SCHEMA
        or document.get("architecture") != manifest["architecture"]
    ):
        raise EvidenceError("trial runtime identity is invalid")
    surfaces = _object(document.get("surfaces"), "trial runtime surfaces")
    if set(surfaces) != set(SURFACES):
        raise EvidenceError("trial runtime surface set is invalid")
    wheels = {"horizon": horizon_wheel, "skyline": skyline_wheel}
    versions = {"horizon": "0.1.0", "skyline": "8.0.0+coffer.1"}
    names = {"horizon": "coffer-horizon", "skyline": "skyline-console"}
    absent = {"horizon": HORIZON_ABSENT, "skyline": SKYLINE_ABSENT}
    for surface in SURFACES:
        runtime = _object(surfaces[surface], f"{surface} cleanup runtime")
        if runtime.get("package") != {
            "name": names[surface],
            "version": versions[surface],
        }:
            raise EvidenceError(f"{surface} cleanup package is invalid")
        if runtime.get("files") != _wheel_members(wheels[surface], surface):
            raise EvidenceError(f"{surface} cleanup runtime files are invalid")
        if tuple(runtime.get("absent") or ()) != absent[surface]:
            raise EvidenceError(f"{surface} cleanup retained build input")
    return document


def scanner_result(evidence: Path, surface: str, scanner: str) -> dict[str, Any]:
    qualification = _load_sibling("qualification")
    before_path = evidence / f"{surface}-before.{_scanner_suffix(scanner)}"
    after_path = evidence / f"{surface}-after.{_scanner_suffix(scanner)}"
    parser = (
        qualification.trivy_report
        if scanner == "trivy"
        else qualification.scout_report
    )
    before = parser(before_path)
    after = parser(after_path)
    introduced = after.critical_high - before.critical_high
    removed = before.critical_high - after.critical_high
    if introduced:
        raise EvidenceError(f"{scanner} {surface} cleanup introduced findings")
    if not removed:
        raise EvidenceError(f"{scanner} {surface} cleanup removed no findings")
    if scanner == "trivy" and (before.secrets or after.secrets):
        raise EvidenceError(f"{surface} trial contains a Trivy secret")
    return {
        "before": before.counts,
        "after": after.counts,
        "removed_critical_high": len(removed),
        "introduced_critical_high": 0,
        "after_secrets": after.secrets,
    }


def _scanner_suffix(scanner: str) -> str:
    return "trivy.json" if scanner == "trivy" else "scout.sarif.json"


def build_report(
    evidence: Path,
    *,
    probe_summary_path: Path,
    horizon_wheel: Path,
    skyline_wheel: Path,
) -> dict[str, Any]:
    probe_summary = _load(probe_summary_path, "stock-parent probe summary")
    if (
        probe_summary.get("schema") != PROBE_SUMMARY_SCHEMA
        or _object(probe_summary.get("decision"), "probe decision").get(
            "safe_to_apply"
        )
        is not False
    ):
        raise EvidenceError("stock-parent probe summary is invalid")
    manifest = validate_manifest(
        evidence,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
    )
    validate_images(evidence, manifest)
    validate_inventories(evidence, manifest, probe_summary)
    validate_runtime(
        evidence,
        manifest,
        horizon_wheel=horizon_wheel,
        skyline_wheel=skyline_wheel,
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
                    f"{scanner} {surface} cleanup remains at "
                    f"{after['critical']} Critical/{after['high']} High"
                )
        surfaces[surface] = {"scanners": scanners}
    if not blockers:
        blockers.append(
            "native AMD64 and Stage 6 release gates remain independent"
        )
    return {
        "schema": RESULT_SCHEMA,
        "architecture": manifest["architecture"],
        "sources": manifest["sources"],
        "artifacts": manifest["artifacts"],
        "evidence": {
            "probe_summary_sha256": sha256_file(probe_summary_path),
            **{
                f"{name}_sha256": sha256_file(evidence / f"{name}.json")
                for name in (
                    "manifest",
                    "images",
                    "inventories",
                    "runtime",
                )
            },
        },
        "surfaces": surfaces,
        "decision": {
            "status": "blocked",
            "production_candidate": False,
            "os_cleanup_trial_accepted": True,
            "production_containerfile_changed": False,
            "private_constraint_override_accepted": False,
            "waivers_applied": False,
            "blockers": blockers,
            "next_action": (
                "evaluate the smallest constraint-bound Python compatibility "
                "set while preserving the absolute scanner gate"
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
    parser.add_argument("--probe-summary", type=Path, required=True)
    parser.add_argument("--horizon-wheel", type=Path, required=True)
    parser.add_argument("--skyline-wheel", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = build_report(
            arguments.evidence,
            probe_summary_path=arguments.probe_summary,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
        )
        write_result(arguments.evidence / "cleanup-trial.json", report)
    except EvidenceError:
        print("coffer-ui-os-cleanup-trial: invalid evidence")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
