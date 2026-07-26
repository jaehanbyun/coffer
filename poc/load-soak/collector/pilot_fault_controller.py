from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


DIRECTORY = Path(__file__).resolve().parent
ROOT_DIRECTORY = DIRECTORY.parents[2]


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


pilot_fault_actions = _module(
    "coffer_stage6_pilot_command_fault_actions",
    DIRECTORY / "pilot_fault_actions.py",
)
control_artifacts = pilot_fault_actions.control_artifacts
native_target = pilot_fault_actions.pilot_schedule.native_target

CONFIG_SCHEMA = "coffer.stage6-pilot-fault-command-config/v1"
OBSERVATION_SCHEMA = (
    "coffer.stage6-pilot-fault-command-observation/v1"
)
ABSENT_SCHEMA = (
    "coffer.stage6-pilot-fault-command-observation-absent/v1"
)
SOURCE_RESULT_SCHEMA = (
    "coffer.stage6-pilot-fault-command-source-result/v1"
)
MAX_OUTPUT_BYTES = 32 * 1024
MAX_ARGUMENTS = 16
MAX_ARGUMENT_BYTES = 4096
MAX_TIMEOUT_SECONDS = 300
COMMANDS = frozenset(
    {
        "apply-kms-outage",
        "apply-wrong-key",
        "observe-kms-outage",
        "observe-wrong-key",
        "recover-kms-outage",
        "recover-wrong-key",
    }
)
ARGUMENT = re.compile(r"^[A-Za-z0-9._:/-]{1,256}$")
FORBIDDEN_ARGUMENT = re.compile(
    r"(?:^|[-_])(password|secret|token|credential)(?:$|[-_])",
    re.IGNORECASE,
)
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_fault_actions.py",
    DIRECTORY / "pilot_fault_controller.py",
)


class PilotFaultControllerError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotFaultControllerError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def controller_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": str(path.relative_to(ROOT_DIRECTORY)),
                    "sha256": _payload_hash(path.read_bytes()),
                }
            )
    except OSError as error:
        raise PilotFaultControllerError(
            "pilot fault controller source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise PilotFaultControllerError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise PilotFaultControllerError(f"{category} is invalid")
    return value


def _executable(
    value: object,
    category: str,
) -> tuple[dict[str, str], os.stat_result]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    try:
        path = control_artifacts._absolute_path(
            raw["file"],
            f"{category} file",
        )
        payload = path.read_bytes()
        metadata = path.stat(follow_symlinks=False)
    except (control_artifacts.ControlArtifactError, OSError) as error:
        raise PilotFaultControllerError(
            f"{category} is unavailable"
        ) from error
    supplied_hash = _sha256(
        raw["file_sha256"],
        f"{category} file hash",
    )
    if (
        supplied_hash != _payload_hash(payload)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) not in {0o500, 0o700}
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise PilotFaultControllerError(f"{category} changed")
    return {
        "file": str(path),
        "file_sha256": supplied_hash,
    }, metadata


def _command(value: object, category: str) -> dict[str, Any]:
    raw = _exact(value, {"argv", "executable"}, category)
    executable, _ = _executable(raw["executable"], category)
    argv = raw["argv"]
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= MAX_ARGUMENTS
        or any(
            not isinstance(argument, str)
            or ARGUMENT.fullmatch(argument) is None
            or FORBIDDEN_ARGUMENT.search(argument) is not None
            for argument in argv
        )
        or sum(len(argument.encode("utf-8")) for argument in argv)
        > MAX_ARGUMENT_BYTES
        or argv[0] != executable["file"]
    ):
        raise PilotFaultControllerError(f"{category} argv changed")
    return {
        "argv": list(argv),
        "executable": executable,
    }


