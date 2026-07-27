from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from residual_finding import (
    SourceArtifact,
    VendorSource,
    load_contract,
)

SCHEMA = "coffer.ui-vendor-source-evidence/v1"
DSC_SOURCE = re.compile(r"^Source: ([A-Za-z0-9._+-]+)$", re.MULTILINE)
DSC_VERSION = re.compile(r"^Version: ([A-Za-z0-9.+:~-]+)$", re.MULTILINE)
DSC_CHECKSUMS = re.compile(
    r"^ ([0-9a-f]{64}) ([0-9]+) ([A-Za-z0-9._+-]+)$",
    re.MULTILINE,
)
DSC_CHECKSUM_BLOCK = re.compile(
    r"^Checksums-Sha256:\n"
    r"((?: [0-9a-f]{64} [0-9]+ [A-Za-z0-9._+-]+\n)+)",
    re.MULTILINE,
)
MAX_DOWNLOAD = 8 * 1024 * 1024


class SourceCollectionError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise SourceCollectionError("residual manifest is missing or linked")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SourceCollectionError("residual manifest is unreadable") from error
    return digest.hexdigest()


def download_artifact(artifact: SourceArtifact) -> bytes:
    request = urllib.request.Request(
        artifact.url,
        headers={"User-Agent": "coffer-ui-source-evidence/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200 or response.geturl() != artifact.url:
                raise SourceCollectionError("vendor source download is not exact")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD or size > artifact.size:
                    raise SourceCollectionError("vendor source download is oversized")
                chunks.append(chunk)
    except (OSError, urllib.error.URLError) as error:
        raise SourceCollectionError("vendor source download failed") from error
    value = b"".join(chunks)
    verify_artifact(artifact, value)
    return value


def verify_artifact(artifact: SourceArtifact, value: bytes) -> None:
    if len(value) != artifact.size or sha256_bytes(value) != artifact.sha256:
        raise SourceCollectionError("vendor source artifact does not match")


def dsc_projection(source: VendorSource, value: bytes) -> dict[str, Any]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceCollectionError("vendor dsc is not UTF-8") from error
    if (
        not text.startswith("-----BEGIN PGP SIGNED MESSAGE-----\n")
        or "-----BEGIN PGP SIGNATURE-----\n" not in text
        or not text.endswith("-----END PGP SIGNATURE-----\n")
    ):
        raise SourceCollectionError("vendor dsc signature envelope is invalid")
    source_match = DSC_SOURCE.search(text)
    version_match = DSC_VERSION.search(text)
    if (
        source_match is None
        or source_match.group(1) != source.package
        or version_match is None
        or version_match.group(1) != source.version
    ):
        raise SourceCollectionError("vendor dsc identity is invalid")
    checksum_block = DSC_CHECKSUM_BLOCK.search(text)
    if checksum_block is None:
        raise SourceCollectionError("vendor dsc checksums are not exact")
    checksums = {
        filename: {
            "sha256": sha256,
            "size": int(size),
        }
        for sha256, size, filename in DSC_CHECKSUMS.findall(checksum_block.group(1))
    }
    expected = {
        artifact.filename: {
            "sha256": artifact.sha256,
            "size": artifact.size,
        }
        for artifact in source.artifacts
        if not artifact.filename.endswith(".dsc")
    }
    if checksums != expected:
        raise SourceCollectionError("vendor dsc checksums are not exact")
    return {
        "clear_signed": True,
        "source": source.package,
        "version": source.version,
        "checksums_sha256": checksums,
    }


def _safe_member_name(name: str) -> str:
    normalized = name.removeprefix("./")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or str(path) != normalized
    ):
        raise SourceCollectionError("vendor source archive path is unsafe")
    return normalized


def archive_files(value: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(value), mode="r:xz") as archive:
            for member in archive.getmembers():
                name = _safe_member_name(member.name)
                if member.isdir():
                    continue
                if not member.isfile() or member.size > MAX_DOWNLOAD:
                    raise SourceCollectionError(
                        "vendor source archive member is unsafe"
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise SourceCollectionError(
                        "vendor source archive member is unreadable"
                    )
                result[name] = stream.read(MAX_DOWNLOAD + 1)
                if len(result[name]) != member.size:
                    raise SourceCollectionError(
                        "vendor source archive member is truncated"
                    )
    except (tarfile.TarError, OSError) as error:
        raise SourceCollectionError("vendor source archive is invalid") from error
    return result


def patch_projection(
    source: VendorSource,
    archive: dict[str, bytes],
) -> tuple[list[dict[str, str]], str]:
    series_path = "debian/patches/series"
    try:
        series = archive[series_path]
    except KeyError as error:
        raise SourceCollectionError("vendor patch series is missing") from error
    if sha256_bytes(series) != source.series_sha256:
        raise SourceCollectionError("vendor patch series does not match")
    try:
        series_entries = tuple(
            line.strip()
            for line in series.decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    except UnicodeDecodeError as error:
        raise SourceCollectionError("vendor patch series is not UTF-8") from error
    expected_entries = tuple(patch.filename for patch in source.patches)
    positions: list[int] = []
    for filename in expected_entries:
        try:
            positions.append(series_entries.index(filename))
        except ValueError as error:
            raise SourceCollectionError(
                "vendor source patch is absent from series"
            ) from error
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise SourceCollectionError("vendor source patch series order is invalid")
    result: list[dict[str, str]] = []
    for patch in source.patches:
        path = f"debian/patches/{patch.filename}"
        try:
            content = archive[path]
        except KeyError as error:
            raise SourceCollectionError("vendor source patch is missing") from error
        if sha256_bytes(content) != patch.sha256:
            raise SourceCollectionError("vendor source patch does not match")
        result.append(
            {
                "filename": patch.filename,
                "finding_id": patch.finding_id,
                "sha256": patch.sha256,
            }
        )
    return result, source.series_sha256


def collect(
    *,
    source: VendorSource,
    manifest_sha256: str,
    fetch: Callable[[SourceArtifact], bytes] = download_artifact,
) -> dict[str, Any]:
    blobs: dict[str, bytes] = {}
    artifacts: list[dict[str, Any]] = []
    for artifact in source.artifacts:
        value = fetch(artifact)
        verify_artifact(artifact, value)
        blobs[artifact.filename] = value
        artifacts.append(
            {
                "filename": artifact.filename,
                "sha256": artifact.sha256,
                "size": artifact.size,
                "url": artifact.url,
            }
        )
    dsc_name = f"{source.package}_{source.version}.dsc"
    archive_name = f"{source.package}_{source.version}.debian.tar.xz"
    try:
        dsc = dsc_projection(source, blobs[dsc_name])
        patches, series_sha256 = patch_projection(
            source,
            archive_files(blobs[archive_name]),
        )
    except KeyError as error:
        raise SourceCollectionError(
            "vendor source artifact set is incomplete"
        ) from error
    return {
        "artifacts": artifacts,
        "decision": {
            "source_backports_verified": True,
            "vex_generation_allowed": False,
            "next_action": (
                "prove the installed system package behavior on both exact "
                "cumulative UI derivatives before generating OpenVEX"
            ),
        },
        "dsc": dsc,
        "manifest_sha256": manifest_sha256,
        "patches": patches,
        "schema": SCHEMA,
        "series_sha256": series_sha256,
        "source": {
            "package": source.package,
            "version": source.version,
        },
    }


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise SourceCollectionError("refusing existing source evidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.chmod(0o640)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    contract = load_contract(arguments.manifest)
    result = collect(
        source=contract.vendor_source,
        manifest_sha256=sha256_file(arguments.manifest),
    )
    atomic_json(arguments.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
