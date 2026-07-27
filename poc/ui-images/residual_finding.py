from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from python_target import DIGEST, FINDING, SCANNERS, SURFACES

SCHEMA = "coffer.ui-residual-findings/v1"
KEY = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
VERSION = re.compile(r"^[0-9][A-Za-z0-9.+:~-]{0,63}$")
PURL = re.compile(r"^pkg:pypi/[A-Za-z0-9._-]+@[0-9][A-Za-z0-9.+!-]{0,31}$")
SOURCE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
DISPOSITIONS = frozenset(
    {
        "affected-no-fixed-release",
        "vendor-backport-to-prove",
    }
)
SOURCE_HOSTS = frozenset(
    {
        "review.opendev.org",
        "ubuntu.com",
    }
)
SCOUT_SUFFIX = ".scout.sarif.json"
TRIVY_SUFFIX = ".trivy.json"


class ResidualError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceSource:
    surface: str
    scanner: str
    path: str
    sha256: str


@dataclass(frozen=True)
class VendorEvidence:
    finding_id: str
    fixed_package_version: str
    source: str


@dataclass(frozen=True)
class SourceArtifact:
    filename: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class SourcePatch:
    filename: str
    finding_id: str
    sha256: str


@dataclass(frozen=True)
class VendorSource:
    package: str
    version: str
    artifacts: tuple[SourceArtifact, ...]
    patches: tuple[SourcePatch, ...]
    series_sha256: str

    def artifact(self, filename: str) -> SourceArtifact:
        try:
            return {artifact.filename: artifact for artifact in self.artifacts}[
                filename
            ]
        except KeyError as error:
            raise ResidualError("vendor source artifact is unsupported") from error


@dataclass(frozen=True)
class ResidualPackage:
    key: str
    package_name: str
    installed_version: str
    installed_path: str
    purl: str
    surfaces: tuple[str, ...]
    disposition: str
    findings_by_scanner: tuple[tuple[str, tuple[str, ...]], ...]
    vendor_evidence: tuple[VendorEvidence, ...]

    def finding_ids_for(self, scanner: str) -> tuple[str, ...]:
        try:
            return dict(self.findings_by_scanner)[scanner]
        except KeyError as error:
            raise ResidualError("residual scanner is unsupported") from error

    @property
    def finding_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    finding
                    for _, findings in self.findings_by_scanner
                    for finding in findings
                }
            )
        )


@dataclass(frozen=True)
class ResidualContract:
    result_sha256: str
    sources: tuple[EvidenceSource, ...]
    packages: tuple[ResidualPackage, ...]
    vendor_source: VendorSource

    def package(self, key: str) -> ResidualPackage:
        try:
            return {package.key: package for package in self.packages}[key]
        except KeyError as error:
            raise ResidualError("residual package is unsupported") from error

    def source(self, surface: str, scanner: str) -> EvidenceSource:
        try:
            return {
                (source.surface, source.scanner): source for source in self.sources
            }[(surface, scanner)]
        except KeyError as error:
            raise ResidualError("residual evidence source is unsupported") from error

    def finding_ids_for(self, surface: str, scanner: str) -> tuple[str, ...]:
        if surface not in SURFACES or scanner not in SCANNERS:
            raise ResidualError("residual projection is unsupported")
        return tuple(
            sorted(
                {
                    finding
                    for package in self.packages
                    if surface in package.surfaces
                    for finding in package.finding_ids_for(scanner)
                }
            )
        )


def _relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResidualError(f"residual {field} is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
        or str(path) != value
    ):
        raise ResidualError(f"residual {field} is invalid")
    return value


def _source_url(value: object) -> str:
    if not isinstance(value, str):
        raise ResidualError("residual vendor source is invalid")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in SOURCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ResidualError("residual vendor source is invalid")
    return value


def _evidence_source(value: object) -> EvidenceSource:
    if not isinstance(value, dict) or set(value) != {
        "surface",
        "scanner",
        "path",
        "sha256",
    }:
        raise ResidualError("residual evidence source is invalid")
    surface = value.get("surface")
    scanner = value.get("scanner")
    sha256 = value.get("sha256")
    if (
        surface not in SURFACES
        or scanner not in SCANNERS
        or not isinstance(sha256, str)
        or not DIGEST.fullmatch(sha256)
    ):
        raise ResidualError("residual evidence source is invalid")
    path = _relative_path(value.get("path"), field="evidence path")
    suffix = SCOUT_SUFFIX if scanner == "scout" else TRIVY_SUFFIX
    expected = (
        f"work/ui-python-overlay-trial-matrix-accepted/evidence/{surface}-after{suffix}"
    )
    if path != expected:
        raise ResidualError("residual evidence path is not exact")
    return EvidenceSource(
        surface=surface,
        scanner=scanner,
        path=path,
        sha256=sha256,
    )