def _configuration(value: object) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "commands",
            "controller_source_sha256",
            "name",
            "schema",
            "timeout_seconds",
        },
        "pilot fault controller configuration",
    )
    commands_raw = _exact(
        raw["commands"],
        COMMANDS,
        "pilot fault command set",
    )
    name = raw["name"]
    if (
        raw["schema"] != CONFIG_SCHEMA
        or raw["controller_source_sha256"]
        != controller_source_sha256()
        or not isinstance(name, str)
        or not name
        or len(name) > 128
        or ARGUMENT.fullmatch(name) is None
    ):
        raise PilotFaultControllerError(
            "pilot fault controller binding changed"
        )
    return {
        "commands": {
            name: _command(
                commands_raw[name],
                f"{name} pilot fault command",
            )
            for name in sorted(COMMANDS)
        },
        "controller_source_sha256": controller_source_sha256(),
        "name": name,
        "schema": CONFIG_SCHEMA,
        "timeout_seconds": _integer(
            raw["timeout_seconds"],
            "pilot fault command timeout",
            minimum=1,
            maximum=MAX_TIMEOUT_SECONDS,
        ),
    }


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired as timeout_error:
            raise PilotFaultControllerError(
                "pilot fault command termination failed"
            ) from timeout_error
        if process.poll() is None:
            raise PilotFaultControllerError(
                "pilot fault command termination failed"
            ) from error
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired as error:
        raise PilotFaultControllerError(
            "pilot fault command termination failed"
        ) from error


