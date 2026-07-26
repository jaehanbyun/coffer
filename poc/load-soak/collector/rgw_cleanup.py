from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Protocol, Sequence


DIRECTORY = Path(__file__).resolve().parent
ROOT_DIRECTORY = DIRECTORY.parents[2]


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


rgw_live_adapter = _module(
    "coffer_stage6_rgw_cleanup_live_adapter",
    DIRECTORY / "rgw_live_adapter.py",
)
control_artifacts = rgw_live_adapter.control_artifacts
native_target = rgw_live_adapter.native_target

RESULT_SCHEMA = "coffer.load-rgw-prefix-cleanup-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-rgw-prefix-cleanup-source-result/v1"
MAX_DELETE_BATCH = 1000
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "rgw_cleanup.py",
)


class RgwCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CleanupInventory:
    current_keys: tuple[str, ...]
    delete_markers: tuple[tuple[str, str], ...]
    multipart_uploads: tuple[tuple[str, str], ...]
    page_sha256: tuple[str, ...]
    versions: tuple[tuple[str, str], ...]


class CleanupClient(Protocol):
    def scan(
        self,
        *,
        max_pages: int,
        prefix: str,
    ) -> CleanupInventory: ...

    def remove(self, inventory: CleanupInventory) -> None: ...


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise RgwCleanupError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def cleanup_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": str(path.relative_to(ROOT_DIRECTORY)),
                    "sha256": _payload_hash(path.read_bytes()),
                }
            )
    except OSError as error:
        raise RgwCleanupError("RGW cleanup source is unavailable") from error
    return _hash({"files": files})


def _key(value: object, prefix: str, category: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.startswith(f"{prefix}/")
        or len(value) > 1024
        or "\x00" in value
    ):
        raise RgwCleanupError(f"{category} escaped the probe prefix")
    return value


def _identity(
    value: object,
    prefix: str,
    category: str,
) -> tuple[str, str]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not isinstance(value[1], str)
        or not value[1]
        or len(value[1]) > 4096
        or "\x00" in value[1]
    ):
        raise RgwCleanupError(f"{category} is invalid")
    return _key(value[0], prefix, category), value[1]


def _inventory(
    value: object,
    *,
    prefix: str,
    max_pages: int,
) -> CleanupInventory:
    if not isinstance(value, CleanupInventory):
        raise RgwCleanupError("RGW cleanup inventory changed")
    current = tuple(
        _key(key, prefix, "RGW current object")
        for key in value.current_keys
    )
    versions = tuple(
        _identity(item, prefix, "RGW object version")
        for item in value.versions
    )
    markers = tuple(
        _identity(item, prefix, "RGW delete marker")
        for item in value.delete_markers
    )
    uploads = tuple(
        _identity(item, prefix, "RGW multipart upload")
        for item in value.multipart_uploads
    )
    pages = tuple(
        rgw_live_adapter._sha256(page, "RGW cleanup page hash")
        for page in value.page_sha256
    )
    if (
        len(pages) < 3
        or len(pages) > max_pages * 3
        or len(set(pages)) != len(pages)
        or len(set(current)) != len(current)
        or len(set(versions)) != len(versions)
        or len(set(markers)) != len(markers)
        or len(set(uploads)) != len(uploads)
        or any(
            len(items)
            > rgw_live_adapter.rgw_artifacts.phase_evidence.MAX_COUNT
            for items in (current, versions, markers, uploads)
        )
    ):
        raise RgwCleanupError("RGW cleanup inventory is incomplete")
    return CleanupInventory(
        current_keys=current,
        delete_markers=markers,
        multipart_uploads=uploads,
        page_sha256=pages,
        versions=versions,
    )


def _counts(inventory: CleanupInventory) -> dict[str, int]:
    return {
        "current_objects": len(inventory.current_keys),
        "delete_markers": len(inventory.delete_markers),
        "multipart_uploads": len(inventory.multipart_uploads),
        "versions": len(inventory.versions),
    }