def _scanner_findings(
    value: object,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, dict) or set(value) != set(SCANNERS):
        raise ResidualError("residual scanner findings are invalid")
    result: list[tuple[str, tuple[str, ...]]] = []
    union: set[str] = set()
    for scanner in SCANNERS:
        findings = value[scanner]
        if (
            not isinstance(findings, list)
            or any(
                not isinstance(finding, str) or not FINDING.fullmatch(finding)
                for finding in findings
            )
            or findings != sorted(set(findings))
        ):
            raise ResidualError("residual scanner findings are invalid")
        union.update(findings)
        result.append((scanner, tuple(findings)))
    if not union:
        raise ResidualError("residual scanner findings are empty")
    return tuple(result)


def _vendor_evidence(value: object) -> tuple[VendorEvidence, ...]:
    if not isinstance(value, list) or not value:
        raise ResidualError("residual vendor evidence is invalid")
    result: list[VendorEvidence] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "finding_id",
            "fixed_package_version",
            "source",
        }:
            raise ResidualError("residual vendor evidence is invalid")
        finding_id = raw.get("finding_id")
        fixed_version = raw.get("fixed_package_version")
        if (
            not isinstance(finding_id, str)
            or not FINDING.fullmatch(finding_id)
            or not isinstance(fixed_version, str)
            or (
                fixed_version != "none-published"
                and not VERSION.fullmatch(fixed_version)
            )
        ):
            raise ResidualError("residual vendor evidence is invalid")
        result.append(
            VendorEvidence(
                finding_id=finding_id,
                fixed_package_version=fixed_version,
                source=_source_url(raw.get("source")),
            )
        )
    if [item.finding_id for item in result] != sorted(
        {item.finding_id for item in result}
    ):
        raise ResidualError("residual vendor evidence is unsorted")
    return tuple(result)


def _source_artifact(value: object, package: str, version: str) -> SourceArtifact:
    if not isinstance(value, dict) or set(value) != {
        "filename",
        "url",
        "sha256",
        "size",
    }:
        raise ResidualError("vendor source artifact is invalid")
    filename = value.get("filename")
    url = value.get("url")
    sha256 = value.get("sha256")
    size = value.get("size")
    if (
        not isinstance(filename, str)
        or not SOURCE_FILENAME.fullmatch(filename)
        or not isinstance(url, str)
        or not isinstance(sha256, str)
        or not DIGEST.fullmatch(sha256)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 1
        or size > 8 * 1024 * 1024
    ):
        raise ResidualError("vendor source artifact is invalid")
    expected_url = (
        f"https://security.ubuntu.com/ubuntu/pool/main/s/{package}/{filename}"
    )
    if url != expected_url:
        raise ResidualError("vendor source artifact URL is not exact")
    if version not in filename and ".orig.tar." not in filename:
        raise ResidualError("vendor source artifact version is not exact")
    return SourceArtifact(
        filename=filename,
        url=url,
        sha256=sha256,
        size=size,
    )


def _source_patch(value: object) -> SourcePatch:
    if not isinstance(value, dict) or set(value) != {
        "filename",
        "finding_id",
        "sha256",
    }:
        raise ResidualError("vendor source patch is invalid")
    filename = value.get("filename")
    finding_id = value.get("finding_id")
    sha256 = value.get("sha256")
    if (
        not isinstance(filename, str)
        or not SOURCE_FILENAME.fullmatch(filename)
        or not filename.endswith(".patch")
        or not isinstance(finding_id, str)
        or not FINDING.fullmatch(finding_id)
        or not isinstance(sha256, str)
        or not DIGEST.fullmatch(sha256)
    ):
        raise ResidualError("vendor source patch is invalid")
    return SourcePatch(
        filename=filename,
        finding_id=finding_id,
        sha256=sha256,
    )


def _vendor_source(value: object) -> VendorSource:
    if not isinstance(value, dict) or set(value) != {
        "package",
        "version",
        "artifacts",
        "patches",
        "series_sha256",
    }:
        raise ResidualError("vendor source is invalid")
    package = value.get("package")
    version = value.get("version")
    raw_artifacts = value.get("artifacts")
    raw_patches = value.get("patches")
    series_sha256 = value.get("series_sha256")
    if (
        package != "setuptools"
        or version != "68.1.2-2ubuntu1.2"
        or not isinstance(raw_artifacts, list)
        or not isinstance(raw_patches, list)
        or not isinstance(series_sha256, str)
        or not DIGEST.fullmatch(series_sha256)
    ):
        raise ResidualError("vendor source is invalid")
    artifacts = tuple(
        _source_artifact(item, package, version) for item in raw_artifacts
    )
    if tuple(item.filename for item in artifacts) != tuple(
        sorted({item.filename for item in artifacts})
    ) or {item.filename for item in artifacts} != {
        "setuptools_68.1.2-2ubuntu1.2.debian.tar.xz",
        "setuptools_68.1.2-2ubuntu1.2.dsc",
        "setuptools_68.1.2.orig.tar.gz",
    }:
        raise ResidualError("vendor source artifact set is not exact")
    patches = tuple(_source_patch(item) for item in raw_patches)
    if tuple(item.filename for item in patches) != tuple(
        sorted({item.filename for item in patches})
    ) or tuple(item.finding_id for item in patches) != (
        "CVE-2024-6345",
        "CVE-2025-47273",
        "CVE-2025-47273",
    ):
        raise ResidualError("vendor source patch set is not exact")
    return VendorSource(
        package=package,
        version=version,
        artifacts=artifacts,
        patches=patches,
        series_sha256=series_sha256,
    )


