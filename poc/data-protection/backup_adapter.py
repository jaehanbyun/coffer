from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Mapping, Protocol, Sequence


MODULE_PATH = Path(__file__).with_name("backup_manifest.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "coffer_data_protection_backup_manifest_adapter",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("data-protection backup verifier is unavailable")
backup_manifest = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = backup_manifest
MODULE_SPEC.loader.exec_module(backup_manifest)
state_machine = backup_manifest.state_machine

ADAPTER_KIND = "fixture"
ADAPTER_VERSION = "1"
MAX_PAGES = 10_000


class AdapterError(RuntimeError):
    pass


class MariaDBBackupClient(Protocol):
    adapter_kind: str

    def inspect_source(self) -> Mapping[str, object]: ...

    def create_backup(self) -> Mapping[str, object]: ...

    def restore_and_inspect(self) -> Mapping[str, object]: ...


class VersionedS3BackupClient(Protocol):
    adapter_kind: str

    def inspect_source(self) -> Mapping[str, object]: ...

    def list_versions(self, cursor: str | None) -> Mapping[str, object]: ...

    def copy_versions(
        self,
        versions: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]: ...

    def restore_and_inspect(self) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class AdapterResult:
    bundle: dict[str, object]
    evidence: dict[str, object]
    trace: tuple[str, ...]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AdapterError(f"{label} must be an object")
    return value


def _exact(
    value: object,
    label: str,
    fields: set[str],
) -> dict[str, object]:
    raw = dict(_mapping(value, label))
    if set(raw) != fields:
        raise AdapterError(f"{label} fields are invalid")
    try:
        state_machine.validate_retained_payload(raw)
    except state_machine.DataProtectionError as error:
        raise AdapterError(f"{label} contains prohibited content") from error
    return raw


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _version_set_digest(
    versions: Sequence[Mapping[str, object]],
) -> str:
    return _canonical_digest(
        [
            {
                "key_sha256": version["key_sha256"],
                "version_sha256": version["version_sha256"],
            }
            for version in versions
        ]
    )


class FixtureMariaDBClient:
    adapter_kind = ADAPTER_KIND

    def __init__(self, sql_manifest: Mapping[str, object]):
        raw = deepcopy(dict(sql_manifest))
        self._source = {
            key: raw[key]
            for key in (
                "tool_name",
                "tool_version",
                "server_product",
                "server_version",
                "source_database_sha256",
                "schema_revision",
                "schema_sha256",
                "recovery_coordinate_sha256",
                "source_content_sha256",
                "row_count",
            )
        }
        self._backup = {
            key: raw[key]
            for key in ("artifact_sha256", "bytes")
        }
        self._restore = deepcopy(dict(_mapping(raw["restore"], "SQL restore")))
        self._phase = "new"

    def inspect_source(self) -> Mapping[str, object]:
        if self._phase != "new":
            raise AdapterError("SQL source inspection is out of order")
        self._phase = "inspected"
        return deepcopy(self._source)

    def create_backup(self) -> Mapping[str, object]:
        if self._phase != "inspected":
            raise AdapterError("SQL backup is out of order")
        self._phase = "backed-up"
        return deepcopy(self._backup)

    def restore_and_inspect(self) -> Mapping[str, object]:
        if self._phase != "backed-up":
            raise AdapterError("SQL restore is out of order")
        self._phase = "restored"
        return deepcopy(self._restore)


class FixtureVersionedS3Client:
    adapter_kind = ADAPTER_KIND

    def __init__(
        self,
        rgw_manifest: Mapping[str, object],
        *,
        page_size: int = 2,
        repeat_cursor: bool = False,
        copy_digest_override: str | None = None,
    ):
        raw = deepcopy(dict(rgw_manifest))
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise AdapterError("fixture page size is invalid")
        self._source = {
            key: raw[key]
            for key in (
                "tool_name",
                "tool_version",
                "server_product",
                "server_version",
                "endpoint_sha256",
                "bucket_sha256",
                "root_sha256",
                "configuration_sha256",
                "kms_policy_sha256",
                "source_signature",
                "multipart_upload_count",
            )
        }
        objects = raw["objects"]
        if not isinstance(objects, list):
            raise AdapterError("fixture object versions are invalid")
        self._objects = deepcopy(objects)
        self._restore = deepcopy(dict(_mapping(raw["restore"], "RGW restore")))
        self._page_size = page_size
        self._repeat_cursor = repeat_cursor
        self._copy_digest_override = copy_digest_override
        self._phase = "new"
        self._expected_cursor: str | None = None

    def inspect_source(self) -> Mapping[str, object]:
        if self._phase != "new":
            raise AdapterError("S3 source inspection is out of order")
        self._phase = "inspected"
        return deepcopy(self._source)

    def list_versions(self, cursor: str | None) -> Mapping[str, object]:
        if self._phase not in {"inspected", "listing"}:
            raise AdapterError("S3 version listing is out of order")
        if cursor != self._expected_cursor:
            raise AdapterError("S3 pagination cursor does not match")
        start = 0 if cursor is None else int(cursor)
        stop = min(start + self._page_size, len(self._objects))
        page = deepcopy(self._objects[start:stop])
        if stop >= len(self._objects):
            next_cursor: str | None = None
            self._phase = "listed"
        else:
            next_cursor = str(start) if self._repeat_cursor else str(stop)
            self._phase = "listing"
        self._expected_cursor = next_cursor
        return {
            "objects": page,
            "next_cursor": next_cursor,
        }

    def copy_versions(
        self,
        versions: Sequence[Mapping[str, object]],
    ) -> Mapping[str, object]:
        if self._phase != "listed":
            raise AdapterError("S3 backup copy is out of order")
        self._phase = "copied"
        return {
            "version_set_sha256": (
                self._copy_digest_override
                if self._copy_digest_override is not None
                else _version_set_digest(versions)
            ),
            "version_count": len(versions),
        }

    def restore_and_inspect(self) -> Mapping[str, object]:
        if self._phase != "copied":
            raise AdapterError("S3 restore is out of order")
        self._phase = "restored"
        return deepcopy(self._restore)


def build_backup_bundle(
    *,
    invocation_id: str,
    target_signature: str,
    topology_digest: str,
    source_signature: str,
    sql_client: MariaDBBackupClient,
    s3_client: VersionedS3BackupClient,
    max_pages: int = MAX_PAGES,
) -> AdapterResult:
    if (
        type(sql_client) is not FixtureMariaDBClient
        or type(s3_client) is not FixtureVersionedS3Client
        or sql_client.adapter_kind != ADAPTER_KIND
        or s3_client.adapter_kind != ADAPTER_KIND
    ):
        raise AdapterError("only the no-network fixture adapter is accepted")
    if (
        not isinstance(max_pages, int)
        or isinstance(max_pages, bool)
        or max_pages < 1
        or max_pages > MAX_PAGES
    ):
        raise AdapterError("pagination bound is invalid")
    trace: list[str] = []
    try:
        sql_source = _exact(
            sql_client.inspect_source(),
            "SQL source observation",
            {
                "tool_name",
                "tool_version",
                "server_product",
                "server_version",
                "source_database_sha256",
                "schema_revision",
                "schema_sha256",
                "recovery_coordinate_sha256",
                "source_content_sha256",
                "row_count",
            },
        )
        trace.append("sql.inspect-source")
        sql_backup = _exact(
            sql_client.create_backup(),
            "SQL backup observation",
            {"artifact_sha256", "bytes"},
        )
        trace.append("sql.create-backup")
        sql_restore = _exact(
            sql_client.restore_and_inspect(),
            "SQL restore observation",
            {
                "isolated_database_sha256",
                "content_sha256",
                "schema_revision",
                "schema_sha256",
                "row_count",
                "baseline_marker_sha256",
                "repository_count",
                "reservation_count",
                "comparison_count",
                "passed",
            },
        )
        trace.append("sql.restore-and-inspect")

        s3_source = _exact(
            s3_client.inspect_source(),
            "S3 source observation",
            {
                "tool_name",
                "tool_version",
                "server_product",
                "server_version",
                "endpoint_sha256",
                "bucket_sha256",
                "root_sha256",
                "configuration_sha256",
                "kms_policy_sha256",
                "source_signature",
                "multipart_upload_count",
            },
        )
        trace.append("s3.inspect-source")
        versions: list[Mapping[str, object]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            if page_count >= max_pages:
                raise AdapterError("S3 pagination exceeded the fixed bound")
            page = _exact(
                s3_client.list_versions(cursor),
                "S3 version page",
                {"objects", "next_cursor"},
            )
            page_count += 1
            trace.append("s3.list-versions")
            page_objects = page["objects"]
            if not isinstance(page_objects, list) or not page_objects:
                raise AdapterError("S3 version page is empty")
            for item in page_objects:
                versions.append(deepcopy(dict(_mapping(item, "S3 object version"))))
            next_cursor = page["next_cursor"]
            if next_cursor is None:
                break
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or len(next_cursor) > 64
                or next_cursor in seen_cursors
            ):
                raise AdapterError("S3 pagination cursor is invalid or repeated")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        copy_result = _exact(
            s3_client.copy_versions(versions),
            "S3 copy observation",
            {"version_set_sha256", "version_count"},
        )
        trace.append("s3.copy-versions")
        expected_set = _version_set_digest(versions)
        if (
            copy_result["version_set_sha256"] != expected_set
            or copy_result["version_count"] != len(versions)
        ):
            raise AdapterError("S3 backup copy does not match the version listing")
        s3_restore = _exact(
            s3_client.restore_and_inspect(),
            "S3 restore observation",
            {
                "isolated_bucket_sha256",
                "isolated_root_sha256",
                "object_count",
                "version_count",
                "delete_marker_count",
                "bytes",
                "source_inventory_sha256",
                "restore_inventory_sha256",
                "metadata_sha256",
                "source_pull_sha256",
                "restore_pull_sha256",
                "passed",
            },
        )
        trace.append("s3.restore-and-inspect")
        bundle = {
            "schema": backup_manifest.BUNDLE_SCHEMA,
            "provenance": {
                "invocation_id": invocation_id,
                "target_signature": target_signature,
                "topology_digest": topology_digest,
                "adapter": ADAPTER_KIND,
                "adapter_version": ADAPTER_VERSION,
            },
            "sql": {
                **sql_source,
                **sql_backup,
                "restore": sql_restore,
            },
            "rgw": {
                **s3_source,
                "pagination_complete": True,
                "page_count": page_count,
                "objects": versions,
                "restore": s3_restore,
            },
        }
        evidence = backup_manifest.verify_backup_bundle(
            bundle,
            invocation_id=invocation_id,
            target_signature=target_signature,
            topology_digest=topology_digest,
            source_signature=source_signature,
        )
        trace.append("bundle.verify")
    except (KeyError, TypeError, ValueError, backup_manifest.ManifestError) as error:
        raise AdapterError("fixture backup observations were refused") from error
    return AdapterResult(
        bundle=deepcopy(bundle),
        evidence=deepcopy(evidence),
        trace=tuple(trace),
    )


def build_fixture_backup(
    fixture: Mapping[str, object],
    *,
    invocation_id: str,
    target_signature: str,
    topology_digest: str,
    source_signature: str,
    page_size: int = 2,
) -> AdapterResult:
    raw = _exact(
        fixture,
        "data-protection fixture",
        {
            "schema",
            "target_signature",
            "unrelated_signature",
            "seed",
            "backup_bundle",
            "evidence",
            "failure_outcomes",
            "residue_counts",
        },
    )
    expected = _mapping(raw["backup_bundle"], "fixture backup bundle")
    sql = _mapping(expected["sql"], "fixture SQL manifest")
    rgw = _mapping(expected["rgw"], "fixture RGW manifest")
    result = build_backup_bundle(
        invocation_id=invocation_id,
        target_signature=target_signature,
        topology_digest=topology_digest,
        source_signature=source_signature,
        sql_client=FixtureMariaDBClient(sql),
        s3_client=FixtureVersionedS3Client(rgw, page_size=page_size),
    )
    expected_evidence = backup_manifest.verify_backup_bundle(
        expected,
        invocation_id=invocation_id,
        target_signature=target_signature,
        topology_digest=topology_digest,
        source_signature=source_signature,
    )
    if (
        result.bundle != expected
        or result.evidence != expected_evidence
    ):
        raise AdapterError("fixture adapter output does not match the exact bundle")
    return result
