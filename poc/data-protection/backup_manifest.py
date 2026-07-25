from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Mapping, Sequence


MODULE_PATH = Path(__file__).with_name("state_machine.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "coffer_data_protection_state_machine_backup",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("data-protection state machine is unavailable")
state_machine = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = state_machine
MODULE_SPEC.loader.exec_module(state_machine)

BUNDLE_SCHEMA = "coffer.data-protection-backup-bundle/v1"
EVIDENCE_SCHEMA = "coffer.data-protection-backup-evidence/v1"
FAILURE_SCHEMA = "coffer.data-protection-backup-failure/v1"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+ -]{0,63}$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]{0,63}$")
FIXED_FAILURE_CATEGORIES = frozenset(
    {
        "contract-refused",
        "local-file-unavailable",
        "manifest-refused",
    }
)


class ManifestError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURE_CATEGORIES:
            raise ValueError("failure category is not fixed")
        super().__init__(category)
        self.category = category


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ManifestError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be an array")
    return value


def _exact(
    value: object,
    label: str,
    fields: set[str],
) -> dict[str, object]:
    raw = dict(_mapping(value, label))
    if set(raw) != fields:
        raise ManifestError(f"{label} fields are invalid")
    return raw


def _sha256(value: object, label: str) -> str:
    text = str(value)
    if state_machine.SHA256_PATTERN.fullmatch(text) is None:
        raise ManifestError(f"{label} must be canonical SHA-256")
    return text


def _count(
    value: object,
    label: str,
    *,
    positive: bool = False,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < (1 if positive else 0)
    ):
        qualifier = "positive" if positive else "nonnegative"
        raise ManifestError(f"{label} must be a {qualifier} integer")
    return value


def _name(value: object, label: str) -> str:
    text = str(value)
    if NAME_PATTERN.fullmatch(text) is None:
        raise ManifestError(f"{label} is invalid")
    return text


def _version(value: object, label: str) -> str:
    text = str(value)
    if VERSION_PATTERN.fullmatch(text) is None:
        raise ManifestError(f"{label} is invalid")
    return text


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _verify_provenance(
    value: object,
    *,
    invocation_id: str,
    target_signature: str,
    topology_digest: str,
) -> tuple[dict[str, object], str]:
    raw = _exact(
        value,
        "provenance",
        {
            "invocation_id",
            "target_signature",
            "topology_digest",
            "adapter",
            "adapter_version",
        },
    )
    if (
        raw["invocation_id"] != invocation_id
        or raw["target_signature"] != target_signature
        or raw["topology_digest"] != topology_digest
        or raw["adapter"] != "fixture"
        or raw["adapter_version"] != "1"
    ):
        raise ManifestError("backup provenance does not match the exact fixture")
    if state_machine.INVOCATION_PATTERN.fullmatch(invocation_id) is None:
        raise ManifestError("invocation ID is invalid")
    if state_machine.TARGET_PATTERN.fullmatch(target_signature) is None:
        raise ManifestError("target signature is invalid")
    _sha256(topology_digest, "topology digest")
    return raw, _canonical_digest(raw)


