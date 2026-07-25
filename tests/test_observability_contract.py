from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from coffer.observability import (
    ADMISSION_RESULTS,
    BOUNDED_COMPONENTS,
    BOUNDED_HTTP_METHODS,
    BOUNDED_ROUTES,
    BOUNDED_STATUS_CLASSES,
    READINESS_RESULTS,
    RECONCILIATION_RESULTS,
    TOKEN_RESULTS,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "observability" / "contract.py"
TOPOLOGY_PATH = ROOT / "poc" / "observability" / "topology.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = _load_module("coffer_observability_contract_tests", MODULE_PATH)


def topology():
    return CONTRACT.load_topology(TOPOLOGY_PATH)


def inventory():
    return {
        "api": [
            {"host": "controller1", "address": "10.0.0.11", "workers": 1, "tls_verified": True},
            {"host": "controller2", "address": "10.0.0.12", "workers": 1, "tls_verified": True},
        ],
        "edge": [
            {"host": "controller1", "address": "10.0.0.11", "workers": 1, "tls_verified": True},
            {"host": "controller2", "address": "10.0.0.12", "workers": 1, "tls_verified": True},
        ],
        "reconcile": [
            {"host": "controller1", "address": "10.0.0.11", "workers": 1, "tls_verified": True},
            {"host": "controller2", "address": "10.0.0.12", "workers": 1, "tls_verified": True},
        ],
        "registry": [
            {"host": "storage1", "address": "10.0.0.21", "workers": 1, "tls_verified": True},
            {"host": "storage2", "address": "10.0.0.22", "workers": 1, "tls_verified": True},
        ],
    }


def test_checked_in_topology_fixes_the_candidate_contract() -> None:
    loaded = topology()

    assert loaded.raw["schema"] == CONTRACT.TOPOLOGY_SCHEMA
    assert set(loaded.components) == {"api", "edge", "reconcile", "registry"}
    assert all(item["workers"] == 1 for item in loaded.components.values())
    assert loaded.raw["scrape_interval_seconds"] == 30
    assert loaded.stale_after_seconds == 90
    assert len(loaded.raw["recording_rules"]) == 6
    assert len(loaded.raw["alerts"]) == 8
    assert len(loaded.raw["dashboard_rows"]) == 8


def test_runtime_metric_allowlists_match_the_versioned_topology() -> None:
    loaded = topology()

    assert BOUNDED_COMPONENTS == frozenset(
        loaded.application_labels["component"]
    )
    assert BOUNDED_HTTP_METHODS | {"OTHER"} == frozenset(
        loaded.application_labels["method"]
    )
    assert BOUNDED_STATUS_CLASSES == frozenset(
        loaded.application_labels["status"]
    )
    assert BOUNDED_ROUTES == CONTRACT.ROUTES
    assert TOKEN_RESULTS == frozenset(loaded.result_labels["token"])
    assert READINESS_RESULTS == frozenset(loaded.result_labels["readiness"])
    assert ADMISSION_RESULTS == frozenset(loaded.result_labels["admission"])
    assert RECONCILIATION_RESULTS == frozenset(
        loaded.result_labels["reconciliation"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("components", {"api": {"workers": 2}}),
        ("public_denied_paths", ["/metrics"]),
        ("recording_rules", ["unknown"]),
        ("alerts", ["unknown"]),
        ("stale_after_seconds", 300),
    ],
)
def test_topology_expansion_or_change_is_refused(field, value) -> None:
    raw = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    raw[field] = value

    with pytest.raises(CONTRACT.ContractError, match="fixed contract"):
        CONTRACT.validate_topology(raw)


@pytest.mark.parametrize(
    ("name", "value", "family"),
    [
        ("component", "api", None),
        ("route", "/v1/repositories/{repository_id}", None),
        ("method", "OTHER", None),
        ("status", "5xx", None),
        ("dependency", "kms", None),
        ("result", "over_quota", "admission"),
        ("result", "stale_claim", "reconciliation"),
    ],
)
def test_fixed_application_labels_are_accepted(name, value, family) -> None:
    CONTRACT.validate_label(topology(), name, value, result_family=family)


@pytest.mark.parametrize(
    ("name", "value", "family"),
    [
        ("component", "project-a", None),
        ("route", "/v1/repositories/concrete-id", None),
        ("method", "UNBOUNDED", None),
        ("status", "599-secret", None),
        ("dependency", "https://rgw.example", None),
        ("result", "project-a", "admission"),
        ("result", "issued", "unknown"),
        ("project_id", "project-a", None),
    ],
)
def test_unbounded_application_labels_are_refused(name, value, family) -> None:
    with pytest.raises(CONTRACT.ContractError, match="label|family"):
        CONTRACT.validate_label(topology(), name, value, result_family=family)


@pytest.mark.parametrize(
    "path",
    [
        "/healthz",
        "/readyz",
        "/metrics",
        "/debug",
        "/debug/",
        "/debug/pprof",
    ],
)
def test_public_operational_paths_are_denied(path) -> None:
    assert CONTRACT.public_operational_path_denied(topology(), path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/v1/repositories",
        "/v2/",
        "/debugger",
        "/metrics-extra",
    ],
)
def test_public_service_paths_are_not_confused_with_operational_paths(path) -> None:
    assert CONTRACT.public_operational_path_denied(topology(), path) is False


