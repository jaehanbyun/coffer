from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, NamedTuple
from zipfile import ZipFile

MANIFEST_SCHEMA = "coffer.ui-image-evidence/v1"
RUNTIME_SCHEMA = "coffer.ui-image-runtime/v1"
RESULT_SCHEMA = "coffer.ui-image-qualification/v1"
KOLLA_REVISION = "686c6d13dc1c31092b22c6c481e16a7329e935ea"
HORIZON_REVISION = "0a4439556517cf67be0aa949b6551a14e409af75"
SKYLINE_REVISION = "c9000cb1be332a213009793598f17a80ce59671e"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
IMAGE_KEYS = (
    "horizon-parent",
    "horizon-custom",
    "skyline-parent",
    "skyline-custom",
)
SURFACES = {
    "horizon": {
        "artifact_name": "coffer-horizon",
        "artifact_version": "0.1.0",
        "revision": HORIZON_REVISION,
        "required_members": (
            "cofferdashboard/enabled/_1910_project_registry_panel_group.py",
            "cofferdashboard/enabled/_1920_project_registry_repositories_panel.py",
            "cofferdashboard/local_settings.d/_1930_coffer_policy.py",
            "cofferdashboard/conf/coffer_policy.yaml",
        ),
        "absent": (
            "/tmp/coffer_horizon-0.1.0-py3-none-any.whl",
            "/tmp/install-coffer-horizon.py",
        ),
    },
    "skyline": {
        "artifact_name": "skyline-console",
        "artifact_version": "8.0.0+coffer.1",
        "revision": SKYLINE_REVISION,
        "required_member_prefix": "skyline_console/static/coffer.bundle.",
        "absent": (
            "/tmp/skyline_console-8.0.0+coffer.1-py3-none-any.whl",
        ),
    },
}


class EvidenceError(RuntimeError):
    pass


class FindingReport(NamedTuple):
    counts: dict[str, int]
    critical_high: frozenset[tuple[str, ...]]
    secrets: int = 0
    version: str = ""


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceError(f"{label} must be an array")
    return value


def _exact_keys(document: dict[str, Any], expected: set[str], label: str) -> None:
    if set(document) != expected:
        raise EvidenceError(f"{label} fields do not match the schema")


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


def _wheel_members(path: Path, surface: str) -> dict[str, str]:
    expected = SURFACES[surface]
    members: dict[str, str] = {}
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            required: tuple[str, ...]
            if surface == "horizon":
                required = expected["required_members"]
            else:
                prefix = str(expected["required_member_prefix"])
                required = tuple(
                    name
                    for name in names
                    if name.startswith(prefix) and name.endswith(".js")
                )
                if len(required) != 1:
                    raise EvidenceError(
                        "Skyline wheel must contain one Coffer production bundle"
                    )
            for member in required:
                info = archive.getinfo(member)
                if info.is_dir():
                    raise EvidenceError(f"wheel member is not a file: {member}")
                members[member] = hashlib.sha256(archive.read(member)).hexdigest()
    except (OSError, KeyError) as error:
        raise EvidenceError(f"required {surface} wheel member is missing") from error
    return members


