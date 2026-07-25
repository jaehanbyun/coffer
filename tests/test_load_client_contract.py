from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIRECTORY = ROOT / "poc" / "load-soak" / "clients"
PINS_PATH = CLIENT_DIRECTORY / "pins.json"
TEST_DIGEST = f"sha256:{'a' * 64}"
TEST_PASSWORD = "owner-only-client-password"
TEST_USERNAME = "finite-client-credential-id"
TEST_REPOSITORY = "p/123e4567-e89b-12d3-a456-426614174000/client"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = load_module(
    "coffer_load_client_contract_tests",
    CLIENT_DIRECTORY / "contract.py",
)


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def fake_client(
    path: Path,
    *,
    client: str,
    version: str,
    containerd_version: str,
    digest: str,
    log_path: Path,
    fail_word: str = "",
    leak_login: bool = False,
    output_word: str = "",
    output_bytes: int = 0,
    sleep_word: str = "",
) -> None:
    source = f"""#!{sys.executable}
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

client = {client!r}
version = {version!r}
containerd_version = {containerd_version!r}
digest = {digest!r}
fail_word = {fail_word!r}
leak_login = {leak_login!r}
output_word = {output_word!r}
output_bytes = {output_bytes!r}
sleep_word = {sleep_word!r}
arguments = sys.argv[1:]
stdin = sys.stdin.buffer.read()
ca_files = list(Path(os.environ["XDG_CONFIG_HOME"]).parent.glob("certs/ca.crt"))
hosts_files = list(Path(os.environ["XDG_CONFIG_HOME"]).rglob("hosts.toml"))
record = {{
    "argv": arguments,
    "environment": dict(os.environ),
    "ca_sha256": (
        hashlib.sha256(ca_files[0].read_bytes()).hexdigest()
        if len(ca_files) == 1
        else ""
    ),
    "hosts": (
        hosts_files[0].read_text(encoding="utf-8")
        if len(hosts_files) == 1
        else ""
    ),
    "hosts_mode": (
        stat.S_IMODE(hosts_files[0].stat().st_mode)
        if len(hosts_files) == 1
        else 0
    ),
    "stdin": stdin.decode("utf-8"),
}}
with Path({str(log_path)!r}).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\\n")
if fail_word and fail_word in arguments:
    raise SystemExit(7)
if output_word and output_word in arguments:
    sys.stdout.buffer.write(b"x" * output_bytes)
    raise SystemExit(0)
if sleep_word and sleep_word in arguments:
    time.sleep(30)
if "login" in arguments and leak_login:
    sys.stdout.buffer.write(stdin)
    raise SystemExit(0)
if (client == "skopeo" and "--version" in arguments):
    print("skopeo version " + version)
elif arguments and arguments[-1] == "version" and client == "nerdctl":
    print("Client:\\n Version:\\t" + version)
    print("Server:\\n containerd:\\n  Version:\\t" + containerd_version)
elif "version" in arguments:
    if client == "docker":
        print(version + "|" + version)
    elif client == "podman":
        print(version)
    elif client == "oras":
        print("Version: " + version)
elif "inspect" in arguments:
    if client in ("docker", "nerdctl"):
        target = arguments[-1].split("@", 1)[0]
        print(json.dumps([target + "@" + digest]))
    else:
        print(digest)
elif "attach" in arguments:
    print(digest)
elif "discover" in arguments:
    print(json.dumps({{"referrers": [{{"digest": digest}}]}}))
"""
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


