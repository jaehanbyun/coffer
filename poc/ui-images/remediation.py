from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import unquote

QUALIFICATION_SCHEMA = "coffer.ui-image-qualification/v1"
RESULT_SCHEMA = "coffer.ui-parent-remediation/v1"
REQUIREMENTS_BRANCH = "stable/2026.1"
REVISION = re.compile(r"^[0-9a-f]{40}$")
CONSTRAINT = re.compile(r"^([A-Za-z0-9_.-]+)={2,3}([^;#\s]+)")
SURFACES = ("horizon", "skyline")
SCANNERS = ("trivy", "scout")
SEVERITIES = ("critical", "high")
NO_FIX = frozenset({"", "n/a", "none", "not fixed", "unfixed", "unknown"})


class EvidenceError(RuntimeError):
    pass


class Finding(NamedTuple):
    scanner: str
    identifier: str
    severity: str
    ecosystem: str
    package: str
    installed_version: str
    fixed_version: str
    finding_class: str
    finding_type: str


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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise EvidenceError(f"artifact is missing or linked: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def normalize_fix(value: object) -> str:
    fixed = str(value or "").strip()
    return "" if fixed.lower() in NO_FIX else fixed


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise EvidenceError(f"{label} is empty")
    return text


def _trivy_ecosystem(finding_class: str, finding_type: str) -> str:
    if finding_type == "python-pkg":
        return "pypi"
    if finding_type == "node-pkg":
        return "npm"
    if finding_class == "os-pkgs" and finding_type == "ubuntu":
        return "deb"
    return finding_type or finding_class or "unknown"


def trivy_findings(path: Path) -> frozenset[Finding]:
    document = _load(path, path.name)
    if document.get("SchemaVersion") != 2:
        raise EvidenceError(f"Trivy schema is invalid in {path.name}")
    findings: set[Finding] = set()
    for result_value in _array(document.get("Results"), f"{path.name} results"):
        result = _object(result_value, f"{path.name} result")
        finding_class = str(result.get("Class", ""))
        finding_type = str(result.get("Type", ""))
        ecosystem = _trivy_ecosystem(finding_class, finding_type)
        for vulnerability_value in result.get("Vulnerabilities") or []:
            vulnerability = _object(
                vulnerability_value,
                f"{path.name} vulnerability",
            )
            severity = str(vulnerability.get("Severity", "")).lower()
            if severity not in SEVERITIES:
                continue
            findings.add(
                Finding(
                    scanner="trivy",
                    identifier=_required_text(
                        vulnerability.get("VulnerabilityID"),
                        f"{path.name} vulnerability ID",
                    ),
                    severity=severity,
                    ecosystem=ecosystem,
                    package=normalize_name(
                        _required_text(
                            vulnerability.get("PkgName"),
                            f"{path.name} package",
                        )
                    ),
                    installed_version=_required_text(
                        vulnerability.get("InstalledVersion"),
                        f"{path.name} installed version",
                    ),
                    fixed_version=normalize_fix(vulnerability.get("FixedVersion")),
                    finding_class=finding_class,
                    finding_type=finding_type,
                )
            )
    return frozenset(findings)


def parse_purl(value: object, label: str) -> tuple[str, str, str]:
    purl = _required_text(value, label)
    if not purl.startswith("pkg:") or "#" in purl:
        raise EvidenceError(f"{label} is not an accepted package URL")
    body = purl[4:].split("?", 1)[0]
    if "/" not in body:
        raise EvidenceError(f"{label} has no package name")
    ecosystem, package_version = body.split("/", 1)
    if "@" not in package_version:
        raise EvidenceError(f"{label} has no installed version")
    package_path, installed_version = package_version.rsplit("@", 1)
    package = package_path.rsplit("/", 1)[-1]
    if not ecosystem or not package or not installed_version:
        raise EvidenceError(f"{label} is incomplete")
    return (
        normalize_name(unquote(ecosystem)),
        normalize_name(unquote(package)),
        unquote(installed_version),
    )


def scout_findings(path: Path) -> frozenset[Finding]:
    document = _load(path, path.name)
    if document.get("version") != "2.1.0":
        raise EvidenceError(f"Scout SARIF schema is invalid in {path.name}")
    runs = _array(document.get("runs"), f"{path.name} runs")
    if len(runs) != 1:
        raise EvidenceError(f"Scout SARIF run count is invalid in {path.name}")
    driver = _object(
        _object(_object(runs[0], "Scout run").get("tool"), "Scout tool").get(
            "driver"
        ),
        "Scout driver",
    )
    if str(driver.get("name", "")).lower() != "docker scout":
        raise EvidenceError(f"Scout driver is invalid in {path.name}")
    findings: set[Finding] = set()
    for rule_value in _array(driver.get("rules"), f"{path.name} rules"):
        rule = _object(rule_value, f"{path.name} rule")
        properties = _object(rule.get("properties") or {}, f"{path.name} properties")
        severity = str(properties.get("cvssV3_severity", "")).lower()
        if severity not in SEVERITIES:
            continue
        purls = _array(properties.get("purls"), f"{path.name} purls")
        if not purls:
            raise EvidenceError(f"{path.name} Critical/High rule has no package URL")
        identifier = _required_text(rule.get("id"), f"{path.name} rule ID")
        fixed_version = normalize_fix(properties.get("fixed_version"))
        for index, purl in enumerate(purls):
            ecosystem, package, installed_version = parse_purl(
                purl,
                f"{path.name} purl {index}",
            )
            findings.add(
                Finding(
                    scanner="scout",
                    identifier=identifier,
                    severity=severity,
                    ecosystem=ecosystem,
                    package=package,
                    installed_version=installed_version,
                    fixed_version=fixed_version,
                    finding_class=str(rule.get("name", "")),
                    finding_type="sarif-rule",
                )
            )
    return frozenset(findings)


def read_constraints(archive_path: Path) -> tuple[str, bytes, dict[str, str]]:
    if not archive_path.is_file() or archive_path.is_symlink():
        raise EvidenceError("openstack-base archive is missing or linked")
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            candidates = [
                member
                for member in archive.getmembers()
                if member.isfile()
                and len(Path(member.name).parts) == 2
                and Path(member.name).name == "upper-constraints.txt"
            ]
            if len(candidates) != 1:
                raise EvidenceError(
                    "archive must contain one root upper-constraints member"
                )
            member = candidates[0]
            if member.size <= 0 or member.size > 5 * 1024 * 1024:
                raise EvidenceError("upper-constraints member size is invalid")
            stream = archive.extractfile(member)
            if stream is None:
                raise EvidenceError("upper-constraints member cannot be read")
            payload = stream.read()
    except (OSError, tarfile.TarError) as error:
        raise EvidenceError("openstack-base archive is invalid") from error
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError("upper constraints are not UTF-8") from error
    constraints: dict[str, str] = {}
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        match = CONSTRAINT.match(candidate)
        if match is None:
            continue
        name = normalize_name(match.group(1))
        version = match.group(2)
        previous = constraints.get(name)
        if previous is not None and previous != version:
            raise EvidenceError(f"conflicting upper constraint for {name}")
        constraints[name] = version
    if not constraints:
        raise EvidenceError("upper constraints contain no pinned packages")
    return member.name, payload, constraints


def _qualification_counts(
    qualification: dict[str, Any],
    surface: str,
    kind: str,
    scanner: str,
) -> tuple[int, int]:
    surfaces = _object(qualification.get("surfaces"), "qualification surfaces")
    surface_result = _object(surfaces.get(surface), f"{surface} qualification")
    images = _object(surface_result.get("images"), f"{surface} images")
    image = _object(images.get(kind), f"{surface} {kind} image")
    counts = _object(image.get(scanner), f"{surface} {kind} {scanner}")
    try:
        return int(counts["critical"]), int(counts["high"])
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceError("qualification Critical/High counts are invalid") from error


def _classification(
    ecosystem: str,
    constraint_match: bool,
    fixed_finding_ids: set[str],
    unfixed_finding_ids: set[str],
) -> str:
    has_fix = bool(fixed_finding_ids)
    has_unfixed = bool(unfixed_finding_ids)
    if ecosystem == "pypi" and constraint_match:
        if has_fix and not has_unfixed:
            return "constraint-bound-all-findings-have-fix"
        if has_fix:
            return "constraint-bound-partial-fix"
        return "constraint-bound-no-fixed-version"
    if ecosystem == "deb":
        if has_fix and not has_unfixed:
            return "os-all-findings-have-fix"
        if has_fix:
            return "os-partial-fix"
        return "os-no-fixed-version"
    if has_fix and not has_unfixed:
        return "unbound-all-findings-have-fix"
    if has_fix:
        return "unbound-partial-fix"
    return "unbound-no-fixed-version"


def _package_rows(
    findings: frozenset[Finding],
    constraints: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    grouped: dict[tuple[str, str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[
            (finding.ecosystem, finding.package, finding.installed_version)
        ].append(finding)
    rows: list[dict[str, Any]] = []
    classifications: Counter[str] = Counter()
    trial_candidates: list[str] = []
    for (ecosystem, package, installed_version), records in sorted(grouped.items()):
        constraint_version = constraints.get(package, "") if ecosystem == "pypi" else ""
        constraint_match = bool(
            constraint_version and constraint_version == installed_version
        )
        fixed_finding_ids = {
            finding.identifier for finding in records if finding.fixed_version
        }
        unfixed_finding_ids = {
            finding.identifier for finding in records if not finding.fixed_version
        }
        classification = _classification(
            ecosystem,
            constraint_match,
            fixed_finding_ids,
            unfixed_finding_ids,
        )
        classifications[classification] += 1
        eligible = classification == "constraint-bound-all-findings-have-fix"
        if eligible:
            trial_candidates.append(package)
        rows.append(
            {
                "ecosystem": ecosystem,
                "package": package,
                "installed_version": installed_version,
                "constraint_version": constraint_version or None,
                "constraint_match": constraint_match,
                "scanners": sorted({finding.scanner for finding in records}),
                "finding_ids": sorted({finding.identifier for finding in records}),
                "severity_counts": dict(
                    sorted(Counter(finding.severity for finding in records).items())
                ),
                "fixed_versions": sorted(
                    {
                        finding.fixed_version
                        for finding in records
                        if finding.fixed_version
                    }
                ),
                "unfixed_finding_ids": sorted(unfixed_finding_ids),
                "classification": classification,
                "eligible_for_compatibility_trial": eligible,
            }
        )
    return rows, dict(sorted(classifications.items())), sorted(trial_candidates)


def build_report(
    evidence: Path,
    *,
    openstack_base_archive: Path,
    requirements_revision: str,
) -> dict[str, Any]:
    if not REVISION.fullmatch(requirements_revision):
        raise EvidenceError("requirements revision must be a lowercase commit SHA")
    qualification_path = evidence / "qualification.json"
    qualification = _load(qualification_path, "qualification")
    if qualification.get("schema") != QUALIFICATION_SCHEMA:
        raise EvidenceError("qualification schema is unsupported")
    architecture = str(qualification.get("architecture", ""))
    if architecture not in {"arm64", "amd64"}:
        raise EvidenceError("qualification architecture is unsupported")
    member, constraints_payload, constraints = read_constraints(openstack_base_archive)
    surfaces: dict[str, Any] = {}
    total_findings = 0
    for surface in SURFACES:
        inherited: set[Finding] = set()
        scanner_counts: dict[str, dict[str, int]] = {}
        for scanner in SCANNERS:
            loader = trivy_findings if scanner == "trivy" else scout_findings
            parent = loader(evidence / f"{surface}-parent.{_suffix(scanner)}")
            custom = loader(evidence / f"{surface}-custom.{_suffix(scanner)}")
            if parent != custom:
                raise EvidenceError(
                    f"{scanner} {surface} parent/custom findings diverge"
                )
            counts = Counter(finding.severity for finding in parent)
            expected_parent = _qualification_counts(
                qualification,
                surface,
                "parent",
                scanner,
            )
            expected_custom = _qualification_counts(
                qualification,
                surface,
                "custom",
                scanner,
            )
            actual = (counts["critical"], counts["high"])
            if actual != expected_parent or actual != expected_custom:
                raise EvidenceError(
                    f"{scanner} {surface} counts do not match qualification"
                )
            scanner_counts[scanner] = {
                "critical": counts["critical"],
                "high": counts["high"],
            }
            inherited.update(parent)
        rows, classifications, trial_candidates = _package_rows(
            frozenset(inherited),
            constraints,
        )
        total_findings += len(inherited)
        surfaces[surface] = {
            "inherited_critical_high": scanner_counts,
            "packages": rows,
            "package_classifications": classifications,
            "compatibility_trial_candidates": trial_candidates,
        }
    status = "blocked" if total_findings else "clean"
    if status == "blocked" and (
        qualification.get("status") != "blocked"
        or qualification.get("production_candidate") is not False
    ):
        raise EvidenceError("qualification does not preserve the inherited block")
    return {
        "schema": RESULT_SCHEMA,
        "architecture": architecture,
        "requirements": {
            "branch": REQUIREMENTS_BRANCH,
            "revision": requirements_revision,
            "constraints_member": member,
            "constraints_sha256": sha256_bytes(constraints_payload),
        },
        "evidence": {
            "qualification_sha256": sha256_file(qualification_path),
        },
        "surfaces": surfaces,
        "decision": {
            "status": status,
            "production_candidate": False,
            "waivers_applied": False,
            "private_constraint_override_accepted": False,
            "os_cleanup_accepted": False,
            "blockers": (
                [
                    "inherited Critical/High findings remain under the "
                    "accepted absolute two-scanner gate",
                    "native AMD64 Scout CVE evidence remains incomplete",
                    "Distribution and Ceph stable-release gates remain blocked",
                ]
                if total_findings
                else [
                    "native AMD64 and Stage 6 release gates remain independent"
                ]
            ),
            "next_experiments": [
                "prove package dependency and runtime safety before OS cleanup",
                "test only constraint-bound fixed-version candidates against "
                "Horizon and Skyline build/runtime contracts",
                "rescan viable derivatives with both accepted scanners",
            ],
        },
    }


def _suffix(scanner: str) -> str:
    return "trivy.json" if scanner == "trivy" else "scout.sarif.json"


def write_result(path: Path, report: dict[str, Any]) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("remediation output is not a regular file")
        if path.read_text(encoding="utf-8") != payload:
            raise EvidenceError("refusing to replace different remediation evidence")
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
    parser.add_argument("--openstack-base-archive", type=Path, required=True)
    parser.add_argument("--requirements-revision", required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    output = arguments.output or arguments.evidence / "remediation.json"
    try:
        report = build_report(
            arguments.evidence,
            openstack_base_archive=arguments.openstack_base_archive,
            requirements_revision=arguments.requirements_revision,
        )
        write_result(output, report)
    except EvidenceError:
        print("coffer-ui-parent-remediation: invalid evidence")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 3 if report["decision"]["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
