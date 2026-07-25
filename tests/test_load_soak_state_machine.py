from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIRECTORY = ROOT / "poc" / "load-soak"
TOPOLOGY_PATH = MODULE_DIRECTORY / "topology.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MODEL = load_module(
    "coffer_load_soak_state_machine_tests",
    MODULE_DIRECTORY / "state_machine.py",
)


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def topology() -> dict:
    return MODEL.load_topology(TOPOLOGY_PATH)


def latency(topo: dict) -> dict:
    return {
        name: {
            "p95": limits["p95"] / 2,
            "p99": limits["p99"] / 2,
        }
        for name, limits in topo["latency_milliseconds"].items()
    }


def profile_evidence(topo: dict, name: str) -> dict:
    profile = topo["profiles"][name]
    return {
        "availability": {
            key: 100.0
            for key in topo["availability_percent"]
        },
        "burst_clients": profile["burst_clients"],
        "digest_mismatches": 0,
        "duration_seconds": profile["duration_seconds"],
        "latency_milliseconds": latency(topo),
        "operation_counts": {
            operation: 1
            for operation in topo["operations"]
        },
        "profile": name,
        "steady_clients": profile["steady_clients"],
        "transfer_bytes": profile["transfer_ceiling_bytes"] // 2,
        "unexpected_errors": 0,
    }


def evidence_for(phase: str, state: dict, topo: dict) -> dict:
    if phase == "preflighted":
        return {
            "invocation_hash": digest("invocation"),
            "ownership_hash": digest("ownership"),
            "target_class": topo["target_class"],
            "transfer_ceiling_bytes": topo["profiles"]["soak"][
                "transfer_ceiling_bytes"
            ],
            "unrelated_before_hash": digest("unrelated"),
            "writer_scope_exact": True,
        }
    if phase == "dependencies-qualified":
        return {
            "architectures": {
                architecture: True
                for architecture in topo["required_architectures"]
            },
            "ceph_evidence_hash": digest("ceph"),
            "distribution_evidence_hash": digest("distribution"),
            "status": "qualified",
        }
    if phase == "topology-verified":
        return {
            "configuration_hash": digest("configuration"),
            "edge_only_ingress": True,
            "observability_direct": True,
            "private_tls": True,
            "replicas": topo["replicas"],
            "shared_rgw": True,
            "shared_sql": True,
        }
    if phase == "clients-qualified":
        return {
            "ca_verified": True,
            "clients": {
                client: True
                for client in topo["clients"]
            },
            "insecure_mode": False,
            "versions_hash": digest("client-versions"),
        }
    if phase == "seed-loaded":
        return {
            "active_uploads": 0,
            "inventory_before_hash": digest("inventory"),
            "logical_bytes": 1024,
            "payload_retained": False,
            "quota_limit_bytes": 10 * 1024,
            "seed_hash": digest("seed"),
        }
    if phase == "smoke-complete":
        return profile_evidence(topo, "smoke")
    if phase == "ramp-complete":
        return {
            "accepted_clients": 32,
            "levels": [
                {
                    "clients": clients,
                    "completed": clients <= 32,
                    "maximum_limit_usage_percent": (
                        60 if clients <= 32 else 80
                    ),
                    "minimum_headroom_percent": (
                        40 if clients <= 32 else 20
                    ),
                    "queue_growth": clients > 32,
                }
                for clients in topo["ramp_clients"]
            ],
            "steady_backlog_growth": False,
        }
    if phase == "baseline-complete":
        return profile_evidence(topo, "qualification")
    if phase == "faults-complete":
        return {
            name: {
                "data_integrity": True,
                "injected": True,
                "recovered": True,
                "recovery_seconds": limits["recovery_seconds"] / 2,
                "security_boundary": True,
                "unexpected_errors": 0,
                "window_seconds": limits["window_seconds"] / 2,
            }
            for name, limits in topo["faults"].items()
        }
    if phase == "soak-complete":
        return profile_evidence(topo, "soak")
    if phase == "data-verified":
        return {
            "active_uploads": 0,
            "claims_exact": True,
            "digest_checks": 1000,
            "digest_checks_passed": 1000,
            "galera_nodes_converged": topo["replicas"]["galera"],
            "inventory_after_hash": state["facts"]["inventory_before_hash"],
            "multipart_uploads": 0,
            "quota_invariant": True,
        }
    if phase == "metrics-verified":
        return {
            "alerts": topo["required_alerts"],
            "direct_targets": {
                component: topo["replicas"][component]
                for component in ("api", "edge", "reconcile", "registry")
            },
            "recording_rules": topo["required_recording_rules"],
            "restart_resets": True,
            "schema_mismatches": 0,
            "secret_leaks": 0,
            "stale_series": True,
        }
    if phase == "torn-down":
        return {
            "audit_complete": True,
            "residue": {
                key: 0
                for key in topo["residue_keys"]
            },
            "unrelated_after_hash": state["facts"]["unrelated_before_hash"],
        }
    raise AssertionError(f"unknown phase {phase}")