def validate_manifest(
    evidence: Path,
    wheels: dict[str, Path],
) -> dict[str, Any]:
    manifest = _load(evidence / "manifest.json", "manifest")
    _exact_keys(
        manifest,
        {
            "schema",
            "architecture",
            "platform",
            "sources",
            "artifacts",
            "images",
            "scanners",
        },
        "manifest",
    )
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise EvidenceError("manifest schema is unsupported")
    architecture = str(manifest["architecture"])
    platform_by_arch = {"arm64": "linux/arm64", "amd64": "linux/amd64"}
    if architecture not in platform_by_arch:
        raise EvidenceError("manifest architecture is unsupported")
    if manifest["platform"] != platform_by_arch[architecture]:
        raise EvidenceError("manifest platform does not match architecture")

    sources = _object(manifest["sources"], "sources")
    _exact_keys(sources, {"kolla", "horizon", "skyline"}, "sources")
    expected_sources = {
        "kolla": KOLLA_REVISION,
        "horizon": HORIZON_REVISION,
        "skyline": SKYLINE_REVISION,
    }
    if sources != expected_sources:
        raise EvidenceError("source revisions do not match the accepted baseline")

    artifacts = _object(manifest["artifacts"], "artifacts")
    _exact_keys(artifacts, set(SURFACES), "artifacts")
    for surface, wheel in wheels.items():
        artifact = _object(artifacts[surface], f"{surface} artifact")
        _exact_keys(artifact, {"name", "version", "sha256"}, f"{surface} artifact")
        expected = SURFACES[surface]
        if (
            artifact["name"] != expected["artifact_name"]
            or artifact["version"] != expected["artifact_version"]
            or artifact["sha256"] != sha256_file(wheel)
        ):
            raise EvidenceError(f"{surface} artifact does not match the actual wheel")

    images = _object(manifest["images"], "images")
    _exact_keys(images, set(SURFACES), "images")
    for surface in SURFACES:
        pair = _object(images[surface], f"{surface} images")
        _exact_keys(pair, {"parent", "custom"}, f"{surface} images")
        for kind in ("parent", "custom"):
            image = _object(pair[kind], f"{surface} {kind} image")
            _exact_keys(image, {"name", "id"}, f"{surface} {kind} image")
            if not str(image["name"]).startswith("localhost/coffer-ui-"):
                raise EvidenceError("only bounded local UI image names are accepted")
            if not DIGEST.fullmatch(str(image["id"])):
                raise EvidenceError("image configuration digest is not immutable")
        if pair["parent"]["id"] == pair["custom"]["id"]:
            raise EvidenceError(f"{surface} parent and custom images are equal")

    scanners = _object(manifest["scanners"], "scanners")
    _exact_keys(scanners, {"docker_scout", "trivy"}, "scanners")
    if not all(isinstance(value, str) and value for value in scanners.values()):
        raise EvidenceError("scanner versions must be non-empty")
    return manifest


