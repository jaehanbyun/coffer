from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


TOPOLOGY_SCHEMA = "coffer.maintenance-identity-topology/v1"
STATE_SCHEMA = "coffer.maintenance-identity-state/v1"
EVIDENCE_SCHEMA = "coffer.maintenance-identity-evidence/v1"
INVOCATION_PATTERN = re.compile(r"^[0-9a-hjkmnp-tv-z]{26}$")
WORKLOAD_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
IMMUTABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{7,255}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_ROLES = ("service", "registry_maintenance")
EXPECTED_ACCESS_RULE = {
    "service": "oci-registry",
    "method": "POST",
    "path": "/v1/internal/maintenance/registry-token",
}
EXPECTED_CLEANUP_ORDER = (
    "sql_session",
    "haproxy_mapping",
    "application_credential",
    "client_certificate",
    "materialization",
    "barbican_consumer",
    "barbican_secret",
    "role_assignment",
    "user",
    "project",
    "role",
)
ALLOWED_RESOURCE_KINDS = frozenset(EXPECTED_CLEANUP_ORDER)
PHASES = frozenset(
    {
        "preflighted",
        "generation1_created",
        "generation1_verified",
        "generation2_created",
        "generation2_verified",
        "rotation_drained",
        "old_revoked",
        "failures_verified",
        "torn_down",
    }
)
FORBIDDEN_RETAINED_KEYS = frozenset(
    {
        "application_credential_secret",
        "authorization",
        "barbican_payload",
        "bearer",
        "bootstrap_password",
        "password",
        "private_key",
        "registry_jwt",
        "secret_payload",
        "token",
    }
)
TOKEN_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
)
ALLOWED_EVIDENCE_FIELDS = frozenset(
    {
        "fixed_failure_category",
        "http_status_class",
        "log_scan_count",
        "residue_counts",
    }
)


class LifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Topology:
    invocation_prefix: str
    allowed_workloads: tuple[str, ...]
    allowed_generations: tuple[int, ...]
    roles: tuple[str, ...]
    minimum_lifetime_seconds: int
    maximum_lifetime_seconds: int
    work_root: str
    cleanup_order: tuple[str, ...]
    digest: str


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LifecycleError(f"{label} must be a JSON object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise LifecycleError(f"{label} must be a JSON array")
    return value


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_topology(path: Path) -> Topology:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LifecycleError("unable to load lifecycle topology") from error
    return validate_topology(value)


def validate_topology(value: object) -> Topology:
    topology = _mapping(value, "topology")
    if topology.get("schema") != TOPOLOGY_SCHEMA:
        raise LifecycleError("topology has an unsupported schema")

    prefix = topology.get("invocation_prefix")
    if prefix != "coffer-maint":
        raise LifecycleError("topology has an unexpected invocation prefix")

    workloads = tuple(
        str(item)
        for item in _sequence(
            topology.get("allowed_workloads"),
            "allowed workloads",
        )
    )
    if not workloads or len(workloads) != len(set(workloads)):
        raise LifecycleError("allowed workloads must be nonempty and unique")
    if any(WORKLOAD_PATTERN.fullmatch(item) is None for item in workloads):
        raise LifecycleError("allowed workload has an invalid format")
    if set(workloads) != {"reconcile-1", "reconcile-2", "comparison-1"}:
        raise LifecycleError("topology expands the fixed workload allowlist")

    generations = tuple(
        int(item)
        for item in _sequence(
            topology.get("allowed_generations"),
            "allowed generations",
        )
        if not isinstance(item, bool)
    )
    if generations != (1, 2):
        raise LifecycleError("allowed generations must be exactly 1 and 2")

    roles = tuple(
        str(item)
        for item in _sequence(topology.get("roles"), "roles")
    )
    if roles != EXPECTED_ROLES:
        raise LifecycleError("roles must be exactly service and maintenance")

    credential = _mapping(
        topology.get("application_credential"),
        "application credential",
    )
    minimum = credential.get("minimum_lifetime_seconds")
    maximum = credential.get("maximum_lifetime_seconds")
    if (
        not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or minimum < 900
        or maximum > 7200
        or minimum > maximum
    ):
        raise LifecycleError("credential lifetime must stay within 900..7200")
    if credential.get("unrestricted") is not False:
        raise LifecycleError("application credential must be restricted")
    rules = _sequence(credential.get("access_rules"), "access rules")
    if len(rules) != 1 or dict(_mapping(rules[0], "access rule")) != EXPECTED_ACCESS_RULE:
        raise LifecycleError("application credential access rule is not exact")

    work_root = str(topology.get("work_root"))
    work_path = Path(work_root)
    if (
        work_path.is_absolute()
        or ".." in work_path.parts
        or work_path.parts[:2] != ("work", "maintenance-identity")
    ):
        raise LifecycleError("work root must stay under work/maintenance-identity")

    cleanup_order = tuple(
        str(item)
        for item in _sequence(topology.get("cleanup_order"), "cleanup order")
    )
    if cleanup_order != EXPECTED_CLEANUP_ORDER:
        raise LifecycleError("cleanup order does not match the fixed contract")

    return Topology(
        invocation_prefix=prefix,
        allowed_workloads=workloads,
        allowed_generations=generations,
        roles=roles,
        minimum_lifetime_seconds=minimum,
        maximum_lifetime_seconds=maximum,
        work_root=work_root,
        cleanup_order=cleanup_order,
        digest=_canonical_digest(topology),
    )


def _utc_timestamp(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise LifecycleError("timestamp must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_selected_workloads(
    topology: Topology,
    selected_workloads: Iterable[str],
) -> tuple[str, ...]:
    selected = tuple(selected_workloads)
    if not selected or len(selected) != len(set(selected)):
        raise LifecycleError("selected workloads must be nonempty and unique")
    if any(item not in topology.allowed_workloads for item in selected):
        raise LifecycleError("selected workload is outside the exact allowlist")
    return selected


def create_preflight_state(
    topology: Topology,
    invocation_id: str,
    target_signature: str,
    selected_workloads: Iterable[str],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if INVOCATION_PATTERN.fullmatch(invocation_id) is None:
        raise LifecycleError("invocation ID must be a lowercase 26-character ULID")
    if SHA256_PATTERN.fullmatch(target_signature) is None:
        raise LifecycleError("target signature must be a lowercase SHA-256")
    selected = _validate_selected_workloads(topology, selected_workloads)
    timestamp = _utc_timestamp(now)
    state: dict[str, object] = {
        "schema": STATE_SCHEMA,
        "topology_digest": topology.digest,
        "invocation_id": invocation_id,
        "target_signature": target_signature,
        "selected_workloads": list(selected),
        "phase": "preflighted",
        "active_generation": {workload: 0 for workload in selected},
        "resources": [],
        "history": [
            {
                "action": "preflight",
                "outcome": "completed",
                "at": timestamp,
            }
        ],
    }
    validate_state(topology, state)
    return state


def _resource_name(
    topology: Topology,
    invocation_id: str,
    kind: str,
    workload: str | None,
    generation: int | None,
    purpose: str | None,
) -> str:
    prefix = f"{topology.invocation_prefix}-{invocation_id}"
    if kind == "project":
        return f"{prefix}-service"
    if kind == "user":
        return f"{prefix}-user"
    if kind == "role":
        return "registry_maintenance"
    if kind == "role_assignment":
        if purpose not in EXPECTED_ROLES:
            raise LifecycleError("role assignment purpose is not allowlisted")
        return purpose
    if workload is None or generation not in topology.allowed_generations:
        raise LifecycleError(f"{kind} requires an exact workload and generation")
    base = f"{prefix}-{workload}-g{generation}"
    suffixes = {
        "application_credential": "",
        "barbican_secret": f"-{purpose}",
        "barbican_consumer": f"-{purpose}-consumer",
        "client_certificate": "-client",
        "haproxy_mapping": "-mapping",
        "materialization": "-materialized",
        "sql_session": "-session",
    }
    if kind not in suffixes:
        raise LifecycleError(f"unsupported resource kind: {kind}")
    if kind in {"barbican_secret", "barbican_consumer"} and purpose not in {
        "appcred",
        "client-key",
    }:
        raise LifecycleError("Barbican resource purpose is not allowlisted")
    return base + suffixes[kind]


def expected_resource_specs(
    topology: Topology,
    state: Mapping[str, object],
    generation: int,
    *,
    maintenance_role_owned: bool = False,
) -> dict[str, dict[str, object]]:
    validate_state(topology, state)
    if generation not in topology.allowed_generations:
        raise LifecycleError("generation is outside the exact allowlist")
    invocation_id = str(state["invocation_id"])
    workloads = tuple(str(item) for item in state["selected_workloads"])
    specs: dict[str, dict[str, object]] = {}

    def add(
        key: str,
        kind: str,
        *,
        workload: str | None = None,
        purpose: str | None = None,
        owned: bool = True,
        generation_value: int | None = generation,
    ) -> None:
        specs[key] = {
            "kind": kind,
            "name": _resource_name(
                topology,
                invocation_id,
                kind,
                workload,
                generation_value,
                purpose,
            ),
            "workload": workload,
            "generation": generation_value,
            "purpose": purpose,
            "owned": owned,
        }

    if generation == 1:
        add("project", "project", generation_value=None)
        add("user", "user", generation_value=None)
        add(
            "role:registry_maintenance",
            "role",
            owned=maintenance_role_owned,
            generation_value=None,
        )
        for role in EXPECTED_ROLES:
            add(
                f"assignment:{role}",
                "role_assignment",
                purpose=role,
                generation_value=None,
            )

    for workload in workloads:
        prefix = f"{workload}:g{generation}"
        add(
            f"application-credential:{prefix}",
            "application_credential",
            workload=workload,
        )
        add(
            f"certificate:{prefix}",
            "client_certificate",
            workload=workload,
        )
        add(f"mapping:{prefix}", "haproxy_mapping", workload=workload)
        add(f"materialization:{prefix}", "materialization", workload=workload)
        for purpose in ("appcred", "client-key"):
            add(
                f"secret:{prefix}:{purpose}",
                "barbican_secret",
                workload=workload,
                purpose=purpose,
            )
            add(
                f"consumer:{prefix}:{purpose}",
                "barbican_consumer",
                workload=workload,
                purpose=purpose,
            )
    return specs


def register_generation(
    topology: Topology,
    state_value: Mapping[str, object],
    generation: int,
    resources_value: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    expected_phase = "preflighted" if generation == 1 else "generation1_verified"
    if state["phase"] != expected_phase:
        raise LifecycleError(
            f"generation {generation} cannot be created from {state['phase']}"
        )
    resources = _mapping(resources_value, "generation resources")
    role_value = resources.get("role:registry_maintenance")
    role_owned = (
        generation == 1
        and isinstance(role_value, Mapping)
        and role_value.get("owned") is True
    )
    expected = expected_resource_specs(
        topology,
        state,
        generation,
        maintenance_role_owned=role_owned,
    )
    if set(resources) != set(expected):
        raise LifecycleError("generation resource keys are incomplete or unexpected")

    existing_ids = {
        str(_mapping(item, "resource").get("id"))
        for item in _sequence(state["resources"], "state resources")
    }
    registered: list[dict[str, object]] = []
    for key, spec in expected.items():
        resource = dict(_mapping(resources[key], f"resource {key}"))
        if set(resource) != {"id", *spec.keys()}:
            raise LifecycleError(f"resource {key} has unexpected fields")
        if any(resource.get(field) != value for field, value in spec.items()):
            raise LifecycleError(f"resource {key} violates the exact allowlist")
        immutable_id = str(resource.get("id"))
        if IMMUTABLE_ID_PATTERN.fullmatch(immutable_id) is None:
            raise LifecycleError(f"resource {key} has an invalid immutable ID")
        if immutable_id in existing_ids:
            raise LifecycleError("resource immutable IDs must be globally unique")
        existing_ids.add(immutable_id)
        resource["key"] = key
        registered.append(resource)

    state["resources"] = [
        *list(_sequence(state["resources"], "state resources")),
        *registered,
    ]
    state["phase"] = f"generation{generation}_created"
    _append_history(state, f"create-generation-{generation}", "completed", now)
    validate_state(topology, state)
    return state


def verify_generation(
    topology: Topology,
    state_value: Mapping[str, object],
    generation: int,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] != f"generation{generation}_created":
        raise LifecycleError("generation verification is out of order")
    state["phase"] = f"generation{generation}_verified"
    state["active_generation"] = {
        workload: generation for workload in state["selected_workloads"]
    }
    _append_history(state, f"verify-generation-{generation}", "completed", now)
    validate_state(topology, state)
    return state


def mark_rotation_drained(
    topology: Topology,
    state_value: Mapping[str, object],
    *,
    elapsed_seconds: int,
    keystone_cache_seconds: int,
    registry_token_seconds: int,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] != "generation2_verified":
        raise LifecycleError("rotation drain requires verified generation 2")
    bounds = (elapsed_seconds, keystone_cache_seconds, registry_token_seconds)
    if any(not isinstance(item, int) or isinstance(item, bool) or item < 0 for item in bounds):
        raise LifecycleError("rotation drain bounds must be nonnegative integers")
    required = max(keystone_cache_seconds, registry_token_seconds)
    if elapsed_seconds < required:
        raise LifecycleError("rotation overlap has not drained")
    state["phase"] = "rotation_drained"
    state["rotation_drain"] = {
        "elapsed_seconds": elapsed_seconds,
        "required_seconds": required,
    }
    _append_history(state, "drain-rotation", "completed", now)
    validate_state(topology, state)
    return state


def revoke_old_generation(
    topology: Topology,
    state_value: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] != "rotation_drained":
        raise LifecycleError("old generation cannot be revoked before drain")
    state["resources"] = [
        item
        for item in state["resources"]
        if _mapping(item, "resource").get("generation") != 1
    ]
    state["phase"] = "old_revoked"
    _append_history(state, "revoke-generation-1", "completed", now)
    validate_state(topology, state)
    return state


def mark_failure_matrix_verified(
    topology: Topology,
    state_value: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] != "old_revoked":
        raise LifecycleError("failure matrix requires old-generation revocation")
    state["phase"] = "failures_verified"
    _append_history(state, "verify-failures", "completed", now)
    validate_state(topology, state)
    return state


def _append_history(
    state: dict[str, object],
    action: str,
    outcome: str,
    now: datetime | None,
) -> None:
    history = list(_sequence(state.get("history"), "state history"))
    history.append(
        {
            "action": action,
            "outcome": outcome,
            "at": _utc_timestamp(now),
        }
    )
    state["history"] = history


def validate_state(topology: Topology, state_value: object) -> None:
    state = _mapping(state_value, "state")
    if state.get("schema") != STATE_SCHEMA:
        raise LifecycleError("state has an unsupported schema")
    if state.get("topology_digest") != topology.digest:
        raise LifecycleError("state topology digest does not match")
    if INVOCATION_PATTERN.fullmatch(str(state.get("invocation_id"))) is None:
        raise LifecycleError("state invocation ID is invalid")
    if SHA256_PATTERN.fullmatch(str(state.get("target_signature"))) is None:
        raise LifecycleError("state target signature is invalid")
    selected = _validate_selected_workloads(
        topology,
        _sequence(state.get("selected_workloads"), "selected workloads"),
    )
    phase = state.get("phase")
    if phase not in PHASES:
        raise LifecycleError("state phase is invalid")
    active = _mapping(state.get("active_generation"), "active generation")
    if set(active) != set(selected):
        raise LifecycleError("active generation does not cover selected workloads")
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value not in (0, 1, 2)
        for value in active.values()
    ):
        raise LifecycleError("active generation is invalid")
    resources = _sequence(state.get("resources"), "state resources")
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for item in resources:
        resource = _mapping(item, "resource")
        kind = resource.get("kind")
        immutable_id = str(resource.get("id"))
        key = str(resource.get("key"))
        if kind not in ALLOWED_RESOURCE_KINDS:
            raise LifecycleError("resource kind is outside the allowlist")
        if IMMUTABLE_ID_PATTERN.fullmatch(immutable_id) is None:
            raise LifecycleError("resource immutable ID is invalid")
        if immutable_id in seen_ids or key in seen_keys:
            raise LifecycleError("resource IDs and keys must be unique")
        seen_ids.add(immutable_id)
        seen_keys.add(key)
        workload = resource.get("workload")
        if workload is not None and workload not in selected:
            raise LifecycleError("resource workload is outside selected workloads")
        generation = resource.get("generation")
        if generation is not None and generation not in topology.allowed_generations:
            raise LifecycleError("resource generation is outside the allowlist")
        expected_name = _resource_name(
            topology,
            str(state["invocation_id"]),
            str(kind),
            None if workload is None else str(workload),
            generation if isinstance(generation, int) else None,
            None if resource.get("purpose") is None else str(resource["purpose"]),
        )
        if resource.get("name") != expected_name:
            raise LifecycleError("resource name violates the exact allowlist")
        if not isinstance(resource.get("owned"), bool):
            raise LifecycleError("resource ownership flag must be boolean")
    history = _sequence(state.get("history"), "state history")
    if not history:
        raise LifecycleError("state history must be nonempty")
    validate_retained_payload(history)


def assert_exact_cleanup_target(
    topology: Topology,
    state: Mapping[str, object],
    target_value: Mapping[str, object],
) -> None:
    validate_state(topology, state)
    target = _mapping(target_value, "cleanup target")
    if set(target) != {"kind", "id", "name"}:
        raise LifecycleError("cleanup target must contain exact kind, ID, and name")
    matches = [
        resource
        for resource in state["resources"]
        if _mapping(resource, "resource").get("owned") is True
        and all(
            _mapping(resource, "resource").get(field) == target.get(field)
            for field in ("kind", "id", "name")
        )
    ]
    if len(matches) != 1:
        raise LifecycleError("cleanup target is not an exact owned resource")


def cleanup_plan(
    topology: Topology,
    state: Mapping[str, object],
) -> list[dict[str, str]]:
    validate_state(topology, state)
    rank = {kind: index for index, kind in enumerate(topology.cleanup_order)}
    resources = [
        _mapping(item, "resource")
        for item in state["resources"]
        if _mapping(item, "resource").get("owned") is True
    ]
    resources.sort(
        key=lambda item: (
            rank[str(item["kind"])],
            -(item.get("generation") or 0),
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


def finalize_teardown(
    topology: Topology,
    state_value: Mapping[str, object],
    removed_targets: Sequence[Mapping[str, object]],
    residue_counts: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    state = deepcopy(dict(state_value))
    validate_state(topology, state)
    if state["phase"] == "torn_down":
        return state
    expected = cleanup_plan(topology, state)
    normalized = [dict(item) for item in removed_targets]
    if normalized != expected:
        raise LifecycleError("teardown targets do not match the exact cleanup plan")
    residue = _mapping(residue_counts, "residue counts")
    if not residue or any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != 0
        for value in residue.values()
    ):
        raise LifecycleError("teardown residue counts must be explicit zeroes")
    state["resources"] = [
        item
        for item in state["resources"]
        if _mapping(item, "resource").get("owned") is not True
    ]
    state["phase"] = "torn_down"
    state["residue_counts"] = dict(residue)
    _append_history(state, "teardown", "completed", now)
    validate_state(topology, state)
    return state


def validate_retained_payload(
    value: object,
    *,
    known_secret_values: Iterable[str] = (),
) -> None:
    secrets = tuple(secret for secret in known_secret_values if secret)
    if any(len(secret) < 8 for secret in secrets):
        raise LifecycleError("known secret scan values must be at least 8 characters")

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in FORBIDDEN_RETAINED_KEYS:
                    raise LifecycleError("retained payload contains a forbidden field")
                visit(nested)
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested)
            return
        if isinstance(item, str):
            if any(secret in item for secret in secrets):
                raise LifecycleError("retained payload contains a known secret")
            if any(pattern.search(item) for pattern in TOKEN_PATTERNS):
                raise LifecycleError("retained payload contains a secret-like value")

    visit(value)


def redacted_evidence(
    topology: Topology,
    state: Mapping[str, object],
    extra: Mapping[str, object] | None = None,
    *,
    known_secret_values: Iterable[str] = (),
) -> dict[str, object]:
    validate_state(topology, state)
    fields = {} if extra is None else dict(extra)
    if set(fields) - ALLOWED_EVIDENCE_FIELDS:
        raise LifecycleError("evidence contains a non-allowlisted field")
    validate_retained_payload(fields, known_secret_values=known_secret_values)
    resources = [
        _mapping(item, "resource")
        for item in state["resources"]
    ]
    counts = {
        kind: sum(1 for item in resources if item.get("kind") == kind)
        for kind in topology.cleanup_order
    }
    id_hashes = sorted(
        hashlib.sha256(str(item["id"]).encode("utf-8")).hexdigest()
        for item in resources
    )
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "topology_digest": topology.digest,
        "invocation_id": state["invocation_id"],
        "target_signature": state["target_signature"],
        "phase": state["phase"],
        "resource_counts": counts,
        "immutable_id_hashes": id_hashes,
        **fields,
    }
    validate_retained_payload(evidence, known_secret_values=known_secret_values)
    return evidence