def cleanup(
    config_value: object,
    *,
    client: CleanupClient,
    clock: rgw_live_adapter.Clock = time.time,
) -> dict[str, Any]:
    try:
        config = rgw_live_adapter._config(config_value)
    except rgw_live_adapter.RgwLiveAdapterError as error:
        raise RgwCleanupError("RGW cleanup configuration changed") from error
    started = rgw_live_adapter._number(
        clock(),
        "RGW cleanup start",
    )
    try:
        before = _inventory(
            client.scan(
                max_pages=config["max_pages"],
                prefix=config["probe_prefix"],
            ),
            prefix=config["probe_prefix"],
            max_pages=config["max_pages"],
        )
        client.remove(before)
        after = _inventory(
            client.scan(
                max_pages=config["max_pages"],
                prefix=config["probe_prefix"],
            ),
            prefix=config["probe_prefix"],
            max_pages=config["max_pages"],
        )
    except RgwCleanupError:
        raise
    except Exception as error:
        raise RgwCleanupError("RGW cleanup client failed") from error
    completed = rgw_live_adapter._number(
        clock(),
        "RGW cleanup completion",
    )
    rgw_live_adapter._inside_window(config, started, completed)
    remaining = _counts(after)
    if any(remaining.values()):
        raise RgwCleanupError("RGW probe prefix cleanup is incomplete")
    unsigned = {
        "bucket_scope_sha256": config["bucket_scope_sha256"],
        "cleanup_source_sha256": cleanup_source_sha256(),
        "completed_at_seconds": completed,
        "execution_source": "pilot",
        "observed_before": _counts(before),
        "page_set_sha256": _hash(
            {
                "after": list(after.page_sha256),
                "before": list(before.page_sha256),
            }
        ),
        "phase": config["phase"],
        "remaining": remaining,
        "rgw_config_sha256": config["rgw_config_sha256"],
        "schema": RESULT_SCHEMA,
        "started_at_seconds": started,
        "synthetic": False,
        "target_sha256": config["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "cleanup_sha256": _hash(unsigned)}


def _page_hash(
    *,
    kind: str,
    identities: Sequence[str],
    truncated: bool,
    cursor: str,
) -> str:
    return _hash(
        {
            "cursor_sha256": _payload_hash(cursor.encode("utf-8")),
            "identities_sha256": sorted(identities),
            "kind": kind,
            "truncated": truncated,
        }
    )


@dataclass(frozen=True)
class Boto3CleanupClient:
    client: Any
    bucket: str

    def _current(
        self,
        *,
        max_pages: int,
        prefix: str,
    ) -> tuple[list[str], list[str]]:
        keys: list[str] = []
        pages: list[str] = []
        token: str | None = None
        seen: set[str] = set()
        while True:
            if len(pages) >= max_pages:
                raise RgwCleanupError(
                    "RGW current-object pagination exceeded"
                )
            arguments: dict[str, Any] = {
                "Bucket": self.bucket,
                "MaxKeys": 1000,
                "Prefix": f"{prefix}/",
            }
            if token is not None:
                arguments["ContinuationToken"] = token
            response = self.client.list_objects_v2(**arguments)
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise RgwCleanupError("RGW current-object page changed")
            page_keys: list[str] = []
            for item in contents:
                if not isinstance(item, Mapping):
                    raise RgwCleanupError(
                        "RGW current-object page changed"
                    )
                key = _key(item.get("Key"), prefix, "RGW current object")
                page_keys.append(key)
                keys.append(key)
            truncated = response.get("IsTruncated") is True
            next_token = response.get("NextContinuationToken", "")
            pages.append(
                _page_hash(
                    kind="current",
                    identities=[_hash({"key": key}) for key in page_keys],
                    truncated=truncated,
                    cursor=str(next_token),
                )
            )
            if not truncated:
                break
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen
            ):
                raise RgwCleanupError(
                    "RGW current-object cursor changed"
                )
            seen.add(next_token)
            token = next_token
        return keys, pages

    def _versions(
        self,
        *,
        max_pages: int,
        prefix: str,
    ) -> tuple[
        list[tuple[str, str]],
        list[tuple[str, str]],
        list[str],
    ]:
        versions: list[tuple[str, str]] = []
        markers: list[tuple[str, str]] = []
        pages: list[str] = []
        key_marker: str | None = None
        version_marker: str | None = None
        seen: set[tuple[str, str]] = set()
        while True:
            if len(pages) >= max_pages:
                raise RgwCleanupError("RGW version pagination exceeded")
            arguments: dict[str, Any] = {
                "Bucket": self.bucket,
                "MaxKeys": 1000,
                "Prefix": f"{prefix}/",
            }
            if key_marker is not None:
                arguments["KeyMarker"] = key_marker
                arguments["VersionIdMarker"] = version_marker
            response = self.client.list_object_versions(**arguments)
            page_identities: list[str] = []
            for field, destination, kind in (
                ("Versions", versions, "version"),
                ("DeleteMarkers", markers, "delete-marker"),
            ):
                items = response.get(field, [])
                if not isinstance(items, list):
                    raise RgwCleanupError("RGW version page changed")
                for item in items:
                    if not isinstance(item, Mapping):
                        raise RgwCleanupError(
                            "RGW version page changed"
                        )
                    identity = _identity(
                        (item.get("Key"), item.get("VersionId")),
                        prefix,
                        f"RGW {kind}",
                    )
                    destination.append(identity)
                    page_identities.append(
                        _hash(
                            {
                                "key": identity[0],
                                "kind": kind,
                                "version_id": identity[1],
                            }
                        )
                    )
            truncated = response.get("IsTruncated") is True
            next_key = response.get("NextKeyMarker", "")
            next_version = response.get("NextVersionIdMarker", "")
            pages.append(
                _page_hash(
                    kind="versions",
                    identities=page_identities,
                    truncated=truncated,
                    cursor=f"{next_key}\0{next_version}",
                )
            )
            if not truncated:
                break
            if (
                not isinstance(next_key, str)
                or not next_key
                or not isinstance(next_version, str)
                or not next_version
                or (next_key, next_version) in seen
            ):
                raise RgwCleanupError("RGW version cursor changed")
            seen.add((next_key, next_version))
            key_marker = next_key
            version_marker = next_version
        return versions, markers, pages

    def _uploads(
        self,
        *,
        max_pages: int,
        prefix: str,
    ) -> tuple[list[tuple[str, str]], list[str]]:
        uploads: list[tuple[str, str]] = []
        pages: list[str] = []
        key_marker: str | None = None
        upload_marker: str | None = None
        seen: set[tuple[str, str]] = set()
        while True:
            if len(pages) >= max_pages:
                raise RgwCleanupError("RGW upload pagination exceeded")
            arguments: dict[str, Any] = {
                "Bucket": self.bucket,
                "MaxUploads": 1000,
                "Prefix": f"{prefix}/",
            }
            if key_marker is not None:
                arguments["KeyMarker"] = key_marker
                arguments["UploadIdMarker"] = upload_marker
            response = self.client.list_multipart_uploads(**arguments)
            items = response.get("Uploads", [])
            if not isinstance(items, list):
                raise RgwCleanupError("RGW upload page changed")
            page_identities: list[str] = []
            for item in items:
                if not isinstance(item, Mapping):
                    raise RgwCleanupError("RGW upload page changed")
                identity = _identity(
                    (item.get("Key"), item.get("UploadId")),
                    prefix,
                    "RGW multipart upload",
                )
                uploads.append(identity)
                page_identities.append(
                    _hash(
                        {
                            "key": identity[0],
                            "upload_id": identity[1],
                        }
                    )
                )
            truncated = response.get("IsTruncated") is True
            next_key = response.get("NextKeyMarker", "")
            next_upload = response.get("NextUploadIdMarker", "")
            pages.append(
                _page_hash(
                    kind="uploads",
                    identities=page_identities,
                    truncated=truncated,
                    cursor=f"{next_key}\0{next_upload}",
                )
            )
            if not truncated:
                break
            if (
                not isinstance(next_key, str)
                or not next_key
                or not isinstance(next_upload, str)
                or not next_upload
                or (next_key, next_upload) in seen
            ):
                raise RgwCleanupError("RGW upload cursor changed")
            seen.add((next_key, next_upload))
            key_marker = next_key
            upload_marker = next_upload
        return uploads, pages

    def scan(
        self,
        *,
        max_pages: int,
        prefix: str,
    ) -> CleanupInventory:
        current, current_pages = self._current(
            max_pages=max_pages,
            prefix=prefix,
        )
        versions, markers, version_pages = self._versions(
            max_pages=max_pages,
            prefix=prefix,
        )
        uploads, upload_pages = self._uploads(
            max_pages=max_pages,
            prefix=prefix,
        )
        return CleanupInventory(
            current_keys=tuple(current),
            delete_markers=tuple(markers),
            multipart_uploads=tuple(uploads),
            page_sha256=tuple(
                [*current_pages, *version_pages, *upload_pages]
            ),
            versions=tuple(versions),
        )

    def remove(self, inventory: CleanupInventory) -> None:
        for key, upload_id in inventory.multipart_uploads:
            self.client.abort_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
            )
        versioned = [
            {"Key": key, "VersionId": version}
            for key, version in (
                *inventory.versions,
                *inventory.delete_markers,
            )
        ]
        versioned_keys = {item["Key"] for item in versioned}
        unversioned = [
            {"Key": key}
            for key in inventory.current_keys
            if key not in versioned_keys
        ]
        objects = [*versioned, *unversioned]
        for start in range(0, len(objects), MAX_DELETE_BATCH):
            batch = objects[start : start + MAX_DELETE_BATCH]
            response = self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": batch, "Quiet": True},
            )
            errors = response.get("Errors", [])
            if errors not in (None, []):
                raise RgwCleanupError("RGW cleanup deletion failed")