def _verify_sql(
    value: object,
    provenance_sha256: str,
) -> dict[str, object]:
    raw = _exact(
        value,
        "SQL backup manifest",
        {
            "tool_name",
            "tool_version",
            "server_product",
            "server_version",
            "source_database_sha256",
            "schema_revision",
            "schema_sha256",
            "recovery_coordinate_sha256",
            "artifact_sha256",
            "source_content_sha256",
            "bytes",
            "row_count",
            "restore",
        },
    )
    _name(raw["tool_name"], "SQL tool name")
    _version(raw["tool_version"], "SQL tool version")
    if _name(raw["server_product"], "SQL server product") != "MariaDB":
        raise ManifestError("SQL server product is unsupported")
    _version(raw["server_version"], "SQL server version")
    source_database = _sha256(
        raw["source_database_sha256"],
        "source database",
    )
    schema_revision = _version(raw["schema_revision"], "schema revision")
    schema_sha256 = _sha256(raw["schema_sha256"], "SQL schema")
    recovery_sha256 = _sha256(
        raw["recovery_coordinate_sha256"],
        "SQL recovery coordinate",
    )
    artifact_sha256 = _sha256(raw["artifact_sha256"], "SQL artifact")
    source_content = _sha256(
        raw["source_content_sha256"],
        "SQL source content",
    )
    backup_bytes = _count(raw["bytes"], "SQL backup bytes", positive=True)
    row_count = _count(raw["row_count"], "SQL row count", positive=True)
    restore = _exact(
        raw["restore"],
        "SQL restore manifest",
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
    isolated_database = _sha256(
        restore["isolated_database_sha256"],
        "isolated database",
    )
    restored_content = _sha256(
        restore["content_sha256"],
        "restored SQL content",
    )
    restored_schema = _sha256(
        restore["schema_sha256"],
        "restored SQL schema",
    )
    _sha256(restore["baseline_marker_sha256"], "baseline marker")
    repository_count = _count(
        restore["repository_count"],
        "restored repository count",
        positive=True,
    )
    reservation_count = _count(
        restore["reservation_count"],
        "restored reservation count",
    )
    comparison_count = _count(
        restore["comparison_count"],
        "restored comparison count",
    )
    if (
        isolated_database == source_database
        or restore["schema_revision"] != schema_revision
        or restored_schema != schema_sha256
        or restore["row_count"] != row_count
        or restored_content != source_content
        or restore["passed"] is not True
        or repository_count < 1
        or reservation_count < 0
        or comparison_count < 0
    ):
        raise ManifestError("isolated SQL restore does not match the backup")
    return {
        "artifact_sha256": artifact_sha256,
        "backup_sha256": source_content,
        "restore_sha256": restored_content,
        "schema_sha256": schema_sha256,
        "recovery_coordinate_sha256": recovery_sha256,
        "provenance_sha256": provenance_sha256,
        "bytes": backup_bytes,
        "row_count": row_count,
        "restored": True,
    }


def _verify_rgw(
    value: object,
    provenance_sha256: str,
    source_signature: str,
) -> dict[str, object]:
    raw = _exact(
        value,
        "RGW backup manifest",
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
            "pagination_complete",
            "page_count",
            "multipart_upload_count",
            "objects",
            "restore",
        },
    )
    _name(raw["tool_name"], "RGW tool name")
    _version(raw["tool_version"], "RGW tool version")
    if _name(raw["server_product"], "RGW server product") != "Ceph RGW":
        raise ManifestError("RGW server product is unsupported")
    _version(raw["server_version"], "RGW server version")
    for field in (
        "endpoint_sha256",
        "bucket_sha256",
        "root_sha256",
        "configuration_sha256",
        "kms_policy_sha256",
    ):
        _sha256(raw[field], field)
    if _sha256(raw["source_signature"], "RGW source signature") != source_signature:
        raise ManifestError("RGW source signature does not match the writer fence")
    if raw["pagination_complete"] is not True:
        raise ManifestError("RGW version listing is incomplete")
    _count(raw["page_count"], "RGW listing page count", positive=True)
    if _count(
        raw["multipart_upload_count"],
        "RGW multipart upload count",
    ) != 0:
        raise ManifestError("RGW backup has incomplete multipart uploads")

    objects_raw = _array(raw["objects"], "RGW objects")
    if len(objects_raw) < 2:
        raise ManifestError("RGW object coverage is incomplete")
    objects: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    has_zero = False
    has_positive = False
    for index, value_item in enumerate(objects_raw):
        item = _exact(
            value_item,
            f"RGW object {index}",
            {
                "kind",
                "key_sha256",
                "version_sha256",
                "size",
                "etag_sha256",
                "checksum_sha256",
                "metadata_sha256",
                "encryption",
                "kms_key_sha256",
            },
        )
        for field in (
            "key_sha256",
            "version_sha256",
            "metadata_sha256",
        ):
            item[field] = _sha256(item[field], f"RGW object {index} {field}")
        size = _count(item["size"], f"RGW object {index} size")
        if item["kind"] == "object":
            for field in ("etag_sha256", "checksum_sha256", "kms_key_sha256"):
                item[field] = _sha256(
                    item[field],
                    f"RGW object {index} {field}",
                )
            has_zero = has_zero or size == 0
            has_positive = has_positive or size > 0
            if item["encryption"] != "SSE-KMS":
                raise ManifestError("RGW object encryption is not SSE-KMS")
        elif item["kind"] == "delete-marker":
            if (
                size != 0
                or item["etag_sha256"] is not None
                or item["checksum_sha256"] is not None
                or item["kms_key_sha256"] is not None
                or item["encryption"] != "none"
            ):
                raise ManifestError("RGW delete marker fields are invalid")
        else:
            raise ManifestError("RGW object version kind is unsupported")
        identity = (str(item["key_sha256"]), str(item["version_sha256"]))
        if identity in identities:
            raise ManifestError("RGW object version identity is repeated")
        identities.add(identity)
        objects.append(item)
    if not has_zero or not has_positive:
        raise ManifestError("RGW object coverage lacks zero or positive size")
    if [
        (str(item["key_sha256"]), str(item["version_sha256"]))
        for item in objects
    ] != sorted(identities):
        raise ManifestError("RGW object versions are not canonically ordered")

    unique_keys = {str(item["key_sha256"]) for item in objects}
    total_bytes = sum(int(item["size"]) for item in objects)
    metadata_sha256 = _canonical_digest(
        [
            {
                "kind": item["kind"],
                "key_sha256": item["key_sha256"],
                "version_sha256": item["version_sha256"],
                "metadata_sha256": item["metadata_sha256"],
                "encryption": item["encryption"],
                "kms_key_sha256": item["kms_key_sha256"],
            }
            for item in objects
        ]
    )
    restore = _exact(
        raw["restore"],
        "RGW restore manifest",
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
    isolated_bucket = _sha256(
        restore["isolated_bucket_sha256"],
        "isolated RGW bucket",
    )
    isolated_root = _sha256(
        restore["isolated_root_sha256"],
        "isolated RGW root",
    )
    source_inventory = _sha256(
        restore["source_inventory_sha256"],
        "source inventory",
    )
    restore_inventory = _sha256(
        restore["restore_inventory_sha256"],
        "restore inventory",
    )
    restore_metadata = _sha256(
        restore["metadata_sha256"],
        "restored metadata",
    )
    source_pull = _sha256(restore["source_pull_sha256"], "source pull")
    restore_pull = _sha256(restore["restore_pull_sha256"], "restore pull")
    delete_marker_count = sum(
        1 for item in objects if item["kind"] == "delete-marker"
    )
    if (
        isolated_bucket == raw["bucket_sha256"]
        or isolated_root == raw["root_sha256"]
        or restore["object_count"] != len(unique_keys)
        or restore["version_count"] != len(objects)
        or restore["delete_marker_count"] != delete_marker_count
        or restore["bytes"] != total_bytes
        or source_inventory != restore_inventory
        or restore_metadata != metadata_sha256
        or source_pull != restore_pull
        or restore["passed"] is not True
    ):
        raise ManifestError("isolated RGW restore does not match the backup")

    source_manifest = {
        key: raw[key]
        for key in raw
        if key != "restore"
    }
    return {
        "manifest_sha256": _canonical_digest(
            {
                "provenance_sha256": provenance_sha256,
                "source": source_manifest,
            }
        ),
        "source_inventory_sha256": source_inventory,
        "restore_inventory_sha256": restore_inventory,
        "metadata_sha256": metadata_sha256,
        "source_signature": source_signature,
        "provenance_sha256": provenance_sha256,
        "bytes": total_bytes,
        "object_count": len(unique_keys),
        "version_count": len(objects),
        "multipart_upload_count": 0,
        "restored": True,
    }


def verify_backup_bundle(
    value: object,
    *,
    invocation_id: str,
    target_signature: str,
    topology_digest: str,
    source_signature: str,
) -> dict[str, object]:
    raw = _exact(
        value,
        "backup bundle",
        {"schema", "provenance", "sql", "rgw"},
    )
    if raw["schema"] != BUNDLE_SCHEMA:
        raise ManifestError("backup bundle schema is unsupported")
    _sha256(source_signature, "source signature")
    try:
        state_machine.validate_retained_payload(raw)
    except state_machine.DataProtectionError as error:
        raise ManifestError("backup bundle contains prohibited content") from error
    provenance, provenance_sha256 = _verify_provenance(
        raw["provenance"],
        invocation_id=invocation_id,
        target_signature=target_signature,
        topology_digest=topology_digest,
    )
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "provenance_sha256": provenance_sha256,
        "bundle_sha256": _canonical_digest(raw),
        "sql_backup": _verify_sql(raw["sql"], provenance_sha256),
        "rgw_backup": _verify_rgw(
            raw["rgw"],
            provenance_sha256,
            source_signature,
        ),
    }
    if provenance["invocation_id"] != invocation_id:
        raise ManifestError("backup bundle invocation changed")
    state_machine.validate_retained_payload(evidence)
    return evidence