def inputs(
    tmp_path: Path,
    client: str,
    *,
    fail_word: str = "",
    leak_login: bool = False,
    output_word: str = "",
    output_bytes: int = 0,
    sleep_word: str = "",
) -> tuple[dict, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pins = CONTRACT.load_pins(PINS_PATH)
    work_root = tmp_path / "work"
    work_root.mkdir(mode=0o700)
    work_root.chmod(0o700)
    ca = tmp_path / "ca.pem"
    owner_file(
        ca,
        b"-----BEGIN CERTIFICATE-----\nfixture\n"
        b"-----END CERTIFICATE-----\n",
    )
    docker_daemon_ca = ""
    if client == "docker":
        daemon_ca_path = (
            tmp_path
            / "docker-certs"
            / "registry.stage6.example"
            / "ca.crt"
        )
        daemon_ca_path.parent.mkdir(parents=True, mode=0o700)
        daemon_ca_path.write_bytes(ca.read_bytes())
        daemon_ca_path.chmod(0o644)
        docker_daemon_ca = str(daemon_ca_path)
    credential = tmp_path / "credential.json"
    owner_file(
        credential,
        (
            json.dumps(
                {
                    "password": TEST_PASSWORD,
                    "schema": "coffer.load-client-credential/v1",
                    "username": TEST_USERNAME,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )
    artifact = tmp_path / "artifact.bin"
    owner_file(artifact, b"bounded artifact")
    log_path = tmp_path / f"{client}.jsonl"
    binary = tmp_path / client
    pin = pins["clients"][client]
    fake_client(
        binary,
        client=client,
        version=pin["version"],
        containerd_version=pin.get("containerd_version", ""),
        digest=TEST_DIGEST,
        log_path=log_path,
        fail_word=fail_word,
        leak_login=leak_login,
        output_word=output_word,
        output_bytes=output_bytes,
        sleep_word=sleep_word,
    )
    binary_hash = "sha256:" + hashlib.sha256(binary.read_bytes()).hexdigest()
    invocation = {
        "artifact_file": str(artifact) if client == "oras" else "",
        "binary": str(binary),
        "binary_sha256": binary_hash,
        "ca_file": str(ca),
        "client": client,
        "containerd_address": (
            "unix:///run/user/1000/containerd.sock"
            if client == "nerdctl"
            else ""
        ),
        "credential_file": str(credential),
        "docker_daemon_ca_file": docker_daemon_ca,
        "expected_digest": TEST_DIGEST,
        "expected_version": pin["version"],
        "registry": "registry.stage6.example",
        "referrers_mode": (
            "v1.1-referrers-api" if client == "oras" else ""
        ),
        "repository": TEST_REPOSITORY,
        "schema": "coffer.load-client-invocation/v1",
        "source": (
            "registry.stage6.example/"
            "p/123e4567-e89b-12d3-a456-426614174000/source:"
            "fixture"
            if client == "skopeo"
            else (
                "registry.stage6.example/"
                "p/123e4567-e89b-12d3-a456-426614174000/client@"
                f"sha256:{'b' * 64}"
                if client == "oras"
                else "coffer-load-source:fixture"
            )
        ),
        "tag": "qualification",
        "timeout_seconds": 5,
        "work_root": str(work_root),
    }
    return invocation, log_path


def records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_exact_client_pins_are_versioned_and_provenance_honest() -> None:
    pins = CONTRACT.load_pins(PINS_PATH)

    assert pins["schema"] == CONTRACT.PINS_SCHEMA
    assert list(pins["clients"]) == list(CONTRACT.CLIENTS)
    assert pins["architectures"] == ["aarch64", "x86_64"]
    assert pins["pins_hash"].startswith("sha256:")
    assert pins["clients"]["docker"]["version"] == "29.6.2"
    assert pins["clients"]["podman"]["version"] == "6.0.2"
    assert pins["clients"]["skopeo"]["version"] == "1.23.0"
    assert pins["clients"]["oras"]["version"] == "1.3.3"
    assert pins["clients"]["nerdctl"]["version"] == "2.3.5"
    assert pins["clients"]["nerdctl"]["containerd_version"] == "2.3.3"
    assert pins["clients"]["skopeo"]["release_commit_verified"] is False
    assert all(
        pin["release_commit_verified"] is True
        for name, pin in pins["clients"].items()
        if name != "skopeo"
    )


@pytest.mark.parametrize("client", CONTRACT.CLIENTS)
def test_each_adapter_uses_clean_state_stdin_and_exact_digest(
    tmp_path: Path,
    client: str,
) -> None:
    invocation, log_path = inputs(tmp_path, client)
    pins = CONTRACT.load_pins(PINS_PATH)

    result = CONTRACT.qualify_client(invocation, pins=pins)

    assert result["schema"] == CONTRACT.RESULT_SCHEMA
    assert result["client"] == client
    assert result["version"] == pins["clients"][client]["version"]
    assert result["digest_checks"] == 1
    assert result["result"] == "success"
    assert result["referrers_mode"] == (
        "native" if client == "oras" else "not-applicable"
    )
    assert not any(Path(invocation["work_root"]).iterdir())
    retained = json.dumps(result, sort_keys=True)
    for forbidden in (
        TEST_PASSWORD,
        TEST_USERNAME,
        invocation["registry"],
        invocation["repository"],
        invocation["source"],
        invocation["tag"],
        invocation["credential_file"],
        invocation["ca_file"],
    ):
        assert forbidden not in retained

    calls = records(log_path)
    login_calls = [
        call for call in calls if "login" in call["argv"]
    ]
    assert len(login_calls) == 1
    assert login_calls[0]["stdin"] == TEST_PASSWORD + "\n"
    for call in calls:
        serialized_argv = json.dumps(call["argv"])
        serialized_environment = json.dumps(call["environment"])
        assert TEST_PASSWORD not in serialized_argv
        assert TEST_PASSWORD not in serialized_environment
        assert "--insecure-registry" not in call["argv"]
        assert "--tls-verify=false" not in call["argv"]
        assert "--plain-http" not in call["argv"]
        assert "--insecure" not in call["argv"]
        assert set(call["environment"]) - {"__CF_USER_TEXT_ENCODING"} == {
            "DOCKER_CONFIG",
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "XDG_CONFIG_HOME",
            "XDG_RUNTIME_DIR",
        }
        if call not in login_calls:
            assert call["stdin"] == ""
        assert call["ca_sha256"] == hashlib.sha256(
            Path(invocation["ca_file"]).read_bytes()
        ).hexdigest()
        assert call["hosts_mode"] == 0o600
        assert (
            f'server = "https://{invocation["registry"]}"'
            in call["hosts"]
        )
        assert "skip_verify" not in call["hosts"]

    flattened = [argument for call in calls for argument in call["argv"]]
    if client in ("podman", "skopeo"):
        assert "--tls-verify=true" in flattened
        assert "--cert-dir" in flattened
        assert "--authfile" in flattened
    elif client == "oras":
        assert "--ca-file" in flattened
        assert "--registry-config" in flattened
        assert "attach" in flattened
        assert "discover" in flattened
        assert "v1.1-referrers-api" in flattened
    elif client == "nerdctl":
        assert "--address" in flattened
        assert "--namespace" in flattened
        assert "--data-root" in flattened
    else:
        assert "--config" in flattened


def test_failure_runs_logout_and_removes_generated_state(
    tmp_path: Path,
) -> None:
    invocation, log_path = inputs(
        tmp_path,
        "docker",
        fail_word="push",
    )

    with pytest.raises(
        CONTRACT.ClientContractError,
        match="client command failed",
    ):
        CONTRACT.qualify_client(
            invocation,
            pins=CONTRACT.load_pins(PINS_PATH),
        )

    calls = records(log_path)
    assert any("logout" in call["argv"] for call in calls)
    assert any("rm" in call["argv"] for call in calls)
    assert not any(Path(invocation["work_root"]).iterdir())


def test_oras_fallback_tag_is_explicit_and_separately_retained(
    tmp_path: Path,
) -> None:
    invocation, log_path = inputs(tmp_path, "oras")
    invocation["referrers_mode"] = "v1.1-referrers-tag"

    result = CONTRACT.qualify_client(
        invocation,
        pins=CONTRACT.load_pins(PINS_PATH),
    )

    assert result["referrers_mode"] == "fallback-tag"
    assert any(
        "v1.1-referrers-tag" in call["argv"] for call in records(log_path)
    )
    assert not any(Path(invocation["work_root"]).iterdir())


def test_secret_echo_and_binary_or_input_drift_fail_closed(
    tmp_path: Path,
) -> None:
    invocation, _ = inputs(tmp_path, "oras", leak_login=True)
    pins = CONTRACT.load_pins(PINS_PATH)
    with pytest.raises(
        CONTRACT.ClientContractError,
        match="exposed credential",
    ):
        CONTRACT.qualify_client(invocation, pins=pins)
    assert not any(Path(invocation["work_root"]).iterdir())

    invocation, log_path = inputs(tmp_path / "second", "podman")
    invocation["binary_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(
        CONTRACT.ClientContractError,
        match="binary digest",
    ):
        CONTRACT.qualify_client(invocation, pins=pins)
    assert not log_path.exists()

    invocation, log_path = inputs(tmp_path / "third", "skopeo")
    Path(invocation["credential_file"]).chmod(0o640)
    with pytest.raises(
        CONTRACT.ClientContractError,
        match="input boundary",
    ):
        CONTRACT.qualify_client(invocation, pins=pins)
    assert not log_path.exists()


def test_output_limit_and_timeout_kill_process_group_and_remove_state(
    tmp_path: Path,
) -> None:
    invocation, _ = inputs(
        tmp_path / "output",
        "docker",
        output_word="version",
        output_bytes=CONTRACT.MAX_OUTPUT_BYTES + 1,
    )
    with pytest.raises(
        CONTRACT.ClientContractError,
        match="output exceeded limit",
    ):
        CONTRACT.qualify_client(
            invocation,
            pins=CONTRACT.load_pins(PINS_PATH),
        )
    assert not any(Path(invocation["work_root"]).iterdir())

    invocation, _ = inputs(
        tmp_path / "timeout",
        "docker",
        sleep_word="version",
    )
    invocation["timeout_seconds"] = 1
    started = time.monotonic()
    with pytest.raises(
        CONTRACT.ClientContractError,
        match="dependency failed",
    ):
        CONTRACT.qualify_client(
            invocation,
            pins=CONTRACT.load_pins(PINS_PATH),
        )
    assert time.monotonic() - started < 5
    assert not any(Path(invocation["work_root"]).iterdir())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registry", "https://registry.example"),
        ("registry", "registry.example:70000"),
        ("repository", "other/repository"),
        ("expected_digest", f"sha256:{'A' * 64}"),
        ("timeout_seconds", 0),
        ("source", "source with space"),
        ("referrers_mode", "v1.1-referrers-tag"),
    ],
)
def test_unsafe_invocation_fails_before_execution(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    invocation, log_path = inputs(tmp_path, "nerdctl")
    invocation[field] = value

    with pytest.raises(CONTRACT.ClientContractError):
        CONTRACT.qualify_client(
            invocation,
            pins=CONTRACT.load_pins(PINS_PATH),
        )

    assert not log_path.exists()
