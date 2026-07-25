from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


TOPOLOGY_SCHEMA = "coffer.gc-retention-topology/v1"
STATE_SCHEMA = "coffer.gc-retention-state/v1"
EVIDENCE_SCHEMA = "coffer.gc-retention-evidence/v1"
INVOCATION_PATTERN = re.compile(r"^[0-9a-hjkmnp-tv-z]{26}$")
RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{7,255}$")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")

EXPECTED_PHASES = (
    "preflighted",
    "source-created",
    "fixture-populated",
    "logical-delete-applied",
    "writers-excluded",
    "backups-verified",
    "baseline-verified",
    "dry-run-one-verified",
    "dry-run-two-verified",
    "collection-authorized",
    "collection-executed",
    "survivors-verified",
    "reclaim-verified",
    "restore-verified",
    "failures-verified",
    "torn-down",
)
EXPECTED_RESOURCE_KEYS = (
    "bucket-source",
    "bucket-backup",
    "bucket-restore",
    "database-source",
    "database-restore",
    "registry-replica-a",
    "registry-replica-b",
    "gc-job",
    "config-tree",
    "network",
    "evidence-file",
)
EXPECTED_CLEANUP_ORDER = (
    "gc_job",
    "registry",
    "database",
    "bucket",
    "config_tree",
    "evidence_file",
    "network",
)
EXPECTED_RESIDUE_KEYS = (
    "buckets",
    "object_versions",
    "delete_markers",
    "multipart_uploads",
    "databases",
    "registries",
    "containers",
    "config_trees",
    "materialized_files",
    "networks",
    "evidence_files",
    "temporary_files",
    "locks",
)
EXPECTED_SURVIVOR_CLASSES = (
    "shared-blob",
    "private-blob",
    "tagged-manifest",
    "index",
    "index-child",
    "digest-only-manifest",
    "subject",
    "referrer",
    "referrers-index",
)
EXPECTED_FAILURE_CASES = (
    "non-disposable-target",
    "incomplete-ownership",
    "writer-path-open",
    "replica-config-drift",
    "active-upload",
    "background-mutator-active",
    "backup-missing",
    "backup-restore-mismatch",
    "inventory-drift",
    "dry-run-output-malformed",
    "dry-run-candidate-drift",
    "candidate-limit-exceeded",
    "retained-content-candidate",
    "delete-untagged-requested",
    "collector-binding-drift",
    "authorization-expired",
    "authorization-replayed",
    "kms-unavailable",
    "rgw-unavailable",
    "collector-interrupted",
    "collector-nonzero-exit",
    "survivor-missing",
    "deleted-content-readable",
    "sql-mutated",
    "reclaim-delta-mismatch",
    "restore-mismatch",
    "rgw-lifecycle-mixed",
    "orphan-delete-mixed",
    "cleanup-residue",
    "unrelated-state-changed",
)
EXPECTED_ACTIONS = (
    "preflight",
    "create-source",
    "populate-fixture",
    "apply-logical-delete",
    "exclude-writers",
    "verify-backups",
    "verify-baseline",
    "verify-dry-run-one",
    "verify-dry-run-two",
    "authorize-collection",
    "execute-collection",
    "verify-survivors",
    "verify-reclaim",
    "verify-restore",
    "verify-failures",
    "teardown",
)
PHASE_BY_ACTION = dict(zip(EXPECTED_ACTIONS, EXPECTED_PHASES, strict=True))
FORBIDDEN_KEYS = frozenset(
    {
        "access_key",
        "authorization_header",
        "barbican_secret_uuid",
        "database_url",
        "endpoint",
        "manifest_digest",
        "object_key",
        "password",
        "private_key",
        "project_id",
        "repository_id",
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


class GCRetentionError(RuntimeError):
    pass


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GCRetentionError(f"{name} must be a SHA-256 evidence hash")
    return value


def _require_int(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GCRetentionError(f"{name} must be an integer >= {minimum}")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise GCRetentionError(f"{name} must be boolean")
    return value


def _require_keys(
    value: Any,
    expected: set[str],
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise GCRetentionError(f"{name} must contain the exact fixed fields")
    return value


def _parse_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise GCRetentionError(f"{name} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GCRetentionError(
            f"{name} must be an RFC3339 UTC timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise GCRetentionError(f"{name} must use UTC")
    return parsed


def _assert_secret_safe(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise GCRetentionError("evidence keys must be strings")
            if key.lower() in FORBIDDEN_KEYS:
                raise GCRetentionError(
                    f"forbidden evidence field: {'.'.join(path + (key,))}"
                )
            _assert_secret_safe(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_secret_safe(child, path + (str(index),))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise GCRetentionError(
                f"secret-like evidence value: {'.'.join(path)}"
            )


def validate_retained_payload(value: Any) -> None:
    _assert_secret_safe(value)


def load_topology(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_topology(raw)
    return raw


def validate_topology(raw: Any) -> None:
    document = _require_keys(
        raw,
        {
            "schema",
            "invocation_prefix",
            "target_class",
            "work_root",
            "phases",
            "resource_keys",
            "cleanup_order",
            "residue_keys",
            "survivor_classes",
            "failure_cases",
            "collector",
        },
        "topology",
    )
    if document["schema"] != TOPOLOGY_SCHEMA:
        raise GCRetentionError("topology schema is not supported")
    if document["invocation_prefix"] != "coffer-gc":
        raise GCRetentionError("invocation prefix is not the fixed contract")
    if document["target_class"] != "disposable-fixture":
        raise GCRetentionError("target class must be disposable-fixture")
    if document["work_root"] != "work/gc-retention":
        raise GCRetentionError("work root is not the fixed contract")
    if tuple(document["phases"]) != EXPECTED_PHASES:
        raise GCRetentionError("phase order is not the fixed contract")
    if tuple(document["resource_keys"]) != EXPECTED_RESOURCE_KEYS:
        raise GCRetentionError("resource ownership is not the fixed contract")
    if tuple(document["cleanup_order"]) != EXPECTED_CLEANUP_ORDER:
        raise GCRetentionError("cleanup order is not the fixed contract")
    if tuple(document["residue_keys"]) != EXPECTED_RESIDUE_KEYS:
        raise GCRetentionError("residue set is not the fixed contract")
    if tuple(document["survivor_classes"]) != EXPECTED_SURVIVOR_CLASSES:
        raise GCRetentionError("survivor set is not the fixed contract")
    if tuple(document["failure_cases"]) != EXPECTED_FAILURE_CASES:
        raise GCRetentionError("failure set is not the fixed contract")
    collector = _require_keys(
        document["collector"],
        {
            "distribution_version",
            "distribution_revision",
            "allow_delete_untagged",
            "candidate_limit",
            "authorization_ttl_seconds",
            "dry_run_count",
        },
        "collector contract",
    )
    if (
        collector["distribution_version"] != "v3.1.1"
        or collector["distribution_revision"]
        != "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
        or collector["allow_delete_untagged"] is not False
        or collector["candidate_limit"] != 1000
        or collector["authorization_ttl_seconds"] != 900
        or collector["dry_run_count"] != 2
    ):
        raise GCRetentionError("collector settings are not the fixed contract")


def create_state(
    topology: Mapping[str, Any],
    *,
    invocation_id: str,
    resources: Mapping[str, str],
    unrelated_signature: str,
    created_at: str,
) -> dict[str, Any]:
    validate_topology(topology)
    if INVOCATION_PATTERN.fullmatch(invocation_id) is None:
        raise GCRetentionError("invocation ID must be a lowercase ULID")
    if set(resources) != set(EXPECTED_RESOURCE_KEYS):
        raise GCRetentionError("immutable resource ownership is incomplete")
    resource_values = list(resources.values())
    if (
        len(set(resource_values)) != len(resource_values)
        or any(
            not isinstance(value, str)
            or RESOURCE_ID_PATTERN.fullmatch(value) is None
            or not value.startswith(f"coffer-gc-{invocation_id}-")
            for value in resource_values
        )
    ):
        raise GCRetentionError(
            "resource IDs must be unique and invocation-owned"
        )
    _require_hash(unrelated_signature, "unrelated signature")
    _parse_timestamp(created_at, "created_at")
    return {
        "schema": STATE_SCHEMA,
        "topology_hash": _canonical_hash(topology),
        "invocation_id": invocation_id,
        "target_class": "disposable-fixture",
        "phase": "initialized",
        "resources": dict(resources),
        "unrelated_signature": unrelated_signature,
        "evidence": {},
        "collection_authority": None,
        "history": [
            {
                "phase": "initialized",
                "at": created_at,
                "evidence_hash": _canonical_hash({}),
            }
        ],
    }


def _validate_state(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    validate_topology(topology)
    _require_keys(
        state,
        {
            "schema",
            "topology_hash",
            "invocation_id",
            "target_class",
            "phase",
            "resources",
            "unrelated_signature",
            "evidence",
            "collection_authority",
            "history",
        },
        "state",
    )
    if state["schema"] != STATE_SCHEMA:
        raise GCRetentionError("state schema is not supported")
    if state["topology_hash"] != _canonical_hash(topology):
        raise GCRetentionError("state topology binding changed")
    if state["target_class"] != "disposable-fixture":
        raise GCRetentionError("only a disposable fixture is accepted")
    if (
        not isinstance(state["resources"], Mapping)
        or set(state["resources"]) != set(EXPECTED_RESOURCE_KEYS)
    ):
        raise GCRetentionError("state resource ownership is incomplete")
    resource_values = list(state["resources"].values())
    if (
        len(set(resource_values)) != len(resource_values)
        or any(
            not isinstance(value, str)
            or RESOURCE_ID_PATTERN.fullmatch(value) is None
            or not value.startswith(
                f"coffer-gc-{state['invocation_id']}-"
            )
            for value in resource_values
        )
    ):
        raise GCRetentionError("state resource ownership changed")
    if state["phase"] not in ("initialized", *EXPECTED_PHASES):
        raise GCRetentionError("state phase is unknown")
    if not isinstance(state["evidence"], Mapping):
        raise GCRetentionError("state evidence must be a mapping")
    if not isinstance(state["history"], list) or not state["history"]:
        raise GCRetentionError("state history is missing")
    _require_hash(state["unrelated_signature"], "unrelated signature")
    _assert_secret_safe(state["evidence"])
    _assert_secret_safe(state["collection_authority"])
    current_index = (
        -1
        if state["phase"] == "initialized"
        else EXPECTED_PHASES.index(state["phase"])
    )
    expected_phases = EXPECTED_PHASES[: current_index + 1]
    if (
        len(state["evidence"]) != len(expected_phases)
        or set(state["evidence"]) != set(expected_phases)
    ):
        raise GCRetentionError("state evidence phase sequence changed")
    if len(state["history"]) != len(expected_phases) + 1:
        raise GCRetentionError("state history length changed")
    if state["history"][0] != {
        "phase": "initialized",
        "at": state["history"][0].get("at"),
        "evidence_hash": _canonical_hash({}),
    }:
        raise GCRetentionError("initial state history changed")
    for phase, history in zip(
        expected_phases,
        state["history"][1:],
        strict=True,
    ):
        if history != {
            "phase": phase,
            "at": history.get("at"),
            "evidence_hash": _canonical_hash(state["evidence"][phase]),
        }:
            raise GCRetentionError("state evidence history changed")
    timestamps = [
        _parse_timestamp(history["at"], "history timestamp")
        for history in state["history"]
    ]
    if any(
        later <= earlier
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise GCRetentionError("state history timestamps changed")


def validate_state(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    _validate_state(topology, state)


def _validate_preflight(
    topology: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {
            "target_class",
            "distribution_version",
            "distribution_revision",
            "image_digest",
            "config_hash",
            "backend_hash",
            "delete_untagged",
            "candidate_limit",
        },
        "preflight evidence",
    )
    if item["target_class"] != "disposable-fixture":
        raise GCRetentionError("preflight target is not disposable")
    if item["distribution_version"] != topology["collector"][
        "distribution_version"
    ]:
        raise GCRetentionError("distribution version is not the pinned baseline")
    if (
        not isinstance(item["distribution_revision"], str)
        or REVISION_PATTERN.fullmatch(item["distribution_revision"]) is None
        or item["distribution_revision"]
        != topology["collector"]["distribution_revision"]
    ):
        raise GCRetentionError("distribution revision is invalid")
    for name in ("image_digest", "config_hash", "backend_hash"):
        _require_hash(item[name], name)
    if item["delete_untagged"] is not False:
        raise GCRetentionError("--delete-untagged is forbidden")
    if item["candidate_limit"] != topology["collector"]["candidate_limit"]:
        raise GCRetentionError("candidate limit changed")


def _validate_source(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {"owned_signature", "unrelated_signature"},
        "source evidence",
    )
    _require_hash(item["owned_signature"], "owned signature")
    if item["unrelated_signature"] != state["unrelated_signature"]:
        raise GCRetentionError("unrelated state changed")


def _validate_fixture(evidence: Mapping[str, Any]) -> None:
    item = _require_keys(
        evidence,
        {
            "fixture_hash",
            "retained_set_hash",
            "deleted_set_hash",
            "counts",
        },
        "fixture evidence",
    )
    for name in ("fixture_hash", "retained_set_hash", "deleted_set_hash"):
        _require_hash(item[name], name)
    counts = _require_keys(
        item["counts"],
        {
            "manifest",
            "shared_blob",
            "index",
            "digest_only",
            "referrer",
        },
        "fixture counts",
    )
    if counts != {
        "manifest": 6,
        "shared_blob": 1,
        "index": 1,
        "digest_only": 1,
        "referrer": 1,
    }:
        raise GCRetentionError("fixture graph is not the fixed contract")


def _validate_logical_delete(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {"policy_hash", "deleted_set_hash", "deleted_manifest_count"},
        "logical delete evidence",
    )
    _require_hash(item["policy_hash"], "delete policy")
    if (
        item["deleted_set_hash"]
        != state["evidence"]["fixture-populated"]["deleted_set_hash"]
    ):
        raise GCRetentionError("logical delete target changed")
    if item["deleted_manifest_count"] != 1:
        raise GCRetentionError("logical delete must select one fixture manifest")


def _validate_fence(evidence: Mapping[str, Any]) -> None:
    item = _require_keys(
        evidence,
        {
            "fence_hash",
            "fence_epoch",
            "replica_count",
            "write_probe_count",
            "active_upload_count",
            "multipart_upload_count",
            "background_mutator_count",
            "all_read_only",
        },
        "writer fence evidence",
    )
    _require_hash(item["fence_hash"], "writer fence")
    if (
        not isinstance(item["fence_epoch"], str)
        or RESOURCE_ID_PATTERN.fullmatch(item["fence_epoch"]) is None
    ):
        raise GCRetentionError("writer fence epoch is invalid")
    if item["replica_count"] != 2:
        raise GCRetentionError("every fixed registry replica must be fenced")
    if _require_int(item["write_probe_count"], "write probe count") < 6:
        raise GCRetentionError("every writer path must be probed")
    for name in (
        "active_upload_count",
        "multipart_upload_count",
        "background_mutator_count",
    ):
        if item[name] != 0:
            raise GCRetentionError(f"{name} must be zero")
    if item["all_read_only"] is not True:
        raise GCRetentionError("every registry replica must be read-only")


def _validate_backups(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {
            "fence_hash",
            "sql_backup_hash",
            "rgw_backup_hash",
            "isolated_restore_hash",
            "object_version_count",
            "delete_marker_count",
            "multipart_upload_count",
            "kms_verified",
        },
        "backup evidence",
    )
    if item["fence_hash"] != state["evidence"]["writers-excluded"]["fence_hash"]:
        raise GCRetentionError("backup writer fence changed")
    for name in (
        "sql_backup_hash",
        "rgw_backup_hash",
        "isolated_restore_hash",
    ):
        _require_hash(item[name], name)
    _require_int(item["object_version_count"], "object version count", minimum=1)
    _require_int(item["delete_marker_count"], "delete marker count")
    if item["multipart_upload_count"] != 0:
        raise GCRetentionError("backup has incomplete multipart uploads")
    if item["kms_verified"] is not True:
        raise GCRetentionError("backup KMS verification is incomplete")


def _validate_baseline(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {
            "fence_hash",
            "inventory_hash",
            "sql_hash",
            "retained_set_hash",
            "expected_candidate_set_hash",
            "current_object_count",
            "object_version_count",
            "delete_marker_count",
        },
        "baseline evidence",
    )
    fixture = state["evidence"]["fixture-populated"]
    backups = state["evidence"]["backups-verified"]
    fence_hash = state["evidence"]["writers-excluded"]["fence_hash"]
    if item["fence_hash"] != fence_hash:
        raise GCRetentionError("baseline writer fence changed")
    for name in ("inventory_hash", "sql_hash"):
        _require_hash(item[name], name)
    if item["retained_set_hash"] != fixture["retained_set_hash"]:
        raise GCRetentionError("baseline retained set changed")
    if item["expected_candidate_set_hash"] != fixture["deleted_set_hash"]:
        raise GCRetentionError("baseline candidate set is unauthorized")
    _require_int(item["current_object_count"], "current object count", minimum=1)
    if item["object_version_count"] != backups["object_version_count"]:
        raise GCRetentionError("baseline object versions drifted")
    if item["delete_marker_count"] != backups["delete_marker_count"]:
        raise GCRetentionError("baseline delete markers drifted")


def _validate_dry_run(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    second: bool,
) -> None:
    item = _require_keys(
        evidence,
        {
            "fence_hash",
            "image_digest",
            "distribution_revision",
            "config_hash",
            "backend_hash",
            "baseline_hash",
            "candidate_set_hash",
            "summary_hash",
            "eligible_blob_count",
            "eligible_manifest_count",
            "eligible_link_count",
            "candidate_total",
        },
        "dry-run evidence",
    )
    preflight = state["evidence"]["preflighted"]
    baseline = state["evidence"]["baseline-verified"]
    fence = state["evidence"]["writers-excluded"]
    expected = {
        "fence_hash": fence["fence_hash"],
        "image_digest": preflight["image_digest"],
        "distribution_revision": preflight["distribution_revision"],
        "config_hash": preflight["config_hash"],
        "backend_hash": preflight["backend_hash"],
        "baseline_hash": baseline["inventory_hash"],
        "candidate_set_hash": baseline["expected_candidate_set_hash"],
    }
    for name, value in expected.items():
        if item[name] != value:
            raise GCRetentionError(f"dry-run {name} binding changed")
    _require_hash(item["summary_hash"], "dry-run summary")
    total = sum(
        _require_int(item[name], name)
        for name in (
            "eligible_blob_count",
            "eligible_manifest_count",
            "eligible_link_count",
        )
    )
    if item["candidate_total"] != total:
        raise GCRetentionError("dry-run candidate total is inconsistent")
    if total < 1 or total > topology["collector"]["candidate_limit"]:
        raise GCRetentionError("dry-run candidate limit is invalid")
    if second:
        first = state["evidence"]["dry-run-one-verified"]
        for name in (
            "fence_hash",
            "image_digest",
            "distribution_revision",
            "config_hash",
            "backend_hash",
            "baseline_hash",
            "candidate_set_hash",
            "summary_hash",
            "eligible_blob_count",
            "eligible_manifest_count",
            "eligible_link_count",
            "candidate_total",
        ):
            if item[name] != first[name]:
                raise GCRetentionError("two dry-run candidate sets differ")


def collection_binding(state: Mapping[str, Any]) -> str:
    dry_run = state["evidence"].get("dry-run-two-verified")
    if not isinstance(dry_run, Mapping):
        raise GCRetentionError("two verified dry runs are required")
    return _canonical_hash(
        {
            "invocation_id": state["invocation_id"],
            "resource_hash": _canonical_hash(state["resources"]),
            "preflight": state["evidence"]["preflighted"],
            "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
            "backups_hash": _canonical_hash(
                state["evidence"]["backups-verified"]
            ),
            "baseline_hash": _canonical_hash(
                state["evidence"]["baseline-verified"]
            ),
            "dry_run_hash": _canonical_hash(dry_run),
        }
    )


def _validate_authority(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    at: str,
) -> dict[str, Any]:
    item = _require_keys(
        evidence,
        {
            "authorization_id",
            "issued_at",
            "expires_at",
            "binding_hash",
            "command_hash",
            "candidate_set_hash",
            "delete_untagged",
        },
        "collection authority",
    )
    if (
        not isinstance(item["authorization_id"], str)
        or RESOURCE_ID_PATTERN.fullmatch(item["authorization_id"]) is None
        or not item["authorization_id"].startswith("coffer-gc-authority-")
    ):
        raise GCRetentionError("collection authorization ID is invalid")
    issued = _parse_timestamp(item["issued_at"], "issued_at")
    expires = _parse_timestamp(item["expires_at"], "expires_at")
    action_at = _parse_timestamp(at, "action timestamp")
    ttl = (expires - issued).total_seconds()
    if issued != action_at or ttl <= 0 or ttl > topology["collector"][
        "authorization_ttl_seconds"
    ]:
        raise GCRetentionError("collection authorization lifetime is invalid")
    if item["binding_hash"] != collection_binding(state):
        raise GCRetentionError("collection authorization binding changed")
    _require_hash(item["command_hash"], "collector command")
    expected_candidate = state["evidence"]["dry-run-two-verified"][
        "candidate_set_hash"
    ]
    if item["candidate_set_hash"] != expected_candidate:
        raise GCRetentionError("collection candidate set changed")
    if item["delete_untagged"] is not False:
        raise GCRetentionError("--delete-untagged is forbidden")
    return {
        **dict(item),
        "consumed": False,
    }


def _validate_execution(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
    at: str,
) -> None:
    item = _require_keys(
        evidence,
        {
            "authorization_id",
            "binding_hash",
            "candidate_set_hash",
            "fence_hash",
            "exit_code",
            "collector_result_hash",
        },
        "collection execution",
    )
    authority = state["collection_authority"]
    if not isinstance(authority, Mapping):
        raise GCRetentionError("collection authority is missing")
    if authority["consumed"] is not False:
        raise GCRetentionError("collection authority was already consumed")
    if authority["binding_hash"] != collection_binding(state):
        raise GCRetentionError("collection binding drifted after authorization")
    if _parse_timestamp(at, "action timestamp") > _parse_timestamp(
        authority["expires_at"],
        "expires_at",
    ):
        raise GCRetentionError("collection authority expired")
    expected = {
        "authorization_id": authority["authorization_id"],
        "binding_hash": authority["binding_hash"],
        "candidate_set_hash": authority["candidate_set_hash"],
        "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
    }
    for name, value in expected.items():
        if item[name] != value:
            raise GCRetentionError(f"collection {name} changed")
    if item["exit_code"] != 0:
        raise GCRetentionError("collector did not exit successfully")
    _require_hash(item["collector_result_hash"], "collector result")


def _validate_survivors(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {
            "fence_hash",
            "retained_set_hash",
            "sql_hash",
            "missing_survivor_count",
            "deleted_readable_count",
            "survivor_classes",
        },
        "survivor evidence",
    )
    baseline = state["evidence"]["baseline-verified"]
    if item["fence_hash"] != state["evidence"]["writers-excluded"]["fence_hash"]:
        raise GCRetentionError("survivor writer fence changed")
    if item["retained_set_hash"] != baseline["retained_set_hash"]:
        raise GCRetentionError("retained content set changed")
    if item["sql_hash"] != baseline["sql_hash"]:
        raise GCRetentionError("collector mutated Coffer SQL")
    if item["missing_survivor_count"] != 0:
        raise GCRetentionError("a required survivor is missing")
    if item["deleted_readable_count"] != 0:
        raise GCRetentionError("deleted content remains readable")
    classes = _require_keys(
        item["survivor_classes"],
        set(EXPECTED_SURVIVOR_CLASSES),
        "survivor classes",
    )
    if any(value is not True for value in classes.values()):
        raise GCRetentionError("a fixed survivor class failed")


def _validate_reclaim(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {
            "current_object_count_before",
            "current_object_count_after",
            "current_bytes_before",
            "current_bytes_after",
            "object_version_count_before",
            "object_version_count_after",
            "delete_marker_count_before",
            "delete_marker_count_after",
            "logical_reclaimed_bytes",
            "physical_reclaimed_bytes_observed",
            "rgw_lifecycle_ran",
            "orphan_delete_ran",
        },
        "reclaim evidence",
    )
    for name in (
        "current_object_count_before",
        "current_object_count_after",
        "current_bytes_before",
        "current_bytes_after",
        "object_version_count_before",
        "object_version_count_after",
        "delete_marker_count_before",
        "delete_marker_count_after",
        "logical_reclaimed_bytes",
        "physical_reclaimed_bytes_observed",
    ):
        _require_int(item[name], name)
    baseline = state["evidence"]["baseline-verified"]
    backups = state["evidence"]["backups-verified"]
    if item["current_object_count_before"] != baseline["current_object_count"]:
        raise GCRetentionError("reclaim current-object baseline changed")
    if item["object_version_count_before"] != backups["object_version_count"]:
        raise GCRetentionError("reclaim object-version baseline changed")
    if item["delete_marker_count_before"] != backups["delete_marker_count"]:
        raise GCRetentionError("reclaim delete-marker baseline changed")
    if (
        item["current_object_count_after"]
        >= item["current_object_count_before"]
        or item["current_bytes_after"] >= item["current_bytes_before"]
        or item["logical_reclaimed_bytes"]
        != item["current_bytes_before"] - item["current_bytes_after"]
        or item["logical_reclaimed_bytes"] <= 0
    ):
        raise GCRetentionError("logical reclaim delta is inconsistent")
    if item["rgw_lifecycle_ran"] is not False:
        raise GCRetentionError("RGW lifecycle is a separate procedure")
    if item["orphan_delete_ran"] is not False:
        raise GCRetentionError("RGW orphan deletion is a separate procedure")


def _validate_restore(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {
            "isolated",
            "kms_verified",
            "restore_inventory_hash",
            "restored_digest_count",
            "mismatch_count",
        },
        "restore evidence",
    )
    if item["isolated"] is not True or item["kms_verified"] is not True:
        raise GCRetentionError("restore must be isolated and KMS verified")
    if (
        item["restore_inventory_hash"]
        != state["evidence"]["baseline-verified"]["inventory_hash"]
    ):
        raise GCRetentionError("restore inventory differs from the baseline")
    _require_int(item["restored_digest_count"], "restored digest count", minimum=1)
    if item["mismatch_count"] != 0:
        raise GCRetentionError("restored content differs from the backup")


def _validate_failures(evidence: Mapping[str, Any]) -> None:
    item = _require_keys(evidence, {"outcomes"}, "failure evidence")
    outcomes = _require_keys(
        item["outcomes"],
        set(EXPECTED_FAILURE_CASES),
        "failure outcomes",
    )
    if any(value != "refused" for value in outcomes.values()):
        raise GCRetentionError("every fixed failure must be refused")


def _validate_teardown(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    item = _require_keys(
        evidence,
        {"residue", "unrelated_signature"},
        "teardown evidence",
    )
    residue = _require_keys(
        item["residue"],
        set(EXPECTED_RESIDUE_KEYS),
        "teardown residue",
    )
    if any(value != 0 for value in residue.values()):
        raise GCRetentionError("teardown left invocation-owned residue")
    if item["unrelated_signature"] != state["unrelated_signature"]:
        raise GCRetentionError("teardown changed unrelated state")


def advance(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    action: str,
    evidence: Mapping[str, Any],
    at: str,
) -> dict[str, Any]:
    _validate_state(topology, state)
    if action not in PHASE_BY_ACTION:
        raise GCRetentionError("action is not supported")
    current_index = (
        -1
        if state["phase"] == "initialized"
        else EXPECTED_PHASES.index(state["phase"])
    )
    expected_action = EXPECTED_ACTIONS[current_index + 1]
    if action != expected_action:
        raise GCRetentionError(
            f"expected action {expected_action}, not {action}"
        )
    timestamp = _parse_timestamp(at, "action timestamp")
    previous = _parse_timestamp(state["history"][-1]["at"], "history timestamp")
    if timestamp <= previous:
        raise GCRetentionError("phase timestamps must increase")
    _assert_secret_safe(evidence)

    if action == "preflight":
        _validate_preflight(topology, evidence)
    elif action == "create-source":
        _validate_source(state, evidence)
    elif action == "populate-fixture":
        _validate_fixture(evidence)
    elif action == "apply-logical-delete":
        _validate_logical_delete(state, evidence)
    elif action == "exclude-writers":
        _validate_fence(evidence)
    elif action == "verify-backups":
        _validate_backups(state, evidence)
    elif action == "verify-baseline":
        _validate_baseline(state, evidence)
    elif action == "verify-dry-run-one":
        _validate_dry_run(topology, state, evidence, second=False)
    elif action == "verify-dry-run-two":
        _validate_dry_run(topology, state, evidence, second=True)
    elif action == "execute-collection":
        _validate_execution(state, evidence, at)
    elif action == "verify-survivors":
        _validate_survivors(state, evidence)
    elif action == "verify-reclaim":
        _validate_reclaim(state, evidence)
    elif action == "verify-restore":
        _validate_restore(state, evidence)
    elif action == "verify-failures":
        _validate_failures(evidence)
    elif action == "teardown":
        _validate_teardown(state, evidence)

    changed = deepcopy(state)
    phase = PHASE_BY_ACTION[action]
    if action == "authorize-collection":
        changed["collection_authority"] = _validate_authority(
            topology,
            state,
            evidence,
            at,
        )
    if action == "execute-collection":
        changed["collection_authority"]["consumed"] = True
    changed["phase"] = phase
    changed["evidence"][phase] = deepcopy(dict(evidence))
    changed["history"].append(
        {
            "phase": phase,
            "at": at,
            "evidence_hash": _canonical_hash(evidence),
        }
    )
    return changed


def public_evidence(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_state(topology, state)
    authority = state["collection_authority"]
    output = {
        "schema": EVIDENCE_SCHEMA,
        "topology_hash": state["topology_hash"],
        "invocation_hash": _canonical_hash(state["invocation_id"]),
        "resource_hash": _canonical_hash(state["resources"]),
        "target_class": state["target_class"],
        "phase": state["phase"],
        "evidence": deepcopy(state["evidence"]),
        "authority": (
            None
            if authority is None
            else {
                "binding_hash": authority["binding_hash"],
                "command_hash": authority["command_hash"],
                "candidate_set_hash": authority["candidate_set_hash"],
                "issued_at": authority["issued_at"],
                "expires_at": authority["expires_at"],
                "consumed": authority["consumed"],
            }
        ),
        "history": deepcopy(state["history"]),
    }
    _assert_secret_safe(output)
    serialized = json.dumps(output, sort_keys=True)
    for resource_id in state["resources"].values():
        if resource_id in serialized:
            raise GCRetentionError("public evidence retained a resource ID")
    return output
