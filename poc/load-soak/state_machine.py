from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping


STATE_SCHEMA = "coffer.load-soak-state/v1"
TOPOLOGY_SCHEMA = "coffer.load-soak-topology/v1"
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
SECRET_KEYS = re.compile(
    r"(?i)(?:^|_)(?:token|secret|password|private_key|credential_id|"
    r"upload_uuid|repository_name|project_id|object_key|connection_string|"
    r"raw_url)(?:$|_)"
)
SECRET_VALUES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"(?i)https?://[^/\s:@]+:[^@\s/]+@"),
)


class LoadSoakError(RuntimeError):
    pass


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_hash(value: object, category: str) -> str:
    if not isinstance(value, str) or HASH.fullmatch(value) is None:
        raise LoadSoakError(f"{category} hash is invalid")
    return value


def _exact_keys(
    value: object,
    expected: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise LoadSoakError(f"{category} boundary changed")
    return value


def _integer(
    value: object,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    category: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise LoadSoakError(f"{category} is invalid")
    return value


def _number(
    value: object,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
    category: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or float(value) < minimum
        or (maximum is not None and float(value) > maximum)
    ):
        raise LoadSoakError(f"{category} is invalid")
    return float(value)


def validate_retained_evidence(value: object) -> None:
    def walk(item: object) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise LoadSoakError("retained evidence has forbidden identity")
                if (
                    SECRET_KEYS.search(key)
                    and not isinstance(child, (bool, int, float))
                ):
                    raise LoadSoakError("retained evidence has forbidden identity")
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            if any(pattern.search(item) for pattern in SECRET_VALUES):
                raise LoadSoakError("retained evidence has secret-like content")
            if "://" in item:
                raise LoadSoakError("retained evidence has a raw endpoint")
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise LoadSoakError("retained evidence type is invalid")

    walk(value)


def load_topology(path: Path) -> dict[str, Any]:
    try:
        topology = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LoadSoakError("load topology is invalid") from error
    if (
        not isinstance(topology, dict)
        or topology.get("schema") != TOPOLOGY_SCHEMA
    ):
        raise LoadSoakError("load topology schema changed")
    expected_phases = [
        "preflighted",
        "dependencies-qualified",
        "topology-verified",
        "clients-qualified",
        "seed-loaded",
        "smoke-complete",
        "ramp-complete",
        "baseline-complete",
        "faults-complete",
        "soak-complete",
        "data-verified",
        "metrics-verified",
        "torn-down",
    ]
    if topology.get("phases") != expected_phases:
        raise LoadSoakError("load phases changed")
    if topology.get("target_class") != "disposable-stage6-pilot":
        raise LoadSoakError("load target class changed")
    if topology.get("invocation_prefix") != "coffer-load":
        raise LoadSoakError("load invocation prefix changed")
    if topology.get("work_root") != "work/load-soak":
        raise LoadSoakError("load work root changed")
    profiles = _exact_keys(
        topology.get("profiles"),
        {"smoke", "qualification", "soak"},
        "load profile",
    )
    expected_profiles = {
        "smoke": (120, 4, 4, 2 * 1024**3),
        "qualification": (1800, 16, 32, 40 * 1024**3),
        "soak": (7200, 8, 32, 160 * 1024**3),
    }
    for name, expected in expected_profiles.items():
        profile = _exact_keys(
            profiles[name],
            {
                "duration_seconds",
                "steady_clients",
                "burst_clients",
                "transfer_ceiling_bytes",
            },
            f"{name} profile",
        )
        actual = (
            profile["duration_seconds"],
            profile["steady_clients"],
            profile["burst_clients"],
            profile["transfer_ceiling_bytes"],
        )
        if actual != expected:
            raise LoadSoakError(f"{name} profile changed")
    if topology.get("ramp_clients") != [1, 2, 4, 8, 16, 32, 64]:
        raise LoadSoakError("load ramp changed")
    for key in (
        "clients",
        "operations",
        "content_classes",
        "required_architectures",
        "required_recording_rules",
        "required_alerts",
        "failure_cases",
        "resource_keys",
        "residue_keys",
    ):
        value = topology.get(key)
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)
        ):
            raise LoadSoakError(f"{key} allowlist is invalid")
    _exact_keys(
        topology.get("replicas"),
        {
            "api",
            "edge",
            "registry",
            "galera",
            "rgw",
            "rgw-ingress",
            "reconcile",
        },
        "replica",
    )
    for count in topology["replicas"].values():
        _integer(count, minimum=2, category="replica count")
    latency = _exact_keys(
        topology.get("latency_milliseconds"),
        {
            "control-token",
            "manifest-read",
            "manifest-publish",
            "blob-control",
            "blob-first-byte",
        },
        "latency",
    )
    for thresholds in latency.values():
        checked = _exact_keys(
            thresholds,
            {"p95", "p99"},
            "latency threshold",
        )
        if (
            _integer(checked["p95"], minimum=1, category="p95")
            > _integer(checked["p99"], minimum=1, category="p99")
        ):
            raise LoadSoakError("latency thresholds are inconsistent")
    faults = topology.get("faults")
    if not isinstance(faults, Mapping) or len(faults) != 10:
        raise LoadSoakError("fault allowlist changed")
    for fault in faults.values():
        checked = _exact_keys(
            fault,
            {"window_seconds", "recovery_seconds"},
            "fault",
        )
        _integer(checked["window_seconds"], minimum=1, category="fault window")
        _integer(
            checked["recovery_seconds"],
            minimum=1,
            category="fault recovery",
        )
    return topology


