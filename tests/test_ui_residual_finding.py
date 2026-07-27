from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
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
MODULE = load("residual_finding", HARNESS / "residual_finding.py")
COLLECTOR = load(
    "coffer_ui_collect_residual_source",
    HARNESS / "collect_residual_source.py",
)


def write_manifest(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "residual_findings.json"
    path.write_text(json.dumps(document))
    return path


def source_fixture():
    patches = {
        "CVE-2024-6345.patch": b"subprocess.check_call([vcs, 'clone'])\n",
        "CVE-2025-47273-pre1.patch": b"def _resolve_download_filename():\n",
        "CVE-2025-47273.patch": b"raise ValueError('Invalid filename')\n",
    }
    series = (
        b"base.patch\n"
        b"CVE-2024-6345.patch\n"
        b"CVE-2025-47273-pre1.patch\n"
        b"CVE-2025-47273.patch\n"
    )
    archive_stream = io.BytesIO()
    with tarfile.open(fileobj=archive_stream, mode="w:xz") as archive:
        for name, value in {
            "debian/patches/series": series,
            **{f"debian/patches/{name}": value for name, value in patches.items()},
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    archive_value = archive_stream.getvalue()
    original_value = b"fixture upstream source\n"
    archive_name = "setuptools_68.1.2-2ubuntu1.2.debian.tar.xz"
    original_name = "setuptools_68.1.2.orig.tar.gz"
    dsc_value = (
        "-----BEGIN PGP SIGNED MESSAGE-----\n"
        "Hash: SHA512\n\n"
        "Source: setuptools\n"
        "Version: 68.1.2-2ubuntu1.2\n"
        "Checksums-Sha256:\n"
        f" {COLLECTOR.sha256_bytes(original_value)} {len(original_value)}"
        f" {original_name}\n"
        f" {COLLECTOR.sha256_bytes(archive_value)} {len(archive_value)}"
        f" {archive_name}\n"
        "-----BEGIN PGP SIGNATURE-----\n"
        "fixture\n"
        "-----END PGP SIGNATURE-----\n"
    ).encode()
    dsc_name = "setuptools_68.1.2-2ubuntu1.2.dsc"
    blobs = {
        archive_name: archive_value,
        dsc_name: dsc_value,
        original_name: original_value,
    }
    artifacts = tuple(
        MODULE.SourceArtifact(
            filename=name,
            url=f"https://security.ubuntu.com/ubuntu/pool/main/s/setuptools/{name}",
            sha256=COLLECTOR.sha256_bytes(value),
            size=len(value),
        )
        for name, value in sorted(blobs.items())
    )
    source_patches = tuple(
        MODULE.SourcePatch(
            filename=name,
            finding_id=(
                "CVE-2024-6345" if name == "CVE-2024-6345.patch" else "CVE-2025-47273"
            ),
            sha256=COLLECTOR.sha256_bytes(value),
        )
        for name, value in sorted(patches.items())
    )
    source = MODULE.VendorSource(
        package="setuptools",
        version="68.1.2-2ubuntu1.2",
        artifacts=artifacts,
        patches=source_patches,
        series_sha256=COLLECTOR.sha256_bytes(series),
    )
    return source, blobs


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
    assert contract.vendor_source.package == "setuptools"
    assert contract.vendor_source.version == "68.1.2-2ubuntu1.2"
    assert len(contract.vendor_source.artifacts) == 3
    assert len(contract.vendor_source.patches) == 3
    assert (
        contract.vendor_source.artifact(
            "setuptools_68.1.2-2ubuntu1.2.debian.tar.xz"
        ).sha256
        == "535a05c43a79ba7519c1a791ba5ef75350d8e48c5b4bb8ddb7c626733a3f36b5"
    )


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
        ("source-package", "vendor source"),
        ("source-version", "vendor source"),
        ("source-field", "vendor source"),
        ("artifact-field", "artifact"),
        ("artifact-order", "artifact set"),
        ("artifact-missing", "artifact set"),
        ("artifact-name", "artifact"),
        ("artifact-url", "URL"),
        ("artifact-version", "version"),
        ("artifact-hash", "artifact"),
        ("artifact-size", "artifact"),
        ("patch-field", "patch"),
        ("patch-order", "patch set"),
        ("patch-missing", "patch set"),
        ("patch-name", "patch"),
        ("patch-finding", "patch set"),
        ("patch-hash", "patch"),
        ("series-hash", "vendor source"),
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
    vendor_source = document["vendor_source"]
    artifacts = vendor_source["artifacts"]
    patches = vendor_source["patches"]
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
    elif mutation == "source-package":
        vendor_source["package"] = "unknown"
    elif mutation == "source-version":
        vendor_source["version"] = "latest"
    elif mutation == "source-field":
        vendor_source["mutable"] = True
    elif mutation == "artifact-field":
        artifacts[0]["mutable"] = True
    elif mutation == "artifact-order":
        artifacts.reverse()
    elif mutation == "artifact-missing":
        artifacts.pop()
    elif mutation == "artifact-name":
        artifacts[0]["filename"] = "../source.tar.xz"
    elif mutation == "artifact-url":
        artifacts[0]["url"] = "https://example.invalid/source.tar.xz"
    elif mutation == "artifact-version":
        artifacts[0]["filename"] = "setuptools_1.0.debian.tar.xz"
        artifacts[0]["url"] = (
            "https://security.ubuntu.com/ubuntu/pool/main/s/setuptools/setuptools_1.0.debian.tar.xz"
        )
    elif mutation == "artifact-hash":
        artifacts[0]["sha256"] = "0"
    elif mutation == "artifact-size":
        artifacts[0]["size"] = 0
    elif mutation == "patch-field":
        patches[0]["mutable"] = True
    elif mutation == "patch-order":
        patches.reverse()
    elif mutation == "patch-missing":
        patches.pop()
    elif mutation == "patch-name":
        patches[0]["filename"] = "../patch"
    elif mutation == "patch-finding":
        patches[0]["finding_id"] = "CVE-2026-44393"
    elif mutation == "patch-hash":
        patches[0]["sha256"] = "0"
    elif mutation == "series-hash":
        vendor_source["series_sha256"] = "0"

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
    with pytest.raises(MODULE.ResidualError, match="artifact is unsupported"):
        contract.vendor_source.artifact("unknown")


def test_source_collector_proves_exact_signed_bundle() -> None:
    source, blobs = source_fixture()

    result = COLLECTOR.collect(
        source=source,
        manifest_sha256="a" * 64,
        fetch=lambda artifact: blobs[artifact.filename],
    )

    assert result["schema"] == "coffer.ui-vendor-source-evidence/v1"
    assert result["source"] == {
        "package": "setuptools",
        "version": "68.1.2-2ubuntu1.2",
    }
    assert result["dsc"]["clear_signed"] is True
    assert len(result["artifacts"]) == 3
    assert [patch["finding_id"] for patch in result["patches"]] == [
        "CVE-2024-6345",
        "CVE-2025-47273",
        "CVE-2025-47273",
    ]
    assert result["decision"] == {
        "source_backports_verified": True,
        "vex_generation_allowed": False,
        "next_action": (
            "prove the installed system package behavior on both exact "
            "cumulative UI derivatives before generating OpenVEX"
        ),
    }


def test_source_collector_rejects_artifact_drift() -> None:
    source, blobs = source_fixture()
    archive = source.artifacts[0]

    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="does not match",
    ):
        COLLECTOR.verify_artifact(archive, blobs[archive.filename] + b"drift")


def test_source_collector_rejects_dsc_checksum_drift() -> None:
    source, blobs = source_fixture()
    dsc_name = "setuptools_68.1.2-2ubuntu1.2.dsc"
    drifted = blobs[dsc_name].replace(b"Checksums-Sha256:", b"Other-Checksums:")

    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="checksums are not exact",
    ):
        COLLECTOR.dsc_projection(source, drifted)