def advance_to(stop_before: str | None = None) -> tuple[dict, dict]:
    topo = topology()
    state = MODEL.new_state(topo)
    for phase in topo["phases"]:
        if phase == stop_before:
            break
        state = MODEL.advance(
            topo,
            state,
            phase,
            evidence_for(phase, state, topo),
        )
    return topo, state


def test_topology_fixes_profiles_clients_faults_and_residue() -> None:
    topo = topology()

    assert topo["profiles"]["qualification"] == {
        "duration_seconds": 1800,
        "steady_clients": 16,
        "burst_clients": 32,
        "transfer_ceiling_bytes": 40 * 1024**3,
    }
    assert topo["ramp_clients"] == [1, 2, 4, 8, 16, 32, 64]
    assert topo["clients"] == [
        "docker",
        "podman",
        "skopeo",
        "oras",
        "nerdctl",
        "raw-oci",
    ]
    assert len(topo["faults"]) == 10
    assert len(topo["residue_keys"]) == 18


def test_complete_lifecycle_is_tamper_evident_and_zero_residue() -> None:
    topo, state = advance_to()

    assert state["complete"] is True
    assert state["phase"] == "torn-down"
    assert len(state["history"]) == len(topo["phases"])
    assert state["facts"]["accepted_clients"] == 32
    assert state["facts"]["inventory_before_hash"] == digest("inventory")
    assert all(
        MODEL.HASH.fullmatch(entry["entry_hash"])
        for entry in state["history"]
    )


def test_out_of_order_or_post_completion_transition_is_refused() -> None:
    topo = topology()
    state = MODEL.new_state(topo)

    with pytest.raises(MODEL.LoadSoakError, match="transition"):
        MODEL.advance(
            topo,
            state,
            "clients-qualified",
            evidence_for("clients-qualified", state, topo),
        )
    _, complete = advance_to()
    with pytest.raises(MODEL.LoadSoakError, match="complete"):
        MODEL.advance(topo, complete, "torn-down", {})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "candidate", "not qualified"),
        ("distribution_evidence_hash", "not-a-hash", "hash"),
    ],
)
def test_dependency_release_gate_fails_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    topo, state = advance_to("dependencies-qualified")
    evidence = evidence_for("dependencies-qualified", state, topo)
    evidence[field] = value

    with pytest.raises(MODEL.LoadSoakError, match=message):
        MODEL.advance(
            topo,
            state,
            "dependencies-qualified",
            evidence,
        )


def test_one_unqualified_architecture_is_refused() -> None:
    topo, state = advance_to("dependencies-qualified")
    evidence = evidence_for("dependencies-qualified", state, topo)
    evidence["architectures"]["aarch64"] = False

    with pytest.raises(MODEL.LoadSoakError, match="architecture"):
        MODEL.advance(topo, state, "dependencies-qualified", evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("edge_only_ingress", False),
        ("private_tls", False),
        ("shared_sql", False),
        ("shared_rgw", False),
        ("observability_direct", False),
    ],
)
def test_runtime_topology_boundary_is_exact(field: str, value: bool) -> None:
    topo, state = advance_to("topology-verified")
    evidence = evidence_for("topology-verified", state, topo)
    evidence[field] = value

    with pytest.raises(MODEL.LoadSoakError, match="topology"):
        MODEL.advance(topo, state, "topology-verified", evidence)