def _validate_owner_file(path: Path, *, required: bool = True) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise CommandError("local-file-unavailable") from None
        return
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise CommandError("local-file-unavailable")


def _read_owner_json(path: Path) -> object:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise CommandError("local-file-unavailable")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = None
            try:
                return json.load(stream)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CommandError("manifest-refused") from error
    except CommandError:
        raise
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_json(path: Path, value: object) -> None:
    state_machine.validate_retained_payload(value)
    try:
        parent = path.parent.lstat()
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.getuid()
    ):
        raise CommandError("local-file-unavailable")
    _validate_owner_file(path, required=False)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        payload = (
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    _validate_owner_file(path)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify one secret-safe Coffer SQL/RGW backup bundle",
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--target-signature", required=True)
    parser.add_argument("--topology-digest", required=True)
    parser.add_argument("--source-signature", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = _read_owner_json(args.manifest)
        try:
            evidence = verify_backup_bundle(
                value,
                invocation_id=args.invocation_id,
                target_signature=args.target_signature,
                topology_digest=args.topology_digest,
                source_signature=args.source_signature,
            )
        except ManifestError as error:
            raise CommandError("manifest-refused") from error
        if args.output is not None:
            _atomic_json(args.output, evidence)
        print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
        return 0
    except state_machine.DataProtectionError:
        failure = CommandError("contract-refused")
    except CommandError as error:
        failure = error
    print(
        json.dumps(
            {
                "schema": FAILURE_SCHEMA,
                "category": failure.category,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
