from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


STATE_PATH = Path(__file__).with_name("state_machine.py")
STATE_SPEC = importlib.util.spec_from_file_location(
    "coffer_load_plan_state_machine",
    STATE_PATH,
)
if STATE_SPEC is None or STATE_SPEC.loader is None:
    raise RuntimeError("load state contract is unavailable")
state_machine = importlib.util.module_from_spec(STATE_SPEC)
sys.modules[STATE_SPEC.name] = state_machine
STATE_SPEC.loader.exec_module(state_machine)

REQUEST_SCHEMA = "coffer.load-execution-plan-request/v1"
PLAN_SCHEMA = "coffer.load-execution-plan/v1"
ENVELOPE_SCHEMA = "coffer.load-execution-plan-envelope/v1"
MAX_REQUEST_BYTES = 1024 * 1024
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
FIXED_FAILURES = frozenset(
    {
        "contract-refused",
        "invalid-arguments",
        "local-file-unavailable",
        "output-unavailable",
    }
)
CONTENT_BYTES = {
    "zero-byte": 0,
    "one-byte": 1,
    "one-mib": 1024**2,
    "thirty-two-mib": 32 * 1024**2,
    "two-hundred-fifty-six-mib": 256 * 1024**2,
    "five-layer": 5 * 1024**2,
    "shared-cross-mount": 32 * 1024**2,
    "multiarch-index": 0,
    "subject-referrer": 1024**2,
}
CLIENT_OPERATIONS = {
    "docker": (
        "token",
        "manifest-read",
        "manifest-publish",
        "blob-read",
        "blob-resumable",
        "index",
    ),
    "podman": (
        "token",
        "manifest-read",
        "manifest-publish",
        "blob-read",
        "blob-resumable",
        "index",
    ),
    "skopeo": (
        "token",
        "manifest-read",
        "manifest-publish",
        "blob-read",
        "index",
    ),
    "oras": (
        "token",
        "manifest-read",
        "manifest-publish",
        "blob-read",
        "index",
        "artifact",
    ),
    "nerdctl": (
        "token",
        "manifest-read",
        "manifest-publish",
        "blob-read",
        "blob-resumable",
        "index",
    ),
    "raw-oci": (
        "control",
        "token",
        "manifest-read",
        "manifest-publish",
        "blob-read",
        "blob-monolithic",
        "blob-resumable",
        "blob-cross-mount",
        "quota-contention",
        "index",
        "artifact",
        "abandoned-upload",
    ),
}
CLIENT_CONTENT = {
    "docker": (
        "zero-byte",
        "one-byte",
        "one-mib",
        "thirty-two-mib",
        "five-layer",
        "shared-cross-mount",
        "multiarch-index",
    ),
    "podman": (
        "zero-byte",
        "one-byte",
        "one-mib",
        "thirty-two-mib",
        "five-layer",
        "shared-cross-mount",
        "multiarch-index",
    ),
    "skopeo": (
        "one-byte",
        "one-mib",
        "thirty-two-mib",
        "five-layer",
        "multiarch-index",
    ),
    "oras": (
        "one-byte",
        "one-mib",
        "multiarch-index",
        "subject-referrer",
    ),
    "nerdctl": (
        "zero-byte",
        "one-byte",
        "one-mib",
        "thirty-two-mib",
        "five-layer",
        "shared-cross-mount",
        "multiarch-index",
    ),
    "raw-oci": tuple(CONTENT_BYTES),
}


class PlanError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("load plan failure category is not fixed")
        super().__init__(category)
        self.category = category


