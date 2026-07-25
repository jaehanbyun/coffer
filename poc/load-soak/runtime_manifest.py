from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


DIRECTORY = Path(__file__).parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


orchestrator = _module(
    "coffer_load_runtime_manifest_orchestrator",
    DIRECTORY / "orchestrator.py",
)
client_run = _module(
    "coffer_load_runtime_manifest_client_run",
    DIRECTORY / "clients" / "run.py",
)

MANIFEST_SCHEMA = "coffer.load-runtime-manifest/v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
FIXED_FAILURES = frozenset(
    {
        "contract-refused",
        "invalid-arguments",
        "local-file-unavailable",
        "output-unavailable",
    }
)
CONTROL_OPERATIONS = {
    "control",
    "quota-contention",
    "token",
}


class ManifestError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("runtime manifest failure category is not fixed")
        super().__init__(category)
        self.category = category


def _hash_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _hash(value: object) -> str:
    return _hash_bytes(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _source_hash(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ManifestError("runtime contract source is unavailable") from error
        relative = str(path.relative_to(DIRECTORY)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return "sha256:" + digest.hexdigest()


def _contract_hashes() -> dict[str, str]:
    client_hash = _source_hash(
        [
            DIRECTORY / "clients" / "contract.py",
            DIRECTORY / "clients" / "run.py",
        ]
    )
    go_paths = [
        path
        for path in (DIRECTORY / "driver").rglob("*.go")
        if path.is_file()
    ]
    return {
        **{
            f"client-{client}": client_hash
            for client in ("docker", "nerdctl", "oras", "podman", "skopeo")
        },
        "raw-oci": _source_hash(go_paths),
        "control-load": _source_hash(
            [
                path
                for path in (DIRECTORY / "control").rglob("*.go")
                if path.is_file()
            ]
        ),
        "profile-load": _source_hash(
            [
                path
                for path in (DIRECTORY / "profile").rglob("*.py")
                if path.is_file()
            ]
        ),
        "fault": _source_hash(
            [
                DIRECTORY / "profile" / "run.py",
                *[
                    path
                    for path in (DIRECTORY / "fault").rglob("*.py")
                    if path.is_file()
                ],
            ]
        ),
        "telemetry-collector": _source_hash(
            [
                DIRECTORY / "telemetry.py",
                *[
                    path
                    for path in (DIRECTORY / "collector").rglob("*.py")
                    if path.is_file()
                ],
            ]
        ),
    }


def build_manifest(
    envelope_value: object,
    *,
    topology: Mapping[str, Any],
    readiness_payload: bytes,
    pins_payload: bytes,
) -> dict[str, Any]:
    plan = orchestrator._validate_envelope(envelope_value, topology)
    if not isinstance(envelope_value, Mapping):
        raise ManifestError("runtime plan envelope is invalid")
    readiness_sha256 = _hash_bytes(readiness_payload)
    pins_sha256 = _hash_bytes(pins_payload)
    try:
        client_run._validate_readiness(readiness_payload, readiness_sha256)
        pins = client_run.contract.parse_pins(pins_payload)
    except (
        client_run.CommandError,
        client_run.contract.ClientContractError,
    ) as error:
        raise ManifestError("runtime dependency evidence is invalid") from error
    bindings = plan["bindings"]
    if (
        bindings["readiness_evidence_hash"] != readiness_sha256
        or bindings["client_versions_hash"] != pins_sha256
        or pins["schema"] != client_run.contract.PINS_SCHEMA
    ):
        raise ManifestError("runtime evidence does not match load plan")
    schedule = orchestrator.build_schedule(plan)
    contract_hashes = _contract_hashes()
    entries: list[dict[str, Any]] = []
    gaps: set[str] = set()
    fault_limits = {
        entry["fault"]: entry for entry in plan["faults"]
    }
    profile_limits = {
        entry["name"]: entry for entry in plan["profiles"]
    }
    for step in schedule:
        if step.kind == "client":
            executor = (
                "raw-oci" if step.name == "raw-oci" else f"client-{step.name}"
            )
            disposition = "contract-only"
            input_contract = (
                "coffer.raw-oci-invocation/v1"
                if executor == "raw-oci"
                else "coffer.load-client-run/v1"
            )
            output_contract = (
                "coffer.raw-oci-driver/v1"
                if executor == "raw-oci"
                else "coffer.load-client-execution/v1"
            )
            timeout_seconds = 10800 if executor == "raw-oci" else 600
        elif step.kind in ("profile", "ramp"):
            executor = "profile-load"
            disposition = "contract-only"
            input_contract = "coffer.load-profile-invocation/v1"
            output_contract = "coffer.load-profile-result/v1"
            if step.kind == "profile":
                duration_seconds = profile_limits[step.name][
                    "duration_seconds"
                ]
            else:
                duration_seconds = next(
                    entry["duration_seconds"]
                    for entry in plan["ramp"]
                    if f"clients-{entry['clients']}" == step.name
                )
            timeout_seconds = duration_seconds + 600
        elif step.kind == "fault":
            executor = "fault"
            disposition = "contract-only"
            input_contract = "coffer.load-fault-invocation/v1"
            output_contract = "coffer.load-fault-result/v1"
            timeout_seconds = (
                fault_limits[step.name]["window_seconds"]
                + fault_limits[step.name]["recovery_seconds"]
                + 60
            )
        else:
            executor = "telemetry-collector"
            disposition = "contract-only"
            input_contract = "coffer.load-telemetry-collection/v1"
            output_contract = "coffer.load-telemetry-collection-result/v1"
            timeout_seconds = 300
        if disposition != "qualified":
            gaps.add(executor)
        entries.append(
            {
                "cleanup_owner": executor,
                "contract_sha256": contract_hashes.get(executor),
                "disposition": disposition,
                "executable_sha256": None,
                "executor": executor,
                "input_contract": input_contract,
                "kind": step.kind,
                "name": step.name,
                "order": step.order,
                "output_contract": output_contract,
                "owner_only_required": True,
                "readiness_bound": True,
                "target_class": plan["target_class"],
                "timeout_seconds": timeout_seconds,
                "verified_tls_required": True,
            }
        )
    operations: list[dict[str, Any]] = []
    raw_hash = contract_hashes["raw-oci"]
    for operation in topology["operations"]:
        owner = (
            "control-load"
            if operation in CONTROL_OPERATIONS
            else "raw-oci"
        )
        operations.append(
            {
                "contract_sha256": contract_hashes.get(owner, raw_hash),
                "disposition": "contract-only",
                "operation": operation,
                "owner": owner,
            }
        )
    manifest = {
        "entries": entries,
        "gaps": sorted(gaps),
        "operation_capabilities": operations,
        "pins_sha256": pins_sha256,
        "plan_sha256": envelope_value["plan_sha256"],
        "readiness_sha256": readiness_sha256,
        "ready": False,
        "schema": MANIFEST_SCHEMA,
        "step_count": len(entries),
        "synthetic": True,
        "target_class": plan["target_class"],
    }
    orchestrator.plan_contract.state_machine.validate_retained_evidence(
        manifest
    )
    return manifest


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
            or details.st_size > MAX_FILE_BYTES
        ):
            raise CommandError("local-file-unavailable")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(MAX_FILE_BYTES + 1)
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


def _canonical(payload: bytes, category: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"{category} is invalid") from error
    if (
        not isinstance(value, Mapping)
        or payload
        != (
            json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
    ):
        raise ManifestError(f"{category} is not canonical")
    return value


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


def _write_output(path: Path, value: object) -> None:
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


def compile_files(
    *,
    plan_path: Path,
    readiness_path: Path,
    pins_path: Path,
    topology_path: Path,
    output_path: Path,
) -> None:
    paths = [
        path.resolve(strict=False)
        for path in (
            plan_path,
            readiness_path,
            pins_path,
            topology_path,
            output_path,
        )
    ]
    if len(paths) != len(set(paths)):
        raise CommandError("contract-refused")
    _validate_output(output_path)
    plan_payload = _read_owner_file(plan_path)
    readiness_payload = _read_owner_file(readiness_path)
    pins_payload = _read_owner_file(pins_path)
    try:
        topology = orchestrator.plan_contract.state_machine.load_topology(
            topology_path
        )
        manifest = build_manifest(
            _canonical(plan_payload, "runtime load plan"),
            topology=topology,
            readiness_payload=readiness_payload,
            pins_payload=pins_payload,
        )
    except (
        ManifestError,
        orchestrator.OrchestratorError,
        orchestrator.plan_contract.PlanError,
        orchestrator.plan_contract.state_machine.LoadSoakError,
    ) as error:
        raise CommandError("contract-refused") from error
    _write_output(output_path, manifest)


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) != 10
        or arguments[0] != "--plan"
        or arguments[2] != "--readiness"
        or arguments[4] != "--pins"
        or arguments[6] != "--topology"
        or arguments[8] != "--output"
        or any(not arguments[index] for index in (1, 3, 5, 7, 9))
    ):
        print("load runtime manifest failed: invalid-arguments", file=stderr)
        return 2
    try:
        compile_files(
            plan_path=Path(arguments[1]),
            readiness_path=Path(arguments[3]),
            pins_path=Path(arguments[5]),
            topology_path=Path(arguments[7]),
            output_path=Path(arguments[9]),
        )
    except CommandError as error:
        print(
            f"load runtime manifest failed: {error.category}",
            file=stderr,
        )
        return 1
    print("load runtime manifest blocked", file=stdout)
    return 3


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
