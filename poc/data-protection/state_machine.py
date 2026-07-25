from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


TOPOLOGY_SCHEMA = "coffer.data-protection-topology/v1"
STATE_SCHEMA = "coffer.data-protection-state/v1"
EVIDENCE_SCHEMA = "coffer.data-protection-evidence/v1"
INVOCATION_PATTERN = re.compile(r"^[0-9a-hjkmnp-tv-z]{26}$")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TARGET_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMMUTABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{7,255}$")
EXPECTED_PHASES = (
    "preflighted",
    "source-created",
    "fixture-populated",
    "writers-excluded",
    "backups-verified",
    "inventory-verified",
    "baseline-imported",
    "live-comparison-verified",
    "admission-cutover",
    "cutover-verified",
    "rollback-verified",
    "restore-verified",
    "failures-verified",
    "torn-down",
)
EXPECTED_RESOURCE_KEYS = (
    "project",
    "tenant-credential",
    "rgw-user-source",
    "rgw-user-backup",
    "rgw-user-restore",
    "bucket-source",
    "bucket-backup",
    "bucket-restore",
    "database-source",
    "database-cutover",
    "database-restore",
    "distribution-source",
    "distribution-cutover",
    "distribution-restore",
    "maintenance-session",
    "ingress-mapping",
    "config-tree",
    "volume-source",
    "volume-backup",
    "volume-restore",
    "network",
)
EXPECTED_CLEANUP_ORDER = (
    "maintenance_session",
    "ingress_mapping",
    "distribution",
    "database",
    "bucket",
    "rgw_user",
    "tenant_credential",
    "project",
    "config_tree",
    "volume",
    "network",
)
EXPECTED_RESIDUE_KEYS = (
    "identities",
    "credentials",
    "sessions",
    "ingress_mappings",
    "buckets",
    "object_versions",
    "multipart_uploads",
    "databases",
    "distributions",
    "containers",
    "config_trees",
    "materialized_files",
    "volumes",
    "networks",
    "temporary_files",
    "locks",
)
EXPECTED_FAILURE_CASES = (
    "sql-backup-interrupted",
    "sql-backup-corrupt",
    "sql-restore-failed",
    "rgw-pagination-drift",
    "rgw-object-read-failed",
    "rgw-backup-corrupt",
    "rgw-multipart-incomplete",
    "kms-wrong-key",
    "rgw-restore-interrupted",
    "source-signature-changed",
    "helper-provenance-mismatch",
    "helper-insecure-tls",
    "import-transaction-failed",
    "import-conflicting-replay",
    "import-deadlock-retry",
    "maintenance-identity-outage",
    "private-frontend-outage",
    "api-outage",
    "distribution-outage",
    "cutover-partial-failure",
    "rollback-interrupted",
    "replica-loss",
)
PHASE_EVIDENCE_KEYS = {
    "preflighted": (),
    "source-created": (),
    "fixture-populated": ("fixture",),
    "writers-excluded": ("fixture", "writer_fence"),
    "backups-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
    ),
    "inventory-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
    ),
    "baseline-imported": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
    ),
    "live-comparison-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
    ),
    "admission-cutover": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
    ),
    "cutover-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
        "cutover_verification",
    ),
    "rollback-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
        "cutover_verification",
        "rollback",
    ),
    "restore-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
        "cutover_verification",
        "rollback",
        "restore",
    ),
    "failures-verified": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
        "cutover_verification",
        "rollback",
        "restore",
        "failure_outcomes",
    ),
    "torn-down": (
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
        "cutover_verification",
        "rollback",
        "restore",
        "failure_outcomes",
    ),
}
PHASE_ACTIONS = (
    "preflight",
    "create-source",
    "populate-fixture",
    "exclude-writers",
    "verify-backups",
    "verify-inventory",
    "import-baseline",
    "verify-live-comparison",
    "cutover-admission",
    "verify-cutover",
    "verify-rollback",
    "verify-restore",
    "verify-failures",
    "teardown",
)
RESOURCE_KIND_BY_PREFIX = {
    "project": "project",
    "tenant-credential": "tenant_credential",
    "rgw-user": "rgw_user",
    "bucket": "bucket",
    "database": "database",
    "distribution": "distribution",
    "maintenance-session": "maintenance_session",
    "ingress-mapping": "ingress_mapping",
    "config-tree": "config_tree",
    "volume": "volume",
    "network": "network",
}
FORBIDDEN_KEYS = frozenset(
    {
        "access_key",
        "authorization",
        "barbican_secret_uuid",
        "database_url",
        "password",
        "private_key",
        "repository_name",
        "secret",
        "secret_key",
        "tenant_path",
        "token",
    }
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
)


class DataProtectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Topology:
    invocation_prefix: str
    work_root: str
    phases: tuple[str, ...]
    resource_keys: tuple[str, ...]
    cleanup_order: tuple[str, ...]
    residue_keys: tuple[str, ...]
    failure_cases: tuple[str, ...]
    digest: str


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DataProtectionError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise DataProtectionError(f"{label} must be an array")
    return value


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_topology(path: Path) -> Topology:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataProtectionError("unable to load data-protection topology") from error
    return validate_topology(value)


def validate_topology(value: object) -> Topology:
    raw = _mapping(value, "topology")
    if set(raw) != {
        "schema",
        "invocation_prefix",
        "work_root",
        "phases",
        "resource_keys",
        "cleanup_order",
        "residue_keys",
        "failure_cases",
    }:
        raise DataProtectionError("topology fields are invalid")
    if raw["schema"] != TOPOLOGY_SCHEMA:
        raise DataProtectionError("topology schema is unsupported")
    if raw["invocation_prefix"] != "coffer-cutover":
        raise DataProtectionError("topology invocation prefix is invalid")
    work_root = str(raw["work_root"])
    work_path = Path(work_root)
    if (
        work_path.is_absolute()
        or ".." in work_path.parts
        or work_path.parts != ("work", "data-protection")
    ):
        raise DataProtectionError("topology work root is outside the fixed boundary")
    phases = tuple(str(item) for item in _array(raw["phases"], "phases"))
    resource_keys = tuple(
        str(item) for item in _array(raw["resource_keys"], "resource keys")
    )
    cleanup_order = tuple(
        str(item) for item in _array(raw["cleanup_order"], "cleanup order")
    )
    residue_keys = tuple(
        str(item) for item in _array(raw["residue_keys"], "residue keys")
    )
    failure_cases = tuple(
        str(item) for item in _array(raw["failure_cases"], "failure cases")
    )
    if phases != EXPECTED_PHASES:
        raise DataProtectionError("topology phases expand or reorder the contract")
    if resource_keys != EXPECTED_RESOURCE_KEYS:
        raise DataProtectionError("topology resources expand or reorder the allowlist")
    if cleanup_order != EXPECTED_CLEANUP_ORDER:
        raise DataProtectionError("topology cleanup order is invalid")
    if residue_keys != EXPECTED_RESIDUE_KEYS:
        raise DataProtectionError("topology residue keys are invalid")
    if failure_cases != EXPECTED_FAILURE_CASES:
        raise DataProtectionError("topology failure matrix is invalid")
    return Topology(
        invocation_prefix="coffer-cutover",
        work_root=work_root,
        phases=phases,
        resource_keys=resource_keys,
        cleanup_order=cleanup_order,
        residue_keys=residue_keys,
        failure_cases=failure_cases,
        digest=_canonical_digest(raw),
    )


def _timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise DataProtectionError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_retained_payload(
    value: object,
    *,
    known_secrets: Iterable[str] = (),
) -> None:
    secrets = tuple(item for item in known_secrets if item)
    if any(len(item) < 8 for item in secrets):
        raise DataProtectionError("known secret values must be at least 8 characters")

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in FORBIDDEN_KEYS:
                    raise DataProtectionError("retained payload has a forbidden field")
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            if any(secret in item for secret in secrets):
                raise DataProtectionError("retained payload contains a known secret")
            if any(pattern.search(item) for pattern in SECRET_PATTERNS):
                raise DataProtectionError("retained payload contains a secret pattern")

    visit(value)