def boto3_cleanup_client(
    config: Mapping[str, Any],
) -> Boto3CleanupClient:
    live = rgw_live_adapter.boto3_client(config)
    return Boto3CleanupClient(
        client=live.client,
        bucket=live.bucket,
    )


def cleanup_file(
    config_path: Path,
    output_path: Path,
    *,
    client: CleanupClient | None = None,
    clock: rgw_live_adapter.Clock = time.time,
) -> dict[str, Any]:
    try:
        config_path = control_artifacts._absolute_path(
            str(config_path),
            "RGW cleanup configuration",
        )
        config, _, metadata = rgw_live_adapter._read_config(config_path)
    except (
        control_artifacts.ControlArtifactError,
        rgw_live_adapter.RgwLiveAdapterError,
    ) as error:
        raise RgwCleanupError(
            "RGW cleanup configuration is unavailable"
        ) from error
    selected = client or boto3_cleanup_client(config)
    result = cleanup(config, client=selected, clock=clock)
    try:
        control_artifacts._write_output(
            output_path,
            result,
            inputs=[(config_path, metadata)],
        )
    except control_artifacts.ControlArtifactError as error:
        raise RgwCleanupError("RGW cleanup output is unavailable") from error
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_hash = cleanup_source_sha256()
        except RgwCleanupError:
            print("rgw-cleanup-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "cleanup_source_sha256": source_hash,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 3 or arguments[0] != "cleanup":
        print("rgw-cleanup-refused", file=sys.stderr)
        return 2
    try:
        result = cleanup_file(
            Path(arguments[1]),
            Path(arguments[2]),
        )
    except (
        RgwCleanupError,
        rgw_live_adapter.RgwLiveAdapterError,
        control_artifacts.ControlArtifactError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("rgw-cleanup-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "cleanup_sha256": result["cleanup_sha256"],
                "schema": RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