def test_replica_or_client_matrix_drift_is_refused() -> None:
    topo, state = advance_to("topology-verified")
    evidence = evidence_for("topology-verified", state, topo)
    evidence["replicas"] = {**evidence["replicas"], "edge": 2}
    with pytest.raises(MODEL.LoadSoakError, match="replica"):
        MODEL.advance(topo, state, "topology-verified", evidence)

    topo, state = advance_to("clients-qualified")
    evidence = evidence_for("clients-qualified", state, topo)
    del evidence["clients"]["oras"]
    with pytest.raises(MODEL.LoadSoakError, match="client"):
        MODEL.advance(topo, state, "clients-qualified", evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ca_verified", False),
        ("insecure_mode", True),
    ],
)
def test_insecure_or_unverified_client_is_refused(
    field: str,
    value: bool,
) -> None:
    topo, state = advance_to("clients-qualified")
    evidence = evidence_for("clients-qualified", state, topo)
    evidence[field] = value

    with pytest.raises(MODEL.LoadSoakError, match="client"):
        MODEL.advance(topo, state, "clients-qualified", evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("active_uploads", 1),
        ("payload_retained", True),
        ("quota_limit_bytes", 1),
    ],
)
def test_seed_requires_clean_bounded_private_input(
    field: str,
    value: object,
) -> None:
    topo, state = advance_to("seed-loaded")
    evidence = evidence_for("seed-loaded", state, topo)
    evidence[field] = value

    with pytest.raises(MODEL.LoadSoakError):
        MODEL.advance(topo, state, "seed-loaded", evidence)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("duration_seconds",), 119, "profile"),
        (("steady_clients",), 5, "profile"),
        (("unexpected_errors",), 1, "profile"),
        (("digest_mismatches",), 1, "profile"),
        (("latency_milliseconds", "manifest-read", "p95"), 501, "latency"),
        (("availability", "pull"), 99.89, "availability"),
        (("operation_counts", "artifact"), 0, "operation"),
    ],
)
def test_smoke_profile_gates_fail_closed(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    topo, state = advance_to("smoke-complete")
    evidence = evidence_for("smoke-complete", state, topo)
    target = evidence
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(MODEL.LoadSoakError, match=message):
        MODEL.advance(topo, state, "smoke-complete", evidence)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("accepted-low", "operating point"),
        ("resume-after-failure", "resumed"),
        ("headroom", "ramp"),
        ("usage", "ramp"),
        ("backlog", "operating point"),
    ],
)
def test_ramp_requires_measured_sustainable_boundary(
    mutation: str,
    message: str,
) -> None:
    topo, state = advance_to("ramp-complete")
    evidence = evidence_for("ramp-complete", state, topo)
    if mutation == "accepted-low":
        evidence["accepted_clients"] = 16
    elif mutation == "resume-after-failure":
        evidence["levels"][-1]["completed"] = True
        evidence["levels"][-1]["queue_growth"] = False
        evidence["levels"][-1]["minimum_headroom_percent"] = 40
        evidence["levels"][-1]["maximum_limit_usage_percent"] = 60
        evidence["levels"][-2]["completed"] = False
    elif mutation == "headroom":
        evidence["levels"][4]["minimum_headroom_percent"] = 29
    elif mutation == "usage":
        evidence["levels"][4]["maximum_limit_usage_percent"] = 71
    else:
        evidence["steady_backlog_growth"] = True

    with pytest.raises(MODEL.LoadSoakError, match=message):
        MODEL.advance(topo, state, "ramp-complete", evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recovered", False),
        ("data_integrity", False),
        ("security_boundary", False),
        ("unexpected_errors", 1),
        ("recovery_seconds", 999),
        ("window_seconds", 999),
    ],
)
def test_every_fault_requires_bounded_secure_recovery(
    field: str,
    value: object,
) -> None:
    topo, state = advance_to("faults-complete")
    evidence = evidence_for("faults-complete", state, topo)
    evidence["registry-mid-upload"][field] = value

    with pytest.raises(MODEL.LoadSoakError, match="fault"):
        MODEL.advance(topo, state, "faults-complete", evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inventory_after_hash", digest("drift")),
        ("quota_invariant", False),
        ("claims_exact", False),
        ("galera_nodes_converged", 2),
        ("active_uploads", 1),
        ("multipart_uploads", 1),
        ("digest_checks_passed", 999),
    ],
)
def test_final_data_invariants_are_exact(
    field: str,
    value: object,
) -> None:
    topo, state = advance_to("data-verified")
    evidence = evidence_for("data-verified", state, topo)
    evidence[field] = value

    with pytest.raises(MODEL.LoadSoakError, match="data"):
        MODEL.advance(topo, state, "data-verified", evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("restart_resets", False),
        ("stale_series", False),
        ("schema_mismatches", 1),
        ("secret_leaks", 1),
    ],
)
def test_metrics_require_direct_restart_correct_secret_safe_evidence(
    field: str,
    value: object,
) -> None:
    topo, state = advance_to("metrics-verified")
    evidence = evidence_for("metrics-verified", state, topo)
    evidence[field] = value

    with pytest.raises(MODEL.LoadSoakError, match="metrics"):
        MODEL.advance(topo, state, "metrics-verified", evidence)