@pytest.mark.parametrize("path", ["metrics", "//metrics", "/metrics?raw=1"])
def test_malformed_public_paths_are_refused(path) -> None:
    with pytest.raises(CONTRACT.ContractError, match="path"):
        CONTRACT.public_operational_path_denied(topology(), path)


def test_targets_are_direct_per_replica_and_never_the_vip() -> None:
    targets = CONTRACT.generate_targets(
        topology(),
        inventory(),
        forbidden_addresses=["10.0.0.10", "203.0.113.10"],
    )

    assert [job["job_name"] for job in targets] == [
        "coffer-api",
        "coffer-edge",
        "coffer-reconcile",
        "coffer-registry",
    ]
    assert sum(len(job["targets"]) for job in targets) == 8
    assert all(job["scheme"] == "https" for job in targets)
    serialized = json.dumps(targets, sort_keys=True)
    assert "10.0.0.10" not in serialized
    assert "203.0.113.10" not in serialized
    assert "controller1" in serialized
    assert "storage2" in serialized


@pytest.mark.parametrize(
    ("component", "field", "value", "message"),
    [
        ("api", "workers", 2, "worker"),
        ("edge", "tls_verified", False, "TLS"),
        ("registry", "address", "not-an-ip", "address"),
        ("reconcile", "host", "UPPERCASE", "host"),
        ("api", "address", "10.0.0.10", "VIP"),
    ],
)
def test_unsafe_target_inputs_are_refused(
    component,
    field,
    value,
    message,
) -> None:
    changed = inventory()
    changed[component][0][field] = value

    with pytest.raises(CONTRACT.ContractError, match=message):
        CONTRACT.generate_targets(
            topology(),
            changed,
            forbidden_addresses=["10.0.0.10"],
        )


def test_duplicate_target_identity_is_refused() -> None:
    changed = inventory()
    changed["api"].append(deepcopy(changed["api"][0]))

    with pytest.raises(CONTRACT.ContractError, match="repeated"):
        CONTRACT.generate_targets(topology(), changed)


def test_counter_reset_requires_a_newer_process_start() -> None:
    loaded = topology()
    state = CONTRACT.create_restart_state(loaded)
    state = CONTRACT.observe_sample(
        loaded,
        state,
        component="api",
        instance="controller1",
        process_start_seconds=100,
        counter=10,
        observed_at_seconds=110,
    )
    state = CONTRACT.observe_sample(
        loaded,
        state,
        component="api",
        instance="controller1",
        process_start_seconds=100,
        counter=12,
        observed_at_seconds=120,
    )
    with pytest.raises(CONTRACT.ContractError, match="newer process start"):
        CONTRACT.observe_sample(
            loaded,
            state,
            component="api",
            instance="controller1",
            process_start_seconds=100,
            counter=1,
            observed_at_seconds=130,
        )

    restarted = CONTRACT.observe_sample(
        loaded,
        state,
        component="api",
        instance="controller1",
        process_start_seconds=125,
        counter=1,
        observed_at_seconds=130,
    )
    sample = restarted["series"]["api:controller1"]
    assert sample["reset"] is True
    assert "controller1" not in json.dumps(sample)


def test_stale_series_uses_the_exact_missed_scrape_bound() -> None:
    loaded = topology()
    state = CONTRACT.observe_sample(
        loaded,
        CONTRACT.create_restart_state(loaded),
        component="registry",
        instance="storage1",
        process_start_seconds=1,
        counter=1,
        observed_at_seconds=100,
    )

    assert CONTRACT.stale_series(loaded, state, 190) == ()
    assert CONTRACT.stale_series(loaded, state, 191) == ("registry:storage1",)


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "do-not-retain"},
        {"repository_id": "concrete-id"},
        {"message": "Authorization: Basic do-not-retain"},
        {"message": "Bearer abcdefghijklmnopqrstuvwxyz"},
        {"message": "-----BEGIN PRIVATE KEY-----"},
        {"message": "eyJabcdefghijk.abcdefghijklmnop.signature"},
    ],
)
def test_retained_evidence_rejects_secrets_and_high_cardinality(payload) -> None:
    with pytest.raises(CONTRACT.ContractError, match="forbidden|secret"):
        CONTRACT.validate_retained_payload(payload)


def test_redacted_evidence_contains_only_hashes_and_counts() -> None:
    loaded = topology()
    targets = CONTRACT.generate_targets(loaded, inventory())
    state = CONTRACT.observe_sample(
        loaded,
        CONTRACT.create_restart_state(loaded),
        component="api",
        instance="controller1",
        process_start_seconds=100,
        counter=1,
        observed_at_seconds=110,
    )
    evidence = CONTRACT.redacted_evidence(loaded, targets, state)
    serialized = json.dumps(evidence, sort_keys=True)

    assert evidence["schema"] == CONTRACT.EVIDENCE_SCHEMA
    assert evidence["target_count"] == 8
    assert evidence["recording_rule_count"] == 6
    assert evidence["alert_count"] == 8
    assert evidence["dashboard_row_count"] == 8
    assert "controller1" not in serialized
    assert "10.0.0.11" not in serialized
