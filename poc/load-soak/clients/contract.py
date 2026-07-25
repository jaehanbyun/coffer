from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any, Mapping, NamedTuple


PINS_SCHEMA = "coffer.load-client-pins/v1"
RESULT_SCHEMA = "coffer.load-client-result/v1"
CLIENTS = ("docker", "nerdctl", "oras", "podman", "skopeo")
ARCHITECTURES = ("aarch64", "x86_64")
REVISION = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY = re.compile(
    r"^(?=.{1,253}(?::[0-9]{1,5})?$)"
    r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?$"
)
REPOSITORY = re.compile(
    r"^p/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_CREDENTIAL_BYTES = 64 * 1024
MAX_CA_BYTES = 1024 * 1024


class ClientContractError(RuntimeError):
    pass


class Command(NamedTuple):
    argv: tuple[str, ...]
    digest_output: str | None = None
    password_stdin: bool = False


def _exact_mapping(
    value: object,
    keys: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ClientContractError(f"{category} boundary changed")
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _client_pin(
    name: str,
    value: object,
) -> Mapping[str, Any]:
    common = {
        "release_commit_verified",
        "release_url",
        "revision",
        "version",
    }
    keys = common
    if name == "nerdctl":
        keys = common | {
            "containerd_release_commit_verified",
            "containerd_release_url",
            "containerd_revision",
            "containerd_version",
        }
    checked = _exact_mapping(value, keys, f"{name} pin")
    if (
        not isinstance(checked["version"], str)
        or VERSION.fullmatch(checked["version"]) is None
        or not isinstance(checked["revision"], str)
        or REVISION.fullmatch(checked["revision"]) is None
        or not isinstance(checked["release_url"], str)
        or not checked["release_url"].startswith("https://")
        or checked["release_commit_verified"] is not (name != "skopeo")
    ):
        raise ClientContractError(f"{name} pin is invalid")
    if name == "nerdctl" and (
        not isinstance(checked["containerd_version"], str)
        or VERSION.fullmatch(checked["containerd_version"]) is None
        or not isinstance(checked["containerd_revision"], str)
        or REVISION.fullmatch(checked["containerd_revision"]) is None
        or not isinstance(checked["containerd_release_url"], str)
        or not checked["containerd_release_url"].startswith("https://")
        or checked["containerd_release_commit_verified"] is not True
    ):
        raise ClientContractError("nerdctl containerd pin is invalid")
    return checked


def parse_pins(payload: bytes) -> dict[str, Any]:
    if not payload or len(payload) > MAX_CREDENTIAL_BYTES or b"\x00" in payload:
        raise ClientContractError("client pins size is invalid")
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ClientContractError("client pins are invalid") from error
    checked = _exact_mapping(
        document,
        {"architectures", "checked_at", "clients", "schema"},
        "client pins",
    )
    if (
        checked["schema"] != PINS_SCHEMA
        or checked["architectures"] != list(ARCHITECTURES)
        or not isinstance(checked["checked_at"], str)
        or re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", checked["checked_at"])
        is None
    ):
        raise ClientContractError("client pins metadata changed")
    clients = _exact_mapping(
        checked["clients"],
        set(CLIENTS),
        "client pin set",
    )
    normalized = {
        name: dict(_client_pin(name, clients[name])) for name in CLIENTS
    }
    return {
        "architectures": list(ARCHITECTURES),
        "checked_at": checked["checked_at"],
        "clients": normalized,
        "pins_hash": _canonical_hash(document),
        "schema": PINS_SCHEMA,
    }


def load_pins(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ClientContractError("client pins are unavailable") from error
    return parse_pins(payload)


def _regular_file(
    path: Path,
    *,
    maximum: int,
    executable: bool = False,
    owner_only: bool = False,
    allow_nul: bool = False,
    trusted_read_only: bool = False,
) -> bytes:
    if not path.is_absolute():
        raise ClientContractError("client input path is not absolute")
    try:
        info = path.lstat()
    except OSError as error:
        raise ClientContractError("client input is unavailable") from error
    owner_invalid = owner_only and info.st_uid != os.geteuid()
    executable_owner_invalid = executable and (
        info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022 != 0
    )
    trusted_owner_invalid = trusted_read_only and (
        info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022 != 0
    )
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or owner_invalid
        or executable_owner_invalid
        or trusted_owner_invalid
        or info.st_size < 1
        or info.st_size > maximum
        or (executable and info.st_mode & 0o111 == 0)
        or (owner_only and stat.S_IMODE(info.st_mode) != 0o600)
    ):
        raise ClientContractError("client input boundary changed")
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ClientContractError("client input is unavailable") from error
    if (
        len(payload) != info.st_size
        or (not allow_nul and b"\x00" in payload)
    ):
        raise ClientContractError("client input is invalid")
    return payload


def _owner_directory(path: Path) -> None:
    if not path.is_absolute():
        raise ClientContractError("client work root is not absolute")
    try:
        info = path.lstat()
    except OSError as error:
        raise ClientContractError("client work root is unavailable") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ClientContractError("client work root boundary changed")


def _credentials(path: Path) -> tuple[str, bytearray]:
    payload = bytearray(
        _regular_file(
            path,
            maximum=MAX_CREDENTIAL_BYTES,
            owner_only=True,
        )
    )
    try:
        document = json.loads(payload)
        checked = _exact_mapping(
            document,
            {"password", "schema", "username"},
            "client credential",
        )
        username = checked["username"]
        password = checked["password"]
        if (
            checked["schema"] != "coffer.load-client-credential/v1"
            or not isinstance(username, str)
            or not isinstance(password, str)
            or not username
            or not password
            or len(username) > 256
            or len(password) > 8192
            or any(ord(character) < 0x20 for character in username + password)
        ):
            raise ClientContractError("client credential is invalid")
        return username, bytearray(password.encode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ClientContractError("client credential is invalid") from error
    finally:
        for index in range(len(payload)):
            payload[index] = 0


def _binary_digest(path: Path) -> str:
    payload = _regular_file(
        path,
        maximum=256 * 1024 * 1024,
        executable=True,
        allow_nul=True,
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_invocation(
    value: object,
    pins: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact_mapping(
        value,
        {
            "artifact_file",
            "binary",
            "binary_sha256",
            "ca_file",
            "client",
            "containerd_address",
            "credential_file",
            "docker_daemon_ca_file",
            "expected_digest",
            "expected_version",
            "registry",
            "referrers_mode",
            "repository",
            "schema",
            "source",
            "tag",
            "timeout_seconds",
            "work_root",
        },
        "client invocation",
    )
    client = checked["client"]
    if (
        checked["schema"] != "coffer.load-client-invocation/v1"
        or client not in CLIENTS
        or checked["expected_version"] != pins["clients"][client]["version"]
        or not isinstance(checked["binary_sha256"], str)
        or DIGEST.fullmatch(checked["binary_sha256"]) is None
        or not isinstance(checked["expected_digest"], str)
        or DIGEST.fullmatch(checked["expected_digest"]) is None
        or not isinstance(checked["registry"], str)
        or REGISTRY.fullmatch(checked["registry"]) is None
        or "." not in checked["registry"].split(":", 1)[0]
        or not isinstance(checked["repository"], str)
        or REPOSITORY.fullmatch(checked["repository"]) is None
        or not isinstance(checked["tag"], str)
        or TAG.fullmatch(checked["tag"]) is None
        or not isinstance(checked["source"], str)
        or not checked["source"]
        or len(checked["source"]) > 1024
        or any(ord(character) < 0x21 for character in checked["source"])
        or not isinstance(checked["timeout_seconds"], int)
        or isinstance(checked["timeout_seconds"], bool)
        or not 1 <= checked["timeout_seconds"] <= 600
    ):
        raise ClientContractError("client invocation is invalid")
    if ":" in checked["registry"]:
        try:
            port = int(checked["registry"].rsplit(":", 1)[1])
        except ValueError as error:
            raise ClientContractError("client registry port is invalid") from error
        if not 1 <= port <= 65535:
            raise ClientContractError("client registry port is invalid")
    for key in ("binary", "ca_file", "credential_file", "work_root"):
        if not isinstance(checked[key], str) or not Path(checked[key]).is_absolute():
            raise ClientContractError("client invocation path is invalid")
    if checked["artifact_file"] and (
        not isinstance(checked["artifact_file"], str)
        or not Path(checked["artifact_file"]).is_absolute()
    ):
        raise ClientContractError("client invocation path is invalid")
    if client == "oras":
        if not checked["artifact_file"]:
            raise ClientContractError("ORAS artifact input is required")
        if ":" in checked["artifact_file"]:
            raise ClientContractError("ORAS artifact path is ambiguous")
    elif checked["artifact_file"]:
        raise ClientContractError("unexpected artifact input")
    if client == "docker":
        daemon_ca = checked["docker_daemon_ca_file"]
        if (
            not isinstance(daemon_ca, str)
            or not Path(daemon_ca).is_absolute()
            or Path(daemon_ca).name != "ca.crt"
            or Path(daemon_ca).parent.name != checked["registry"]
        ):
            raise ClientContractError("Docker daemon CA boundary changed")
    elif checked["docker_daemon_ca_file"]:
        raise ClientContractError("unexpected Docker daemon CA")
    if client == "nerdctl":
        if (
            not isinstance(checked["containerd_address"], str)
            or not checked["containerd_address"].startswith("unix://")
            or len(checked["containerd_address"]) > 512
        ):
            raise ClientContractError("containerd address is invalid")
    elif checked["containerd_address"]:
        raise ClientContractError("unexpected containerd address")
    if client == "oras":
        if checked["referrers_mode"] not in (
            "v1.1-referrers-api",
            "v1.1-referrers-tag",
        ):
            raise ClientContractError("ORAS Referrers mode changed")
    elif checked["referrers_mode"]:
        raise ClientContractError("unexpected Referrers mode")
    if client in ("oras", "skopeo"):
        source_prefix = checked["registry"] + "/"
        if not checked["source"].startswith(source_prefix):
            raise ClientContractError("client source registry changed")
        source_name = checked["source"][len(source_prefix) :]
        source_repository = source_name.rsplit("@", 1)[0].rsplit(":", 1)[0]
        if (
            REPOSITORY.fullmatch(source_repository) is None
            or source_repository.split("/", 2)[1]
            != checked["repository"].split("/", 2)[1]
        ):
            raise ClientContractError("client source repository changed")
        if client == "oras" and (
            "@" not in source_name
            or DIGEST.fullmatch(source_name.rsplit("@", 1)[1]) is None
        ):
            raise ClientContractError("ORAS subject digest changed")
    paths = [
        Path(checked[key]).resolve(strict=False)
        for key in (
            "artifact_file",
            "binary",
            "ca_file",
            "credential_file",
            "docker_daemon_ca_file",
            "work_root",
        )
        if checked[key]
    ]
    if len(paths) != len(set(paths)):
        raise ClientContractError("client invocation paths overlap")
    return dict(checked)


def _common_target(invocation: Mapping[str, Any]) -> tuple[str, str]:
    tagged = (
        f"{invocation['registry']}/{invocation['repository']}:"
        f"{invocation['tag']}"
    )
    digested = (
        f"{invocation['registry']}/{invocation['repository']}@"
        f"{invocation['expected_digest']}"
    )
    return tagged, digested


def _command_plan(
    invocation: Mapping[str, Any],
    session: Path,
    username: str,
) -> tuple[list[Command], list[Command]]:
    client = invocation["client"]
    binary = invocation["binary"]
    registry = invocation["registry"]
    source = invocation["source"]
    tagged, digested = _common_target(invocation)
    auth_file = session / "auth.json"
    cert_dir = session / "certs"
    ca_file = cert_dir / "ca.crt"
    output_dir = session / "output"
    template = "{{json .RepoDigests}}"
    commands: list[Command]
    cleanup: list[Command]
    if client == "docker":
        config = session / "docker"
        commands = [
            Command((binary, "version", "--format", "{{.Client.Version}}|{{.Server.Version}}")),
            Command(
                (
                    binary,
                    "--config",
                    str(config),
                    "login",
                    "--username",
                    username,
                    "--password-stdin",
                    registry,
                ),
                password_stdin=True,
            ),
            Command((binary, "tag", source, tagged)),
            Command((binary, "--config", str(config), "push", tagged)),
            Command((binary, "--config", str(config), "pull", digested)),
            Command(
                (binary, "image", "inspect", "--format", template, digested),
                digest_output="repo-digests",
            ),
        ]
        cleanup = [
            Command((binary, "image", "rm", "--force", tagged, digested)),
            Command((binary, "--config", str(config), "logout", registry)),
        ]
    elif client == "podman":
        login = (
            binary,
            "login",
            "--authfile",
            str(auth_file),
            "--cert-dir",
            str(cert_dir),
            "--tls-verify=true",
        )
        commands = [
            Command((binary, "version", "--format", "{{.Client.Version}}")),
            Command(
                login
                + (
                    "--username",
                    username,
                    "--password-stdin",
                    registry,
                ),
                password_stdin=True,
            ),
            Command((binary, "tag", source, tagged)),
            Command(
                (
                    binary,
                    "push",
                    "--authfile",
                    str(auth_file),
                    "--cert-dir",
                    str(cert_dir),
                    "--tls-verify=true",
                    tagged,
                )
            ),
            Command(
                (
                    binary,
                    "pull",
                    "--authfile",
                    str(auth_file),
                    "--cert-dir",
                    str(cert_dir),
                    "--tls-verify=true",
                    digested,
                )
            ),
            Command(
                (binary, "image", "inspect", "--format", "{{.Digest}}", digested),
                digest_output="digest",
            ),
        ]
        cleanup = [
            Command((binary, "image", "rm", "--force", tagged, digested)),
            Command(
                (
                    binary,
                    "logout",
                    "--authfile",
                    str(auth_file),
                    registry,
                )
            ),
        ]
    elif client == "skopeo":
        commands = [
            Command((binary, "--version")),
            Command(
                (
                    binary,
                    "login",
                    "--authfile",
                    str(auth_file),
                    "--cert-dir",
                    str(cert_dir),
                    "--tls-verify=true",
                    "--username",
                    username,
                    "--password-stdin",
                    registry,
                ),
                password_stdin=True,
            ),
            Command(
                (
                    binary,
                    "copy",
                    "--authfile",
                    str(auth_file),
                    "--src-cert-dir",
                    str(cert_dir),
                    "--dest-cert-dir",
                    str(cert_dir),
                    "--src-tls-verify=true",
                    "--dest-tls-verify=true",
                    "docker://" + source,
                    "docker://" + tagged,
                )
            ),
            Command(
                (
                    binary,
                    "inspect",
                    "--authfile",
                    str(auth_file),
                    "--cert-dir",
                    str(cert_dir),
                    "--tls-verify=true",
                    "--format",
                    "{{.Digest}}",
                    "docker://" + tagged,
                ),
                digest_output="digest",
            ),
        ]
        cleanup = [
            Command(
                (
                    binary,
                    "logout",
                    "--authfile",
                    str(auth_file),
                    registry,
                )
            )
        ]
    elif client == "oras":
        registry_config = session / "oras-auth.json"
        commands = [
            Command((binary, "version")),
            Command(
                (
                    binary,
                    "login",
                    "--registry-config",
                    str(registry_config),
                    "--ca-file",
                    str(ca_file),
                    "--username",
                    username,
                    "--password-stdin",
                    registry,
                ),
                password_stdin=True,
            ),
            Command(
                (
                    binary,
                    "attach",
                    "--registry-config",
                    str(registry_config),
                    "--ca-file",
                    str(ca_file),
                    "--artifact-type",
                    "application/vnd.coffer.load.v1",
                    "--distribution-spec",
                    invocation["referrers_mode"],
                    "--format",
                    "go-template",
                    "--template",
                    "{{.digest}}",
                    source,
                    invocation["artifact_file"]
                    + ":application/vnd.coffer.load.v1",
                ),
                digest_output="digest",
            ),
            Command(
                (
                    binary,
                    "discover",
                    "--registry-config",
                    str(registry_config),
                    "--ca-file",
                    str(ca_file),
                    "--artifact-type",
                    "application/vnd.coffer.load.v1",
                    "--distribution-spec",
                    invocation["referrers_mode"],
                    "--format",
                    "json",
                    "--depth",
                    "1",
                    source,
                )
            ),
            Command(
                (
                    binary,
                    "pull",
                    "--registry-config",
                    str(registry_config),
                    "--ca-file",
                    str(ca_file),
                    "--output",
                    str(output_dir),
                    digested,
                )
            ),
        ]
        cleanup = [
            Command(
                (
                    binary,
                    "logout",
                    "--registry-config",
                    str(registry_config),
                    registry,
                )
            )
        ]
    else:
        prefix = (
            binary,
            "--address",
            invocation["containerd_address"],
            "--namespace",
            "coffer-load",
            "--data-root",
            str(session / "nerdctl-data"),
        )
        commands = [
            Command(prefix + ("version",)),
            Command(
                prefix
                + (
                    "login",
                    "--username",
                    username,
                    "--password-stdin",
                    registry,
                ),
                password_stdin=True,
            ),
            Command(prefix + ("tag", source, tagged)),
            Command(prefix + ("push", tagged)),
            Command(prefix + ("pull", digested)),
            Command(
                prefix
                + ("image", "inspect", "--format", template, digested),
                digest_output="repo-digests",
            ),
        ]
        cleanup = [
            Command(prefix + ("image", "rm", "--force", tagged, digested)),
            Command(prefix + ("logout", registry)),
        ]
    return commands, cleanup


def _clean_environment(session: Path) -> dict[str, str]:
    return {
        "DOCKER_CONFIG": str(session / "docker"),
        "HOME": str(session / "home"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "XDG_CONFIG_HOME": str(session / "xdg-config"),
        "XDG_RUNTIME_DIR": str(session / "xdg-runtime"),
    }


def _run(
    command: Command,
    *,
    environment: Mapping[str, str],
    password: bytearray,
    timeout: int,
) -> bytes:
    stdin = bytes(password) + b"\n" if command.password_stdin else b""
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    streams: dict[str, bytearray] = {
        "stderr": bytearray(),
        "stdout": bytearray(),
    }
    failure: str | None = None
    try:
        process = subprocess.Popen(
            command.argv,
            env=dict(environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        if stdin:
            process.stdin.write(stdin)
            process.stdin.flush()
        process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "client command dependency failed"
                break
            events = selector.select(min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in tuple(selector.get_map().values())
                ]
            for key, _ in events:
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output = streams[key.data]
                if len(output) + len(chunk) > MAX_OUTPUT_BYTES:
                    failure = "client command output exceeded limit"
                    break
                output.extend(chunk)
            if failure is not None:
                break
        if failure is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "client command dependency failed"
            else:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    failure = "client command dependency failed"
    except (OSError, subprocess.SubprocessError) as error:
        failure = "client command dependency failed"
        dependency_error = error
    finally:
        selector.close()
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    if failure is not None:
        if "dependency_error" in locals():
            raise ClientContractError(failure) from dependency_error
        raise ClientContractError(failure)
    assert process is not None
    stdout = bytes(streams["stdout"])
    stderr = bytes(streams["stderr"])
    if bytes(password) in stdout or bytes(password) in stderr:
        raise ClientContractError("client command exposed credential")
    if process.returncode != 0:
        raise ClientContractError("client command failed")
    return stdout


def _check_version(
    client: str,
    output: bytes,
    pin: Mapping[str, Any],
) -> None:
    try:
        text = output.decode("utf-8", errors="strict").strip()
    except UnicodeError as error:
        raise ClientContractError("client version output is invalid") from error
    version = pin["version"]
    if client == "docker":
        valid = text == f"{version}|{version}"
    elif client in ("podman",):
        valid = text == version
    elif client == "skopeo":
        valid = text == f"skopeo version {version}"
    elif client == "oras":
        valid = re.search(
            rf"(?m)^Version:\s*v?{re.escape(version)}$",
            text,
        ) is not None
    else:
        valid = (
            re.search(
                rf"(?m)^\s*Version:\s*v?{re.escape(version)}$",
                text,
            )
            is not None
            and re.search(
                rf"(?m)^\s*Version:\s*v?{re.escape(pin['containerd_version'])}$",
                text,
            )
            is not None
        )
    if not valid:
        raise ClientContractError("client version does not match pin")


def _check_digest(kind: str, output: bytes, expected: str) -> None:
    try:
        text = output.decode("utf-8", errors="strict").strip()
        if kind == "digest":
            actual = text
        else:
            values = json.loads(text)
            if (
                not isinstance(values, list)
                or len(values) < 1
                or not all(isinstance(value, str) for value in values)
            ):
                raise ClientContractError("client digest output is invalid")
            matches = [value for value in values if value.endswith("@" + expected)]
            actual = expected if len(matches) == 1 else ""
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ClientContractError("client digest output is invalid") from error
    if actual != expected:
        raise ClientContractError("client digest mismatch")


def qualify_client(
    invocation_document: object,
    *,
    pins: Mapping[str, Any],
) -> dict[str, Any]:
    invocation = validate_invocation(invocation_document, pins)
    work_root = Path(invocation["work_root"])
    _owner_directory(work_root)
    binary = Path(invocation["binary"])
    if _binary_digest(binary) != invocation["binary_sha256"]:
        raise ClientContractError("client binary digest changed")
    ca_payload = _regular_file(
        Path(invocation["ca_file"]),
        maximum=MAX_CA_BYTES,
        owner_only=True,
    )
    if (
        not ca_payload.startswith(b"-----BEGIN CERTIFICATE-----")
        or not ca_payload.rstrip().endswith(b"-----END CERTIFICATE-----")
    ):
        raise ClientContractError("client CA is invalid")
    if invocation["docker_daemon_ca_file"]:
        daemon_ca = _regular_file(
            Path(invocation["docker_daemon_ca_file"]),
            maximum=MAX_CA_BYTES,
            trusted_read_only=True,
        )
        if daemon_ca != ca_payload:
            raise ClientContractError("Docker daemon CA changed")
    if invocation["artifact_file"]:
        _regular_file(
            Path(invocation["artifact_file"]),
            maximum=256 * 1024 * 1024,
            owner_only=True,
        )
    username, password = _credentials(Path(invocation["credential_file"]))
    try:
        session = Path(
            tempfile.mkdtemp(prefix=".coffer-client-", dir=work_root)
        )
        os.chmod(session, 0o700)
    except OSError as error:
        raise ClientContractError("client state creation failed") from error
    command_count = 0
    digest_checks = 0
    primary_error: ClientContractError | None = None
    try:
        for relative in (
            "certs",
            "docker",
            "home",
            "nerdctl-data",
            "output",
            "xdg-config",
            "xdg-runtime",
        ):
            directory = session / relative
            directory.mkdir(mode=0o700)
        ca_destination = session / "certs" / "ca.crt"
        ca_destination.write_bytes(ca_payload)
        ca_destination.chmod(0o600)
        registry_cert_directory = (
            session
            / "xdg-config"
            / "containerd"
            / "certs.d"
            / invocation["registry"]
        )
        registry_cert_directory.mkdir(parents=True, mode=0o700)
        nerdctl_ca = registry_cert_directory / "ca.crt"
        nerdctl_ca.write_bytes(ca_payload)
        nerdctl_ca.chmod(0o600)
        hosts = registry_cert_directory / "hosts.toml"
        hosts.write_text(
            f'server = "https://{invocation["registry"]}"\n'
            f'[host."https://{invocation["registry"]}"]\n'
            f'  ca = "{nerdctl_ca}"\n'
            '  capabilities = ["pull", "resolve", "push"]\n',
            encoding="utf-8",
        )
        hosts.chmod(0o600)
        environment = _clean_environment(session)
        commands, cleanup = _command_plan(invocation, session, username)
        for index, command in enumerate(commands):
            output = _run(
                command,
                environment=environment,
                password=password,
                timeout=invocation["timeout_seconds"],
            )
            command_count += 1
            if index == 0:
                _check_version(
                    invocation["client"],
                    output,
                    pins["clients"][invocation["client"]],
                )
            if command.digest_output is not None:
                _check_digest(
                    command.digest_output,
                    output,
                    invocation["expected_digest"],
                )
                digest_checks += 1
    except ClientContractError as error:
        primary_error = error
    except OSError:
        primary_error = ClientContractError("client state operation failed")
    finally:
        if "cleanup" in locals() and "environment" in locals():
            for command in cleanup:
                try:
                    _run(
                        command,
                        environment=environment,
                        password=password,
                        timeout=invocation["timeout_seconds"],
                    )
                    command_count += 1
                except ClientContractError:
                    if primary_error is None:
                        primary_error = ClientContractError(
                            "client cleanup failed"
                        )
        for index in range(len(password)):
            password[index] = 0
        try:
            shutil.rmtree(session)
        except OSError:
            if primary_error is None:
                primary_error = ClientContractError("client cleanup failed")
    if primary_error is not None:
        raise primary_error
    if digest_checks != 1:
        raise ClientContractError("client digest verification is incomplete")
    return {
        "binary_sha256": invocation["binary_sha256"],
        "client": invocation["client"],
        "command_count": command_count,
        "digest_checks": digest_checks,
        "pins_hash": pins["pins_hash"],
        "referrers_mode": (
            "native"
            if invocation["referrers_mode"] == "v1.1-referrers-api"
            else (
                "fallback-tag"
                if invocation["referrers_mode"] == "v1.1-referrers-tag"
                else "not-applicable"
            )
        ),
        "result": "success",
        "schema": RESULT_SCHEMA,
        "version": invocation["expected_version"],
    }
