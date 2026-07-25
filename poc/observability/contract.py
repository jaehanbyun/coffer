from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence


TOPOLOGY_SCHEMA = "coffer.observability-topology/v1"
STATE_SCHEMA = "coffer.observability-restart-state/v1"
EVIDENCE_SCHEMA = "coffer.observability-evidence/v1"
HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ROUTES = frozenset(
    {
        "/auth/token",
        "/healthz",
        "/metrics",
        "/readyz",
        "/v1/internal/maintenance/registry-token",
        "/v1/repositories",
        "/v1/repositories/{repository_id}",
        "edge-auth",
        "edge-blob",
        "edge-manifest",
        "edge-other",
        "edge-upload",
        "unmatched",
    }
)
FORBIDDEN_KEYS = frozenset(
    {
        "access_key",
        "authorization",
        "database_url",
        "digest",
        "jti",
        "password",
        "private_key",
        "project_id",
        "repository",
        "repository_id",
        "secret",
        "secret_key",
        "token",
        "user_id",
    }
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
)


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class Topology:
    raw: dict[str, object]
    digest: str

    @property
    def components(self) -> Mapping[str, object]:
        return self.raw["components"]  # type: ignore[return-value]

    @property
    def application_labels(self) -> Mapping[str, object]:
        return self.raw["application_labels"]  # type: ignore[return-value]

    @property
    def result_labels(self) -> Mapping[str, object]:
        return self.raw["result_labels"]  # type: ignore[return-value]

    @property
    def stale_after_seconds(self) -> int:
        return int(self.raw["stale_after_seconds"])


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    return value


def validate_retained_payload(value: object) -> None:
    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in FORBIDDEN_KEYS:
                    raise ContractError("retained payload has a forbidden field")
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            if any(pattern.search(item) for pattern in SECRET_PATTERNS):
                raise ContractError("retained payload contains a secret pattern")

    visit(value)


def _validate_secret_strings(value: object) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _validate_secret_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_secret_strings(nested)
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            raise ContractError("contract contains a secret pattern")


def load_topology(path: Path) -> Topology:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError("unable to load observability topology") from error
    return validate_topology(value)


def validate_topology(value: object) -> Topology:
    raw = dict(_mapping(value, "topology"))
    if set(raw) != {
        "schema",
        "components",
        "application_labels",
        "result_labels",
        "public_denied_paths",
        "recording_rules",
        "alerts",
        "dashboard_rows",
        "scrape_interval_seconds",
        "stale_after_seconds",
    }:
        raise ContractError("topology fields are invalid")
    if raw["schema"] != TOPOLOGY_SCHEMA:
        raise ContractError("topology schema is unsupported")
    expected_path = Path(__file__).with_name("topology.json")
    if value is not None and expected_path.exists():
        canonical = json.loads(expected_path.read_text(encoding="utf-8"))
        if raw != canonical:
            raise ContractError("topology expands or changes the fixed contract")
    _validate_secret_strings(raw)
    return Topology(raw=raw, digest=_canonical_digest(raw))


def validate_label(
    topology: Topology,
    name: str,
    value: str,
    *,
    result_family: str | None = None,
) -> None:
    if name == "route":
        allowed = ROUTES
    elif name == "result":
        if result_family is None or result_family not in topology.result_labels:
            raise ContractError("metric result family is invalid")
        allowed = frozenset(
            str(item)
            for item in _array(
                topology.result_labels[result_family],
                "result labels",
            )
        )
    elif name in topology.application_labels:
        allowed = frozenset(
            str(item)
            for item in _array(
                topology.application_labels[name],
                f"{name} labels",
            )
        )
    else:
        raise ContractError("application metric label name is not allowed")
    if value not in allowed:
        raise ContractError("application metric label value is not bounded")


def public_operational_path_denied(topology: Topology, path: str) -> bool:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "?" in path
        or "#" in path
        or "//" in path
    ):
        raise ContractError("public path is invalid")
    for denied_value in _array(
        topology.raw["public_denied_paths"],
        "public denied paths",
    ):
        denied = str(denied_value)
        if path == denied or (denied.endswith("/") and path.startswith(denied)):
            return True
    return False


