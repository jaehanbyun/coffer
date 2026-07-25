from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

import importlib.util
import sys


MODULE_PATH = Path(__file__).with_name("state_machine.py")
SPEC = importlib.util.spec_from_file_location(
    "coffer_load_soak_state_machine_evidence",
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("load/soak state machine is unavailable")
state_machine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = state_machine
SPEC.loader.exec_module(state_machine)

EVIDENCE_SCHEMA = "coffer.load-soak-evidence/v1"
VERIFIED_SCHEMA = "coffer.load-soak-verified/v1"
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
REVISION = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")


class EvidenceError(RuntimeError):
    pass


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _exact_mapping(
    value: object,
    keys: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise EvidenceError(f"{category} boundary changed")
    return value


def _validate_bindings(
    bindings: object,
    expected: Mapping[str, Any],
    topology: Mapping[str, Any],
) -> Mapping[str, Any]:
    keys = {
        "architectures",
        "ceph_revision",
        "ceph_version",
        "client_versions_hash",
        "configuration_hash",
        "distribution_revision",
        "distribution_version",
        "driver_revision",
        "image_set_hash",
        "readiness_evidence_hash",
        "readiness_status",
    }
    checked = _exact_mapping(bindings, keys, "load evidence binding")
    if checked != expected:
        raise EvidenceError("load evidence binding changed")
    if (
        checked["readiness_status"] != "qualified"
        or checked["architectures"] != topology["required_architectures"]
        or VERSION.fullmatch(checked["distribution_version"]) is None
        or VERSION.fullmatch(checked["ceph_version"]) is None
        or REVISION.fullmatch(checked["distribution_revision"]) is None
        or REVISION.fullmatch(checked["ceph_revision"]) is None
        or REVISION.fullmatch(checked["driver_revision"]) is None
    ):
        raise EvidenceError("load release binding is not qualified")
    for key in (
        "client_versions_hash",
        "configuration_hash",
        "image_set_hash",
        "readiness_evidence_hash",
    ):
        if (
            not isinstance(checked[key], str)
            or state_machine.HASH.fullmatch(checked[key]) is None
        ):
            raise EvidenceError("load evidence hash binding is invalid")
    return checked


def verify_document(
    document: object,
    *,
    topology: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_mapping(
        document,
        {
            "bindings",
            "phase_evidence",
            "schema",
            "synthetic",
            "topology_hash",
        },
        "load evidence",
    )
    if checked["schema"] != EVIDENCE_SCHEMA:
        raise EvidenceError("load evidence schema changed")
    if checked["synthetic"] is not False:
        raise EvidenceError("synthetic load evidence is not promotable")
    expected_topology_hash = state_machine._hash(topology)
    if checked["topology_hash"] != expected_topology_hash:
        raise EvidenceError("load evidence topology changed")
    bindings = _validate_bindings(
        checked["bindings"],
        expected_bindings,
        topology,
    )
    phases = checked["phase_evidence"]
    if not isinstance(phases, list) or len(phases) != len(topology["phases"]):
        raise EvidenceError("load phase evidence is incomplete")
    state = state_machine.new_state(topology)
    for expected_phase, item in zip(topology["phases"], phases):
        phase = _exact_mapping(
            item,
            {"evidence", "phase"},
            "load phase evidence",
        )
        if phase["phase"] != expected_phase or not isinstance(
            phase["evidence"],
            Mapping,
        ):
            raise EvidenceError("load phase evidence order changed")
        try:
            state = state_machine.advance(
                topology,
                state,
                expected_phase,
                phase["evidence"],
            )
        except state_machine.LoadSoakError as error:
            raise EvidenceError("load phase evidence failed") from error
    if not state["complete"]:
        raise EvidenceError("load evidence is incomplete")
    binding_hash = _hash(bindings)
    return {
        "binding_hash": binding_hash,
        "evidence_hash": _hash(checked),
        "facts_hash": _hash(state["facts"]),
        "history_hash": _hash(state["history"]),
        "phase_count": len(phases),
        "schema": VERIFIED_SCHEMA,
        "topology_hash": expected_topology_hash,
    }


def verify_file(
    path: Path,
    *,
    topology: Mapping[str, Any],
    expected_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise EvidenceError("load evidence file is unavailable") from error
    if not payload or len(payload) > MAX_EVIDENCE_BYTES or b"\x00" in payload:
        raise EvidenceError("load evidence file size is invalid")
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError("load evidence file is invalid") from error
    canonical = (
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    if payload != canonical:
        raise EvidenceError("load evidence file is not canonical")
    return verify_document(
        document,
        topology=topology,
        expected_bindings=expected_bindings,
    )