def new_state(topology: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "complete": False,
        "facts": {},
        "history": [],
        "phase": "new",
        "schema": STATE_SCHEMA,
        "topology_hash": _hash(topology),
    }


def _validate_state(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    if (
        state.get("schema") != STATE_SCHEMA
        or state.get("topology_hash") != _hash(topology)
        or not isinstance(state.get("facts"), Mapping)
        or not isinstance(state.get("history"), list)
        or not isinstance(state.get("phase"), str)
        or not isinstance(state.get("complete"), bool)
    ):
        raise LoadSoakError("load state is invalid")
    previous = state["topology_hash"]
    for index, entry in enumerate(state["history"]):
        checked = _exact_keys(
            entry,
            {
                "entry_hash",
                "evidence_hash",
                "phase",
                "previous_hash",
                "sequence",
            },
            "history",
        )
        unsigned = {
            key: checked[key]
            for key in checked
            if key != "entry_hash"
        }
        if (
            checked["sequence"] != index + 1
            or checked["previous_hash"] != previous
            or checked["phase"] != topology["phases"][index]
            or checked["entry_hash"] != _hash(unsigned)
        ):
            raise LoadSoakError("load history is invalid")
        previous = checked["entry_hash"]
    expected_phase = (
        topology["phases"][len(state["history"]) - 1]
        if state["history"]
        else "new"
    )
    if state["phase"] != expected_phase:
        raise LoadSoakError("load phase is invalid")
    if state["complete"] != (state["phase"] == "torn-down"):
        raise LoadSoakError("load completion state is invalid")


def _validate_preflight(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "invocation_hash",
        "ownership_hash",
        "target_class",
        "transfer_ceiling_bytes",
        "unrelated_before_hash",
        "writer_scope_exact",
    }
    checked = _exact_keys(evidence, expected, "preflight")
    for key in ("invocation_hash", "ownership_hash", "unrelated_before_hash"):
        _require_hash(checked[key], key)
    if checked["target_class"] != topology["target_class"]:
        raise LoadSoakError("preflight target is not disposable")
    if checked["writer_scope_exact"] is not True:
        raise LoadSoakError("preflight writer scope is incomplete")
    ceiling = topology["profiles"]["soak"]["transfer_ceiling_bytes"]
    if checked["transfer_ceiling_bytes"] != ceiling:
        raise LoadSoakError("preflight transfer ceiling changed")
    return {
        "invocation_hash": checked["invocation_hash"],
        "unrelated_before_hash": checked["unrelated_before_hash"],
    }


def _validate_dependencies(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {
            "architectures",
            "ceph_evidence_hash",
            "distribution_evidence_hash",
            "status",
        },
        "dependency qualification",
    )
    if checked["status"] != "qualified":
        raise LoadSoakError("load dependencies are not qualified")
    for key in ("ceph_evidence_hash", "distribution_evidence_hash"):
        _require_hash(checked[key], key)
    architectures = _exact_keys(
        checked["architectures"],
        set(topology["required_architectures"]),
        "architecture qualification",
    )
    if any(value is not True for value in architectures.values()):
        raise LoadSoakError("load architecture is not qualified")
    return {"dependencies_hash": _hash(checked)}


def _validate_topology(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {
            "configuration_hash",
            "edge_only_ingress",
            "observability_direct",
            "private_tls",
            "replicas",
            "shared_rgw",
            "shared_sql",
        },
        "runtime topology",
    )
    _require_hash(checked["configuration_hash"], "configuration")
    if checked["replicas"] != topology["replicas"]:
        raise LoadSoakError("runtime replica topology changed")
    if any(
        checked[key] is not True
        for key in (
            "edge_only_ingress",
            "observability_direct",
            "private_tls",
            "shared_rgw",
            "shared_sql",
        )
    ):
        raise LoadSoakError("runtime topology boundary is incomplete")
    return {"configuration_hash": checked["configuration_hash"]}


def _validate_clients(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {
            "ca_verified",
            "clients",
            "insecure_mode",
            "versions_hash",
        },
        "client qualification",
    )
    _require_hash(checked["versions_hash"], "client versions")
    clients = _exact_keys(
        checked["clients"],
        set(topology["clients"]),
        "client",
    )
    if (
        checked["ca_verified"] is not True
        or checked["insecure_mode"] is not False
        or any(value is not True for value in clients.values())
    ):
        raise LoadSoakError("client qualification failed")
    return {"clients_hash": _hash(checked)}


def _validate_seed(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {
            "active_uploads",
            "inventory_before_hash",
            "logical_bytes",
            "payload_retained",
            "quota_limit_bytes",
            "seed_hash",
        },
        "load seed",
    )
    for key in ("inventory_before_hash", "seed_hash"):
        _require_hash(checked[key], key)
    logical = _integer(
        checked["logical_bytes"],
        minimum=1,
        maximum=topology["profiles"]["soak"]["transfer_ceiling_bytes"],
        category="seed logical bytes",
    )
    quota = _integer(
        checked["quota_limit_bytes"],
        minimum=logical,
        category="seed quota",
    )
    if checked["active_uploads"] != 0 or checked["payload_retained"] is not False:
        raise LoadSoakError("load seed boundary is unsafe")
    return {
        "inventory_before_hash": checked["inventory_before_hash"],
        "quota_limit_bytes": quota,
    }


def _validate_latency(
    topology: Mapping[str, Any],
    latency: object,
) -> None:
    checked = _exact_keys(
        latency,
        set(topology["latency_milliseconds"]),
        "latency result",
    )
    for name, result in checked.items():
        values = _exact_keys(
            result,
            {"p95", "p99"},
            "latency percentile",
        )
        thresholds = topology["latency_milliseconds"][name]
        p95 = _number(values["p95"], category="p95 result")
        p99 = _number(values["p99"], category="p99 result")
        if p95 > thresholds["p95"] or p99 > thresholds["p99"] or p95 > p99:
            raise LoadSoakError("load latency gate failed")


def _validate_availability(
    topology: Mapping[str, Any],
    availability: object,
) -> None:
    checked = _exact_keys(
        availability,
        set(topology["availability_percent"]),
        "availability result",
    )
    for name, minimum in topology["availability_percent"].items():
        if _number(
            checked[name],
            minimum=0,
            maximum=100,
            category="availability",
        ) < minimum:
            raise LoadSoakError("load availability gate failed")


def _validate_operation_counts(
    topology: Mapping[str, Any],
    counts: object,
) -> None:
    checked = _exact_keys(
        counts,
        set(topology["operations"]),
        "operation count",
    )
    for value in checked.values():
        _integer(value, minimum=1, category="operation count")


def _validate_profile_result(
    topology: Mapping[str, Any],
    evidence: Mapping[str, Any],
    profile_name: str,
) -> None:
    checked = _exact_keys(
        evidence,
        {
            "availability",
            "burst_clients",
            "digest_mismatches",
            "duration_seconds",
            "latency_milliseconds",
            "operation_counts",
            "profile",
            "steady_clients",
            "transfer_bytes",
            "unexpected_errors",
        },
        f"{profile_name} result",
    )
    profile = topology["profiles"][profile_name]
    if (
        checked["profile"] != profile_name
        or checked["steady_clients"] != profile["steady_clients"]
        or checked["burst_clients"] != profile["burst_clients"]
        or _integer(
            checked["duration_seconds"],
            minimum=profile["duration_seconds"],
            category="profile duration",
        )
        < profile["duration_seconds"]
        or _integer(
            checked["transfer_bytes"],
            maximum=profile["transfer_ceiling_bytes"],
            category="profile transfer",
        )
        > profile["transfer_ceiling_bytes"]
        or checked["unexpected_errors"]
        != topology["resource_gates"]["maximum_unexpected_errors"]
        or checked["digest_mismatches"] != 0
    ):
        raise LoadSoakError(f"{profile_name} profile gate failed")
    _validate_operation_counts(topology, checked["operation_counts"])
    _validate_latency(topology, checked["latency_milliseconds"])
    _validate_availability(topology, checked["availability"])


def _profile_validator(
    name: str,
) -> Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    dict[str, Any],
]:
    def validate(
        topology: Mapping[str, Any],
        state: Mapping[str, Any],
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        _validate_profile_result(topology, evidence, name)
        return {f"{name}_evidence_hash": _hash(evidence)}

    return validate


def _validate_ramp(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {"accepted_clients", "levels", "steady_backlog_growth"},
        "load ramp",
    )
    levels = checked["levels"]
    if not isinstance(levels, list) or len(levels) != len(topology["ramp_clients"]):
        raise LoadSoakError("load ramp level set changed")
    completed: set[int] = set()
    first_failed: int | None = None
    for expected_clients, level in zip(topology["ramp_clients"], levels):
        item = _exact_keys(
            level,
            {
                "clients",
                "completed",
                "minimum_headroom_percent",
                "maximum_limit_usage_percent",
                "queue_growth",
            },
            "load ramp level",
        )
        if item["clients"] != expected_clients:
            raise LoadSoakError("load ramp order changed")
        if item["completed"] is True:
            if first_failed is not None:
                raise LoadSoakError("load ramp resumed after failure")
            if (
                _number(
                    item["minimum_headroom_percent"],
                    minimum=topology["resource_gates"][
                        "minimum_headroom_percent"
                    ],
                    maximum=100,
                    category="ramp headroom",
                )
                < topology["resource_gates"]["minimum_headroom_percent"]
                or _number(
                    item["maximum_limit_usage_percent"],
                    minimum=0,
                    maximum=topology["resource_gates"][
                        "maximum_limit_usage_percent"
                    ],
                    category="ramp limit usage",
                )
                > topology["resource_gates"]["maximum_limit_usage_percent"]
                or item["queue_growth"] is not False
            ):
                raise LoadSoakError("completed ramp level violated resource gate")
            completed.add(expected_clients)
        elif item["completed"] is False:
            first_failed = expected_clients
        else:
            raise LoadSoakError("load ramp completion is invalid")
    accepted = checked["accepted_clients"]
    if (
        isinstance(accepted, bool)
        or accepted not in completed
        or accepted < 32
        or max(completed) != accepted
        or accepted == topology["ramp_clients"][-1]
        or first_failed != topology["ramp_clients"][
            topology["ramp_clients"].index(accepted) + 1
        ]
        or checked["steady_backlog_growth"] is not False
    ):
        raise LoadSoakError("load ramp operating point is invalid")
    return {"accepted_clients": accepted, "ramp_evidence_hash": _hash(evidence)}


def _validate_baseline(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_profile_result(topology, evidence, "qualification")
    accepted = state["facts"].get("accepted_clients")
    if (
        not isinstance(accepted, int)
        or topology["profiles"]["qualification"]["steady_clients"]
        > accepted * 0.8
        or topology["profiles"]["qualification"]["burst_clients"] > accepted
    ):
        raise LoadSoakError("qualification exceeds the ramp boundary")
    return {"qualification_evidence_hash": _hash(evidence)}


def _validate_faults(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(evidence, set(topology["faults"]), "fault result")
    for name, limits in topology["faults"].items():
        result = _exact_keys(
            checked[name],
            {
                "data_integrity",
                "injected",
                "recovered",
                "recovery_seconds",
                "security_boundary",
                "unexpected_errors",
                "window_seconds",
            },
            "fault outcome",
        )
        if (
            result["injected"] is not True
            or result["recovered"] is not True
            or result["data_integrity"] is not True
            or result["security_boundary"] is not True
            or result["unexpected_errors"] != 0
            or _number(
                result["window_seconds"],
                minimum=0,
                maximum=limits["window_seconds"],
                category="fault window",
            )
            > limits["window_seconds"]
            or _number(
                result["recovery_seconds"],
                minimum=0,
                maximum=limits["recovery_seconds"],
                category="fault recovery",
            )
            > limits["recovery_seconds"]
        ):
            raise LoadSoakError("load fault gate failed")
    return {"faults_evidence_hash": _hash(evidence)}


def _validate_data(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {
            "active_uploads",
            "claims_exact",
            "digest_checks",
            "digest_checks_passed",
            "galera_nodes_converged",
            "inventory_after_hash",
            "multipart_uploads",
            "quota_invariant",
        },
        "data verification",
    )
    digest_checks = _integer(
        checked["digest_checks"],
        minimum=1,
        category="digest checks",
    )
    if (
        checked["digest_checks_passed"] != digest_checks
        or checked["inventory_after_hash"]
        != state["facts"].get("inventory_before_hash")
        or checked["quota_invariant"] is not True
        or checked["claims_exact"] is not True
        or checked["galera_nodes_converged"] != topology["replicas"]["galera"]
        or checked["active_uploads"] != 0
        or checked["multipart_uploads"] != 0
    ):
        raise LoadSoakError("load data invariant failed")
    return {"data_evidence_hash": _hash(evidence)}


def _validate_metrics(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {
            "alerts",
            "direct_targets",
            "recording_rules",
            "restart_resets",
            "schema_mismatches",
            "secret_leaks",
            "stale_series",
        },
        "metrics verification",
    )
    targets = _exact_keys(
        checked["direct_targets"],
        {"api", "edge", "reconcile", "registry"},
        "direct target",
    )
    for component, count in targets.items():
        if count != topology["replicas"][component]:
            raise LoadSoakError("direct metrics target count changed")
    if (
        checked["recording_rules"] != topology["required_recording_rules"]
        or checked["alerts"] != topology["required_alerts"]
        or checked["restart_resets"] is not True
        or checked["stale_series"] is not True
        or checked["schema_mismatches"] != 0
        or checked["secret_leaks"] != 0
    ):
        raise LoadSoakError("load metrics gate failed")
    return {"metrics_evidence_hash": _hash(evidence)}


def _validate_teardown(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_keys(
        evidence,
        {"audit_complete", "residue", "unrelated_after_hash"},
        "load teardown",
    )
    residue = _exact_keys(
        checked["residue"],
        set(topology["residue_keys"]),
        "load residue",
    )
    if (
        checked["audit_complete"] is not True
        or checked["unrelated_after_hash"]
        != state["facts"].get("unrelated_before_hash")
        or any(value != 0 for value in residue.values())
    ):
        raise LoadSoakError("load teardown residue remains")
    return {"teardown_evidence_hash": _hash(evidence)}


VALIDATORS: dict[
    str,
    Callable[
        [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
        dict[str, Any],
    ],
] = {
    "preflighted": _validate_preflight,
    "dependencies-qualified": _validate_dependencies,
    "topology-verified": _validate_topology,
    "clients-qualified": _validate_clients,
    "seed-loaded": _validate_seed,
    "smoke-complete": _profile_validator("smoke"),
    "ramp-complete": _validate_ramp,
    "baseline-complete": _validate_baseline,
    "faults-complete": _validate_faults,
    "soak-complete": _profile_validator("soak"),
    "data-verified": _validate_data,
    "metrics-verified": _validate_metrics,
    "torn-down": _validate_teardown,
}


def advance(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    phase: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_state(topology, state)
    if state["complete"]:
        raise LoadSoakError("load lifecycle is already complete")
    expected = topology["phases"][len(state["history"])]
    if phase != expected or phase not in VALIDATORS:
        raise LoadSoakError("load phase transition is invalid")
    validate_retained_evidence(evidence)
    facts = dict(state["facts"])
    facts.update(VALIDATORS[phase](topology, state, evidence))
    unsigned = {
        "evidence_hash": _hash(evidence),
        "phase": phase,
        "previous_hash": (
            state["history"][-1]["entry_hash"]
            if state["history"]
            else state["topology_hash"]
        ),
        "sequence": len(state["history"]) + 1,
    }
    entry = {**unsigned, "entry_hash": _hash(unsigned)}
    return {
        "complete": phase == "torn-down",
        "facts": facts,
        "history": [*state["history"], entry],
        "phase": phase,
        "schema": STATE_SCHEMA,
        "topology_hash": state["topology_hash"],
    }