def _package(key: str, value: object) -> ResidualPackage:
    if (
        not KEY.fullmatch(key)
        or not isinstance(value, dict)
        or set(value)
        != {
            "package_name",
            "installed_version",
            "installed_path",
            "purl",
            "surfaces",
            "disposition",
            "findings_by_scanner",
            "vendor_evidence",
        }
    ):
        raise ResidualError("residual package is invalid")
    package_name = value.get("package_name")
    installed_version = value.get("installed_version")
    purl = value.get("purl")
    surfaces = value.get("surfaces")
    disposition = value.get("disposition")
    if (
        not isinstance(package_name, str)
        or not PACKAGE.fullmatch(package_name)
        or not isinstance(installed_version, str)
        or not VERSION.fullmatch(installed_version)
        or not isinstance(purl, str)
        or not PURL.fullmatch(purl)
        or not isinstance(surfaces, list)
        or surfaces != sorted(SURFACES)
        or disposition not in DISPOSITIONS
    ):
        raise ResidualError("residual package value is invalid")
    findings = _scanner_findings(value.get("findings_by_scanner"))
    vendor = _vendor_evidence(value.get("vendor_evidence"))
    all_findings = tuple(
        sorted(
            {
                finding
                for _, scanner_findings in findings
                for finding in scanner_findings
            }
        )
    )
    if tuple(item.finding_id for item in vendor) != all_findings:
        raise ResidualError("residual vendor evidence is not exact")
    if disposition == "affected-no-fixed-release" and any(
        item.fixed_package_version != "none-published" for item in vendor
    ):
        raise ResidualError("residual affected disposition is invalid")
    if disposition == "vendor-backport-to-prove" and any(
        item.fixed_package_version == "none-published" for item in vendor
    ):
        raise ResidualError("residual backport disposition is invalid")
    return ResidualPackage(
        key=key,
        package_name=package_name,
        installed_version=installed_version,
        installed_path=_relative_path(
            value.get("installed_path"),
            field="installed path",
        ),
        purl=purl,
        surfaces=tuple(surfaces),
        disposition=disposition,
        findings_by_scanner=findings,
        vendor_evidence=vendor,
    )


def load_contract(path: Path) -> ResidualContract:
    if not path.is_file() or path.is_symlink():
        raise ResidualError("residual manifest is missing or linked")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResidualError("residual manifest is unreadable") from error
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "baseline", "packages", "vendor_source"}
        or document.get("schema") != SCHEMA
    ):
        raise ResidualError("residual manifest schema is unsupported")
    baseline = document.get("baseline")
    if not isinstance(baseline, dict) or set(baseline) != {
        "result_sha256",
        "sources",
    }:
        raise ResidualError("residual baseline is invalid")
    result_sha256 = baseline.get("result_sha256")
    raw_sources = baseline.get("sources")
    if (
        not isinstance(result_sha256, str)
        or not DIGEST.fullmatch(result_sha256)
        or not isinstance(raw_sources, list)
    ):
        raise ResidualError("residual baseline is invalid")
    sources = tuple(_evidence_source(source) for source in raw_sources)
    source_keys = tuple((source.surface, source.scanner) for source in sources)
    expected_source_keys = tuple(
        (surface, scanner)
        for surface in sorted(SURFACES)
        for scanner in sorted(SCANNERS)
    )
    if source_keys != expected_source_keys:
        raise ResidualError("residual evidence source set is not exact")
    raw_packages = document.get("packages")
    if not isinstance(raw_packages, dict) or not raw_packages:
        raise ResidualError("residual packages are invalid")
    if list(raw_packages) != sorted(raw_packages):
        raise ResidualError("residual packages are unsorted")
    packages = tuple(_package(key, value) for key, value in raw_packages.items())
    finding_owners: dict[str, str] = {}
    for package in packages:
        for finding in package.finding_ids:
            if finding in finding_owners:
                raise ResidualError("residual findings overlap packages")
            finding_owners[finding] = package.key
    contract = ResidualContract(
        result_sha256=result_sha256,
        sources=sources,
        packages=packages,
        vendor_source=_vendor_source(document.get("vendor_source")),
    )
    if any(
        not contract.finding_ids_for(surface, scanner)
        for surface in sorted(SURFACES)
        for scanner in SCANNERS
    ):
        raise ResidualError("residual surface projection is empty")
    return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args()
    contract = load_contract(arguments.manifest)
    print(
        json.dumps(
            {
                "result_sha256": contract.result_sha256,
                "packages": [package.key for package in contract.packages],
                "vendor_source": {
                    "package": contract.vendor_source.package,
                    "version": contract.vendor_source.version,
                },
                "projections": {
                    surface: {
                        scanner: list(contract.finding_ids_for(surface, scanner))
                        for scanner in SCANNERS
                    }
                    for surface in sorted(SURFACES)
                },
                "schema": SCHEMA,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
