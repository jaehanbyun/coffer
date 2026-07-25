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


CONTRACT_PATH = Path(__file__).with_name("contract.py")
CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "coffer_load_client_contract_runtime",
    CONTRACT_PATH,
)
if CONTRACT_SPEC is None or CONTRACT_SPEC.loader is None:
    raise RuntimeError("load client contract is unavailable")
contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = contract
CONTRACT_SPEC.loader.exec_module(contract)

RUN_SCHEMA = "coffer.load-client-run/v1"
EXECUTION_SCHEMA = "coffer.load-client-execution/v1"
READINESS_SCHEMA = "coffer.upstream-readiness/v1"
MAX_INVOCATION_BYTES = 256 * 1024
MAX_READINESS_BYTES = 1024 * 1024
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
FIXED_FAILURES = frozenset(
    {
        "contract-refused",
        "execution-unavailable",
        "invalid-arguments",
        "local-file-unavailable",
        "output-unavailable",
        "readiness-refused",
    }
)


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("load client failure category is not fixed")
        super().__init__(category)
        self.category = category


def _exact(
    value: object,
    keys: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CommandError(category)
    return value


def _read_owner_file(path: Path, maximum: int) -> bytes:
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
            or details.st_size > maximum
        ):
            raise CommandError("local-file-unavailable")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(maximum + 1)
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