def test_metric_target_rule_or_alert_drift_is_refused() -> None:
    topo, state = advance_to("metrics-verified")
    evidence = evidence_for("metrics-verified", state, topo)
    evidence["direct_targets"]["api"] = 2
    with pytest.raises(MODEL.LoadSoakError, match="target"):
        MODEL.advance(topo, state, "metrics-verified", evidence)

    evidence = evidence_for("metrics-verified", state, topo)
    evidence["recording_rules"] = evidence["recording_rules"][:-1]
    with pytest.raises(MODEL.LoadSoakError, match="metrics"):
        MODEL.advance(topo, state, "metrics-verified", evidence)


def test_teardown_requires_zero_residue_and_unchanged_unrelated_state() -> None:
    topo, state = advance_to("torn-down")
    evidence = evidence_for("torn-down", state, topo)
    evidence["residue"]["object_versions"] = 1
    with pytest.raises(MODEL.LoadSoakError, match="residue"):
        MODEL.advance(topo, state, "torn-down", evidence)

    evidence = evidence_for("torn-down", state, topo)
    evidence["unrelated_after_hash"] = digest("changed")
    with pytest.raises(MODEL.LoadSoakError, match="residue"):
        MODEL.advance(topo, state, "torn-down", evidence)


def test_state_history_tamper_is_refused() -> None:
    topo, state = advance_to("clients-qualified")
    tampered = copy.deepcopy(state)
    tampered["history"][1]["evidence_hash"] = digest("tampered")

    with pytest.raises(MODEL.LoadSoakError, match="history"):
        MODEL.advance(
            topo,
            tampered,
            "seed-loaded",
            evidence_for("seed-loaded", state, topo),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "not-retained"},
        {"repository_name": "tenant/repository"},
        {"endpoint": "https://registry.example.test/v2/"},
        {"value": "Bearer abcdefghijklmnopqrstuvwxyz"},
        {"value": "eyJabcdefgh.ijklmnop.qrstuvwx"},
    ],
)
def test_secret_or_identity_bearing_evidence_is_refused(payload: dict) -> None:
    with pytest.raises(MODEL.LoadSoakError, match="retained evidence"):
        MODEL.validate_retained_evidence(payload)


def test_state_machine_has_no_runtime_or_external_adapter() -> None:
    source = (MODULE_DIRECTORY / "state_machine.py").read_text(encoding="utf-8")

    for forbidden in (
        "import boto",
        "import http",
        "import requests",
        "import socket",
        "import sqlalchemy",
        "import subprocess",
        "urllib",
    ):
        assert forbidden not in source
