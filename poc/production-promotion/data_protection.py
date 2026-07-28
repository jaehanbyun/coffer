from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
MAINTENANCE_RESULT_SOURCE = DIRECTORY / "maintenance_identity.py"
DATA_DIRECTORY = ROOT / "poc" / "data-protection"
STATE_MACHINE_SOURCE = DATA_DIRECTORY / "state_machine.py"
LIFECYCLE_SOURCE = DATA_DIRECTORY / "lifecycle.py"
TOPOLOGY_SOURCE = DATA_DIRECTORY / "topology.json"
RUNTIME_SOURCES = {
    "backup_adapter_sha256": DATA_DIRECTORY / "backup_adapter.py",
    "backup_manifest_sha256": DATA_DIRECTORY / "backup_manifest.py",
    "data_lifecycle_sha256": LIFECYCLE_SOURCE,
    "data_state_machine_sha256": STATE_MACHINE_SOURCE,
    "data_topology_sha256": TOPOLOGY_SOURCE,
    "inventory_sha256": ROOT / "src" / "coffer" / "inventory.py",
    "maintenance_result_verifier_sha256": MAINTENANCE_RESULT_SOURCE,
    "quota_import_sha256": ROOT / "src" / "coffer" / "quota_import.py",
    "quota_sha256": ROOT / "src" / "coffer" / "quota.py",
}

SCHEMA = "coffer.production-promotion-data-protection-result/v1"
EVIDENCE_SCHEMA = "coffer.production-promotion-data-protection-evidence/v1"
INVENTORY_SCHEMA = "coffer.inventory/v3"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DataProtectionResultError(RuntimeError):
    pass