def _decode(payload: bytes, category: str) -> Mapping[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CommandError(category) from error
    if not isinstance(document, Mapping):
        raise CommandError(category)
    return document


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _version_greater(value: object, baseline: object) -> bool:
    current = VERSION.fullmatch(str(value))
    previous = VERSION.fullmatch(str(baseline))
    if current is None or previous is None:
        return False
    return tuple(map(int, current.groups())) > tuple(
        map(int, previous.groups())
    )


def _validate_readiness(payload: bytes, expected: object) -> str:
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        raise CommandError("readiness-refused")
    if _digest(payload) != expected:
        raise CommandError("readiness-refused")
    document = _exact(
        _decode(payload, "readiness-refused"),
        {"ceph", "distribution", "schema", "status"},
        "readiness-refused",
    )
    distribution = _exact(
        document["distribution"],
        {
            "baseline",
            "latest_stable",
            "published_at",
            "reasons",
            "revision",
            "status",
            "url",
            "verified_release_commit",
        },
        "readiness-refused",
    )
    ceph = _exact(
        document["ceph"],
        {
            "baseline",
            "fix_in_latest_stable",
            "fix_merge_revision",
            "fix_merged_to_tentacle",
            "fix_pull_request",
            "latest_stable",
            "reasons",
            "revision",
            "status",
        },
        "readiness-refused",
    )
    if (
        document["schema"] != READINESS_SCHEMA
        or document["status"] != "candidate-qualified"
        or distribution["status"] != "candidate-qualified"
        or ceph["status"] != "candidate-qualified"
        or distribution["verified_release_commit"] is not True
        or ceph["fix_in_latest_stable"] is not True
        or ceph["fix_merged_to_tentacle"] is not True
        or distribution["reasons"] != []
        or ceph["reasons"] != []
        or distribution["baseline"] != "v3.1.1"
        or ceph["baseline"] != "v20.2.2"
        or ceph["fix_pull_request"] != 69277
        or ceph["fix_merge_revision"]
        != "c6fc9801f55e24152f0e934b2ddc3e5cda33d63e"
        or not _version_greater(
            distribution["latest_stable"],
            distribution["baseline"],
        )
        or not _version_greater(
            ceph["latest_stable"],
            ceph["baseline"],
        )
        or not str(ceph["latest_stable"]).startswith("v20.2.")
        or not isinstance(distribution["revision"], str)
        or REVISION.fullmatch(distribution["revision"]) is None
        or not isinstance(ceph["revision"], str)
        or REVISION.fullmatch(ceph["revision"]) is None
        or not isinstance(distribution["published_at"], str)
        or not distribution["published_at"]
        or not isinstance(distribution["url"], str)
        or not distribution["url"].startswith("https://")
    ):
        raise CommandError("readiness-refused")
    return expected


def _validate_directory(path: Path) -> None:
    try:
        details = path.lstat()
    except OSError as error:
        raise CommandError("output-unavailable") from error
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise CommandError("output-unavailable")


def _validate_output(path: Path) -> None:
    if not path.is_absolute() or path.name in ("", ".", ".."):
        raise CommandError("output-unavailable")
    _validate_directory(path.parent)
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


def _atomic_result(path: Path, result: object) -> None:
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
            json.dump(result, stream, separators=(",", ":"), sort_keys=True)
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


def _paths(document: Mapping[str, Any], invocation_path: Path) -> list[Path]:
    values = [
        invocation_path,
        Path(document["output_file"]),
        Path(document["pins_file"]),
        Path(document["readiness_file"]),
    ]
    invocation = document["invocation"]
    if isinstance(invocation, Mapping):
        for key in (
            "artifact_file",
            "binary",
            "ca_file",
            "credential_file",
            "docker_daemon_ca_file",
            "work_root",
        ):
            value = invocation.get(key)
            if isinstance(value, str) and value:
                values.append(Path(value))
    return values


def execute(invocation_path: Path) -> None:
    invocation_payload = _read_owner_file(
        invocation_path,
        MAX_INVOCATION_BYTES,
    )
    document = _exact(
        _decode(invocation_payload, "contract-refused"),
        {
            "invocation",
            "output_file",
            "pins_file",
            "pins_sha256",
            "readiness_file",
            "readiness_sha256",
            "schema",
        },
        "contract-refused",
    )
    if document["schema"] != RUN_SCHEMA:
        raise CommandError("contract-refused")
    for key in ("output_file", "pins_file", "readiness_file"):
        if (
            not isinstance(document[key], str)
            or not Path(document[key]).is_absolute()
        ):
            raise CommandError("contract-refused")
    paths = [path.resolve(strict=False) for path in _paths(document, invocation_path)]
    if len(paths) != len(set(paths)):
        raise CommandError("contract-refused")
    output_path = Path(document["output_file"])
    _validate_output(output_path)

    pins_payload = _read_owner_file(
        Path(document["pins_file"]),
        contract.MAX_CREDENTIAL_BYTES,
    )
    if (
        not isinstance(document["pins_sha256"], str)
        or SHA256.fullmatch(document["pins_sha256"]) is None
        or _digest(pins_payload) != document["pins_sha256"]
    ):
        raise CommandError("contract-refused")
    try:
        pins = contract.parse_pins(pins_payload)
        contract.validate_invocation(document["invocation"], pins)
    except contract.ClientContractError as error:
        raise CommandError("contract-refused") from error

    readiness_payload = _read_owner_file(
        Path(document["readiness_file"]),
        MAX_READINESS_BYTES,
    )
    readiness_sha256 = _validate_readiness(
        readiness_payload,
        document["readiness_sha256"],
    )
    try:
        client_result = contract.qualify_client(
            document["invocation"],
            pins=pins,
        )
    except contract.ClientContractError as error:
        raise CommandError("execution-unavailable") from error
    result = {
        "client_result": client_result,
        "pins_file_sha256": document["pins_sha256"],
        "readiness_sha256": readiness_sha256,
        "schema": EXECUTION_SCHEMA,
    }
    _atomic_result(output_path, result)


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) != 2
        or arguments[0] != "--invocation"
        or not arguments[1]
    ):
        print("load client failed: invalid-arguments", file=stderr)
        return 2
    try:
        execute(Path(arguments[1]))
    except KeyboardInterrupt:
        print("load client failed: execution-unavailable", file=stderr)
        return 1
    except CommandError as error:
        print(f"load client failed: {error.category}", file=stderr)
        return 1
    print("load client completed", file=stdout)
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