def generate_targets(
    topology: Topology,
    inventory_value: object,
    *,
    forbidden_addresses: Sequence[str] = (),
) -> list[dict[str, object]]:
    inventory = _mapping(inventory_value, "inventory")
    if set(inventory) != set(topology.components):
        raise ContractError("target inventory components are incomplete")
    forbidden = {
        str(ipaddress.ip_address(address))
        for address in forbidden_addresses
    }
    seen_addresses: set[tuple[str, int]] = set()
    seen_hosts: set[tuple[str, str]] = set()
    jobs: list[dict[str, object]] = []
    for component in topology.components:
        settings = _mapping(topology.components[component], "component settings")
        entries = _array(inventory[component], f"{component} targets")
        if not entries:
            raise ContractError("every component requires at least one target")
        targets: list[dict[str, object]] = []
        for entry_value in entries:
            entry = _mapping(entry_value, "target")
            if set(entry) != {"host", "address", "workers", "tls_verified"}:
                raise ContractError("target fields are invalid")
            host = str(entry["host"])
            if HOST_PATTERN.fullmatch(host) is None:
                raise ContractError("target host is invalid")
            try:
                address = str(ipaddress.ip_address(str(entry["address"])))
            except ValueError as error:
                raise ContractError("target address is invalid") from error
            workers = entry["workers"]
            if workers != settings["workers"] or isinstance(workers, bool):
                raise ContractError("target worker count violates the baseline")
            if entry["tls_verified"] is not True:
                raise ContractError("target does not use verified TLS")
            if address in forbidden:
                raise ContractError("VIP or public target address is forbidden")
            port = int(settings["port"])
            if (address, port) in seen_addresses or (component, host) in seen_hosts:
                raise ContractError("target identity is repeated")
            seen_addresses.add((address, port))
            seen_hosts.add((component, host))
            formatted = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
            targets.append(
                {
                    "target": formatted,
                    "labels": {
                        "service": f"coffer-{component}",
                        "instance": host,
                    },
                }
            )
        jobs.append(
            {
                "job_name": f"coffer-{component}",
                "scheme": "https",
                "metrics_path": settings["metrics_path"],
                "targets": targets,
            }
        )
    validate_retained_payload(jobs)
    return jobs


def create_restart_state(topology: Topology) -> dict[str, object]:
    return {
        "schema": STATE_SCHEMA,
        "topology_digest": topology.digest,
        "series": {},
    }


def _number(value: object, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ContractError(f"{label} must be a finite nonnegative number")
    return float(value)


def observe_sample(
    topology: Topology,
    state_value: object,
    *,
    component: str,
    instance: str,
    process_start_seconds: float,
    counter: float,
    observed_at_seconds: float,
) -> dict[str, object]:
    state = deepcopy(dict(_mapping(state_value, "restart state")))
    if set(state) != {"schema", "topology_digest", "series"}:
        raise ContractError("restart state fields are invalid")
    if state["schema"] != STATE_SCHEMA or state["topology_digest"] != topology.digest:
        raise ContractError("restart state contract does not match")
    if component not in topology.components or HOST_PATTERN.fullmatch(instance) is None:
        raise ContractError("restart series identity is invalid")
    start = _number(process_start_seconds, "process start")
    value = _number(counter, "counter")
    observed = _number(observed_at_seconds, "observation time")
    if start > observed:
        raise ContractError("process start is after observation")
    series = dict(_mapping(state["series"], "restart series"))
    key = f"{component}:{instance}"
    previous = series.get(key)
    reset = False
    if previous is not None:
        old = _mapping(previous, "restart sample")
        old_start = float(old["process_start_seconds"])
        old_counter = float(old["counter"])
        old_observed = float(old["observed_at_seconds"])
        if observed <= old_observed or start < old_start:
            raise ContractError("restart sample time regressed")
        if start == old_start and value < old_counter:
            raise ContractError("counter reset lacks a newer process start")
        if start > old_start:
            reset = True
    series[key] = {
        "component": component,
        "instance_sha256": _canonical_digest(instance),
        "process_start_seconds": start,
        "counter": value,
        "observed_at_seconds": observed,
        "reset": reset,
    }
    state["series"] = series
    validate_retained_payload(state)
    return state


def stale_series(
    topology: Topology,
    state_value: object,
    now_seconds: float,
) -> tuple[str, ...]:
    state = _mapping(state_value, "restart state")
    if state.get("schema") != STATE_SCHEMA or state.get("topology_digest") != topology.digest:
        raise ContractError("restart state contract does not match")
    now = _number(now_seconds, "current time")
    result: list[str] = []
    for key, value in _mapping(state.get("series"), "restart series").items():
        sample = _mapping(value, "restart sample")
        observed = float(sample["observed_at_seconds"])
        if now < observed:
            raise ContractError("current time precedes an observation")
        if now - observed > topology.stale_after_seconds:
            result.append(str(key))
    return tuple(sorted(result))


def redacted_evidence(
    topology: Topology,
    targets: Sequence[Mapping[str, object]],
    state: Mapping[str, object],
) -> dict[str, object]:
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "topology_digest": topology.digest,
        "target_count": sum(
            len(_array(job["targets"], "job targets"))
            for job in targets
        ),
        "target_set_sha256": _canonical_digest(targets),
        "restart_state_sha256": _canonical_digest(state),
        "recording_rule_count": len(
            _array(topology.raw["recording_rules"], "recording rules")
        ),
        "alert_count": len(_array(topology.raw["alerts"], "alerts")),
        "dashboard_row_count": len(
            _array(topology.raw["dashboard_rows"], "dashboard rows")
        ),
    }
    validate_retained_payload(evidence)
    return evidence