class DataProtectionInputsBlocked(DataProtectionResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise DataProtectionResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise DataProtectionResultError(f"unable to load {path}") from error
    return module


MAINTENANCE_RESULT = _load_module(
    "coffer_data_promotion_maintenance",
    MAINTENANCE_RESULT_SOURCE,
)
ARTIFACT_RESULT = MAINTENANCE_RESULT.ARTIFACT_RESULT
RGW_KMS_RESULT = MAINTENANCE_RESULT.RGW_KMS_RESULT
STATE_MACHINE = _load_module(
    "coffer_data_promotion_state_machine",
    STATE_MACHINE_SOURCE,
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise DataProtectionResultError(f"unable to hash {path}") from error


def runtime_source_hashes() -> dict[str, str]:
    return {
        name: _sha256(path)
        for name, path in sorted(RUNTIME_SOURCES.items())
    }


def source_hashes() -> dict[str, str]:
    return {
        "data_protection_compiler_sha256": _sha256(Path(__file__).resolve()),
        **runtime_source_hashes(),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataProtectionResultError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DataProtectionResultError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise DataProtectionResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise DataProtectionResultError(f"{label} is invalid")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DataProtectionResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result < 1:
        raise DataProtectionResultError(f"{label} is invalid")
    return result


def _qualified_prerequisites(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    maintenance_result: object,
    maintenance_digest: str,
) -> dict[str, str]:
    try:
        base = MAINTENANCE_RESULT._qualified_prerequisites(
            release_readiness=release_readiness,
            release_digest=release_digest,
            artifact_result=artifact_result,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms_result,
            rgw_kms_digest=rgw_kms_digest,
        )
        maintenance = MAINTENANCE_RESULT.validate_final_result(
            maintenance_result
        )
    except MAINTENANCE_RESULT.MaintenanceIdentityInputsBlocked as error:
        raise DataProtectionInputsBlocked(str(error)) from error
    except MAINTENANCE_RESULT.MaintenanceIdentityResultError as error:
        raise DataProtectionInputsBlocked(
            "maintenance identity is not candidate-qualified"
        ) from error
    if maintenance["prerequisites"] != base:
        raise DataProtectionInputsBlocked(
            "maintenance identity prerequisite binding changed"
        )
    return {
        **base,
        "maintenance_identity_result_sha256": _digest(
            maintenance_digest,
            "maintenance identity result",
        ),
    }


def _validate_lifecycle(value: object) -> dict[str, Any]:
    lifecycle = _mapping(value, "data-protection lifecycle evidence")
    _exact_keys(
        lifecycle,
        {
            "invocation_id",
            "phase",
            "phase_evidence_sha256",
            "resource_counts",
            "resource_id_hashes",
            "schema",
            "target_signature",
            "topology_digest",
            "unrelated_signature",
        },
        "data-protection lifecycle evidence",
    )
    try:
        topology = STATE_MACHINE.load_topology(TOPOLOGY_SOURCE)
    except STATE_MACHINE.DataProtectionError as error:
        raise DataProtectionResultError(
            "data-protection topology is invalid"
        ) from error
    if (
        lifecycle["schema"] != STATE_MACHINE.EVIDENCE_SCHEMA
        or lifecycle["topology_digest"] != topology.digest
        or lifecycle["phase"] != "torn-down"
        or STATE_MACHINE.INVOCATION_PATTERN.fullmatch(
            str(lifecycle["invocation_id"])
        )
        is None
        or HEX_SHA256.fullmatch(str(lifecycle["target_signature"])) is None
    ):
        raise DataProtectionResultError(
            "data-protection lifecycle is not terminal"
        )
    _digest(lifecycle["phase_evidence_sha256"], "phase evidence")
    _digest(lifecycle["unrelated_signature"], "unrelated signature")
    resources = _mapping(
        lifecycle["resource_counts"],
        "data-protection lifecycle resource counts",
    )
    if set(resources) != set(STATE_MACHINE.EXPECTED_CLEANUP_ORDER) or any(
        _nonnegative_integer(
            resources[name],
            f"data-protection {name} resource count",
        )
        != 0
        for name in STATE_MACHINE.EXPECTED_CLEANUP_ORDER
    ):
        raise DataProtectionResultError(
            "data-protection lifecycle resources remain"
        )
    identities = _array(
        lifecycle["resource_id_hashes"],
        "data-protection lifecycle resource ID hashes",
    )
    if identities:
        raise DataProtectionResultError(
            "data-protection lifecycle retained resource identities"
        )
    try:
        STATE_MACHINE.validate_retained_payload(lifecycle)
    except STATE_MACHINE.DataProtectionError as error:
        raise DataProtectionResultError(
            "data-protection lifecycle retained forbidden data"
        ) from error
    return {
        "phase_evidence_sha256": lifecycle["phase_evidence_sha256"],
        "terminal_phase": "torn-down",
    }


def _validate_execution(value: object) -> dict[str, Any]:
    execution = _mapping(value, "data-protection execution")
    _exact_keys(
        execution,
        {"adapter", "disposable", "non_synthetic", "phase_count"},
        "data-protection execution",
    )
    if (
        execution["adapter"] != "openstack"
        or execution["disposable"] is not True
        or execution["non_synthetic"] is not True
        or execution["phase_count"] != len(STATE_MACHINE.EXPECTED_PHASES)
    ):
        raise DataProtectionResultError(
            "data-protection execution is not a complete disposable run"
        )
    return {
        "adapter": "openstack",
        "disposable": True,
        "non_synthetic": True,
        "phase_count": len(STATE_MACHINE.EXPECTED_PHASES),
    }


def _validate_writer_exclusion(value: object) -> dict[str, Any]:
    writer = _mapping(value, "writer exclusion")
    _exact_keys(
        writer,
        {
            "active_uploads",
            "canary_write_status",
            "digest_read_status",
            "source_stable",
            "unknown_listeners",
            "writers_disabled",
        },
        "writer exclusion",
    )
    if (
        writer["active_uploads"] != 0
        or writer["unknown_listeners"] != 0
        or writer["canary_write_status"] not in {403, 405}
        or writer["digest_read_status"] != 200
        or writer["source_stable"] is not True
        or writer["writers_disabled"] is not True
    ):
        raise DataProtectionResultError("writers were not exactly excluded")
    return dict(writer)


def _validate_backup_restore(value: object) -> dict[str, Any]:
    backup = _mapping(value, "data-protection backup and restore")
    _exact_keys(
        backup,
        {
            "delete_marker_count",
            "isolated_restore",
            "multipart_upload_count",
            "object_count",
            "rgw_inventory_equal",
            "rgw_restored",
            "sql_restored",
            "sql_row_count",
            "sse_kms",
            "version_count",
        },
        "data-protection backup and restore",
    )
    normalized = {
        name: _nonnegative_integer(
            backup[name],
            f"data-protection {name}",
        )
        for name in (
            "delete_marker_count",
            "multipart_upload_count",
            "object_count",
            "sql_row_count",
            "version_count",
        )
    }
    if (
        normalized["object_count"] < 2
        or normalized["version_count"] < 3
        or normalized["sql_row_count"] < 1
        or normalized["multipart_upload_count"] != 0
        or backup["isolated_restore"] is not True
        or backup["rgw_inventory_equal"] is not True
        or backup["rgw_restored"] is not True
        or backup["sql_restored"] is not True
        or backup["sse_kms"] is not True
    ):
        raise DataProtectionResultError(
            "SQL/RGW backup and isolated restore are not qualified"
        )
    return {**dict(backup), **normalized}


def _validate_inventory_import(value: object) -> dict[str, Any]:
    inventory = _mapping(value, "data-protection inventory and import")
    _exact_keys(
        inventory,
        {
            "conflicting_replay_refused",
            "descriptor_count",
            "idempotent_replay",
            "imported",
            "inventory_schema",
            "live_comparison_verified",
            "manifest_count",
            "partial_rows",
            "private_tls_verified",
            "pull_only",
            "repository_count",
            "scans_equal",
            "session_closed",
        },
        "data-protection inventory and import",
    )
    counts = {
        name: _positive_integer(
            inventory[name],
            f"data-protection {name}",
        )
        for name in (
            "descriptor_count",
            "manifest_count",
            "repository_count",
        )
    }
    if (
        inventory["inventory_schema"] != INVENTORY_SCHEMA
        or inventory["partial_rows"] != 0
        or any(
            inventory[name] is not True
            for name in (
                "conflicting_replay_refused",
                "idempotent_replay",
                "imported",
                "live_comparison_verified",
                "private_tls_verified",
                "pull_only",
                "scans_equal",
                "session_closed",
            )
        )
    ):
        raise DataProtectionResultError(
            "inventory/import/live comparison is not qualified"
        )
    return {**dict(inventory), **counts}


def _all_true(
    value: object,
    fields: set[str],
    label: str,
) -> dict[str, bool]:
    item = _mapping(value, label)
    _exact_keys(item, fields, label)
    if any(item[name] is not True for name in fields):
        raise DataProtectionResultError(f"{label} is incomplete")
    return {name: True for name in sorted(fields)}


def _validate_cutover(value: object) -> dict[str, bool]:
    return _all_true(
        value,
        {
            "dependency_503",
            "direct_registry_closed",
            "existing_pull",
            "new_push_accounted",
            "over_quota_429",
            "project_isolation",
            "quota_edge_forced",
            "reconciliation",
            "restart_persistence",
        },
        "admission cutover",
    )


def _validate_rollback_recovery(value: object) -> dict[str, Any]:
    rollback = _mapping(value, "rollback and recovery")
    _exact_keys(
        rollback,
        {
            "active_uploads",
            "admission_checks",
            "ambiguous_differences",
            "authenticated_comparison",
            "backup_recovery",
            "original_digest_readable",
            "post_cutover_write_count",
            "pull_digest_match",
            "removed_post_cutover_write_count",
            "writer_fence_reapplied",
        },
        "rollback and recovery",
    )
    writes = _nonnegative_integer(
        rollback["post_cutover_write_count"],
        "post-cutover write count",
    )
    removed = _nonnegative_integer(
        rollback["removed_post_cutover_write_count"],
        "removed post-cutover write count",
    )
    if (
        rollback["active_uploads"] != 0
        or rollback["ambiguous_differences"] != 0
        or writes != removed
        or any(
            rollback[name] is not True
            for name in (
                "admission_checks",
                "authenticated_comparison",
                "backup_recovery",
                "original_digest_readable",
                "pull_digest_match",
                "writer_fence_reapplied",
            )
        )
    ):
        raise DataProtectionResultError(
            "rollback and recovery are not qualified"
        )
    return {
        **dict(rollback),
        "post_cutover_write_count": writes,
        "removed_post_cutover_write_count": removed,
    }


def _validate_failures(value: object) -> dict[str, bool]:
    failures = _mapping(value, "data-protection failure matrix")
    expected = set(STATE_MACHINE.EXPECTED_FAILURE_CASES)
    if set(failures) != expected or any(
        failures[name] is not True for name in expected
    ):
        raise DataProtectionResultError(
            "data-protection failure matrix is incomplete"
        )
    return {name: True for name in STATE_MACHINE.EXPECTED_FAILURE_CASES}


def _validate_unrelated(value: object) -> dict[str, Any]:
    unrelated = _mapping(value, "unrelated state")
    _exact_keys(
        unrelated,
        {"after_sha256", "before_sha256", "unchanged"},
        "unrelated state",
    )
    before = _digest(unrelated["before_sha256"], "unrelated before state")
    after = _digest(unrelated["after_sha256"], "unrelated after state")
    if unrelated["unchanged"] is not True or before != after:
        raise DataProtectionResultError("unrelated state changed")
    return {"sha256": before, "unchanged": True}


def _validate_residue(value: object) -> dict[str, int]:
    residue = _mapping(value, "data-protection residue")
    names = set(STATE_MACHINE.EXPECTED_RESIDUE_KEYS) | {
        "known_secret_matches",
        "total",
    }
    _exact_keys(residue, names, "data-protection residue")
    result = {
        name: _nonnegative_integer(
            residue[name],
            f"data-protection {name} residue",
        )
        for name in names
    }
    if any(result.values()) or result["total"] != sum(
        result[name] for name in names if name != "total"
    ):
        raise DataProtectionResultError("data-protection residue remains")
    return {name: 0 for name in sorted(names)}


def _validate_evidence_hashes(value: object) -> dict[str, str]:
    hashes = _mapping(value, "data-protection evidence hashes")
    names = {
        "backup_restore_sha256",
        "cutover_sha256",
        "failure_matrix_sha256",
        "inventory_import_sha256",
        "lifecycle_sha256",
        "rollback_recovery_sha256",
        "teardown_sha256",
        "unrelated_state_sha256",
        "writer_exclusion_sha256",
    }
    _exact_keys(hashes, names, "data-protection evidence hashes")
    return {
        name: _digest(hashes[name], f"data-protection {name}")
        for name in sorted(names)
    }


def _validate_evidence(
    value: object,
    *,
    prerequisites: Mapping[str, str],
) -> dict[str, Any]:
    evidence = _mapping(value, "data-protection evidence")
    _exact_keys(
        evidence,
        {
            "backup_restore",
            "cutover",
            "evidence_sha256",
            "execution",
            "failure_matrix",
            "inventory_import",
            "lifecycle",
            "prerequisites",
            "residue",
            "rollback_recovery",
            "schema",
            "source",
            "unrelated_state",
            "writer_exclusion",
        },
        "data-protection evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["prerequisites"] != prerequisites
        or evidence["source"] != runtime_source_hashes()
    ):
        raise DataProtectionResultError(
            "data-protection evidence binding changed"
        )
    return {
        "backup_restore": _validate_backup_restore(
            evidence["backup_restore"]
        ),
        "cutover": _validate_cutover(evidence["cutover"]),
        "evidence_sha256": _validate_evidence_hashes(
            evidence["evidence_sha256"]
        ),
        "execution": _validate_execution(evidence["execution"]),
        "failure_matrix": _validate_failures(evidence["failure_matrix"]),
        "inventory_import": _validate_inventory_import(
            evidence["inventory_import"]
        ),
        "lifecycle": _validate_lifecycle(evidence["lifecycle"]),
        "residue": _validate_residue(evidence["residue"]),
        "rollback_recovery": _validate_rollback_recovery(
            evidence["rollback_recovery"]
        ),
        "unrelated_state": _validate_unrelated(
            evidence["unrelated_state"]
        ),
        "writer_exclusion": _validate_writer_exclusion(
            evidence["writer_exclusion"]
        ),
    }


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    maintenance_result: object,
    maintenance_digest: str,
    evidence: object,
    evidence_digest: str,
) -> dict[str, Any]:
    prerequisites = _qualified_prerequisites(
        release_readiness=release_readiness,
        release_digest=release_digest,
        artifact_result=artifact_result,
        artifact_digest=artifact_digest,
        rgw_kms_result=rgw_kms_result,
        rgw_kms_digest=rgw_kms_digest,
        maintenance_result=maintenance_result,
        maintenance_digest=maintenance_digest,
    )
    validated = _validate_evidence(
        evidence,
        prerequisites=prerequisites,
    )
    return {
        **validated,
        "input_evidence_sha256": _digest(
            evidence_digest,
            "data-protection input evidence",
        ),
        "prerequisites": prerequisites,
        "production_candidate": True,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "data-protection result"))
    expected = {
        "backup_restore",
        "cutover",
        "evidence_sha256",
        "execution",
        "failure_matrix",
        "input_evidence_sha256",
        "inventory_import",
        "lifecycle",
        "prerequisites",
        "production_candidate",
        "residue",
        "rollback_recovery",
        "schema",
        "source",
        "unrelated_state",
        "writer_exclusion",
    }
    _exact_keys(result, expected, "data-protection result")
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise DataProtectionResultError(
            "data-protection result is not qualified"
        )
    prerequisites = _mapping(
        result["prerequisites"],
        "data-protection prerequisites",
    )
    expected_prerequisites = {
        "artifact_result_sha256",
        "maintenance_identity_result_sha256",
        "release_readiness_sha256",
        "rgw_kms_result_sha256",
    }
    _exact_keys(
        prerequisites,
        expected_prerequisites,
        "data-protection prerequisites",
    )
    for name in expected_prerequisites:
        _digest(prerequisites[name], f"data-protection prerequisite {name}")
    _digest(result["input_evidence_sha256"], "data-protection input evidence")
    lifecycle = _mapping(result["lifecycle"], "data-protection lifecycle")
    _exact_keys(
        lifecycle,
        {"phase_evidence_sha256", "terminal_phase"},
        "data-protection lifecycle",
    )
    if lifecycle["terminal_phase"] != "torn-down":
        raise DataProtectionResultError(
            "data-protection terminal lifecycle is not qualified"
        )
    _digest(lifecycle["phase_evidence_sha256"], "phase evidence")
    _validate_execution(result["execution"])
    _validate_writer_exclusion(result["writer_exclusion"])
    _validate_backup_restore(result["backup_restore"])
    _validate_inventory_import(result["inventory_import"])
    _validate_cutover(result["cutover"])
    _validate_rollback_recovery(result["rollback_recovery"])
    _validate_failures(result["failure_matrix"])
    unrelated = _mapping(result["unrelated_state"], "unrelated state")
    _exact_keys(unrelated, {"sha256", "unchanged"}, "unrelated state")
    _digest(unrelated["sha256"], "unrelated state")
    if unrelated["unchanged"] is not True:
        raise DataProtectionResultError("unrelated state changed")
    _validate_residue(result["residue"])
    _validate_evidence_hashes(result["evidence_sha256"])
    return result


def _load_private(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
        ):
            raise DataProtectionResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise DataProtectionResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except DataProtectionResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DataProtectionResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise DataProtectionResultError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise DataProtectionResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise DataProtectionResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise DataProtectionResultError(
            "output directory ownership is unsafe"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError as error:
        raise DataProtectionResultError(
            "unable to write data-protection result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _load_prerequisite(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], str]:
    try:
        return _load_private(path, label)
    except DataProtectionResultError as error:
        raise DataProtectionInputsBlocked(
            f"{label} is absent or unsafe"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile non-synthetic writer-excluded backup, cutover, "
            "rollback, recovery, and teardown evidence only after every "
            "earlier promotion prerequisite qualifies."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--artifact-result", type=Path, required=True)
    parser.add_argument("--rgw-kms-result", type=Path, required=True)
    parser.add_argument(
        "--maintenance-identity-result",
        type=Path,
        required=True,
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness,
            "release readiness",
        )
        try:
            RGW_KMS_RESULT.require_release_qualified(release)
        except RGW_KMS_RESULT.RgwKmsInputsBlocked as error:
            raise DataProtectionInputsBlocked(str(error)) from error
        artifact, artifact_digest = _load_prerequisite(
            arguments.artifact_result,
            "artifact specialist result",
        )
        rgw_kms, rgw_kms_digest = _load_prerequisite(
            arguments.rgw_kms_result,
            "RGW/KMS specialist result",
        )
        maintenance, maintenance_digest = _load_prerequisite(
            arguments.maintenance_identity_result,
            "maintenance identity specialist result",
        )
        prerequisites = _qualified_prerequisites(
            release_readiness=release,
            release_digest=release_digest,
            artifact_result=artifact,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_result=maintenance,
            maintenance_digest=maintenance_digest,
        )
        evidence, evidence_digest = _load_private(
            arguments.evidence,
            "data-protection evidence",
        )
        if evidence.get("prerequisites") != prerequisites:
            raise DataProtectionResultError(
                "data-protection evidence prerequisite binding changed"
            )
        result = compile_result(
            release_readiness=release,
            release_digest=release_digest,
            artifact_result=artifact,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_result=maintenance,
            maintenance_digest=maintenance_digest,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except DataProtectionInputsBlocked as error:
        print(
            f"production data-protection gate blocked: {error}",
            file=sys.stderr,
        )
        return 3
    except DataProtectionResultError as error:
        print(
            f"production data-protection result error: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
