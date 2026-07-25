from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "load-soak" / "profile" / "run.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PROFILE = load_module("coffer_load_profile_run_tests", MODULE_PATH)
TOPOLOGY = PROFILE.orchestrator.plan_contract.state_machine.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


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
        "topology_sha256": PROFILE.orchestrator.plan_contract._hash(
            TOPOLOGY
        ),
    }


def fake_binary(
    path: Path,
    *,
    fail: bool = False,
    sleep: bool = False,
    spam: bool = False,
) -> None:
    source = f"""#!{sys.executable}
import hashlib
import json
import os
from pathlib import Path
import sys
import time

if {spam!r}:
    print("x" * 5000, end="")
    raise SystemExit(0)
if {sleep!r}:
    time.sleep(30)
if {fail!r}:
    print("fixed fake failure", file=sys.stderr)
    raise SystemExit(1)
arguments = sys.argv[1:]
if len(arguments) != 2 or arguments[0] != "--invocation":
    raise SystemExit(2)
invocation = json.loads(Path(arguments[1]).read_bytes())
output = Path(invocation["output_file"])
if invocation["schema"] == "coffer.raw-oci-invocation/v1":
    names = [
        "le-10ms",
        "le-25ms",
        "le-50ms",
        "le-100ms",
        "le-250ms",
        "le-500ms",
        "le-1000ms",
        "le-2000ms",
        "le-5000ms",
        "gt-5000ms",
    ]
    result = {{
        "duration_milliseconds": 1,
        "operations": [{{
            "attempts": 1,
            "count": 1,
            "digest_checks": 1,
            "latency_buckets": [
                {{"count": 1 if index == 0 else 0, "name": name}}
                for index, name in enumerate(names)
            ],
            "operation": "fixture",
            "result": "success",
            "retries": 0,
            "transferred_bytes": 10,
        }}],
        "schema": "coffer.raw-oci-driver/v1",
    }}
    message = "raw OCI driver completed"
else:
    manifest_hash = "sha256:" + hashlib.sha256(b"fixture").hexdigest()
    result = {{
        "contract_sha256": invocation["contract_sha256"],
        "executable_sha256": invocation["executable_sha256"],
        "manifest_set_sha256": manifest_hash,
        "readiness_sha256": invocation["readiness_sha256"],
        "schema": "coffer.control-load-execution/v1",
        "snapshot": {{
            "duration_milliseconds": 1,
            "results": [
                {{"count": 2, "operation": "control", "result": "success"}},
                {{
                    "count": 1,
                    "operation": "quota-contention",
                    "result": "success",
                }},
                {{"count": 1, "operation": "token", "result": "success"}},
            ],
            "schema": "coffer.control-load-driver/v1",
        }},
    }}
    message = "control load driver completed"
payload = (json.dumps(result, separators=(",", ":"), sort_keys=True) + "\\n").encode()
output.write_bytes(payload)
output.chmod(0o600)
print(message)
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


RAW_DRIVER_OPERATIONS = {
    "manifest-read": "manifest-get",
    "manifest-publish": "manifest-publish",
    "blob-read": "blob-read-full",
    "blob-monolithic": "blob-monolithic",
    "blob-resumable": "blob-resumable",
    "blob-cross-mount": "blob-cross-mount",
    "index": "manifest-publish",
    "artifact": "artifact",
    "abandoned-upload": "abandoned-upload",
}


def raw_invocation(
    tmp_path: Path,
    operation: str,
    readiness_sha256: str,
) -> dict:
    driver_operation = RAW_DRIVER_OPERATIONS[operation]
    manifest_operation = operation in {
        "manifest-read",
        "manifest-publish",
        "index",
        "artifact",
    }
    return {
        "base_url": "https://registry.stage6.example",
        "ca_file": str(tmp_path / "ca.pem"),
        "chunk_bytes": (
            16
            if driver_operation in ("blob-resumable", "abandoned-upload")
            else 0
        ),
        "credential_file": str(tmp_path / "credential.json"),
        "length_bytes": (
            16
            if driver_operation in ("blob-read-full", "abandoned-upload")
            else 0
        ),
        "manifest_file": (
            str(tmp_path / f"{operation}-manifest.json")
            if manifest_operation
            else ""
        ),
        "manifest_media_type": (
            "application/vnd.oci.image.index.v1+json"
            if operation == "index"
            else (
                "application/vnd.oci.image.manifest.v1+json"
                if manifest_operation
                else ""
            )
        ),
        "max_attempts": 4,
        "offset_bytes": 0,
        "operation": driver_operation,
        "output_file": str(tmp_path / f"{operation}-unused.json"),
        "readiness_file": str(tmp_path / "readiness.json"),
        "readiness_sha256": readiness_sha256,
        "reference": "fixture" if manifest_operation else "",
        "repository": "p/123e4567-e89b-12d3-a456-426614174000/load",
        "schema": "coffer.raw-oci-invocation/v1",
        "seed": "" if manifest_operation else f"seed-{operation}",
        "size_bytes": 0 if manifest_operation else 32,
        "source_repository": (
            "p/123e4567-e89b-12d3-a456-426614174000/source"
            if operation == "blob-cross-mount"
            else ""
        ),
        "target_class": "disposable-stage6-pilot",
        "timeout_seconds": 5,
    }


class AcceleratedClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(seconds, 60)


def fixture(
    tmp_path: Path,
    *,
    fail: bool = False,
    transfer_limit: int = 1024,
) -> tuple[dict, Path, Path, Path, Path, Path]:
    tmp_path.chmod(0o700)
    session = tmp_path / "session"
    session.mkdir(mode=0o700)
    work = session / "work"
    work.mkdir(mode=0o700)
    binary = tmp_path / "fixture-child"
    fake_binary(binary, fail=fail)
    binary_sha256 = PROFILE._binary_hash(binary)

    envelope = PROFILE.orchestrator.plan_contract.compile_plan(
        request(),
        topology=TOPOLOGY,
    )
    plan_payload = canonical(envelope)
    plan_path = tmp_path / "plan.json"
    owner_file(plan_path, plan_payload)
    readiness_sha256 = envelope["plan"]["bindings"][
        "readiness_evidence_hash"
    ]

    jobs = []
    control_contract = f"sha256:{'c' * 64}"
    control_invocation = {
        "ca_file": str(tmp_path / "ca.pem"),
        "contract_sha256": control_contract,
        "control_base": "https://control.stage6.example",
        "credential_file": str(tmp_path / "credential.json"),
        "executable_sha256": binary_sha256,
        "expected_quota": 1,
        "expected_success": 1,
        "identity_base": "https://identity.stage6.example",
        "manifest_sources": [],
        "max_concurrency": 2,
        "output_file": str(tmp_path / "control-unused.json"),
        "readiness_file": str(tmp_path / "readiness.json"),
        "readiness_sha256": readiness_sha256,
        "registry_base": "https://registry.stage6.example",
        "repository": "p/123e4567-e89b-12d3-a456-426614174000/load",
        "schema": "coffer.control-load-invocation/v1",
        "service": "registry.stage6.example",
        "target_class": "disposable-stage6-pilot",
        "timeout_seconds": 5,
    }
    control_path = tmp_path / "control-invocation.json"
    control_payload = canonical(control_invocation)
    owner_file(control_path, control_payload)
    jobs.append(
        {
            "binary": str(binary),
            "binary_sha256": binary_sha256,
            "cleanup_scope": "invocation",
            "contract_sha256": control_contract,
            "executor": "control-load",
            "invocation_file": str(control_path),
            "invocation_sha256": digest(control_payload),
            "maximum_transfer_bytes": 0,
            "operations": ["control", "token", "quota-contention"],
        }
    )
    for operation in TOPOLOGY["operations"]:
        if operation in PROFILE.CONTROL_OPERATIONS:
            continue
        child = raw_invocation(tmp_path, operation, readiness_sha256)
        child_path = tmp_path / f"{operation}-invocation.json"
        child_payload = canonical(child)
        owner_file(child_path, child_payload)
        jobs.append(
            {
                "binary": str(binary),
                "binary_sha256": binary_sha256,
                "cleanup_scope": "repository-teardown",
                "contract_sha256": f"sha256:{'d' * 64}",
                "executor": "raw-oci",
                "invocation_file": str(child_path),
                "invocation_sha256": digest(child_payload),
                "maximum_transfer_bytes": transfer_limit,
                "operations": [operation],
            }
        )

    invocation = {
        "contract_sha256": f"sha256:{'e' * 64}",
        "execution_source": "fixture",
        "jobs": jobs,
        "lock_file": str(session / "lock"),
        "output_file": str(session / "result.json"),
        "plan_file": str(plan_path),
        "plan_file_sha256": digest(plan_payload),
        "schema": "coffer.load-profile-invocation/v1",
        "state_file": str(session / "state.json"),
        "step": {"kind": "profile", "name": "smoke", "order": 7},
        "target_class": "disposable-stage6-pilot",
        "work_root": str(work),
    }
    invocation_path = tmp_path / "invocation.json"
    owner_file(invocation_path, canonical(invocation))
    return (
        invocation,
        invocation_path,
        session / "state.json",
        session / "result.json",
        session / "lock",
        work,
    )


def test_real_fake_executables_checkpoint_resume_and_finish_without_residue(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, lock_path, work = fixture(
        tmp_path
    )

    assert (
        PROFILE.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
            max_waves=1,
        )
        is False
    )
    state = json.loads(state_path.read_bytes())
    assert state["waves"] == 1
    assert state["elapsed_seconds"] == 60
    assert state["attempts"] == 4
    assert state["operation_counts"]["control"] == 1
    assert state["operation_counts"]["token"] == 1
    assert state["operation_counts"]["quota-contention"] == 1
    assert not output_path.exists()
    assert not any(path.name.startswith(".profile-") for path in work.iterdir())

    assert PROFILE.execute_invocation(
        invocation_path,
        clock=AcceleratedClock(),
    )
    result_payload = output_path.read_bytes()
    result = json.loads(result_payload)
    assert result_payload == canonical(result)
    assert result["schema"] == "coffer.load-profile-result/v1"
    assert result["synthetic"] is True
    assert result["execution_source"] == "fixture"
    assert result["duration_seconds"] == 120
    assert result["maximum_clients"] == 4
    assert result["unexpected_errors"] == 0
    assert result["transferred_bytes"] > 0
    assert set(result["operation_counts"]) == set(TOPOLOGY["operations"])
    assert all(count > 0 for count in result["operation_counts"].values())
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    assert not any(path.name.startswith(".profile-") for path in work.iterdir())
    serialized = json.dumps(result, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "https://" not in serialized
    assert "123e4567" not in serialized

    assert PROFILE.execute_invocation(
        invocation_path,
        clock=AcceleratedClock(),
    )
    assert output_path.read_bytes() == result_payload
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert (
        PROFILE.run(
            ["--invocation", str(invocation_path)],
            stdout=stdout,
            stderr=stderr,
        )
        == 3
    )
    assert stdout.getvalue() == "load profile fixture completed\n"
    assert stderr.getvalue() == ""


def test_profile_and_ramp_limits_fix_concurrency_cadence() -> None:
    envelope = PROFILE.orchestrator.plan_contract.compile_plan(
        request(),
        topology=TOPOLOGY,
    )
    plan = envelope["plan"]
    assert PROFILE._profile_limits(
        plan,
        kind="profile",
        name="qualification",
    ) == (1800, 16, 32, 40 * 1024**3)
    assert PROFILE._profile_limits(
        plan,
        kind="ramp",
        name="clients-64",
    ) == (
        120,
        64,
        64,
        40 * 1024**3 // 7,
    )
    assert PROFILE._concurrency(
        elapsed_seconds=0,
        duration_seconds=120,
        steady_clients=4,
        burst_clients=8,
    ) == 4
    assert PROFILE._concurrency(
        elapsed_seconds=30,
        duration_seconds=120,
        steady_clients=4,
        burst_clients=8,
    ) == 8
    assert PROFILE._concurrency(
        elapsed_seconds=90,
        duration_seconds=120,
        steady_clients=4,
        burst_clients=8,
    ) == 4


def test_child_failure_and_transfer_violation_preserve_checkpoint_boundary(
    tmp_path: Path,
) -> None:
    for name, arguments in (
        ("child", {"fail": True}),
        ("transfer", {"transfer_limit": 1}),
    ):
        root = tmp_path / name
        root.mkdir(mode=0o700)
        _, invocation_path, state_path, output_path, _, work = fixture(
            root,
            **arguments,
        )
        with pytest.raises(
            PROFILE.CommandError,
            match="execution-unavailable",
        ):
            PROFILE.execute_invocation(
                invocation_path,
                clock=AcceleratedClock(),
            )
        assert not state_path.exists()
        assert not output_path.exists()
        assert not any(
            path.name.startswith(".profile-") for path in work.iterdir()
        )


def test_checkpoint_hash_chain_detects_state_tampering(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(tmp_path)
    assert (
        PROFILE.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
            max_waves=1,
        )
        is False
    )
    state = json.loads(state_path.read_bytes())
    state["operation_counts"]["control"] += 1
    owner_file(state_path, canonical(state))

    with pytest.raises(PROFILE.CommandError, match="contract-refused"):
        PROFILE.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    assert not output_path.exists()
    assert not any(path.name.startswith(".profile-") for path in work.iterdir())


@pytest.mark.parametrize(
    "mutation",
    [
        "invocation-mode",
        "plan-hash",
        "binary-hash",
        "child-mode",
        "missing-operation",
        "source",
        "path-alias",
    ],
)
def test_profile_preflight_drift_fails_without_state(
    tmp_path: Path,
    mutation: str,
) -> None:
    (
        invocation,
        invocation_path,
        state_path,
        output_path,
        _,
        work,
    ) = fixture(tmp_path)
    if mutation == "invocation-mode":
        invocation_path.chmod(0o640)
    elif mutation == "plan-hash":
        invocation["plan_file_sha256"] = f"sha256:{'0' * 64}"
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "binary-hash":
        invocation["jobs"][0]["binary_sha256"] = f"sha256:{'0' * 64}"
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "child-mode":
        Path(invocation["jobs"][0]["invocation_file"]).chmod(0o640)
    elif mutation == "missing-operation":
        invocation["jobs"].pop()
        owner_file(invocation_path, canonical(invocation))
    elif mutation == "source":
        invocation["execution_source"] = "live"
        owner_file(invocation_path, canonical(invocation))
    else:
        invocation["output_file"] = invocation["state_file"]
        owner_file(invocation_path, canonical(invocation))

    with pytest.raises(
        PROFILE.CommandError,
        match="contract-refused",
    ):
        PROFILE.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
        )
    assert not state_path.exists()
    assert not output_path.exists()
    assert not any(path.name.startswith(".profile-") for path in work.iterdir())


def test_interruption_removes_generated_child_files(
    tmp_path: Path,
) -> None:
    _, invocation_path, state_path, output_path, _, work = fixture(tmp_path)

    class InterruptingRunner:
        def run(self, tasks, *, timeout_seconds, work_root):
            raise KeyboardInterrupt

    with pytest.raises(
        PROFILE.CommandError,
        match="execution-unavailable",
    ):
        PROFILE.execute_invocation(
            invocation_path,
            clock=AcceleratedClock(),
            runner=InterruptingRunner(),
        )
    assert not state_path.exists()
    assert not output_path.exists()
    assert not any(path.name.startswith(".profile-") for path in work.iterdir())


def test_subprocess_timeout_terminates_group_and_removes_stream_files(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    binary = tmp_path / "sleeping-child"
    fake_binary(binary, sleep=True)
    invocation = tmp_path / "invocation.json"
    owner_file(invocation, b"{}\n")
    output = tmp_path / "output.json"
    job = PROFILE.Job(
        binary=binary,
        binary_sha256=PROFILE._binary_hash(binary),
        cleanup_scope="repository-teardown",
        contract_sha256=f"sha256:{'1' * 64}",
        executor="raw-oci",
        invocation={},
        invocation_file=invocation,
        invocation_sha256=digest(b"{}\n"),
        maximum_transfer_bytes=0,
        operations=("blob-read",),
    )
    task = PROFILE.ChildTask(
        binary=binary,
        expected_stdout=b"raw OCI driver completed\n",
        invocation_file=invocation,
        job=job,
        output_file=output,
    )

    with pytest.raises(PROFILE.ProfileError, match="timed out"):
        PROFILE.SubprocessBatchRunner().run(
            [task],
            timeout_seconds=1,
            work_root=tmp_path,
        )
    assert not any(
        path.name.startswith((".profile-stdout-", ".profile-stderr-"))
        for path in tmp_path.iterdir()
    )


def test_subprocess_output_bound_terminates_group_and_removes_stream_files(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    binary = tmp_path / "noisy-child"
    fake_binary(binary, spam=True)
    invocation = tmp_path / "invocation.json"
    owner_file(invocation, b"{}\n")
    output = tmp_path / "output.json"
    job = PROFILE.Job(
        binary=binary,
        binary_sha256=PROFILE._binary_hash(binary),
        cleanup_scope="repository-teardown",
        contract_sha256=f"sha256:{'1' * 64}",
        executor="raw-oci",
        invocation={},
        invocation_file=invocation,
        invocation_sha256=digest(b"{}\n"),
        maximum_transfer_bytes=0,
        operations=("blob-read",),
    )
    task = PROFILE.ChildTask(
        binary=binary,
        expected_stdout=b"raw OCI driver completed\n",
        invocation_file=invocation,
        job=job,
        output_file=output,
    )

    with pytest.raises(PROFILE.ProfileError, match="output exceeded"):
        PROFILE.SubprocessBatchRunner().run(
            [task],
            timeout_seconds=5,
            work_root=tmp_path,
        )
    assert not any(
        path.name.startswith((".profile-stdout-", ".profile-stderr-"))
        for path in tmp_path.iterdir()
    )


def test_profile_cli_argument_failure_is_fixed() -> None:
    for arguments in ([], ["--unknown"], ["--invocation", "a", "extra"]):
        stdout = io.StringIO()
        stderr = io.StringIO()
        assert PROFILE.run(arguments, stdout=stdout, stderr=stderr) == 2
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == "load profile failed: invalid-arguments\n"
