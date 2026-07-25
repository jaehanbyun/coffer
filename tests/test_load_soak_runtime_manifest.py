from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "load-soak" / "runtime_manifest.py"
TOPOLOGY_PATH = ROOT / "poc" / "load-soak" / "topology.json"
PINS_SOURCE = ROOT / "poc" / "load-soak" / "clients" / "pins.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUNTIME = load_module("coffer_load_soak_runtime_manifest_tests", MODULE_PATH)
TOPOLOGY = RUNTIME.orchestrator.plan_contract.state_machine.load_topology(
    TOPOLOGY_PATH
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def readiness() -> dict:
    return {
        "ceph": {
            "baseline": "v20.2.2",
            "fix_in_latest_stable": True,
            "fix_merge_revision": (
                "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e"
            ),
            "fix_merged_to_tentacle": True,
            "fix_pull_request": 69277,
            "latest_stable": "v20.2.3",
            "reasons": [],
            "revision": "b" * 40,
            "status": "candidate-qualified",
        },
        "distribution": {
            "baseline": "v3.1.1",
            "latest_stable": "v3.1.2",
            "published_at": "2026-07-25T00:00:00Z",
            "reasons": [],
            "revision": "a" * 40,
            "status": "candidate-qualified",
            "url": "https://github.com/distribution/distribution/releases",
            "verified_release_commit": True,
        },
        "schema": "coffer.upstream-readiness/v1",
        "status": "candidate-qualified",
    }


def envelope_inputs() -> tuple[dict, bytes, bytes]:
    readiness_payload = canonical(readiness())
    pins_payload = PINS_SOURCE.read_bytes()
    request = {
        "bindings": {
            "architectures": ["aarch64", "x86_64"],
            "ceph_revision": "b" * 40,
            "ceph_version": "v20.2.3",
            "client_versions_hash": RUNTIME._hash_bytes(pins_payload),
            "configuration_hash": f"sha256:{'2' * 64}",
            "distribution_revision": "a" * 40,
            "distribution_version": "v3.1.2",
            "driver_revision": "c" * 40,
            "image_set_hash": f"sha256:{'3' * 64}",
            "readiness_evidence_hash": RUNTIME._hash_bytes(
                readiness_payload
            ),
            "readiness_status": "qualified",
        },
        "schema": "coffer.load-execution-plan-request/v1",
        "topology_sha256": RUNTIME._hash(TOPOLOGY),
    }
    envelope = RUNTIME.orchestrator.plan_contract.compile_plan(
        request,
        topology=TOPOLOGY,
    )
    return envelope, readiness_payload, pins_payload


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def test_current_runtime_manifest_exposes_every_gap_without_claiming_ready() -> None:
    envelope, readiness_payload, pins_payload = envelope_inputs()

    manifest = RUNTIME.build_manifest(
        envelope,
        topology=TOPOLOGY,
        readiness_payload=readiness_payload,
        pins_payload=pins_payload,
    )

    assert manifest["schema"] == "coffer.load-runtime-manifest/v1"
    assert manifest["ready"] is False
    assert manifest["synthetic"] is True
    assert manifest["target_class"] == "disposable-stage6-pilot"
    assert manifest["step_count"] == 29
    assert len(manifest["entries"]) == 29
    assert [entry["order"] for entry in manifest["entries"]] == list(
        range(1, 30)
    )
    assert manifest["gaps"] == sorted(
        [
            "client-docker",
            "client-nerdctl",
            "client-oras",
            "client-podman",
            "client-skopeo",
            "fault",
            "profile-load",
            "raw-oci",
            "telemetry-collector",
        ]
    )
    assert all(
        entry["disposition"] in ("contract-only", "missing")
        for entry in manifest["entries"]
    )
    assert all(
        entry["executable_sha256"] is None
        and entry["owner_only_required"] is True
        and entry["readiness_bound"] is True
        and entry["verified_tls_required"] is True
        and entry["target_class"] == "disposable-stage6-pilot"
        and entry["timeout_seconds"] > 0
        and entry["cleanup_owner"] == entry["executor"]
        for entry in manifest["entries"]
    )
    assert not any(
        entry["disposition"] == "qualified"
        for entry in manifest["entries"]
    )
    profile_entries = [
        entry
        for entry in manifest["entries"]
        if entry["executor"] == "profile-load"
    ]
    assert len(profile_entries) == 10
    assert all(
        entry["disposition"] == "contract-only"
        and entry["contract_sha256"].startswith("sha256:")
        for entry in profile_entries
    )
    fault_entries = [
        entry
        for entry in manifest["entries"]
        if entry["executor"] == "fault"
    ]
    assert len(fault_entries) == 10
    assert all(
        entry["disposition"] == "contract-only"
        and entry["contract_sha256"].startswith("sha256:")
        for entry in fault_entries
    )
    operations = {
        entry["operation"]: entry
        for entry in manifest["operation_capabilities"]
    }
    assert set(operations) == set(TOPOLOGY["operations"])
    for name in ("control", "quota-contention", "token"):
        assert operations[name]["disposition"] == "contract-only"
        assert operations[name]["owner"] == "control-load"
        assert operations[name]["contract_sha256"].startswith("sha256:")
    for name in set(operations) - {
        "control",
        "quota-contention",
        "token",
    }:
        assert operations[name]["disposition"] == "contract-only"
        assert operations[name]["contract_sha256"].startswith("sha256:")


def test_manifest_is_deterministic_and_retains_no_paths_or_targets() -> None:
    envelope, readiness_payload, pins_payload = envelope_inputs()
    first = RUNTIME.build_manifest(
        envelope,
        topology=TOPOLOGY,
        readiness_payload=readiness_payload,
        pins_payload=pins_payload,
    )
    second = RUNTIME.build_manifest(
        deepcopy(envelope),
        topology=TOPOLOGY,
        readiness_payload=readiness_payload,
        pins_payload=pins_payload,
    )

    assert canonical(first) == canonical(second)
    serialized = json.dumps(first, sort_keys=True)
    assert str(ROOT) not in serialized
    assert "https://" not in serialized
    assert "project_id" not in serialized


@pytest.mark.parametrize(
    "mutation",
    [
        "blocked-readiness",
        "readiness-hash",
        "pins-hash",
        "plan",
        "unknown",
    ],
)
def test_dependency_or_plan_drift_fails_closed(mutation: str) -> None:
    envelope, readiness_payload, pins_payload = envelope_inputs()
    if mutation == "blocked-readiness":
        document = readiness()
        document["status"] = "blocked"
        readiness_payload = canonical(document)
        envelope["plan"]["bindings"]["readiness_evidence_hash"] = (
            RUNTIME._hash_bytes(readiness_payload)
        )
        envelope["plan"]["bindings_sha256"] = RUNTIME._hash(
            envelope["plan"]["bindings"]
        )
        envelope["plan_sha256"] = RUNTIME._hash(envelope["plan"])
    elif mutation == "readiness-hash":
        envelope["plan"]["bindings"]["readiness_evidence_hash"] = (
            f"sha256:{'0' * 64}"
        )
        envelope["plan"]["bindings_sha256"] = RUNTIME._hash(
            envelope["plan"]["bindings"]
        )
        envelope["plan_sha256"] = RUNTIME._hash(envelope["plan"])
    elif mutation == "pins-hash":
        envelope["plan"]["bindings"]["client_versions_hash"] = (
            f"sha256:{'0' * 64}"
        )
        envelope["plan"]["bindings_sha256"] = RUNTIME._hash(
            envelope["plan"]["bindings"]
        )
        envelope["plan_sha256"] = RUNTIME._hash(envelope["plan"])
    elif mutation == "plan":
        envelope["plan"]["profiles"][0]["duration_seconds"] += 1
        envelope["plan_sha256"] = RUNTIME._hash(envelope["plan"])
    else:
        envelope["future"] = True

    with pytest.raises(
        (
            RUNTIME.ManifestError,
            RUNTIME.orchestrator.OrchestratorError,
            RUNTIME.orchestrator.plan_contract.PlanError,
        )
    ):
        RUNTIME.build_manifest(
            envelope,
            topology=TOPOLOGY,
            readiness_payload=readiness_payload,
            pins_payload=pins_payload,
        )


def file_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    envelope, readiness_payload, pins_payload = envelope_inputs()
    plan_path = tmp_path / "plan.json"
    readiness_path = tmp_path / "readiness.json"
    pins_path = tmp_path / "pins.json"
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output_path = output_root / "runtime.json"
    owner_file(plan_path, canonical(envelope))
    owner_file(readiness_path, readiness_payload)
    owner_file(pins_path, pins_payload)
    return plan_path, readiness_path, pins_path, output_path, output_root


def arguments(
    plan_path: Path,
    readiness_path: Path,
    pins_path: Path,
    output_path: Path,
) -> list[str]:
    return [
        "--plan",
        str(plan_path),
        "--readiness",
        str(readiness_path),
        "--pins",
        str(pins_path),
        "--topology",
        str(TOPOLOGY_PATH),
        "--output",
        str(output_path),
    ]


def test_owner_only_cli_writes_canonical_blocked_manifest(
    tmp_path: Path,
) -> None:
    plan_path, readiness_path, pins_path, output_path, output_root = (
        file_fixture(tmp_path)
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = RUNTIME.run(
        arguments(plan_path, readiness_path, pins_path, output_path),
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 3
    assert stdout.getvalue() == "load runtime manifest blocked\n"
    assert stderr.getvalue() == ""
    manifest = json.loads(output_path.read_bytes())
    assert manifest["ready"] is False
    assert output_path.read_bytes() == canonical(manifest)
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert not any(
        path.name.startswith(".runtime.json.")
        for path in output_root.iterdir()
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
def test_cli_file_drift_fails_without_manifest(
    tmp_path: Path,
    mutation: str,
    failure: str,
) -> None:
    plan_path, readiness_path, pins_path, output_path, _ = file_fixture(
        tmp_path
    )
    if mutation == "mode":
        plan_path.chmod(0o640)
    elif mutation == "noncanonical":
        owner_file(
            plan_path,
            json.dumps(json.loads(plan_path.read_bytes()), indent=2).encode(
                "utf-8"
            ),
        )
    elif mutation == "symlink-output":
        target = output_path.parent / "target"
        owner_file(target, b"preserved\n")
        output_path.symlink_to(target)
    else:
        output_path = plan_path

    stderr = io.StringIO()
    status = RUNTIME.run(
        arguments(plan_path, readiness_path, pins_path, output_path),
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 1
    assert stderr.getvalue() == (
        f"load runtime manifest failed: {failure}\n"
    )
    if mutation not in ("symlink-output", "alias"):
        assert not output_path.exists()


def test_cli_arguments_are_fixed() -> None:
    stderr = io.StringIO()
    assert RUNTIME.run([], stdout=io.StringIO(), stderr=stderr) == 2
    assert stderr.getvalue() == (
        "load runtime manifest failed: invalid-arguments\n"
    )


def test_manifest_builder_has_no_network_or_subprocess_import() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import http",
        "import requests",
        "import socket",
        "import subprocess",
        "import urllib",
    ):
        assert forbidden not in source
