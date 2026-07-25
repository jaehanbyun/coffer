from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "load-soak" / "plan.py"
TOPOLOGY_PATH = ROOT / "poc" / "load-soak" / "topology.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PLAN = load_module("coffer_load_soak_plan_tests", MODULE_PATH)
TOPOLOGY = PLAN.state_machine.load_topology(TOPOLOGY_PATH)


def request() -> dict:
    return {
        "bindings": {
            "architectures": ["aarch64", "x86_64"],
            "ceph_revision": "b" * 40,
            "ceph_version": "v20.2.3",
            "client_versions_hash": f"sha256:{'1' * 64}",
            "configuration_hash": f"sha256:{'2' * 64}",
            "distribution_revision": "a" * 40,
            "distribution_version": "v3.1.2",
            "driver_revision": "c" * 40,
            "image_set_hash": f"sha256:{'3' * 64}",
            "readiness_evidence_hash": f"sha256:{'4' * 64}",
            "readiness_status": "qualified",
        },
        "schema": "coffer.load-execution-plan-request/v1",
        "topology_sha256": PLAN._hash(TOPOLOGY),
    }


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def test_compiler_covers_every_fixed_dimension_and_budget() -> None:
    envelope = PLAN.compile_plan(request(), topology=TOPOLOGY)
    plan = envelope["plan"]

    assert envelope["schema"] == "coffer.load-execution-plan-envelope/v1"
    assert envelope["synthetic"] is True
    assert envelope["plan_sha256"] == PLAN._hash(plan)
    assert plan["schema"] == "coffer.load-execution-plan/v1"
    assert plan["target_class"] == "disposable-stage6-pilot"
    assert plan["phases"] == TOPOLOGY["phases"]
    assert plan["telemetry_windows"] == ["before", "during", "after"]
    assert [entry["name"] for entry in plan["profiles"]] == [
        "smoke",
        "qualification",
        "soak",
    ]
    assert [
        entry["transfer_ceiling_bytes"] for entry in plan["profiles"]
    ] == [
        TOPOLOGY["profiles"][name]["transfer_ceiling_bytes"]
        for name in ("smoke", "qualification", "soak")
    ]
    assert [entry["clients"] for entry in plan["ramp"]] == TOPOLOGY[
        "ramp_clients"
    ]
    assert sum(
        entry["transfer_ceiling_bytes"] for entry in plan["ramp"]
    ) <= TOPOLOGY["profiles"]["qualification"]["transfer_ceiling_bytes"]
    assert [entry["fault"] for entry in plan["faults"]] == list(
        TOPOLOGY["faults"]
    )
    assert all(entry["serial"] is True for entry in plan["faults"])
    assert [entry["name"] for entry in plan["content"]] == TOPOLOGY[
        "content_classes"
    ]
    assert [entry["client"] for entry in plan["matrix"]] == TOPOLOGY["clients"]
    assert all(
        entry["executor_contract"] == "required"
        and entry["verified_tls_required"] is True
        for entry in plan["matrix"]
    )
    assert {
        operation
        for entry in plan["matrix"]
        for operation in entry["operations"]
    } == set(TOPOLOGY["operations"])
    assert {
        content
        for entry in plan["matrix"]
        for content in entry["content_classes"]
    } == set(TOPOLOGY["content_classes"])
    raw = next(
        entry for entry in plan["matrix"] if entry["client"] == "raw-oci"
    )
    assert raw["operations"] == TOPOLOGY["operations"]
    assert raw["content_classes"] == TOPOLOGY["content_classes"]