def _run(
    argv: Sequence[str],
    *,
    environment: Mapping[str, str],
    timeout_seconds: int,
) -> bytes:
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    streams: dict[str, bytearray] = {
        "stderr": bytearray(),
        "stdout": bytearray(),
    }
    failure: str | None = None
    dependency_error: BaseException | None = None
    try:
        process = subprocess.Popen(
            list(argv),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + timeout_seconds
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "pilot fault command timed out"
                break
            events = selector.select(min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in tuple(selector.get_map().values())
                ]
            for key, _ in events:
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output = streams[key.data]
                if len(output) + len(chunk) > MAX_OUTPUT_BYTES:
                    failure = "pilot fault command output exceeded"
                    break
                output.extend(chunk)
            if failure is not None:
                break
        if failure is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "pilot fault command timed out"
            else:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    failure = "pilot fault command timed out"
    except (OSError, subprocess.SubprocessError) as error:
        failure = "pilot fault command failed"
        dependency_error = error
    finally:
        selector.close()
        if process is not None and process.poll() is None:
            _terminate(process)
    if failure is not None:
        if dependency_error is not None:
            raise PilotFaultControllerError(failure) from dependency_error
        raise PilotFaultControllerError(failure)
    assert process is not None
    if process.returncode != 0 or streams["stderr"]:
        raise PilotFaultControllerError("pilot fault command failed")
    return bytes(streams["stdout"])


def _observation(
    payload: bytes,
    *,
    evidence_sha256: str,
    fault: str,
    state: str,
    allow_absent: bool,
) -> pilot_fault_actions.FaultObservation | None:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PilotFaultControllerError(
            "pilot fault command observation is invalid"
        ) from error
    if payload != _canonical(value):
        raise PilotFaultControllerError(
            "pilot fault command observation is not canonical"
        )
    if isinstance(value, Mapping) and value.get("schema") == ABSENT_SCHEMA:
        raw = _exact(
            value,
            {
                "evidence_sha256",
                "fault",
                "observation_sha256",
                "observed",
                "schema",
                "state",
            },
            "pilot absent fault observation",
        )
        unsigned = {
            key: raw[key]
            for key in raw
            if key != "observation_sha256"
        }
        if (
            not allow_absent
            or raw["observed"] is not False
            or raw["fault"] != fault
            or raw["state"] != state
            or raw["evidence_sha256"] != evidence_sha256
            or raw["observation_sha256"] != _hash(unsigned)
        ):
            raise PilotFaultControllerError(
                "pilot absent fault observation changed"
            )
        return None
    raw = _exact(
        value,
        {
            "completed_at_seconds",
            "evidence_sha256",
            "fault",
            "observation_sha256",
            "schema",
            "started_at_seconds",
            "state",
        },
        "pilot fault command observation",
    )
    unsigned = {
        key: raw[key] for key in raw if key != "observation_sha256"
    }
    try:
        started = pilot_fault_actions.rgw_live_adapter._number(
            raw["started_at_seconds"],
            "pilot fault observation start",
        )
        completed = pilot_fault_actions.rgw_live_adapter._number(
            raw["completed_at_seconds"],
            "pilot fault observation completion",
        )
    except pilot_fault_actions.rgw_live_adapter.RgwLiveAdapterError as error:
        raise PilotFaultControllerError(
            "pilot fault command observation time changed"
        ) from error
    if (
        raw["schema"] != OBSERVATION_SCHEMA
        or started > completed
        or raw["fault"] != fault
        or raw["state"] != state
        or raw["evidence_sha256"] != evidence_sha256
        or raw["observation_sha256"] != _hash(unsigned)
    ):
        raise PilotFaultControllerError(
            "pilot fault command observation changed"
        )
    return pilot_fault_actions.FaultObservation(
        completed_at_seconds=completed,
        evidence_sha256=evidence_sha256,
        fault=fault,
        started_at_seconds=started,
        state=state,
    )


class CommandFaultController:
    def __init__(self, configuration: Mapping[str, Any]) -> None:
        self.configuration = dict(configuration)
        self.name = str(configuration["name"])
        self.source_sha256 = str(
            configuration["controller_source_sha256"]
        )

    @classmethod
    def load(cls, path: Path) -> CommandFaultController:
        try:
            value, _, _ = control_artifacts._read_owner_document(path)
        except control_artifacts.ControlArtifactError as error:
            raise PilotFaultControllerError(
                "pilot fault controller configuration is unavailable"
            ) from error
        return cls(_configuration(value))

    def _invoke(
        self,
        operation: str,
        fault: str,
        state: str,
        evidence_sha256: str,
        *,
        allow_absent: bool,
    ) -> pilot_fault_actions.FaultObservation | None:
        if (
            fault not in pilot_fault_actions.FAULTS
            or state not in pilot_fault_actions.STATES
            or operation not in {"apply", "observe", "recover"}
        ):
            raise PilotFaultControllerError(
                "pilot fault command request changed"
            )
        evidence_sha256 = _sha256(
            evidence_sha256,
            "pilot fault evidence hash",
        )
        command = self.configuration["commands"][
            f"{operation}-{fault}"
        ]
        payload = _run(
            command["argv"],
            environment={
                "COFFER_PILOT_FAULT": fault,
                "COFFER_PILOT_FAULT_EVIDENCE_SHA256": evidence_sha256,
                "COFFER_PILOT_FAULT_OPERATION": operation,
                "COFFER_PILOT_FAULT_STATE": state,
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": "/usr/bin:/bin",
            },
            timeout_seconds=self.configuration["timeout_seconds"],
        )
        return _observation(
            payload,
            evidence_sha256=evidence_sha256,
            fault=fault,
            state=state,
            allow_absent=allow_absent,
        )

    def apply(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> pilot_fault_actions.FaultObservation:
        observation = self._invoke(
            "apply",
            fault,
            "applied",
            evidence_sha256,
            allow_absent=False,
        )
        if observation is None:
            raise PilotFaultControllerError(
                "pilot fault apply was not observed"
            )
        return observation

    def recover(
        self,
        fault: str,
        evidence_sha256: str,
    ) -> pilot_fault_actions.FaultObservation:
        observation = self._invoke(
            "recover",
            fault,
            "recovered",
            evidence_sha256,
            allow_absent=False,
        )
        if observation is None:
            raise PilotFaultControllerError(
                "pilot fault recovery was not observed"
            )
        return observation

    def observe(
        self,
        fault: str,
        state: str,
        evidence_sha256: str,
    ) -> pilot_fault_actions.FaultObservation | None:
        return self._invoke(
            "observe",
            fault,
            state,
            evidence_sha256,
            allow_absent=True,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["source-hash"]:
        print("pilot-fault-controller-refused", file=sys.stderr)
        return 2
    try:
        source_hash = controller_source_sha256()
    except PilotFaultControllerError:
        print("pilot-fault-controller-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "controller_source_sha256": source_hash,
                "schema": SOURCE_RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