def test_source_collector_rejects_unsafe_archive_member() -> None:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:xz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="path is unsafe",
    ):
        COLLECTOR.archive_files(stream.getvalue())


def test_source_collector_rejects_missing_or_changed_patch() -> None:
    source, blobs = source_fixture()
    archive_name = "setuptools_68.1.2-2ubuntu1.2.debian.tar.xz"
    files = COLLECTOR.archive_files(blobs[archive_name])
    files.pop("debian/patches/CVE-2024-6345.patch")
    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="patch is missing",
    ):
        COLLECTOR.patch_projection(source, files)

    files = COLLECTOR.archive_files(blobs[archive_name])
    files["debian/patches/CVE-2024-6345.patch"] += b"drift"
    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="patch does not match",
    ):
        COLLECTOR.patch_projection(source, files)


def test_source_collector_writes_exclusive_owner_readable_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "evidence" / "source.json"
    COLLECTOR.atomic_json(output, {"schema": "fixture"})

    assert output.stat().st_mode & 0o777 == 0o640
    assert output.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="refusing existing",
    ):
        COLLECTOR.atomic_json(output, {"schema": "fixture"})


def test_source_collector_refuses_linked_manifest(tmp_path: Path) -> None:
    linked = tmp_path / "manifest.json"
    linked.symlink_to(MANIFEST)
    with pytest.raises(
        COLLECTOR.SourceCollectionError,
        match="missing or linked",
    ):
        COLLECTOR.sha256_file(linked)
