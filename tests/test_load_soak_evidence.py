from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIRECTORY = ROOT / "poc" / "load-soak"
TOPOLOGY_PATH = MODULE_DIRECTORY / "topology.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "load_soak.json"
UNRELATED = f"sha256:{'b' * 64}"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EVIDENCE = load_module(
    "coffer_load_soak_evidence_tests",
    MODULE_DIRECTORY / "evidence.py",
)
LIFECYCLE = load_module(
    "coffer_load_soak_lifecycle_evidence_tests",
    MODULE_DIRECTORY / "lifecycle.py",
)


def topology() -> dict:
    return EVIDENCE.state_machine.load_topology(TOPOLOGY_PATH)


def bindings() -> dict:
    return {
        "architectures": ["aarch64", "x86_64"],
        "ceph_revision": "c" * 40,
        "ceph_version": "v20.2.3",
        "client_versions_hash": f"sha256:{'1' * 64}",
        "configuration_hash": f"sha256:{'2' * 64}",
        "distribution_revision": "d" * 40,
        "distribution_version": "v3.1.2",
        "driver_revision": "e" * 40,
        "image_set_hash": f"sha256:{'3' * 64}",
        "readiness_evidence_hash": f"sha256:{'4' * 64}",
        "readiness_status": "qualified",
    }


def document() -> dict:
    topo = topology()
    fixture = LIFECYCLE.load_fixture(FIXTURE_PATH, topo)
    state = EVIDENCE.state_machine.new_state(topo)
    phases = []
    for phase in topo["phases"]:
        phase_evidence = LIFECYCLE.fixture_evidence(
            phase,
            topo,
            state,
            fixture,
            UNRELATED,
        )
        phases.append({"evidence": phase_evidence, "phase": phase})
        state = EVIDENCE.state_machine.advance(
            topo,
            state,
            phase,
            phase_evidence,
        )
    return {
        "bindings": bindings(),
        "phase_evidence": phases,
        "schema": EVIDENCE.EVIDENCE_SCHEMA,
        "synthetic": False,
        "topology_hash": EVIDENCE.state_machine._hash(topo),
    }


def test_complete_canonical_document_verifies_to_hashes() -> None:
    result = EVIDENCE.verify_document(
        document(),
        topology=topology(),
        expected_bindings=bindings(),
    )

    assert result == {
        "binding_hash": result["binding_hash"],
        "evidence_hash": result["evidence_hash"],
        "facts_hash": result["facts_hash"],
        "history_hash": result["history_hash"],
        "phase_count": 13,
        "schema": EVIDENCE.VERIFIED_SCHEMA,
        "topology_hash": EVIDENCE.state_machine._hash(topology()),
    }
    assert all(
        value.startswith("sha256:")
        for key, value in result.items()
        if key.endswith("_hash")
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("synthetic", "synthetic"),
        ("unknown", "boundary"),
        ("topology", "topology"),
        ("binding", "binding"),
        ("readiness", "binding"),
        ("architecture", "binding"),
        ("phase-missing", "incomplete"),
        ("phase-order", "order"),
        ("phase-invalid", "phase evidence failed"),
    ],
)
def test_drift_in_identity_phase_or_gate_is_refused(
    mutation: str,
    message: str,
) -> None:
    value = document()
    expected = bindings()
    if mutation == "synthetic":
        value["synthetic"] = True
    elif mutation == "unknown":
        value["raw_logs"] = []
    elif mutation == "topology":
        value["topology_hash"] = f"sha256:{'0' * 64}"
    elif mutation == "binding":
        value["bindings"]["distribution_version"] = "v3.1.3"
    elif mutation == "readiness":
        value["bindings"]["readiness_status"] = "candidate"
        expected["readiness_status"] = "candidate"
    elif mutation == "architecture":
        value["bindings"]["architectures"] = ["x86_64"]
        expected["architectures"] = ["x86_64"]
    elif mutation == "phase-missing":
        value["phase_evidence"].pop()
    elif mutation == "phase-order":
        value["phase_evidence"][0]["phase"] = "seed-loaded"
    else:
        value["phase_evidence"][5]["evidence"]["unexpected_errors"] = 1

    with pytest.raises(EVIDENCE.EvidenceError, match=message):
        EVIDENCE.verify_document(
            value,
            topology=topology(),
            expected_bindings=expected,
        )


def test_expected_binding_must_be_exact_not_caller_weakened() -> None:
    expected = bindings()
    expected["distribution_version"] = "v3.1.3"

    with pytest.raises(EVIDENCE.EvidenceError, match="binding"):
        EVIDENCE.verify_document(
            document(),
            topology=topology(),
            expected_bindings=expected,
        )


def test_canonical_file_verifies_and_noncanonical_file_is_refused(
    tmp_path: Path,
) -> None:
    value = document()
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = EVIDENCE.verify_file(
        path,
        topology=topology(),
        expected_bindings=bindings(),
    )
    assert result["phase_count"] == 13

    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(EVIDENCE.EvidenceError, match="canonical"):
        EVIDENCE.verify_file(
            path,
            topology=topology(),
            expected_bindings=bindings(),
        )


def test_secret_like_phase_evidence_is_refused() -> None:
    value = document()
    value["phase_evidence"][0]["evidence"]["token"] = "eyJabcdefgh.ijklmnop.qrstuvwx"

    with pytest.raises(EVIDENCE.EvidenceError, match="phase evidence failed"):
        EVIDENCE.verify_document(
            value,
            topology=topology(),
            expected_bindings=bindings(),
        )


def test_verifier_has_no_runtime_or_external_adapter() -> None:
    source = (MODULE_DIRECTORY / "evidence.py").read_text(encoding="utf-8")

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
