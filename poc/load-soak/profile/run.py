from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Protocol, Sequence


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent
ORCHESTRATOR_PATH = LOAD_DIRECTORY / "orchestrator.py"
ORCHESTRATOR_SPEC = importlib.util.spec_from_file_location(
    "coffer_load_profile_orchestrator",
    ORCHESTRATOR_PATH,
)
if ORCHESTRATOR_SPEC is None or ORCHESTRATOR_SPEC.loader is None:
    raise RuntimeError("load orchestrator contract is unavailable")
orchestrator = importlib.util.module_from_spec(ORCHESTRATOR_SPEC)
sys.modules[ORCHESTRATOR_SPEC.name] = orchestrator
ORCHESTRATOR_SPEC.loader.exec_module(orchestrator)

INVOCATION_SCHEMA = "coffer.load-profile-invocation/v1"
STATE_SCHEMA = "coffer.load-profile-state/v1"
RESULT_SCHEMA = "coffer.load-profile-result/v1"
RAW_INVOCATION_SCHEMA = "coffer.raw-oci-invocation/v1"
RAW_RESULT_SCHEMA = "coffer.raw-oci-driver/v1"
CONTROL_INVOCATION_SCHEMA = "coffer.control-load-invocation/v1"
CONTROL_RESULT_SCHEMA = "coffer.control-load-execution/v1"
TARGET_CLASS = "disposable-stage6-pilot"
MAX_BINARY_BYTES = 256 * 1024 * 1024
MAX_CHILD_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 4096
SHA256 = orchestrator.plan_contract.SHA256
CommandError = orchestrator.CommandError
OPERATIONS = tuple(
    orchestrator.plan_contract.state_machine.load_topology(
        LOAD_DIRECTORY / "topology.json"
    )["operations"]
)
CONTROL_OPERATIONS = ("control", "token", "quota-contention")
RAW_OPERATION_MAP = {
    "manifest-read": {"manifest-get", "manifest-head"},
    "manifest-publish": {"manifest-publish"},
    "blob-read": {"blob-head", "blob-read-full", "blob-read-range"},
    "blob-monolithic": {"blob-monolithic"},
    "blob-resumable": {"blob-resumable"},
    "blob-cross-mount": {"blob-cross-mount"},
    "index": {"manifest-publish"},
    "artifact": {"artifact"},
    "abandoned-upload": {"abandoned-upload"},
}
RAW_KEYS = {
    "base_url",
    "ca_file",
    "chunk_bytes",
    "credential_file",
    "length_bytes",
    "manifest_file",
    "manifest_media_type",
    "max_attempts",
    "offset_bytes",
    "operation",
    "output_file",
    "readiness_file",
    "readiness_sha256",
    "reference",
    "repository",
    "schema",
    "seed",
    "size_bytes",
    "source_repository",
    "target_class",
    "timeout_seconds",
}
CONTROL_KEYS = {
    "ca_file",
    "contract_sha256",
    "control_base",
    "credential_file",
    "executable_sha256",
    "expected_quota",
    "expected_success",
    "identity_base",
    "manifest_sources",
    "max_concurrency",
    "output_file",
    "readiness_file",
    "readiness_sha256",
    "registry_base",
    "repository",
    "schema",
    "service",
    "target_class",
    "timeout_seconds",
}


class ProfileError(RuntimeError):
    pass


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class Job:
    binary: Path
    binary_sha256: str
    cleanup_scope: str
    contract_sha256: str
    executor: str
    invocation: Mapping[str, Any]
    invocation_file: Path
    invocation_sha256: str
    maximum_transfer_bytes: int
    operations: tuple[str, ...]


@dataclass(frozen=True)
class ChildTask:
    binary: Path
    expected_stdout: bytes
    invocation_file: Path
    job: Job
    output_file: Path


class BatchRunner(Protocol):
    def run(
        self,
        tasks: Sequence[ChildTask],
        *,
        timeout_seconds: int,
        work_root: Path,
    ) -> None: ...


def _exact(value: object, keys: set[str], category: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ProfileError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)[:-1]).hexdigest()