def test_compiler_is_byte_deterministic_and_retains_no_identity() -> None:
    first = PLAN.compile_plan(request(), topology=TOPOLOGY)
    second = PLAN.compile_plan(deepcopy(request()), topology=TOPOLOGY)

    assert canonical(first) == canonical(second)
    serialized = json.dumps(first, sort_keys=True)
    for forbidden in (
        "https://",
        "project_id",
        "repository_name",
        "credential_id",
        "upload_uuid",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "topology",
        "architectures",
        "readiness",
        "distribution-version",
        "distribution-revision",
        "ceph-version",
        "ceph-series",
        "ceph-revision",
        "driver-revision",
        "evidence-hash",
        "client-order",
        "operation",
        "content",
    ],
)
def test_binding_or_capability_drift_fails_closed(mutation: str) -> None:
    value = request()
    topology = deepcopy(TOPOLOGY)
    if mutation == "schema":
        value["schema"] = "future"
    elif mutation == "topology":
        value["topology_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "architectures":
        value["bindings"]["architectures"] = ["x86_64"]
    elif mutation == "readiness":
        value["bindings"]["readiness_status"] = "candidate"
    elif mutation == "distribution-version":
        value["bindings"]["distribution_version"] = "v3.1.1"
    elif mutation == "distribution-revision":
        value["bindings"]["distribution_revision"] = "short"
    elif mutation == "ceph-version":
        value["bindings"]["ceph_version"] = "v20.2.2"
    elif mutation == "ceph-series":
        value["bindings"]["ceph_version"] = "v21.0.1"
    elif mutation == "ceph-revision":
        value["bindings"]["ceph_revision"] = "short"
    elif mutation == "driver-revision":
        value["bindings"]["driver_revision"] = "short"
    elif mutation == "evidence-hash":
        value["bindings"]["image_set_hash"] = "sha256:short"
    elif mutation == "client-order":
        topology["clients"][0], topology["clients"][1] = (
            topology["clients"][1],
            topology["clients"][0],
        )
        value["topology_sha256"] = PLAN._hash(topology)
    elif mutation == "operation":
        topology["operations"].pop()
        value["topology_sha256"] = PLAN._hash(topology)
    else:
        topology["content_classes"].pop()
        value["topology_sha256"] = PLAN._hash(topology)

    with pytest.raises(PLAN.PlanError):
        PLAN.compile_plan(value, topology=topology)


def test_owner_only_cli_emits_canonical_mode_0600_envelope(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "request.json"
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output_path = output_root / "plan.json"
    owner_file(request_path, canonical(request()))
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = PLAN.run(
        [
            "--request",
            str(request_path),
            "--output",
            str(output_path),
            "--topology",
            str(TOPOLOGY_PATH),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0
    assert stdout.getvalue() == "load plan compiled\n"
    assert stderr.getvalue() == ""
    document = json.loads(output_path.read_bytes())
    assert output_path.read_bytes() == canonical(document)
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert not any(
        path.name.startswith(".plan.json.") for path in output_root.iterdir()
    )


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("mode", "local-file-unavailable"),
        ("noncanonical", "contract-refused"),
        ("symlink-output", "output-unavailable"),
        ("alias", "contract-refused"),
    ],
)
def test_cli_file_boundary_fails_without_plan(
    tmp_path: Path,
    mutation: str,
    failure: str,
) -> None:
    request_path = tmp_path / "request.json"
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output_path = output_root / "plan.json"
    owner_file(request_path, canonical(request()))
    if mutation == "mode":
        request_path.chmod(0o640)
    elif mutation == "noncanonical":
        owner_file(
            request_path,
            json.dumps(request(), indent=2).encode("utf-8"),
        )
    elif mutation == "symlink-output":
        target = output_root / "target"
        owner_file(target, b"preserved\n")
        output_path.symlink_to(target)
    else:
        output_path = request_path

    stderr = io.StringIO()
    status = PLAN.run(
        [
            "--request",
            str(request_path),
            "--output",
            str(output_path),
            "--topology",
            str(TOPOLOGY_PATH),
        ],
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 1
    assert stderr.getvalue() == f"load plan failed: {failure}\n"
    if mutation not in ("symlink-output", "alias"):
        assert not output_path.exists()


def test_cli_arguments_are_fixed() -> None:
    stderr = io.StringIO()
    assert PLAN.run([], stdout=io.StringIO(), stderr=stderr) == 2
    assert stderr.getvalue() == "load plan failed: invalid-arguments\n"


def test_compiler_has_no_runtime_or_external_adapter_import() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import http",
        "import requests",
        "import socket",
        "import subprocess",
        "import urllib",
    ):
        assert forbidden not in source