def _exact(
    value: object,
    keys: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PlanError(f"{category} boundary changed")
    return value


def _hash(value: object) -> str:
    payload = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _version(value: object, baseline: str, category: str) -> str:
    match = VERSION.fullmatch(str(value))
    previous = VERSION.fullmatch(baseline)
    if match is None or previous is None:
        raise PlanError(f"{category} version is invalid")
    if tuple(map(int, match.groups())) <= tuple(map(int, previous.groups())):
        raise PlanError(f"{category} release is not newer than baseline")
    return str(value)


def _validate_bindings(
    value: object,
    topology: Mapping[str, Any],
) -> dict[str, Any]:
    bindings = _exact(
        value,
        {
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
        },
        "execution binding",
    )
    if (
        bindings["architectures"] != topology["required_architectures"]
        or bindings["readiness_status"] != "qualified"
        or not isinstance(bindings["distribution_revision"], str)
        or REVISION.fullmatch(bindings["distribution_revision"]) is None
        or not isinstance(bindings["ceph_revision"], str)
        or REVISION.fullmatch(bindings["ceph_revision"]) is None
        or not isinstance(bindings["driver_revision"], str)
        or REVISION.fullmatch(bindings["driver_revision"]) is None
    ):
        raise PlanError("execution release binding is not qualified")
    _version(bindings["distribution_version"], "v3.1.1", "Distribution")
    ceph_version = _version(bindings["ceph_version"], "v20.2.2", "Ceph")
    if not ceph_version.startswith("v20.2."):
        raise PlanError("Ceph release is outside Tentacle v20.2")
    for key in (
        "client_versions_hash",
        "configuration_hash",
        "image_set_hash",
        "readiness_evidence_hash",
    ):
        if (
            not isinstance(bindings[key], str)
            or SHA256.fullmatch(bindings[key]) is None
        ):
            raise PlanError("execution evidence hash is invalid")
    return dict(bindings)


def _matrix(topology: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (
        tuple(topology["clients"]) != tuple(CLIENT_OPERATIONS)
        or set(topology["operations"])
        != {
            operation
            for operations in CLIENT_OPERATIONS.values()
            for operation in operations
        }
        or set(topology["content_classes"]) != set(CONTENT_BYTES)
    ):
        raise PlanError("execution capability matrix does not cover topology")
    matrix = []
    for client in topology["clients"]:
        operations = list(CLIENT_OPERATIONS[client])
        content = list(CLIENT_CONTENT[client])
        if (
            not set(operations).issubset(topology["operations"])
            or not set(content).issubset(topology["content_classes"])
            or not operations
            or not content
        ):
            raise PlanError("client execution capability changed")
        matrix.append(
            {
                "client": client,
                "content_classes": content,
                "executor_contract": "required",
                "operations": operations,
                "verified_tls_required": True,
            }
        )
    return matrix


def compile_plan(
    request_value: object,
    *,
    topology: Mapping[str, Any],
) -> dict[str, Any]:
    request = _exact(
        request_value,
        {"bindings", "schema", "topology_sha256"},
        "execution plan request",
    )
    topology_hash = _hash(topology)
    if (
        request["schema"] != REQUEST_SCHEMA
        or request["topology_sha256"] != topology_hash
    ):
        raise PlanError("execution plan topology binding changed")
    bindings = _validate_bindings(request["bindings"], topology)
    profiles = [
        {
            "burst_clients": topology["profiles"][name]["burst_clients"],
            "duration_seconds": topology["profiles"][name][
                "duration_seconds"
            ],
            "name": name,
            "order": order,
            "steady_clients": topology["profiles"][name]["steady_clients"],
            "transfer_ceiling_bytes": topology["profiles"][name][
                "transfer_ceiling_bytes"
            ],
        }
        for order, name in enumerate(("smoke", "qualification", "soak"), 1)
    ]
    ramp_budget = (
        topology["profiles"]["qualification"]["transfer_ceiling_bytes"]
        // len(topology["ramp_clients"])
    )
    ramp = [
        {
            "clients": clients,
            "order": order,
            "transfer_ceiling_bytes": ramp_budget,
        }
        for order, clients in enumerate(topology["ramp_clients"], 1)
    ]
    faults = [
        {
            "fault": name,
            "order": order,
            "recovery_seconds": limits["recovery_seconds"],
            "serial": True,
            "window_seconds": limits["window_seconds"],
        }
        for order, (name, limits) in enumerate(topology["faults"].items(), 1)
    ]
    content = [
        {
            "name": name,
            "payload_bytes": CONTENT_BYTES[name],
        }
        for name in topology["content_classes"]
    ]
    plan = {
        "bindings": bindings,
        "bindings_sha256": _hash(bindings),
        "content": content,
        "faults": faults,
        "matrix": _matrix(topology),
        "phases": list(topology["phases"]),
        "profiles": profiles,
        "ramp": ramp,
        "schema": PLAN_SCHEMA,
        "target_class": topology["target_class"],
        "telemetry_windows": ["before", "during", "after"],
        "topology_sha256": topology_hash,
        "transfer_ceiling_bytes": topology["profiles"]["soak"][
            "transfer_ceiling_bytes"
        ],
    }
    state_machine.validate_retained_evidence(plan)
    return {
        "plan": plan,
        "plan_sha256": _hash(plan),
        "schema": ENVELOPE_SCHEMA,
        "synthetic": True,
    }


def _read_owner_file(path: Path) -> bytes:
    if not path.is_absolute():
        raise CommandError("local-file-unavailable")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or details.st_size < 1
            or details.st_size > MAX_REQUEST_BYTES
        ):
            raise CommandError("local-file-unavailable")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(MAX_REQUEST_BYTES + 1)
    except CommandError:
        raise
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) != details.st_size or b"\x00" in payload:
        raise CommandError("local-file-unavailable")
    return payload


def _validate_output(path: Path) -> None:
    if not path.is_absolute():
        raise CommandError("output-unavailable")
    try:
        parent = path.parent.lstat()
    except OSError as error:
        raise CommandError("output-unavailable") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.geteuid()
    ):
        raise CommandError("output-unavailable")
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise CommandError("output-unavailable") from error
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        raise CommandError("output-unavailable")


def _atomic_output(path: Path, value: object) -> None:
    _validate_output(path)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise CommandError("output-unavailable") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _validate_output(path)


def compile_file(
    request_path: Path,
    output_path: Path,
    topology_path: Path,
) -> None:
    resolved = [
        path.resolve(strict=False)
        for path in (request_path, output_path, topology_path)
    ]
    if len(resolved) != len(set(resolved)):
        raise CommandError("contract-refused")
    _validate_output(output_path)
    payload = _read_owner_file(request_path)
    try:
        request = json.loads(payload)
        if payload != (
            json.dumps(request, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8"):
            raise PlanError("execution plan request is not canonical")
        topology = state_machine.load_topology(topology_path)
        envelope = compile_plan(request, topology=topology)
    except (
        UnicodeError,
        json.JSONDecodeError,
        state_machine.LoadSoakError,
        PlanError,
    ) as error:
        raise CommandError("contract-refused") from error
    _atomic_output(output_path, envelope)


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) != 6
        or arguments[0] != "--request"
        or arguments[2] != "--output"
        or arguments[4] != "--topology"
        or any(not arguments[index] for index in (1, 3, 5))
    ):
        print("load plan failed: invalid-arguments", file=stderr)
        return 2
    try:
        compile_file(
            Path(arguments[1]),
            Path(arguments[3]),
            Path(arguments[5]),
        )
    except CommandError as error:
        print(f"load plan failed: {error.category}", file=stderr)
        return 1
    print("load plan compiled", file=stdout)
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