def create_preflight_state(
    topology: Topology,
    invocation_id: str,
    target_signature: str,
    unrelated_signature: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if INVOCATION_PATTERN.fullmatch(invocation_id) is None:
        raise DataProtectionError("invocation ID must be a lowercase ULID")
    if TARGET_PATTERN.fullmatch(target_signature) is None:
        raise DataProtectionError("target signature must be a lowercase SHA-256")
    if SHA256_PATTERN.fullmatch(unrelated_signature) is None:
        raise DataProtectionError("unrelated signature must be canonical SHA-256")
    state: dict[str, object] = {
        "schema": STATE_SCHEMA,
        "topology_digest": topology.digest,
        "invocation_id": invocation_id,
        "target_signature": target_signature,
        "unrelated_signature": unrelated_signature,
        "phase": "preflighted",
        "resources": [],
        "evidence": {},
        "history": [
            {
                "action": "preflight",
                "outcome": "completed",
                "at": _timestamp(now),
            }
        ],
    }
    validate_state(topology, state)
    return state


def _resource_kind(key: str) -> str:
    for prefix, kind in RESOURCE_KIND_BY_PREFIX.items():
        if key == prefix or key.startswith(prefix + "-"):
            return kind
    raise DataProtectionError("resource key has no fixed kind")


def expected_resource_specs(
    topology: Topology,
    invocation_id: str,
) -> dict[str, dict[str, object]]:
    if INVOCATION_PATTERN.fullmatch(invocation_id) is None:
        raise DataProtectionError("invocation ID must be a lowercase ULID")
    prefix = f"{topology.invocation_prefix}-{invocation_id}"
    return {
        key: {
            "kind": _resource_kind(key),
            "name": f"{prefix}-{key}",
            "owned": True,
        }
        for key in topology.resource_keys
    }


def register_source_resources(
    topology: Topology,
    state_value: Mapping[str, object],
    resources_value: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] != "preflighted":
        raise DataProtectionError("source resources can be created only after preflight")
    expected = expected_resource_specs(topology, str(state["invocation_id"]))
    resources = _mapping(resources_value, "resources")
    if set(resources) != set(expected):
        raise DataProtectionError("resource set is incomplete or unexpected")
    ids: set[str] = set()
    registered: list[dict[str, object]] = []
    for key, spec in expected.items():
        resource = dict(_mapping(resources[key], f"resource {key}"))
        if set(resource) != {"id", *spec.keys()}:
            raise DataProtectionError(f"resource {key} has invalid fields")
        if any(resource[field] != value for field, value in spec.items()):
            raise DataProtectionError(f"resource {key} violates the exact allowlist")
        immutable_id = str(resource["id"])
        if (
            IMMUTABLE_ID_PATTERN.fullmatch(immutable_id) is None
            or immutable_id in ids
        ):
            raise DataProtectionError("resource immutable IDs are invalid or repeated")
        ids.add(immutable_id)
        resource["key"] = key
        registered.append(resource)
    state["resources"] = registered
    return _advance(topology, state, "source-created", "create-source", {}, now)


def _exact_digest_fields(
    value: object,
    label: str,
    digest_fields: set[str],
    other_fields: set[str],
) -> dict[str, object]:
    raw = dict(_mapping(value, label))
    if set(raw) != digest_fields | other_fields:
        raise DataProtectionError(f"{label} fields are invalid")
    for field in digest_fields:
        if SHA256_PATTERN.fullmatch(str(raw[field])) is None:
            raise DataProtectionError(f"{label}.{field} is not canonical SHA-256")
    return raw


def _require_phase(
    topology: Topology,
    state: Mapping[str, object],
    phase: str,
) -> None:
    validate_state(topology, state)
    if state["phase"] != phase:
        raise DataProtectionError(f"action requires phase {phase}")


def mark_fixture_populated(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "source-created")
    raw = _exact_digest_fields(
        evidence,
        "fixture evidence",
        {"content_sha256", "source_signature"},
        {
            "manifest_count",
            "blob_count",
            "index_count",
            "artifact_count",
            "zero_byte_blob_count",
            "multipart_upload_count",
        },
    )
    for field in set(raw) - {"content_sha256", "source_signature"}:
        if (
            not isinstance(raw[field], int)
            or isinstance(raw[field], bool)
            or raw[field] < 0
        ):
            raise DataProtectionError("fixture counts must be nonnegative integers")
    if raw["manifest_count"] < 3 or raw["blob_count"] < 2:
        raise DataProtectionError("fixture coverage is incomplete")
    return _advance(
        topology,
        state,
        "fixture-populated",
        "populate-fixture",
        {"fixture": raw},
        now,
    )


def mark_writers_excluded(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "fixture-populated")
    raw = _exact_digest_fields(
        evidence,
        "writer fence",
        {
            "ingress_config_sha256",
            "replica_set_sha256",
            "disabled_workers_sha256",
            "database_fence_sha256",
            "source_signature",
        },
        {
            "active_uploads",
            "unknown_listeners",
            "canary_write_status",
            "digest_read_status",
        },
    )
    if (
        raw["active_uploads"] != 0
        or raw["unknown_listeners"] != 0
        or raw["canary_write_status"] not in {403, 405}
        or raw["digest_read_status"] != 200
    ):
        raise DataProtectionError("writer fence does not prove closed writes")
    prior = _mapping(_mapping(state["evidence"], "state evidence")["fixture"], "fixture")
    if raw["source_signature"] != prior["source_signature"]:
        raise DataProtectionError("source signature changed before writer exclusion")
    return _advance(
        topology,
        state,
        "writers-excluded",
        "exclude-writers",
        {"writer_fence": raw},
        now,
    )


def mark_backups_verified(
    topology: Topology,
    state: Mapping[str, object],
    sql_value: object,
    rgw_value: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "writers-excluded")
    sql = _exact_digest_fields(
        sql_value,
        "SQL backup",
        {
            "backup_sha256",
            "restore_sha256",
            "schema_sha256",
            "recovery_coordinate_sha256",
        },
        {"bytes", "row_count", "restored"},
    )
    rgw = _exact_digest_fields(
        rgw_value,
        "RGW backup",
        {
            "manifest_sha256",
            "source_inventory_sha256",
            "restore_inventory_sha256",
            "metadata_sha256",
            "source_signature",
        },
        {
            "bytes",
            "object_count",
            "version_count",
            "multipart_upload_count",
            "restored",
        },
    )
    for label, evidence in (("SQL", sql), ("RGW", rgw)):
        if evidence["restored"] is not True:
            raise DataProtectionError(f"{label} backup was not restored")
        for field in set(evidence) - {
            "restored",
            *(
                {
                    "backup_sha256",
                    "restore_sha256",
                    "schema_sha256",
                    "recovery_coordinate_sha256",
                }
                if label == "SQL"
                else {
                    "manifest_sha256",
                    "source_inventory_sha256",
                    "restore_inventory_sha256",
                    "metadata_sha256",
                    "source_signature",
                }
            ),
        }:
            if (
                not isinstance(evidence[field], int)
                or isinstance(evidence[field], bool)
                or evidence[field] < 0
            ):
                raise DataProtectionError(f"{label} backup counts are invalid")
    if sql["backup_sha256"] != sql["restore_sha256"]:
        raise DataProtectionError("SQL restore digest does not match backup")
    if rgw["multipart_upload_count"] != 0:
        raise DataProtectionError("RGW backup has incomplete multipart uploads")
    if rgw["source_inventory_sha256"] != rgw["restore_inventory_sha256"]:
        raise DataProtectionError("RGW restore inventory does not match backup")
    fence = _mapping(
        _mapping(state["evidence"], "state evidence")["writer_fence"],
        "writer fence",
    )
    if rgw["source_signature"] != fence["source_signature"]:
        raise DataProtectionError("RGW backup source signature changed")
    return _advance(
        topology,
        state,
        "backups-verified",
        "verify-backups",
        {"sql_backup": sql, "rgw_backup": rgw},
        now,
    )


def mark_inventory_verified(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "backups-verified")
    raw = _exact_digest_fields(
        evidence,
        "inventory",
        {
            "scan_one_sha256",
            "scan_two_sha256",
            "inventory_sha256",
            "provenance_sha256",
            "source_signature",
        },
        {
            "repository_count",
            "manifest_count",
            "descriptor_count",
            "scans_equal",
        },
    )
    if raw["scans_equal"] is not True:
        raise DataProtectionError("inventory scans are not equal")
    if raw["scan_one_sha256"] != raw["scan_two_sha256"]:
        raise DataProtectionError("inventory scan digests are not equal")
    for field in ("repository_count", "manifest_count", "descriptor_count"):
        if (
            not isinstance(raw[field], int)
            or isinstance(raw[field], bool)
            or raw[field] <= 0
        ):
            raise DataProtectionError("inventory counts must be positive")
    fence = _mapping(
        _mapping(state["evidence"], "state evidence")["writer_fence"],
        "writer fence",
    )
    if raw["source_signature"] != fence["source_signature"]:
        raise DataProtectionError("inventory source signature changed")
    return _advance(
        topology,
        state,
        "inventory-verified",
        "verify-inventory",
        {"inventory": raw},
        now,
    )


def mark_baseline_imported(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "inventory-verified")
    raw = _exact_digest_fields(
        evidence,
        "baseline import",
        {"inventory_sha256", "database_sha256"},
        {
            "status",
            "idempotent_replay",
            "conflicting_replay_refused",
            "partial_rows",
        },
    )
    inventory = _mapping(
        _mapping(state["evidence"], "state evidence")["inventory"],
        "inventory",
    )
    if (
        raw["inventory_sha256"] != inventory["inventory_sha256"]
        or raw["status"] != "imported"
        or raw["idempotent_replay"] is not True
        or raw["conflicting_replay_refused"] is not True
        or raw["partial_rows"] != 0
    ):
        raise DataProtectionError("baseline import evidence is incomplete")
    return _advance(
        topology,
        state,
        "baseline-imported",
        "import-baseline",
        {"baseline_import": raw},
        now,
    )


def mark_live_comparison_verified(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "baseline-imported")
    raw = _exact_digest_fields(
        evidence,
        "live comparison",
        {"inventory_sha256", "session_sha256", "workload_sha256"},
        {
            "expected_manifest_count",
            "verified_manifest_count",
            "failure_count",
            "private_tls_verified",
            "pull_only",
            "session_closed",
        },
    )
    inventory = _mapping(
        _mapping(state["evidence"], "state evidence")["inventory"],
        "inventory",
    )
    if (
        raw["inventory_sha256"] != inventory["inventory_sha256"]
        or raw["expected_manifest_count"] != inventory["manifest_count"]
        or raw["verified_manifest_count"] != raw["expected_manifest_count"]
        or raw["failure_count"] != 0
        or raw["private_tls_verified"] is not True
        or raw["pull_only"] is not True
        or raw["session_closed"] is not True
    ):
        raise DataProtectionError("live comparison evidence is incomplete")
    return _advance(
        topology,
        state,
        "live-comparison-verified",
        "verify-live-comparison",
        {"live_comparison": raw},
        now,
    )


def cutover_marker_digest(
    topology: Topology,
    state: Mapping[str, object],
    routing_sha256: str,
    database_sha256: str,
) -> str:
    _require_phase(topology, state, "live-comparison-verified")
    if (
        SHA256_PATTERN.fullmatch(routing_sha256) is None
        or SHA256_PATTERN.fullmatch(database_sha256) is None
    ):
        raise DataProtectionError("cutover marker inputs are not canonical SHA-256")
    evidence = _mapping(state["evidence"], "state evidence")
    writer_fence = _mapping(evidence["writer_fence"], "writer fence")
    sql_backup = _mapping(evidence["sql_backup"], "SQL backup")
    rgw_backup = _mapping(evidence["rgw_backup"], "RGW backup")
    inventory = _mapping(evidence["inventory"], "inventory")
    baseline_import = _mapping(evidence["baseline_import"], "baseline import")
    live_comparison = _mapping(evidence["live_comparison"], "live comparison")
    return _canonical_digest(
        {
            "topology_digest": topology.digest,
            "invocation_id": state["invocation_id"],
            "target_signature": state["target_signature"],
            "writer_fence": {
                "ingress_config_sha256": writer_fence["ingress_config_sha256"],
                "source_signature": writer_fence["source_signature"],
            },
            "sql_backup_sha256": sql_backup["backup_sha256"],
            "rgw_manifest_sha256": rgw_backup["manifest_sha256"],
            "inventory_sha256": inventory["inventory_sha256"],
            "provenance_sha256": inventory["provenance_sha256"],
            "baseline_database_sha256": baseline_import["database_sha256"],
            "maintenance_session_sha256": live_comparison["session_sha256"],
            "maintenance_workload_sha256": live_comparison["workload_sha256"],
            "routing_sha256": routing_sha256,
            "database_sha256": database_sha256,
        }
    )


def mark_admission_cutover(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "live-comparison-verified")
    raw = _exact_digest_fields(
        evidence,
        "admission cutover",
        {"marker_sha256", "routing_sha256", "database_sha256"},
        {
            "quota_edge_forced",
            "direct_registry_closed",
            "writer_fence_released",
        },
    )
    if (
        raw["quota_edge_forced"] is not True
        or raw["direct_registry_closed"] is not True
        or raw["writer_fence_released"] is not True
    ):
        raise DataProtectionError("admission cutover routing is incomplete")
    expected_marker = cutover_marker_digest(
        topology,
        state,
        str(raw["routing_sha256"]),
        str(raw["database_sha256"]),
    )
    if raw["marker_sha256"] != expected_marker:
        raise DataProtectionError("admission cutover marker is not provenance-bound")
    return _advance(
        topology,
        state,
        "admission-cutover",
        "cutover-admission",
        {"admission_cutover": raw},
        now,
    )


def mark_cutover_verified(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "admission-cutover")
    raw = dict(_mapping(evidence, "cutover verification"))
    expected = {
        "existing_pull",
        "new_push_accounted",
        "project_isolation",
        "over_quota_429",
        "dependency_503",
        "restart_persistence",
        "reconciliation",
    }
    if set(raw) != expected or any(raw[field] is not True for field in expected):
        raise DataProtectionError("cutover verification matrix is incomplete")
    return _advance(
        topology,
        state,
        "cutover-verified",
        "verify-cutover",
        {"cutover_verification": raw},
        now,
    )


def mark_rollback_verified(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "cutover-verified")
    raw = _exact_digest_fields(
        evidence,
        "rollback",
        {
            "original_source_sha256",
            "restored_source_sha256",
            "routing_sha256",
            "rollback_manifest_sha256",
        },
        {
            "writer_fence_reapplied",
            "active_uploads",
            "ambiguous_differences",
            "original_digest_readable",
            "post_cutover_write_count",
            "removed_post_cutover_write_count",
        },
    )
    if (
        raw["original_source_sha256"] != raw["restored_source_sha256"]
        or raw["writer_fence_reapplied"] is not True
        or raw["active_uploads"] != 0
        or raw["ambiguous_differences"] != 0
        or raw["original_digest_readable"] is not True
        or not isinstance(raw["post_cutover_write_count"], int)
        or isinstance(raw["post_cutover_write_count"], bool)
        or raw["post_cutover_write_count"] < 0
        or raw["removed_post_cutover_write_count"]
        != raw["post_cutover_write_count"]
    ):
        raise DataProtectionError("rollback evidence is incomplete")
    return _advance(
        topology,
        state,
        "rollback-verified",
        "verify-rollback",
        {"rollback": raw},
        now,
    )


def mark_restore_verified(
    topology: Topology,
    state: Mapping[str, object],
    evidence: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "rollback-verified")
    raw = _exact_digest_fields(
        evidence,
        "restore",
        {
            "sql_backup_sha256",
            "sql_restore_sha256",
            "rgw_manifest_sha256",
            "inventory_sha256",
        },
        {
            "authenticated_comparison",
            "pull_digest_match",
            "admission_checks",
        },
    )
    backups = _mapping(state["evidence"], "state evidence")
    sql = _mapping(backups["sql_backup"], "SQL backup")
    rgw = _mapping(backups["rgw_backup"], "RGW backup")
    inventory = _mapping(backups["inventory"], "inventory")
    if (
        raw["sql_backup_sha256"] != sql["backup_sha256"]
        or raw["sql_restore_sha256"] != sql["restore_sha256"]
        or raw["rgw_manifest_sha256"] != rgw["manifest_sha256"]
        or raw["inventory_sha256"] != inventory["inventory_sha256"]
        or raw["authenticated_comparison"] is not True
        or raw["pull_digest_match"] is not True
        or raw["admission_checks"] is not True
    ):
        raise DataProtectionError("restore evidence is incomplete")
    return _advance(
        topology,
        state,
        "restore-verified",
        "verify-restore",
        {"restore": raw},
        now,
    )


def mark_failures_verified(
    topology: Topology,
    state: Mapping[str, object],
    outcomes_value: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _require_phase(topology, state, "restore-verified")
    outcomes = dict(_mapping(outcomes_value, "failure outcomes"))
    if set(outcomes) != set(topology.failure_cases) or any(
        value != "passed" for value in outcomes.values()
    ):
        raise DataProtectionError("failure matrix is incomplete")
    return _advance(
        topology,
        state,
        "failures-verified",
        "verify-failures",
        {"failure_outcomes": outcomes},
        now,
    )


def _advance(
    topology: Topology,
    state_value: Mapping[str, object],
    next_phase: str,
    action: str,
    evidence: Mapping[str, object],
    now: datetime | None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    current_index = topology.phases.index(str(state["phase"]))
    if current_index + 1 >= len(topology.phases):
        raise DataProtectionError("terminal state cannot advance")
    if topology.phases[current_index + 1] != next_phase:
        raise DataProtectionError(
            f"{next_phase} cannot follow {state['phase']}"
        )
    retained = dict(_mapping(state["evidence"], "state evidence"))
    if set(retained) & set(evidence):
        raise DataProtectionError("phase evidence cannot be overwritten")
    retained.update(deepcopy(dict(evidence)))
    validate_retained_payload(retained)
    history = list(_array(state["history"], "history"))
    history.append(
        {
            "action": action,
            "outcome": "completed",
            "at": _timestamp(now),
        }
    )
    state["phase"] = next_phase
    state["evidence"] = retained
    state["history"] = history
    validate_state(topology, state)
    return state


def validate_state(topology: Topology, value: object) -> None:
    state = _mapping(value, "state")
    phase = str(state.get("phase"))
    expected_fields = {
        "schema",
        "topology_digest",
        "invocation_id",
        "target_signature",
        "unrelated_signature",
        "phase",
        "resources",
        "evidence",
        "history",
    }
    if phase == "torn-down":
        expected_fields.add("residue_counts")
    if set(state) != expected_fields:
        raise DataProtectionError("state fields are invalid for its phase")
    if state.get("schema") != STATE_SCHEMA:
        raise DataProtectionError("state schema is unsupported")
    if state.get("topology_digest") != topology.digest:
        raise DataProtectionError("state topology digest does not match")
    if INVOCATION_PATTERN.fullmatch(str(state.get("invocation_id"))) is None:
        raise DataProtectionError("state invocation ID is invalid")
    if TARGET_PATTERN.fullmatch(str(state.get("target_signature"))) is None:
        raise DataProtectionError("state target signature is invalid")
    if SHA256_PATTERN.fullmatch(str(state.get("unrelated_signature"))) is None:
        raise DataProtectionError("state unrelated signature is invalid")
    if phase not in topology.phases:
        raise DataProtectionError("state phase is invalid")
    resources = _array(state.get("resources"), "resources")
    expected = expected_resource_specs(topology, str(state["invocation_id"]))
    if resources:
        if len(resources) != len(expected):
            raise DataProtectionError("state resource count is invalid")
        ids: set[str] = set()
        keys: set[str] = set()
        for value_item in resources:
            item = _mapping(value_item, "resource")
            if set(item) != {"id", "key", "kind", "name", "owned"}:
                raise DataProtectionError("state resource fields are invalid")
            key = str(item["key"])
            if key not in expected or any(
                item[field] != expected[key][field]
                for field in ("kind", "name", "owned")
            ):
                raise DataProtectionError("state resource violates the allowlist")
            immutable_id = str(item["id"])
            if (
                IMMUTABLE_ID_PATTERN.fullmatch(immutable_id) is None
                or immutable_id in ids
                or key in keys
            ):
                raise DataProtectionError("state resource identity is invalid")
            ids.add(immutable_id)
            keys.add(key)
        if keys != set(expected):
            raise DataProtectionError("state resource keys are incomplete")
    if phase in {"preflighted", "torn-down"} and resources:
        raise DataProtectionError("boundary state must not retain resources")
    if phase not in {"preflighted", "torn-down"} and not resources:
        raise DataProtectionError("active state has no owned resources")
    evidence = _mapping(state.get("evidence"), "state evidence")
    if set(evidence) != set(PHASE_EVIDENCE_KEYS[phase]):
        raise DataProtectionError("state evidence does not match its phase")
    validate_retained_payload(evidence)
    history = _array(state.get("history"), "history")
    phase_index = topology.phases.index(phase)
    expected_actions = PHASE_ACTIONS[: phase_index + 1]
    if len(history) != len(expected_actions):
        raise DataProtectionError("state history length does not match its phase")
    previous_at: datetime | None = None
    for item_value, expected_action in zip(history, expected_actions, strict=True):
        item = _mapping(item_value, "history item")
        if (
            set(item) != {"action", "outcome", "at"}
            or item["action"] != expected_action
            or item["outcome"] != "completed"
            or not isinstance(item["at"], str)
        ):
            raise DataProtectionError("state history is invalid")
        try:
            at = datetime.fromisoformat(item["at"].replace("Z", "+00:00"))
        except ValueError as error:
            raise DataProtectionError("state history timestamp is invalid") from error
        if at.tzinfo is None or _timestamp(at) != item["at"]:
            raise DataProtectionError("state history timestamp is not canonical UTC")
        if previous_at is not None and at < previous_at:
            raise DataProtectionError("state history is not monotonic")
        previous_at = at
    validate_retained_payload(history)
    if phase == "torn-down":
        residue = _mapping(state.get("residue_counts"), "residue counts")
        if set(residue) != set(topology.residue_keys) or any(
            not isinstance(count, int)
            or isinstance(count, bool)
            or count != 0
            for count in residue.values()
        ):
            raise DataProtectionError(
                "terminal residue counts must contain exact explicit zeroes"
            )


def cleanup_plan(
    topology: Topology,
    state: Mapping[str, object],
) -> list[dict[str, str]]:
    validate_state(topology, state)
    rank = {kind: index for index, kind in enumerate(topology.cleanup_order)}
    resources = [
        _mapping(item, "resource")
        for item in state["resources"]
        if _mapping(item, "resource")["owned"] is True
    ]
    resources.sort(
        key=lambda item: (
            rank[str(item["kind"])],
            str(item["key"]),
        )
    )
    return [
        {
            "kind": str(item["kind"]),
            "id": str(item["id"]),
            "name": str(item["name"]),
        }
        for item in resources
    ]


def assert_exact_cleanup_target(
    topology: Topology,
    state: Mapping[str, object],
    target_value: Mapping[str, object],
) -> None:
    validate_state(topology, state)
    target = dict(_mapping(target_value, "cleanup target"))
    if set(target) != {"kind", "id", "name"}:
        raise DataProtectionError("cleanup target fields are invalid")
    if target not in cleanup_plan(topology, state):
        raise DataProtectionError("cleanup target is not an exact owned resource")


def finalize_teardown(
    topology: Topology,
    state_value: Mapping[str, object],
    removed_targets: Sequence[Mapping[str, object]],
    residue_counts: Mapping[str, object],
    unrelated_signature: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] == "torn-down":
        return state
    if state["phase"] != "failures-verified":
        raise DataProtectionError("teardown requires the complete failure matrix")
    expected = cleanup_plan(topology, state)
    if [dict(item) for item in removed_targets] != expected:
        raise DataProtectionError("removed targets do not match the cleanup plan")
    residue = dict(_mapping(residue_counts, "residue counts"))
    if set(residue) != set(topology.residue_keys) or any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != 0
        for value in residue.values()
    ):
        raise DataProtectionError(
            "residue counts must contain exact explicit zeroes"
        )
    if unrelated_signature != state["unrelated_signature"]:
        raise DataProtectionError("unrelated resource signature changed")
    state["resources"] = []
    state["residue_counts"] = residue
    state["phase"] = "torn-down"
    history = list(_array(state["history"], "history"))
    history.append(
        {
            "action": "teardown",
            "outcome": "completed",
            "at": _timestamp(now),
        }
    )
    state["history"] = history
    validate_state(topology, state)
    return state


def redacted_evidence(
    topology: Topology,
    state: Mapping[str, object],
    *,
    known_secrets: Iterable[str] = (),
) -> dict[str, object]:
    validate_state(topology, state)
    counts = {
        kind: sum(
            1
            for resource in state["resources"]
            if _mapping(resource, "resource")["kind"] == kind
        )
        for kind in topology.cleanup_order
    }
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "topology_digest": topology.digest,
        "invocation_id": state["invocation_id"],
        "target_signature": state["target_signature"],
        "unrelated_signature": state["unrelated_signature"],
        "phase": state["phase"],
        "resource_counts": counts,
        "resource_id_hashes": sorted(
            f"sha256:{hashlib.sha256(str(resource['id']).encode()).hexdigest()}"
            for resource in state["resources"]
        ),
        "phase_evidence_sha256": _canonical_digest(state["evidence"]),
    }
    validate_retained_payload(evidence, known_secrets=known_secrets)
    return evidence