def validate_images(evidence: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    document = _load(evidence / "images.json", "image inspection")
    _exact_keys(document, {"schema", "images"}, "image inspection")
    if document["schema"] != "coffer.ui-image-inspection/v1":
        raise EvidenceError("image inspection schema is unsupported")
    images = _object(document["images"], "inspected images")
    _exact_keys(images, set(IMAGE_KEYS), "inspected images")
    architecture = manifest["architecture"]

    for surface in SURFACES:
        parent = _object(images[f"{surface}-parent"], f"{surface} parent inspection")
        custom = _object(images[f"{surface}-custom"], f"{surface} custom inspection")
        required = {
            "id",
            "architecture",
            "os",
            "user",
            "entrypoint",
            "cmd",
            "labels",
            "layers",
        }
        _exact_keys(parent, required, f"{surface} parent inspection")
        _exact_keys(custom, required, f"{surface} custom inspection")
        pair = manifest["images"][surface]
        if parent["id"] != pair["parent"]["id"] or custom["id"] != pair["custom"]["id"]:
            raise EvidenceError(f"{surface} image IDs do not match the manifest")
        for image in (parent, custom):
            if image["architecture"] != architecture or image["os"] != "linux":
                raise EvidenceError(f"{surface} image platform is inconsistent")
            if not isinstance(image["layers"], list) or not image["layers"]:
                raise EvidenceError(f"{surface} image layers are missing")
        for field in ("user", "entrypoint", "cmd"):
            if custom[field] != parent[field]:
                raise EvidenceError(f"{surface} custom image changed Kolla {field}")
        parent_layers = parent["layers"]
        custom_layers = custom["layers"]
        if (
            len(custom_layers) <= len(parent_layers)
            or custom_layers[: len(parent_layers)] != parent_layers
        ):
            raise EvidenceError(f"{surface} custom image does not inherit exact parent")
        labels = _object(custom["labels"], f"{surface} custom labels")
        expected_labels = {
            "io.coffer.ui.contract": "coffer-ui-image-v1",
            "io.coffer.ui.surface": surface,
            "org.opencontainers.image.revision": SURFACES[surface]["revision"],
        }
        if any(labels.get(key) != value for key, value in expected_labels.items()):
            raise EvidenceError(f"{surface} custom image labels are invalid")
    return document


def validate_runtime(
    evidence: Path,
    manifest: dict[str, Any],
    wheels: dict[str, Path],
) -> dict[str, Any]:
    runtime = _load(evidence / "runtime.json", "runtime evidence")
    _exact_keys(runtime, {"schema", "architecture", "surfaces"}, "runtime evidence")
    if runtime["schema"] != RUNTIME_SCHEMA:
        raise EvidenceError("runtime evidence schema is unsupported")
    if runtime["architecture"] != manifest["architecture"]:
        raise EvidenceError("runtime architecture does not match the manifest")
    surfaces = _object(runtime["surfaces"], "runtime surfaces")
    _exact_keys(surfaces, set(SURFACES), "runtime surfaces")
    for surface, wheel in wheels.items():
        result = _object(surfaces[surface], f"{surface} runtime")
        _exact_keys(result, {"package", "files", "absent"}, f"{surface} runtime")
        package = _object(result["package"], f"{surface} runtime package")
        _exact_keys(package, {"name", "version"}, f"{surface} runtime package")
        expected = SURFACES[surface]
        if (
            package["name"] != expected["artifact_name"]
            or package["version"] != expected["artifact_version"]
        ):
            raise EvidenceError(f"{surface} runtime package is invalid")
        files = _object(result["files"], f"{surface} runtime files")
        if files != _wheel_members(wheel, surface):
            raise EvidenceError(f"{surface} runtime files do not match the wheel")
        absent = _array(result["absent"], f"{surface} absent paths")
        if tuple(absent) != expected["absent"]:
            raise EvidenceError(f"{surface} build-input absence is not proven")
    return runtime


def spdx_package_count(path: Path) -> int:
    document = _load(path, path.name)
    if not str(document.get("spdxVersion", "")).startswith("SPDX-"):
        raise EvidenceError(f"SPDX metadata is missing from {path.name}")
    packages = _array(document.get("packages"), f"{path.name} packages")
    if not packages:
        raise EvidenceError(f"SPDX package inventory is empty in {path.name}")
    return len(packages)


def trivy_report(path: Path) -> FindingReport:
    document = _load(path, path.name)
    if document.get("SchemaVersion") != 2:
        raise EvidenceError(f"Trivy schema is invalid in {path.name}")
    results = _array(document.get("Results"), f"{path.name} results")
    counts: Counter[str] = Counter()
    findings: set[tuple[str, ...]] = set()
    secrets = 0
    for result in results:
        item = _object(result, f"{path.name} result")
        finding_class = str(item.get("Class", ""))
        finding_type = str(item.get("Type", ""))
        for finding in item.get("Vulnerabilities") or []:
            vulnerability = _object(finding, f"{path.name} vulnerability")
            severity = str(vulnerability.get("Severity", "UNKNOWN")).lower()
            counts[severity] += 1
            if severity in {"critical", "high"}:
                findings.add(
                    (
                        str(vulnerability.get("VulnerabilityID", "")),
                        str(vulnerability.get("PkgName", "")),
                        str(vulnerability.get("InstalledVersion", "")),
                        str(vulnerability.get("FixedVersion", "")),
                        finding_class,
                        finding_type,
                    )
                )
        secrets += len(item.get("Secrets") or [])
    return FindingReport(
        counts={
            severity: counts[severity]
            for severity in ("critical", "high", "medium", "low", "unknown")
        },
        critical_high=frozenset(findings),
        secrets=secrets,
        version=str(document.get("CreatedAt", "unknown")),
    )


def scout_report(path: Path) -> FindingReport:
    document = _load(path, path.name)
    if document.get("version") != "2.1.0":
        raise EvidenceError(f"Scout SARIF schema is invalid in {path.name}")
    runs = _array(document.get("runs"), f"{path.name} runs")
    if len(runs) != 1:
        raise EvidenceError(f"Scout SARIF run count is invalid in {path.name}")
    driver = _object(_object(runs[0], "Scout run").get("tool"), "Scout tool").get(
        "driver"
    )
    driver = _object(driver, "Scout driver")
    if str(driver.get("name", "")).lower() != "docker scout":
        raise EvidenceError(f"Scout driver is invalid in {path.name}")
    rules = _array(driver.get("rules"), f"{path.name} rules")
    counts: Counter[str] = Counter()
    findings: set[tuple[str, ...]] = set()
    for rule_value in rules:
        rule = _object(rule_value, f"{path.name} rule")
        properties = _object(rule.get("properties") or {}, f"{path.name} properties")
        severity = str(properties.get("cvssV3_severity", "")).lower()
        if not severity:
            tags = properties.get("tags") or []
            severity = str(tags[0]).lower() if tags else "unknown"
        counts[severity] += 1
        if severity in {"critical", "high"}:
            purls = tuple(sorted(str(value) for value in properties.get("purls") or []))
            findings.add(
                (
                    str(rule.get("id", "")),
                    *purls,
                    str(properties.get("affected_version", "")),
                    str(properties.get("fixed_version", "")),
                )
            )
    return FindingReport(
        counts={
            severity: counts[severity]
            for severity in ("critical", "high", "medium", "low", "unknown")
        },
        critical_high=frozenset(findings),
        version=str(driver.get("version", "")),
    )


def qualify(
    evidence: Path,
    *,
    horizon_wheel: Path,
    skyline_wheel: Path,
) -> dict[str, Any]:
    wheels = {"horizon": horizon_wheel, "skyline": skyline_wheel}
    manifest = validate_manifest(evidence, wheels)
    validate_images(evidence, manifest)
    validate_runtime(evidence, manifest, wheels)
    report: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "architecture": manifest["architecture"],
        "platform": manifest["platform"],
        "sources": manifest["sources"],
        "artifacts": manifest["artifacts"],
        "images": manifest["images"],
        "scanners": manifest["scanners"],
        "surfaces": {},
    }
    blockers: list[str] = []
    for surface in SURFACES:
        surface_result: dict[str, Any] = {"images": {}}
        reports: dict[str, dict[str, FindingReport]] = {"trivy": {}, "scout": {}}
        for kind in ("parent", "custom"):
            key = f"{surface}-{kind}"
            sbom = spdx_package_count(evidence / f"{key}.spdx.json")
            trivy = trivy_report(evidence / f"{key}.trivy.json")
            scout = scout_report(evidence / f"{key}.scout.sarif.json")
            reports["trivy"][kind] = trivy
            reports["scout"][kind] = scout
            surface_result["images"][kind] = {
                "sbom_packages": sbom,
                "trivy": trivy.counts,
                "scout": scout.counts,
                "secrets": trivy.secrets,
            }
            if trivy.secrets:
                blockers.append(f"{key} contains {trivy.secrets} Trivy secrets")
            for scanner, finding_report in (("trivy", trivy), ("scout", scout)):
                if finding_report.counts["critical"] or finding_report.counts["high"]:
                    blockers.append(
                        f"{scanner} {key} has "
                        f"{finding_report.counts['critical']} Critical/"
                        f"{finding_report.counts['high']} High"
                    )
        if (
            surface_result["images"]["custom"]["sbom_packages"]
            < surface_result["images"]["parent"]["sbom_packages"]
        ):
            blockers.append(f"{surface} custom SBOM lost parent packages")
        delta: dict[str, Any] = {}
        for scanner in ("trivy", "scout"):
            parent_findings = reports[scanner]["parent"].critical_high
            custom_findings = reports[scanner]["custom"].critical_high
            missing = parent_findings - custom_findings
            introduced = custom_findings - parent_findings
            delta[scanner] = {
                "introduced_critical_high": len(introduced),
                "missing_parent_critical_high": len(missing),
            }
            if missing:
                blockers.append(
                    f"{scanner} {surface} custom evidence lost "
                    f"{len(missing)} parent Critical/High findings"
                )
            if introduced:
                blockers.append(
                    f"{scanner} {surface} custom image introduced "
                    f"{len(introduced)} Critical/High findings"
                )
        surface_result["delta"] = delta
        report["surfaces"][surface] = surface_result
    report["status"] = "qualified" if not blockers else "blocked"
    report["production_candidate"] = not blockers
    report["blockers"] = blockers
    return report


def write_result(path: Path, report: dict[str, Any]) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("qualification output is not a regular file")
        if path.read_text(encoding="utf-8") != payload:
            raise EvidenceError("refusing to replace different qualification evidence")
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
    parser.add_argument("--horizon-wheel", type=Path, required=True)
    parser.add_argument("--skyline-wheel", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        report = qualify(
            arguments.evidence,
            horizon_wheel=arguments.horizon_wheel,
            skyline_wheel=arguments.skyline_wheel,
        )
        write_result(arguments.evidence / "qualification.json", report)
    except EvidenceError:
        print("coffer-ui-image-qualification: invalid evidence")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["production_candidate"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