def _file_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _binary_hash(path: Path) -> str:
    if not path.is_absolute():
        raise ProfileError("child binary path is invalid")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_mode & 0o111 == 0
            or details.st_size < 1
            or details.st_size > MAX_BINARY_BYTES
        ):
            raise ProfileError("child binary is invalid")
        digest = hashlib.sha256()
        total = 0
        while total <= MAX_BINARY_BYTES:
            payload = os.read(
                descriptor,
                min(1024 * 1024, MAX_BINARY_BYTES + 1 - total),
            )
            if not payload:
                break
            digest.update(payload)
            total += len(payload)
        if total != details.st_size:
            raise ProfileError("child binary changed while reading")
    except ProfileError:
        raise
    except OSError as error:
        raise ProfileError("child binary is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _owner_directory(path: Path) -> None:
    if not path.is_absolute():
        raise CommandError("local-file-unavailable")
    try:
        details = path.lstat()
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_ISLNK(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise CommandError("local-file-unavailable")


def _child_document(
    payload: bytes,
    *,
    executor: str,
    binary_sha256: str,
    contract_sha256: str,
    operations: tuple[str, ...],
    readiness_sha256: str,
) -> Mapping[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError("child invocation is invalid") from error
    keys = RAW_KEYS if executor == "raw-oci" else CONTROL_KEYS
    document = _exact(value, keys, "child invocation")
    if (
        document["target_class"] != TARGET_CLASS
        or document["readiness_sha256"] != readiness_sha256
        or not isinstance(document["output_file"], str)
        or not Path(document["output_file"]).is_absolute()
    ):
        raise ProfileError("child invocation binding changed")
    if executor == "raw-oci":
        if (
            document["schema"] != RAW_INVOCATION_SCHEMA
            or len(operations) != 1
            or operations[0] not in RAW_OPERATION_MAP
            or document["operation"] not in RAW_OPERATION_MAP[operations[0]]
            or (
                operations[0] == "index"
                and document["manifest_media_type"]
                != "application/vnd.oci.image.index.v1+json"
            )
        ):
            raise ProfileError("raw child operation changed")
    elif (
        executor != "control-load"
        or document["schema"] != CONTROL_INVOCATION_SCHEMA
        or operations != CONTROL_OPERATIONS
        or document["executable_sha256"] != binary_sha256
        or document["contract_sha256"] != contract_sha256
    ):
        raise ProfileError("control child operation changed")
    return dict(document)


def _load_jobs(
    values: object,
    *,
    readiness_sha256: str,
) -> list[Job]:
    if not isinstance(values, list) or not 2 <= len(values) <= 64:
        raise ProfileError("profile jobs are invalid")
    jobs: list[Job] = []
    invocation_paths: set[Path] = set()
    operation_owners: dict[str, int] = {}
    for value in values:
        checked = _exact(
            value,
            {
                "binary",
                "binary_sha256",
                "cleanup_scope",
                "contract_sha256",
                "executor",
                "invocation_file",
                "invocation_sha256",
                "maximum_transfer_bytes",
                "operations",
            },
            "profile job",
        )
        executor = checked["executor"]
        operations_value = checked["operations"]
        if (
            executor not in ("raw-oci", "control-load")
            or not isinstance(operations_value, list)
            or not operations_value
            or any(
                not isinstance(operation, str)
                or operation not in OPERATIONS
                for operation in operations_value
            )
            or len(set(operations_value)) != len(operations_value)
            or checked["cleanup_scope"]
            not in ("invocation", "repository-teardown")
            or (
                executor == "control-load"
                and checked["cleanup_scope"] != "invocation"
            )
            or (
                executor == "raw-oci"
                and checked["cleanup_scope"] != "repository-teardown"
            )
            or not isinstance(checked["maximum_transfer_bytes"], int)
            or isinstance(checked["maximum_transfer_bytes"], bool)
            or not 0 <= checked["maximum_transfer_bytes"] <= 256 * 1024**2
        ):
            raise ProfileError("profile job is invalid")
        for key in (
            "binary_sha256",
            "contract_sha256",
            "invocation_sha256",
        ):
            if (
                not isinstance(checked[key], str)
                or SHA256.fullmatch(checked[key]) is None
            ):
                raise ProfileError("profile job evidence is invalid")
        binary = Path(str(checked["binary"]))
        invocation_file = Path(str(checked["invocation_file"]))
        if (
            not isinstance(checked["binary"], str)
            or not isinstance(checked["invocation_file"], str)
            or not binary.is_absolute()
            or not invocation_file.is_absolute()
        ):
            raise ProfileError("profile job path is invalid")
        resolved_invocation = invocation_file.resolve(strict=False)
        if resolved_invocation in invocation_paths:
            raise ProfileError("profile child invocation is reused")
        invocation_paths.add(resolved_invocation)
        if _binary_hash(binary) != checked["binary_sha256"]:
            raise ProfileError("profile child binary changed")
        try:
            payload = orchestrator._read_owner_file(invocation_file)
        except orchestrator.CommandError as error:
            raise ProfileError("profile child invocation is unsafe") from error
        assert payload is not None
        if _file_hash(payload) != checked["invocation_sha256"]:
            raise ProfileError("profile child invocation changed")
        operations = tuple(operations_value)
        document = _child_document(
            payload,
            executor=executor,
            binary_sha256=checked["binary_sha256"],
            contract_sha256=checked["contract_sha256"],
            operations=operations,
            readiness_sha256=readiness_sha256,
        )
        for operation in operations:
            operation_owners[operation] = operation_owners.get(operation, 0) + 1
        jobs.append(
            Job(
                binary=binary,
                binary_sha256=checked["binary_sha256"],
                cleanup_scope=checked["cleanup_scope"],
                contract_sha256=checked["contract_sha256"],
                executor=executor,
                invocation=document,
                invocation_file=invocation_file,
                invocation_sha256=checked["invocation_sha256"],
                maximum_transfer_bytes=checked["maximum_transfer_bytes"],
                operations=operations,
            )
        )
    if operation_owners != {operation: 1 for operation in OPERATIONS}:
        raise ProfileError("profile operation ownership changed")
    return jobs


def _signal_process_group(
    process: subprocess.Popen[bytes],
    requested_signal: signal.Signals,
) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, requested_signal)
    except ProcessLookupError:
        process.poll()
    except PermissionError as error:
        # On Darwin an exited, unreaped session leader can briefly return
        # EPERM rather than ESRCH for killpg(). Reap that exact Popen child;
        # a genuinely running process with an inaccessible group still fails
        # closed instead of being treated as terminated.
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired as timeout_error:
            raise ProfileError(
                "profile child termination failed"
            ) from timeout_error


def _terminate(processes: Sequence[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        _signal_process_group(process, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while any(process.poll() is None for process in processes):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    for process in processes:
        _signal_process_group(process, signal.SIGKILL)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise ProfileError(
                "profile child termination failed"
            ) from error


class SubprocessBatchRunner:
    def run(
        self,
        tasks: Sequence[ChildTask],
        *,
        timeout_seconds: int,
        work_root: Path,
    ) -> None:
        processes: list[subprocess.Popen[bytes]] = []
        streams: list[tuple[Any, Any, Path, Path]] = []
        try:
            for task in tasks:
                stdout_descriptor, stdout_name = tempfile.mkstemp(
                    prefix=".profile-stdout-",
                    dir=work_root,
                )
                os.fchmod(stdout_descriptor, 0o600)
                stdout_stream = os.fdopen(stdout_descriptor, "wb")
                try:
                    stderr_descriptor, stderr_name = tempfile.mkstemp(
                        prefix=".profile-stderr-",
                        dir=work_root,
                    )
                    os.fchmod(stderr_descriptor, 0o600)
                    stderr_stream = os.fdopen(stderr_descriptor, "wb")
                except OSError:
                    stdout_stream.close()
                    Path(stdout_name).unlink(missing_ok=True)
                    raise
                streams.append(
                    (
                        stdout_stream,
                        stderr_stream,
                        Path(stdout_name),
                        Path(stderr_name),
                    )
                )
                processes.append(
                    subprocess.Popen(
                        [
                            str(task.binary),
                            "--invocation",
                            str(task.invocation_file),
                        ],
                        cwd=work_root,
                        env={
                            "LANG": "C",
                            "LC_ALL": "C",
                            "PATH": "/usr/bin:/bin",
                        },
                        stdin=subprocess.DEVNULL,
                        stdout=stdout_stream,
                        stderr=stderr_stream,
                        start_new_session=True,
                    )
                )
            deadline = time.monotonic() + timeout_seconds
            while any(process.poll() is None for process in processes):
                if any(
                    stdout_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                    or stderr_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                    for _, _, stdout_path, stderr_path in streams
                ):
                    raise ProfileError("profile child output exceeded")
                if time.monotonic() >= deadline:
                    raise ProfileError("profile child timed out")
                time.sleep(0.02)
            for process, task, streams_for_process in zip(
                processes,
                tasks,
                streams,
            ):
                stdout_stream, stderr_stream, stdout_path, stderr_path = (
                    streams_for_process
                )
                stdout_stream.close()
                stderr_stream.close()
                if (
                    stdout_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                    or stderr_path.stat().st_size > MAX_PROCESS_OUTPUT_BYTES
                ):
                    raise ProfileError("profile child output exceeded")
                with stdout_path.open("rb") as stream:
                    stdout = stream.read(MAX_PROCESS_OUTPUT_BYTES + 1)
                with stderr_path.open("rb") as stream:
                    stderr = stream.read(MAX_PROCESS_OUTPUT_BYTES + 1)
                if (
                    process.returncode != 0
                    or stdout != task.expected_stdout
                    or stderr
                    or len(stdout) > MAX_PROCESS_OUTPUT_BYTES
                    or len(stderr) > MAX_PROCESS_OUTPUT_BYTES
                ):
                    raise ProfileError("profile child execution failed")
        except (OSError, subprocess.SubprocessError) as error:
            raise ProfileError("profile child execution failed") from error
        finally:
            _terminate(processes)
            for stdout_stream, stderr_stream, stdout_path, stderr_path in streams:
                if not stdout_stream.closed:
                    stdout_stream.close()
                if not stderr_stream.closed:
                    stderr_stream.close()
                stdout_path.unlink(missing_ok=True)
                stderr_path.unlink(missing_ok=True)


def _raw_result(value: object) -> int:
    document = _exact(
        value,
        {"duration_milliseconds", "operations", "schema"},
        "raw child result",
    )
    if (
        document["schema"] != RAW_RESULT_SCHEMA
        or not isinstance(document["duration_milliseconds"], int)
        or isinstance(document["duration_milliseconds"], bool)
        or document["duration_milliseconds"] < 0
        or not isinstance(document["operations"], list)
        or not document["operations"]
    ):
        raise ProfileError("raw child result is invalid")
    transferred = 0
    for value in document["operations"]:
        operation = _exact(
            value,
            {
                "attempts",
                "count",
                "digest_checks",
                "latency_buckets",
                "operation",
                "result",
                "retries",
                "transferred_bytes",
            },
            "raw operation result",
        )
        buckets_value = operation["latency_buckets"]
        if not isinstance(buckets_value, list) or len(buckets_value) != 10:
            raise ProfileError("raw latency buckets changed")
        buckets = [
            _exact(bucket, {"count", "name"}, "raw latency bucket")
            for bucket in buckets_value
        ]
        expected_bucket_names = [
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
        if (
            operation["result"] != "success"
            or not isinstance(operation["count"], int)
            or isinstance(operation["count"], bool)
            or operation["count"] < 1
            or not isinstance(operation["transferred_bytes"], int)
            or isinstance(operation["transferred_bytes"], bool)
            or operation["transferred_bytes"] < 0
            or not isinstance(operation["operation"], str)
            or not operation["operation"]
            or any(
                not isinstance(operation[key], int)
                or isinstance(operation[key], bool)
                or operation[key] < 0
                for key in (
                    "attempts",
                    "digest_checks",
                    "retries",
                )
            )
            or operation["attempts"] < operation["count"]
            or operation["retries"] > operation["attempts"]
            or [bucket["name"] for bucket in buckets]
            != expected_bucket_names
            or any(
                not isinstance(bucket["count"], int)
                or isinstance(bucket["count"], bool)
                or bucket["count"] < 0
                for bucket in buckets
            )
            or sum(bucket["count"] for bucket in buckets)
            != operation["count"]
        ):
            raise ProfileError("raw child operation failed")
        transferred += operation["transferred_bytes"]
    return transferred


def _control_result(
    value: object,
    *,
    job: Job,
    readiness_sha256: str,
) -> int:
    document = _exact(
        value,
        {
            "contract_sha256",
            "executable_sha256",
            "manifest_set_sha256",
            "readiness_sha256",
            "schema",
            "snapshot",
        },
        "control child result",
    )
    if (
        document["schema"] != CONTROL_RESULT_SCHEMA
        or document["contract_sha256"] != job.contract_sha256
        or document["executable_sha256"] != job.binary_sha256
        or document["readiness_sha256"] != readiness_sha256
        or not isinstance(document["manifest_set_sha256"], str)
        or SHA256.fullmatch(document["manifest_set_sha256"]) is None
    ):
        raise ProfileError("control child result changed")
    snapshot = _exact(
        document["snapshot"],
        {"duration_milliseconds", "results", "schema"},
        "control child snapshot",
    )
    if (
        snapshot["schema"] != "coffer.control-load-driver/v1"
        or not isinstance(snapshot["duration_milliseconds"], int)
        or isinstance(snapshot["duration_milliseconds"], bool)
        or snapshot["duration_milliseconds"] < 0
        or not isinstance(snapshot["results"], list)
        or not snapshot["results"]
    ):
        raise ProfileError("control child snapshot changed")
    expected_results = {
        ("control", "success"): 2,
        ("quota-contention", "success"): 1,
        ("token", "success"): 1,
    }
    actual_results: dict[tuple[str, str], int] = {}
    for value in snapshot["results"]:
        result = _exact(
            value,
            {"count", "operation", "result"},
            "control operation result",
        )
        if (
            result["result"] != "success"
            or not isinstance(result["count"], int)
            or isinstance(result["count"], bool)
            or result["count"] < 1
            or not isinstance(result["operation"], str)
        ):
            raise ProfileError("control child operation failed")
        actual_results[(result["operation"], result["result"])] = result[
            "count"
        ]
    if actual_results != expected_results:
        raise ProfileError("control child aggregate changed")
    return 0


def _read_child_result(
    task: ChildTask,
    *,
    readiness_sha256: str,
) -> int:
    try:
        payload = orchestrator._read_owner_file(task.output_file)
    except orchestrator.CommandError as error:
        raise ProfileError("profile child result is unavailable") from error
    assert payload is not None
    if len(payload) > MAX_CHILD_OUTPUT_BYTES:
        raise ProfileError("profile child result is too large")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProfileError("profile child result is invalid") from error
    if task.job.executor == "raw-oci":
        transferred = _raw_result(value)
    else:
        transferred = _control_result(
            value,
            job=task.job,
            readiness_sha256=readiness_sha256,
        )
    if transferred > task.job.maximum_transfer_bytes:
        raise ProfileError("profile child transfer exceeded")
    return transferred


def _profile_limits(
    plan: Mapping[str, Any],
    *,
    kind: str,
    name: str,
) -> tuple[int, int, int, int]:
    if kind == "profile":
        entries = [
            entry for entry in plan["profiles"] if entry["name"] == name
        ]
        if len(entries) != 1:
            raise ProfileError("profile step is unknown")
        entry = entries[0]
        return (
            entry["duration_seconds"],
            entry["steady_clients"],
            entry["burst_clients"],
            entry["transfer_ceiling_bytes"],
        )
    if kind != "ramp" or not name.startswith("clients-"):
        raise ProfileError("profile step kind is invalid")
    try:
        clients = int(name.removeprefix("clients-"))
    except ValueError as error:
        raise ProfileError("ramp client count is invalid") from error
    entries = [entry for entry in plan["ramp"] if entry["clients"] == clients]
    if len(entries) != 1:
        raise ProfileError("ramp step is unknown")
    entry = entries[0]
    return (
        entry["duration_seconds"],
        clients,
        clients,
        entry["transfer_ceiling_bytes"],
    )


def _concurrency(
    *,
    elapsed_seconds: int,
    duration_seconds: int,
    steady_clients: int,
    burst_clients: int,
) -> int:
    if (
        duration_seconds // 4
        <= elapsed_seconds
        < (duration_seconds * 3) // 4
    ):
        return burst_clients
    return steady_clients


def _binding(
    *,
    contract_sha256: str,
    execution_source: str,
    jobs: Sequence[Job],
    kind: str,
    name: str,
    order: int,
    plan_sha256: str,
) -> str:
    return _hash(
        {
            "contract_sha256": contract_sha256,
            "execution_source": execution_source,
            "jobs": [
                {
                    "binary_sha256": job.binary_sha256,
                    "cleanup_scope": job.cleanup_scope,
                    "contract_sha256": job.contract_sha256,
                    "executor": job.executor,
                    "invocation_sha256": job.invocation_sha256,
                    "maximum_transfer_bytes": job.maximum_transfer_bytes,
                    "operations": list(job.operations),
                }
                for job in jobs
            ],
            "kind": kind,
            "name": name,
            "order": order,
            "plan_sha256": plan_sha256,
        }
    )


def _new_state(
    *,
    binding_sha256: str,
    execution_source: str,
    plan_sha256: str,
) -> dict[str, Any]:
    return {
        "attempts": 0,
        "complete": False,
        "elapsed_seconds": 0,
        "execution_source": execution_source,
        "history": [],
        "last_wave_sha256": binding_sha256,
        "operation_counts": {operation: 0 for operation in OPERATIONS},
        "plan_sha256": plan_sha256,
        "profile_binding_sha256": binding_sha256,
        "schema": STATE_SCHEMA,
        "successful_operations": 0,
        "synthetic": execution_source == "fixture",
        "transferred_bytes": 0,
        "waves": 0,
    }


def _validate_state(
    value: object,
    *,
    binding_sha256: str,
    duration_seconds: int,
    execution_source: str,
    plan_sha256: str,
    transfer_ceiling_bytes: int,
) -> dict[str, Any]:
    state = dict(
        _exact(
            value,
            {
                "attempts",
                "complete",
                "elapsed_seconds",
                "execution_source",
                "history",
                "last_wave_sha256",
                "operation_counts",
                "plan_sha256",
                "profile_binding_sha256",
                "schema",
                "successful_operations",
                "synthetic",
                "transferred_bytes",
                "waves",
            },
            "profile state",
        )
    )
    counts = _exact(
        state["operation_counts"],
        set(OPERATIONS),
        "profile operation counts",
    )
    integers = (
        state["attempts"],
        state["elapsed_seconds"],
        state["successful_operations"],
        state["transferred_bytes"],
        state["waves"],
        *counts.values(),
    )
    if not isinstance(state["history"], list):
        raise ProfileError("profile history is invalid")
    expected_attempts = 0
    expected_elapsed = 0
    expected_counts = {operation: 0 for operation in OPERATIONS}
    expected_transferred = 0
    previous_sha256 = binding_sha256
    for index, entry_value in enumerate(state["history"], 1):
        entry = _exact(
            entry_value,
            {
                "attempts",
                "elapsed_seconds",
                "entry_sha256",
                "operation_counts",
                "previous_sha256",
                "sequence",
                "transferred_bytes",
            },
            "profile wave history",
        )
        entry_counts = _exact(
            entry["operation_counts"],
            set(OPERATIONS),
            "profile wave operation counts",
        )
        unsigned = {
            key: entry[key] for key in entry if key != "entry_sha256"
        }
        if (
            entry["sequence"] != index
            or entry["previous_sha256"] != previous_sha256
            or entry["entry_sha256"] != _hash(unsigned)
            or not isinstance(entry["attempts"], int)
            or isinstance(entry["attempts"], bool)
            or entry["attempts"] < 1
            or not isinstance(entry["elapsed_seconds"], int)
            or isinstance(entry["elapsed_seconds"], bool)
            or entry["elapsed_seconds"] < 1
            or not isinstance(entry["transferred_bytes"], int)
            or isinstance(entry["transferred_bytes"], bool)
            or entry["transferred_bytes"] < 0
            or any(
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
                for count in entry_counts.values()
            )
            or not entry["attempts"]
            <= sum(entry_counts.values())
            <= entry["attempts"] * 3
        ):
            raise ProfileError("profile wave history is invalid")
        expected_attempts += entry["attempts"]
        expected_elapsed = min(
            duration_seconds,
            expected_elapsed + entry["elapsed_seconds"],
        )
        expected_transferred += entry["transferred_bytes"]
        for operation, count in entry_counts.items():
            expected_counts[operation] += count
        previous_sha256 = entry["entry_sha256"]
    if (
        state["schema"] != STATE_SCHEMA
        or state["profile_binding_sha256"] != binding_sha256
        or state["plan_sha256"] != plan_sha256
        or state["execution_source"] != execution_source
        or state["synthetic"] != (execution_source == "fixture")
        or not isinstance(state["complete"], bool)
        or not isinstance(state["last_wave_sha256"], str)
        or SHA256.fullmatch(state["last_wave_sha256"]) is None
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item < 0
            for item in integers
        )
        or state["attempts"] != expected_attempts
        or state["successful_operations"] < state["attempts"]
        or state["successful_operations"] > state["attempts"] * 3
        or sum(counts.values()) != state["successful_operations"]
        or counts != expected_counts
        or state["elapsed_seconds"] != expected_elapsed
        or state["transferred_bytes"] != expected_transferred
        or state["waves"] != len(state["history"])
        or state["last_wave_sha256"] != previous_sha256
        or state["elapsed_seconds"] > duration_seconds
        or state["transferred_bytes"] > transfer_ceiling_bytes
        or state["complete"] != (
            state["elapsed_seconds"] == duration_seconds
            and all(count > 0 for count in counts.values())
        )
    ):
        raise ProfileError("profile state is invalid")
    return state


def _public_result(
    state: Mapping[str, Any],
    *,
    duration_seconds: int,
    kind: str,
    maximum_clients: int,
    name: str,
    order: int,
) -> dict[str, Any]:
    if state["complete"] is not True:
        raise ProfileError("profile state is incomplete")
    result = {
        "attempts": state["attempts"],
        "duration_seconds": duration_seconds,
        "execution_source": state["execution_source"],
        "kind": kind,
        "last_wave_sha256": state["last_wave_sha256"],
        "maximum_clients": maximum_clients,
        "name": name,
        "operation_counts": dict(state["operation_counts"]),
        "order": order,
        "plan_sha256": state["plan_sha256"],
        "profile_binding_sha256": state["profile_binding_sha256"],
        "schema": RESULT_SCHEMA,
        "successful_operations": state["successful_operations"],
        "synthetic": state["synthetic"],
        "transferred_bytes": state["transferred_bytes"],
        "unexpected_errors": 0,
        "waves": state["waves"],
    }
    orchestrator.plan_contract.state_machine.validate_retained_evidence(result)
    return result


def _prepare_tasks(
    *,
    concurrency: int,
    jobs: Sequence[Job],
    wave: int,
    work_root: Path,
) -> list[ChildTask]:
    raw_jobs = [job for job in jobs if job.executor == "raw-oci"]
    if len(raw_jobs) != len(RAW_OPERATION_MAP):
        raise ProfileError("raw profile job set changed")
    selected_jobs = [jobs[(wave - 1) % len(jobs)]]
    raw_cursor = (wave - 1) * max(1, concurrency - 1)
    for offset in range(concurrency - 1):
        selected_jobs.append(
            raw_jobs[(raw_cursor + offset) % len(raw_jobs)]
        )
    tasks: list[ChildTask] = []
    for slot, job in enumerate(selected_jobs):
        invocation_file = work_root / (
            f".profile-wave-{wave:06d}-{slot:03d}.invocation.json"
        )
        output_file = work_root / (
            f".profile-wave-{wave:06d}-{slot:03d}.result.json"
        )
        invocation = dict(job.invocation)
        invocation["output_file"] = str(output_file)
        orchestrator._atomic_json(invocation_file, invocation)
        tasks.append(
            ChildTask(
                binary=job.binary,
                expected_stdout=(
                    b"raw OCI driver completed\n"
                    if job.executor == "raw-oci"
                    else b"control load driver completed\n"
                ),
                invocation_file=invocation_file,
                job=job,
                output_file=output_file,
            )
        )
    return tasks


def _cleanup_tasks(tasks: Sequence[ChildTask]) -> None:
    for task in tasks:
        task.invocation_file.unlink(missing_ok=True)
        task.output_file.unlink(missing_ok=True)


def _assert_no_temporary_residue(work_root: Path) -> None:
    if any(
        path.name.startswith(
            (
                ".profile-wave-",
                ".profile-stdout-",
                ".profile-stderr-",
            )
        )
        for path in work_root.iterdir()
    ):
        raise ProfileError("profile temporary residue remains")


def execute_invocation(
    invocation_path: Path,
    *,
    clock: Clock | None = None,
    runner: BatchRunner | None = None,
    max_waves: int | None = None,
) -> bool:
    if (
        max_waves is not None
        and (
            not isinstance(max_waves, int)
            or isinstance(max_waves, bool)
            or max_waves < 0
        )
    ):
        raise CommandError("contract-refused")
    try:
        invocation_payload = orchestrator._read_owner_file(invocation_path)
        assert invocation_payload is not None
        invocation = _exact(
            orchestrator._canonical_document(
                invocation_payload,
                "profile invocation",
            ),
            {
                "contract_sha256",
                "execution_source",
                "jobs",
                "lock_file",
                "output_file",
                "plan_file",
                "plan_file_sha256",
                "schema",
                "state_file",
                "step",
                "target_class",
                "work_root",
            },
            "profile invocation",
        )
        if (
            invocation["schema"] != INVOCATION_SCHEMA
            or invocation["target_class"] != TARGET_CLASS
            or invocation["execution_source"] not in ("fixture", "pilot")
            or not isinstance(invocation["contract_sha256"], str)
            or SHA256.fullmatch(invocation["contract_sha256"]) is None
            or not isinstance(invocation["plan_file_sha256"], str)
            or SHA256.fullmatch(invocation["plan_file_sha256"]) is None
        ):
            raise ProfileError("profile invocation is invalid")
        step = _exact(
            invocation["step"],
            {"kind", "name", "order"},
            "profile step",
        )
        if (
            step["kind"] not in ("profile", "ramp")
            or not isinstance(step["name"], str)
            or not step["name"]
            or not isinstance(step["order"], int)
            or isinstance(step["order"], bool)
            or not 1 <= step["order"] <= 29
        ):
            raise ProfileError("profile step is invalid")
        for key in (
            "lock_file",
            "output_file",
            "plan_file",
            "state_file",
            "work_root",
        ):
            if (
                not isinstance(invocation[key], str)
                or not Path(invocation[key]).is_absolute()
            ):
                raise ProfileError("profile path is invalid")
        work_root = Path(invocation["work_root"])
        _owner_directory(work_root)
        plan_payload = orchestrator._read_owner_file(
            Path(invocation["plan_file"])
        )
        assert plan_payload is not None
        if _file_hash(plan_payload) != invocation["plan_file_sha256"]:
            raise ProfileError("profile plan file changed")
        envelope = orchestrator._canonical_document(
            plan_payload,
            "profile plan",
        )
        topology = orchestrator.plan_contract.state_machine.load_topology(
            LOAD_DIRECTORY / "topology.json"
        )
        plan = orchestrator._validate_envelope(envelope, topology)
        schedule = orchestrator.build_schedule(plan)
        matches = [
            candidate
            for candidate in schedule
            if candidate.kind == step["kind"]
            and candidate.name == step["name"]
            and candidate.order == step["order"]
        ]
        if len(matches) != 1:
            raise ProfileError("profile step does not match plan")
        duration, steady, burst, ceiling = _profile_limits(
            plan,
            kind=step["kind"],
            name=step["name"],
        )
        jobs = _load_jobs(
            invocation["jobs"],
            readiness_sha256=plan["bindings"]["readiness_evidence_hash"],
        )
        binding = _binding(
            contract_sha256=invocation["contract_sha256"],
            execution_source=invocation["execution_source"],
            jobs=jobs,
            kind=step["kind"],
            name=step["name"],
            order=step["order"],
            plan_sha256=envelope["plan_sha256"],
        )
        paths = [
            invocation_path.resolve(strict=False),
            work_root.resolve(strict=False),
            *[
                Path(invocation[key]).resolve(strict=False)
                for key in (
                    "lock_file",
                    "output_file",
                    "plan_file",
                    "state_file",
                )
            ],
            *[job.invocation_file.resolve(strict=False) for job in jobs],
        ]
        if len(paths) != len(set(paths)):
            raise ProfileError("profile paths overlap")
    except (
        orchestrator.CommandError,
        orchestrator.OrchestratorError,
        orchestrator.plan_contract.PlanError,
        orchestrator.plan_contract.state_machine.LoadSoakError,
        ProfileError,
    ) as error:
        raise CommandError("contract-refused") from error

    state_path = Path(invocation["state_file"])
    output_path = Path(invocation["output_file"])
    lock_path = Path(invocation["lock_file"])
    orchestrator._validate_owner_path(state_path)
    orchestrator._validate_owner_path(output_path, output=True)
    selected_clock = clock or RealClock()
    selected_runner = runner or SubprocessBatchRunner()
    with orchestrator._lock(lock_path):
        state_payload = orchestrator._read_owner_file(
            state_path,
            required=False,
        )
        try:
            state = (
                _new_state(
                    binding_sha256=binding,
                    execution_source=invocation["execution_source"],
                    plan_sha256=envelope["plan_sha256"],
                )
                if state_payload is None
                else _validate_state(
                    orchestrator._canonical_document(
                        state_payload,
                        "profile state",
                    ),
                    binding_sha256=binding,
                    duration_seconds=duration,
                    execution_source=invocation["execution_source"],
                    plan_sha256=envelope["plan_sha256"],
                    transfer_ceiling_bytes=ceiling,
                )
            )
            output_payload = orchestrator._read_owner_file(
                output_path,
                required=False,
            )
            expected_result = (
                _public_result(
                    state,
                    duration_seconds=duration,
                    kind=step["kind"],
                    maximum_clients=burst,
                    name=step["name"],
                    order=step["order"],
                )
                if state["complete"]
                else None
            )
            if output_payload is not None:
                if (
                    expected_result is None
                    or orchestrator._canonical_document(
                        output_payload,
                        "profile output",
                    )
                    != expected_result
                ):
                    raise ProfileError("profile output changed")
                return True
        except ProfileError as error:
            raise CommandError("contract-refused") from error

        waves_this_run = 0
        while not state["complete"]:
            if max_waves is not None and waves_this_run >= max_waves:
                break
            concurrency = _concurrency(
                elapsed_seconds=state["elapsed_seconds"],
                duration_seconds=duration,
                steady_clients=steady,
                burst_clients=burst,
            )
            tasks: list[ChildTask] = []
            started = selected_clock.monotonic()
            try:
                tasks = _prepare_tasks(
                    concurrency=concurrency,
                    jobs=jobs,
                    wave=state["waves"] + 1,
                    work_root=work_root,
                )
                selected_runner.run(
                    tasks,
                    timeout_seconds=min(duration + 600, 3 * 60 * 60),
                    work_root=work_root,
                )
                transfers = [
                    _read_child_result(
                        task,
                        readiness_sha256=plan["bindings"][
                            "readiness_evidence_hash"
                        ],
                    )
                    for task in tasks
                ]
                runtime = selected_clock.monotonic() - started
                if runtime < 1:
                    selected_clock.sleep(1 - runtime)
                elapsed_delta = max(
                    1,
                    int(selected_clock.monotonic() - started),
                )
                transferred = sum(transfers)
                if state["transferred_bytes"] + transferred > ceiling:
                    raise ProfileError("profile transfer ceiling exceeded")
                count_delta = {operation: 0 for operation in OPERATIONS}
                for task in tasks:
                    for operation in task.job.operations:
                        count_delta[operation] += 1
                wave_evidence = {
                    "attempts": len(tasks),
                    "elapsed_seconds": elapsed_delta,
                    "operation_counts": count_delta,
                    "previous_sha256": state["last_wave_sha256"],
                    "sequence": state["waves"] + 1,
                    "transferred_bytes": transferred,
                }
                wave_entry = {
                    **wave_evidence,
                    "entry_sha256": _hash(wave_evidence),
                }
                state["attempts"] += len(tasks)
                state["successful_operations"] += sum(count_delta.values())
                state["transferred_bytes"] += transferred
                state["waves"] += 1
                state["elapsed_seconds"] = min(
                    duration,
                    state["elapsed_seconds"] + elapsed_delta,
                )
                for operation, count in count_delta.items():
                    state["operation_counts"][operation] += count
                state["history"].append(wave_entry)
                state["last_wave_sha256"] = wave_entry["entry_sha256"]
                state["complete"] = (
                    state["elapsed_seconds"] == duration
                    and all(
                        count > 0
                        for count in state["operation_counts"].values()
                    )
                )
                state = _validate_state(
                    state,
                    binding_sha256=binding,
                    duration_seconds=duration,
                    execution_source=invocation["execution_source"],
                    plan_sha256=envelope["plan_sha256"],
                    transfer_ceiling_bytes=ceiling,
                )
                orchestrator._atomic_json(state_path, state)
                waves_this_run += 1
            except KeyboardInterrupt as error:
                raise CommandError("execution-unavailable") from error
            except (
                OSError,
                ProfileError,
                orchestrator.CommandError,
            ) as error:
                raise CommandError("execution-unavailable") from error
            finally:
                try:
                    _cleanup_tasks(tasks)
                    _assert_no_temporary_residue(work_root)
                except (OSError, ProfileError) as error:
                    raise CommandError("execution-unavailable") from error
        if state["complete"]:
            orchestrator._atomic_json(
                output_path,
                _public_result(
                    state,
                    duration_seconds=duration,
                    kind=step["kind"],
                    maximum_clients=burst,
                    name=step["name"],
                    order=step["order"],
                ),
                output=True,
            )
        return bool(state["complete"])


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
        print("load profile failed: invalid-arguments", file=stderr)
        return 2
    try:
        complete = execute_invocation(Path(arguments[1]))
    except CommandError as error:
        print(f"load profile failed: {error.category}", file=stderr)
        return 1
    except ProfileError:
        print("load profile failed: execution-unavailable", file=stderr)
        return 1
    if not complete:
        print("load profile failed: execution-unavailable", file=stderr)
        return 1
    try:
        invocation_payload = orchestrator._read_owner_file(Path(arguments[1]))
        if invocation_payload is None:
            raise ProfileError("profile invocation disappeared")
        invocation = orchestrator._canonical_document(
            invocation_payload,
            "profile invocation",
        )
        output_value = invocation.get("output_file")
        if not isinstance(output_value, str):
            raise ProfileError("profile output path changed")
        payload = orchestrator._read_owner_file(Path(output_value))
        if payload is None:
            raise ProfileError("profile output disappeared")
        result = orchestrator._canonical_document(payload, "profile output")
        if not isinstance(result.get("synthetic"), bool):
            raise ProfileError("profile output source changed")
    except (
        CommandError,
        orchestrator.OrchestratorError,
        ProfileError,
    ):
        print("load profile failed: execution-unavailable", file=stderr)
        return 1
    if result["synthetic"] is True:
        print("load profile fixture completed", file=stdout)
        return 3
    print("load profile completed", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
