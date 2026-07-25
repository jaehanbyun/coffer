from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIRECTORY = ROOT / "poc" / "load-soak" / "clients"
RUN_PATH = CLIENT_DIRECTORY / "run.py"
PINS_SOURCE = CLIENT_DIRECTORY / "pins.json"
EXPECTED_DIGEST = f"sha256:{'a' * 64}"
PASSWORD = "owner-only-run-password"
REGISTRY = "registry.stage6.example"
REPOSITORY = "p/123e4567-e89b-12d3-a456-426614174000/client"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUN = load_module("coffer_load_client_run_tests", RUN_PATH)


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def canonical_file(path: Path, value: object) -> bytes:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    owner_file(path, payload)
    return payload


def qualified_readiness() -> dict:
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


def fake_docker(
    path: Path,
    *,
    marker: Path,
    log: Path,
    fail_push: bool,
    sleep_version: bool,
) -> str:
    source = f"""#!{sys.executable}
import json
from pathlib import Path
import sys
import time

arguments = sys.argv[1:]
stdin = sys.stdin.buffer.read()
with Path({str(log)!r}).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({{"argv": arguments, "stdin": stdin.decode()}},
                            separators=(",", ":"), sort_keys=True) + "\\n")
if "version" in arguments:
    Path({str(marker)!r}).write_text("started", encoding="utf-8")
    if {sleep_version!r}:
        time.sleep(30)
    print("29.6.2|29.6.2")
elif {fail_push!r} and "push" in arguments:
    raise SystemExit(7)
elif "inspect" in arguments:
    target = arguments[-1].split("@", 1)[0]
    print(json.dumps([target + "@{EXPECTED_DIGEST}"]))
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(
    tmp_path: Path,
    *,
    fail_push: bool = False,
    sleep_version: bool = False,
) -> tuple[dict, Path, Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    work_root = tmp_path / "work"
    work_root.mkdir(mode=0o700)
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output = output_root / "result.json"

    pins = tmp_path / "pins.json"
    pins_payload = PINS_SOURCE.read_bytes()
    owner_file(pins, pins_payload)

    readiness = tmp_path / "readiness.json"
    readiness_payload = canonical_file(readiness, qualified_readiness())

    ca = tmp_path / "ca.pem"
    ca_payload = (
        b"-----BEGIN CERTIFICATE-----\nfixture\n"
        b"-----END CERTIFICATE-----\n"
    )
    owner_file(ca, ca_payload)
    daemon_ca = tmp_path / "certs" / REGISTRY / "ca.crt"
    daemon_ca.parent.mkdir(parents=True, mode=0o700)
    daemon_ca.write_bytes(ca_payload)
    daemon_ca.chmod(0o644)

    credential = tmp_path / "credential.json"
    canonical_file(
        credential,
        {
            "password": PASSWORD,
            "schema": "coffer.load-client-credential/v1",
            "username": "finite-run-credential-id",
        },
    )
    marker = tmp_path / "marker"
    log = tmp_path / "client.jsonl"
    binary = tmp_path / "docker"
    binary_digest = fake_docker(
        binary,
        marker=marker,
        log=log,
        fail_push=fail_push,
        sleep_version=sleep_version,
    )
    client_invocation = {
        "artifact_file": "",
        "binary": str(binary),
        "binary_sha256": binary_digest,
        "ca_file": str(ca),
        "client": "docker",
        "containerd_address": "",
        "credential_file": str(credential),
        "docker_daemon_ca_file": str(daemon_ca),
        "expected_digest": EXPECTED_DIGEST,
        "expected_version": "29.6.2",
        "referrers_mode": "",
        "registry": REGISTRY,
        "repository": REPOSITORY,
        "schema": "coffer.load-client-invocation/v1",
        "source": "coffer-load-source:fixture",
        "tag": "qualification",
        "timeout_seconds": 5,
        "work_root": str(work_root),
    }
    document = {
        "invocation": client_invocation,
        "output_file": str(output),
        "pins_file": str(pins),
        "pins_sha256": (
            "sha256:" + hashlib.sha256(pins_payload).hexdigest()
        ),
        "readiness_file": str(readiness),
        "readiness_sha256": (
            "sha256:" + hashlib.sha256(readiness_payload).hexdigest()
        ),
        "schema": "coffer.load-client-run/v1",
    }
    invocation = tmp_path / "invocation.json"
    canonical_file(invocation, document)
    return document, invocation, output, marker, log


def test_owner_only_run_emits_one_canonical_result_and_zero_residue(
    tmp_path: Path,
) -> None:
    document, invocation, output, _, log = fixture(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = RUN.run(
        ["--invocation", str(invocation)],
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0
    assert stdout.getvalue() == "load client completed\n"
    assert stderr.getvalue() == ""
    retained = json.loads(output.read_bytes())
    expected_payload = (
        json.dumps(retained, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    assert output.read_bytes() == expected_payload
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert retained["schema"] == "coffer.load-client-execution/v1"
    assert retained["pins_file_sha256"] == document["pins_sha256"]
    assert retained["readiness_sha256"] == document["readiness_sha256"]
    assert retained["client_result"]["result"] == "success"
    assert retained["client_result"]["digest_checks"] == 1
    assert not any(Path(document["invocation"]["work_root"]).iterdir())
    serialized = output.read_text(encoding="utf-8")
    for forbidden in (
        PASSWORD,
        REGISTRY,
        REPOSITORY,
        str(document["pins_file"]),
        str(document["readiness_file"]),
    ):
        assert forbidden not in serialized
    calls = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
    ]
    assert any("logout" in call["argv"] for call in calls)
    assert any("rm" in call["argv"] for call in calls)


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("blocked-readiness", "readiness-refused"),
        ("pins-digest", "contract-refused"),
        ("invocation-mode", "local-file-unavailable"),
        ("output-symlink", "output-unavailable"),
        ("path-alias", "contract-refused"),
    ],
)
def test_preflight_drift_fails_before_client_execution(
    tmp_path: Path,
    mutation: str,
    failure: str,
) -> None:
    document, invocation, output, marker, log = fixture(tmp_path)
    if mutation == "blocked-readiness":
        readiness = qualified_readiness()
        readiness["status"] = "blocked"
        payload = canonical_file(Path(document["readiness_file"]), readiness)
        document["readiness_sha256"] = (
            "sha256:" + hashlib.sha256(payload).hexdigest()
        )
        canonical_file(invocation, document)
    elif mutation == "pins-digest":
        document["pins_sha256"] = f"sha256:{'0' * 64}"
        canonical_file(invocation, document)
    elif mutation == "invocation-mode":
        invocation.chmod(0o640)
    elif mutation == "output-symlink":
        target = output.parent / "target"
        owner_file(target, b"preserved\n")
        output.symlink_to(target)
    else:
        document["output_file"] = document["pins_file"]
        canonical_file(invocation, document)

    stderr = io.StringIO()
    assert (
        RUN.run(
            ["--invocation", str(invocation)],
            stdout=io.StringIO(),
            stderr=stderr,
        )
        == 1
    )
    assert stderr.getvalue() == f"load client failed: {failure}\n"
    assert not marker.exists()
    assert not log.exists()
    if mutation != "path-alias":
        assert not output.exists() or output.is_symlink()


def test_execution_failure_is_fixed_and_removes_generated_state(
    tmp_path: Path,
) -> None:
    document, invocation, output, _, log = fixture(
        tmp_path,
        fail_push=True,
    )

    stderr = io.StringIO()
    assert (
        RUN.run(
            ["--invocation", str(invocation)],
            stdout=io.StringIO(),
            stderr=stderr,
        )
        == 1
    )

    assert stderr.getvalue() == "load client failed: execution-unavailable\n"
    assert not output.exists()
    assert not any(Path(document["invocation"]["work_root"]).iterdir())
    calls = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
    ]
    assert any("logout" in call["argv"] for call in calls)
    assert any("rm" in call["argv"] for call in calls)


def test_sigint_kills_child_and_leaves_no_output_or_generated_state(
    tmp_path: Path,
) -> None:
    document, invocation, output, marker, _ = fixture(
        tmp_path,
        sleep_version=True,
    )
    process = subprocess.Popen(
        [sys.executable, str(RUN_PATH), "--invocation", str(invocation)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists()

    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 1
    assert stdout == ""
    assert stderr == "load client failed: execution-unavailable\n"
    assert not output.exists()
    assert not any(Path(document["invocation"]["work_root"]).iterdir())


def test_cli_argument_failure_is_fixed() -> None:
    stderr = io.StringIO()
    assert RUN.run([], stdout=io.StringIO(), stderr=stderr) == 2
    assert stderr.getvalue() == "load client failed: invalid-arguments\n"
