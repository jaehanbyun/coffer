from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent
ROOT_DIRECTORY = DIRECTORY.parents[2]
TOPOLOGY_PATH = LOAD_DIRECTORY / "topology.json"


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


rgw_live_adapter = _module(
    "coffer_stage6_pilot_schedule_rgw",
    DIRECTORY / "rgw_live_adapter.py",
)
control_artifacts = rgw_live_adapter.control_artifacts
render_target = control_artifacts.render_target
plan_contract = _module(
    "coffer_stage6_pilot_schedule_plan",
    LOAD_DIRECTORY / "plan.py",
)
native_target = rgw_live_adapter.native_target

REQUEST_SCHEMA = "coffer.stage6-pilot-schedule-request/v1"
SCHEDULE_SCHEMA = "coffer.stage6-pilot-schedule/v1"
RESULT_SCHEMA = "coffer.stage6-pilot-schedule-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.stage6-pilot-schedule-source-result/v1"
READINESS_SCHEMA = "coffer.upstream-readiness/v1"
QUALIFIED_STATUS = "candidate-qualified"
PHASE_CONFIG_FILES = {
    phase: f"{phase}-rgw-live-config.json"
    for phase in native_target.PHASES
}
RETAINED_FILES = (
    *PHASE_CONFIG_FILES.values(),
    "schedule.json",
)
OUTPUT_FILES = frozenset((*RETAINED_FILES, "result.json"))
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "pilot_schedule.py",
    LOAD_DIRECTORY / "plan.py",
    LOAD_DIRECTORY / "state_machine.py",
    TOPOLOGY_PATH,
)
COMPONENT_KEYS = {
    "distribution": frozenset(
        {
            "baseline",
            "latest_stable",
            "published_at",
            "reasons",
            "revision",
            "status",
            "url",
            "verified_release_commit",
        }
    ),
    "ceph": frozenset(
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
        }
    ),
}
ACTION_KEYS = frozenset(
    {
        "action",
        "config_file",
        "fault_evidence_sha256",
        "input_file",
        "order",
        "output_file",
        "phase",
        "step_index",
    }
)


class PilotScheduleError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotScheduleError(f"{category} boundary changed")
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


def renderer_source_sha256() -> str:
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
        raise PilotScheduleError(
            "pilot schedule source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise PilotScheduleError(f"{category} is invalid")
    return value


def _owner_document(
    value: object,
    category: str,
) -> tuple[dict[str, str], object, bytes, os.stat_result]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    try:
        path = control_artifacts._absolute_path(
            raw["file"],
            f"{category} file",
        )
        payload, metadata = control_artifacts._read_owner_bytes(
            path,
            maximum_bytes=1024 * 1024,
        )
        document = json.loads(payload)
    except (
        control_artifacts.ControlArtifactError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise PilotScheduleError(f"{category} is unavailable") from error
    supplied = _sha256(raw["file_sha256"], f"{category} file hash")
    if supplied != _payload_hash(payload):
        raise PilotScheduleError(f"{category} file changed")
    return (
        {"file": str(path), "file_sha256": supplied},
        document,
        payload,
        metadata,
    )


def _owner_bytes_descriptor(
    value: object,
    category: str,
) -> tuple[dict[str, str], os.stat_result]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    try:
        path = control_artifacts._absolute_path(
            raw["file"],
            f"{category} file",
        )
        payload, metadata = control_artifacts._read_owner_bytes(
            path,
            maximum_bytes=64 * 1024,
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotScheduleError(f"{category} is unavailable") from error
    supplied = _sha256(raw["file_sha256"], f"{category} file hash")
    if supplied != _payload_hash(payload):
        raise PilotScheduleError(f"{category} file changed")
    return {"file": str(path), "file_sha256": supplied}, metadata


def _safe_new_directory(value: object, category: str) -> Path:
    try:
        path = control_artifacts._absolute_path(value, category)
        parent = path.parent.stat(follow_symlinks=False)
    except (control_artifacts.ControlArtifactError, OSError) as error:
        raise PilotScheduleError(f"{category} is unavailable") from error
    if (
        path.name in {"", ".", ".."}
        or not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.getuid()
    ):
        raise PilotScheduleError(f"{category} is unsafe")
    return path


def _readiness(value: object) -> dict[str, Any]:
    raw = _exact(
        value,
        {"ceph", "distribution", "schema", "status"},
        "upstream readiness",
    )
    if raw["schema"] != READINESS_SCHEMA or raw["status"] != QUALIFIED_STATUS:
        raise PilotScheduleError("released dependencies are not qualified")
    components: dict[str, dict[str, Any]] = {}
    for name in ("distribution", "ceph"):
        component = _exact(
            raw[name],
            COMPONENT_KEYS[name],
            f"{name} readiness",
        )
        reasons = component["reasons"]
        if (
            component["status"] != QUALIFIED_STATUS
            or reasons != []
            or not isinstance(component["latest_stable"], str)
            or not isinstance(component["revision"], str)
            or plan_contract.REVISION.fullmatch(component["revision"])
            is None
        ):
            raise PilotScheduleError(
                f"{name} released dependency is not qualified"
            )
        components[name] = dict(component)
    if (
        components["distribution"]["verified_release_commit"] is not True
        or components["ceph"]["fix_merged_to_tentacle"] is not True
        or components["ceph"]["fix_in_latest_stable"] is not True
    ):
        raise PilotScheduleError("released dependency provenance changed")
    return {
        "ceph": components["ceph"],
        "distribution": components["distribution"],
        "schema": READINESS_SCHEMA,
        "status": QUALIFIED_STATUS,
    }


def _load_plan(value: object) -> dict[str, Any]:
    envelope = _exact(
        value,
        {"plan", "plan_sha256", "schema", "synthetic"},
        "load plan envelope",
    )
    plan = envelope["plan"]
    if (
        envelope["schema"] != plan_contract.ENVELOPE_SCHEMA
        or envelope["synthetic"] is not True
        or not isinstance(plan, Mapping)
        or envelope["plan_sha256"] != plan_contract._hash(plan)
    ):
        raise PilotScheduleError("load plan envelope changed")
    try:
        topology = plan_contract.state_machine.load_topology(TOPOLOGY_PATH)
        expected = plan_contract.compile_plan(
            {
                "bindings": plan["bindings"],
                "schema": plan_contract.REQUEST_SCHEMA,
                "topology_sha256": plan["topology_sha256"],
            },
            topology=topology,
        )
    except (
        KeyError,
        plan_contract.PlanError,
        plan_contract.state_machine.LoadSoakError,
    ) as error:
        raise PilotScheduleError("load plan is not qualified") from error
    if expected != envelope:
        raise PilotScheduleError("load plan envelope changed")
    return json.loads(json.dumps(envelope, separators=(",", ":")))


def _target(value: object) -> dict[str, Any]:
    try:
        target, _ = control_artifacts._validated_target(value)
    except control_artifacts.ControlArtifactError as error:
        raise PilotScheduleError("native target is invalid") from error
    return target


def _window(value: object, phase: str) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "window_completed_at_seconds",
            "window_sha256",
            "window_started_at_seconds",
        },
        f"{phase} window",
    )
    started = rgw_live_adapter._number(
        raw["window_started_at_seconds"],
        f"{phase} window start",
    )
    completed = rgw_live_adapter._number(
        raw["window_completed_at_seconds"],
        f"{phase} window completion",
    )
    if started >= completed:
        raise PilotScheduleError(f"{phase} window order changed")
    return {
        "window_completed_at_seconds": completed,
        "window_sha256": _sha256(
            raw["window_sha256"],
            f"{phase} window hash",
        ),
        "window_started_at_seconds": started,
    }


def _steps(
    phase: str,
    fault_hashes: Mapping[str, str],
) -> list[dict[str, str]]:
    steps = [
        {
            "fault_evidence_sha256": (
                rgw_live_adapter.NO_FAULT_SHA256
            ),
            "operation": operation,
            "result": "success",
        }
        for operation in rgw_live_adapter.HEALTHY_OPERATION_ORDER
    ]
    if phase == "during":
        steps.extend(
            [
                {
                    "fault_evidence_sha256": fault_hashes["wrong_key"],
                    "operation": "put_zero",
                    "result": "expected_wrong_key",
                },
                {
                    "fault_evidence_sha256": (
                        rgw_live_adapter.NO_FAULT_SHA256
                    ),
                    "operation": "put_zero",
                    "result": "success",
                },
                {
                    "fault_evidence_sha256": fault_hashes["kms_outage"],
                    "operation": "put_positive",
                    "result": "expected_kms_outage",
                },
                {
                    "fault_evidence_sha256": (
                        rgw_live_adapter.NO_FAULT_SHA256
                    ),
                    "operation": "put_positive",
                    "result": "success",
                },
            ]
        )
    return steps


def _request(
    value: object,
) -> tuple[dict[str, Any], list[tuple[Path, os.stat_result]]]:
    raw = _exact(
        value,
        {
            "fault_evidence_sha256",
            "load_plan",
            "output_directory",
            "readiness",
            "renderer_source_sha256",
            "rgw",
            "runtime_directory",
            "schema",
            "target",
            "windows",
        },
        "pilot schedule request",
    )
    if (
        raw["schema"] != REQUEST_SCHEMA
        or raw["renderer_source_sha256"] != renderer_source_sha256()
    ):
        raise PilotScheduleError("pilot schedule request binding changed")
    readiness_descriptor, readiness_value, readiness_payload, readiness_stat = (
        _owner_document(raw["readiness"], "upstream readiness")
    )
    readiness = _readiness(readiness_value)
    plan_descriptor, plan_value, _, plan_stat = _owner_document(
        raw["load_plan"],
        "load plan",
    )
    envelope = _load_plan(plan_value)
    target_descriptor, target_value, _, target_stat = _owner_document(
        raw["target"],
        "native target",
    )
    target = _target(target_value)
    bindings = envelope["plan"]["bindings"]
    if (
        bindings["readiness_status"] != "qualified"
        or bindings["readiness_evidence_hash"]
        != _payload_hash(readiness_payload)
        or bindings["distribution_version"]
        != readiness["distribution"]["latest_stable"]
        or bindings["distribution_revision"]
        != readiness["distribution"]["revision"]
        or bindings["ceph_version"] != readiness["ceph"]["latest_stable"]
        or bindings["ceph_revision"] != readiness["ceph"]["revision"]
    ):
        raise PilotScheduleError(
            "load plan and released qualification diverged"
        )
    rgw = _exact(
        raw["rgw"],
        {
            "bucket",
            "bucket_scope_sha256",
            "ca_file",
            "endpoint",
            "kms_policy_sha256",
            "max_pages",
            "probe_prefix_root",
            "region",
            "rgw_config_sha256",
            "timeout_seconds",
        },
        "pilot RGW settings",
    )
    ca_descriptor, ca_stat = _owner_bytes_descriptor(
        rgw["ca_file"],
        "RGW CA",
    )
    faults_raw = _exact(
        raw["fault_evidence_sha256"],
        {"kms_outage", "wrong_key"},
        "fault evidence hashes",
    )
    fault_hashes = {
        name: _sha256(value, f"{name} fault evidence hash")
        for name, value in faults_raw.items()
    }
    if (
        len(set(fault_hashes.values())) != 2
        or rgw_live_adapter.NO_FAULT_SHA256 in fault_hashes.values()
    ):
        raise PilotScheduleError("fault evidence binding changed")
    windows_raw = _exact(
        raw["windows"],
        set(native_target.PHASES),
        "pilot phase windows",
    )
    windows = {
        phase: _window(windows_raw[phase], phase)
        for phase in native_target.PHASES
    }
    if any(
        left["window_completed_at_seconds"]
        >= right["window_started_at_seconds"]
        for left, right in zip(
            (windows[phase] for phase in native_target.PHASES),
            (windows[phase] for phase in native_target.PHASES[1:]),
        )
    ):
        raise PilotScheduleError("pilot phase windows overlap")
    output = _safe_new_directory(
        raw["output_directory"],
        "pilot schedule output directory",
    )
    runtime = _safe_new_directory(
        raw["runtime_directory"],
        "pilot runtime directory",
    )
    if (
        output == runtime
        or output in runtime.parents
        or runtime in output.parents
        or runtime.exists()
        or runtime.is_symlink()
    ):
        raise PilotScheduleError("pilot runtime directory is unsafe")
    metadata = [
        (Path(readiness_descriptor["file"]), readiness_stat),
        (Path(plan_descriptor["file"]), plan_stat),
        (Path(target_descriptor["file"]), target_stat),
        (Path(ca_descriptor["file"]), ca_stat),
    ]
    try:
        control_artifacts._distinct_inputs(metadata)
    except control_artifacts.ControlArtifactError as error:
        raise PilotScheduleError("pilot schedule inputs alias") from error
    return (
        {
            "fault_evidence_sha256": fault_hashes,
            "load_plan": plan_descriptor,
            "output_directory": str(output),
            "readiness": readiness_descriptor,
            "readiness_evidence_sha256": _payload_hash(readiness_payload),
            "renderer_source_sha256": renderer_source_sha256(),
            "rgw": {
                "bucket": rgw["bucket"],
                "bucket_scope_sha256": rgw["bucket_scope_sha256"],
                "ca_file": ca_descriptor,
                "endpoint": rgw["endpoint"],
                "kms_policy_sha256": rgw["kms_policy_sha256"],
                "max_pages": rgw["max_pages"],
                "probe_prefix_root": rgw["probe_prefix_root"],
                "region": rgw["region"],
                "rgw_config_sha256": rgw["rgw_config_sha256"],
                "timeout_seconds": rgw["timeout_seconds"],
            },
            "runtime_directory": str(runtime),
            "schema": REQUEST_SCHEMA,
            "target": target_descriptor,
            "target_sha256": target["target_sha256"],
            "windows": windows,
        },
        metadata,
    )


def _phase_config(
    request: Mapping[str, Any],
    phase: str,
) -> dict[str, Any]:
    rgw = request["rgw"]
    steps = _steps(phase, request["fault_evidence_sha256"])
    counts = {
        operation: sum(step["operation"] == operation for step in steps)
        for operation in rgw_live_adapter.rgw_artifacts.OPERATION_CLASSES
    }
    config = {
        "adapter_source_sha256": (
            rgw_live_adapter.adapter_source_sha256()
        ),
        "bucket": rgw["bucket"],
        "bucket_scope_sha256": rgw["bucket_scope_sha256"],
        "ca_file": rgw["ca_file"]["file"],
        "ca_file_sha256": rgw["ca_file"]["file_sha256"],
        "endpoint": rgw["endpoint"],
        "expected_operation_counts": counts,
        "kms_policy_sha256": rgw["kms_policy_sha256"],
        "max_pages": rgw["max_pages"],
        "multipart_source_sha256": (
            rgw_live_adapter.adapter_source_sha256()
        ),
        "phase": phase,
        "probe_prefix": f"{str(rgw['probe_prefix_root']).rstrip('/')}/{phase}",
        "probe_source_sha256": (
            rgw_live_adapter.adapter_source_sha256()
        ),
        "region": rgw["region"],
        "rgw_config_sha256": rgw["rgw_config_sha256"],
        "schema": rgw_live_adapter.CONFIG_SCHEMA,
        "steps": steps,
        "target_sha256": request["target_sha256"],
        "timeout_seconds": rgw["timeout_seconds"],
        **request["windows"][phase],
    }
    try:
        return rgw_live_adapter._config(config)
    except rgw_live_adapter.RgwLiveAdapterError as error:
        raise PilotScheduleError("pilot RGW settings are invalid") from error


def _action(
    *,
    action: str,
    config_file: Path,
    fault_hash: str,
    input_file: Path,
    order: int,
    output_file: Path,
    phase: str,
    step_index: int = -1,
) -> dict[str, Any]:
    return {
        "action": action,
        "config_file": str(config_file),
        "fault_evidence_sha256": fault_hash,
        "input_file": str(input_file),
        "order": order,
        "output_file": str(output_file),
        "phase": phase,
        "step_index": step_index,
    }


def _schedule(
    request: Mapping[str, Any],
    configs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    runtime = Path(request["runtime_directory"])
    output = Path(request["output_directory"])
    actions: list[dict[str, Any]] = []

    def append(
        phase: str,
        action: str,
        *,
        input_file: Path,
        output_file: Path,
        step_index: int = -1,
        fault_hash: str = rgw_live_adapter.NO_FAULT_SHA256,
    ) -> None:
        actions.append(
            _action(
                action=action,
                config_file=output / PHASE_CONFIG_FILES[phase],
                fault_hash=fault_hash,
                input_file=input_file,
                order=len(actions) + 1,
                output_file=output_file,
                phase=phase,
                step_index=step_index,
            )
        )

    for phase in native_target.PHASES:
        phase_runtime = runtime / phase
        config_file = output / PHASE_CONFIG_FILES[phase]
        append(
            phase,
            "open-phase",
            input_file=config_file,
            output_file=phase_runtime,
        )
        for index in range(len(rgw_live_adapter.HEALTHY_OPERATION_ORDER)):
            append(
                phase,
                "collect-rgw-step",
                input_file=config_file,
                output_file=phase_runtime / f"rgw-step-{index}.json",
                step_index=index,
            )
        if phase == "during":
            fault_sequence = (
                (
                    "wrong-key",
                    7,
                    8,
                    request["fault_evidence_sha256"]["wrong_key"],
                ),
                (
                    "kms-outage",
                    9,
                    10,
                    request["fault_evidence_sha256"]["kms_outage"],
                ),
            )
            for name, fault_index, recovery_index, evidence_hash in (
                fault_sequence
            ):
                append(
                    phase,
                    f"apply-{name}",
                    input_file=config_file,
                    output_file=phase_runtime / f"apply-{name}.json",
                    fault_hash=evidence_hash,
                )
                append(
                    phase,
                    "collect-rgw-step",
                    input_file=config_file,
                    output_file=(
                        phase_runtime / f"rgw-step-{fault_index}.json"
                    ),
                    step_index=fault_index,
                    fault_hash=evidence_hash,
                )
                append(
                    phase,
                    f"recover-{name}",
                    input_file=phase_runtime / f"apply-{name}.json",
                    output_file=phase_runtime / f"recover-{name}.json",
                )
                append(
                    phase,
                    "collect-rgw-step",
                    input_file=config_file,
                    output_file=(
                        phase_runtime / f"rgw-step-{recovery_index}.json"
                    ),
                    step_index=recovery_index,
                )
        step_files = [
            phase_runtime / f"rgw-step-{index}.json"
            for index in range(len(configs[phase]["steps"]))
        ]
        append(
            phase,
            "compile-rgw-probe",
            input_file=phase_runtime / "rgw-step-set.json",
            output_file=phase_runtime / "rgw-probe.json",
        )
        append(
            phase,
            "collect-rgw-multipart",
            input_file=config_file,
            output_file=phase_runtime / "rgw-multipart.json",
        )
        append(
            phase,
            "cleanup-rgw-prefix",
            input_file=config_file,
            output_file=phase_runtime / "rgw-cleanup.json",
        )
        append(
            phase,
            "verify-rgw-cleanup",
            input_file=phase_runtime / "rgw-cleanup.json",
            output_file=phase_runtime / "rgw-cleanup-verified.json",
        )
        append(
            phase,
            "render-phase-preparation-request",
            input_file=phase_runtime / "collector-inputs.json",
            output_file=phase_runtime / "phase-preparation-request.json",
        )
        append(
            phase,
            "prepare-phase-atomically",
            input_file=phase_runtime / "phase-preparation-request.json",
            output_file=phase_runtime / "phase-evidence" / "result.json",
        )
        append(
            phase,
            "complete-phase",
            input_file=phase_runtime / "phase-evidence" / "result.json",
            output_file=phase_runtime / "phase-complete.json",
        )
        if len(step_files) != len(configs[phase]["steps"]):
            raise PilotScheduleError("RGW step output set changed")
    schedule = {
        "action_count": len(actions),
        "actions": actions,
        "cleanup_contract": {
            phase: {
                "probe_prefix": configs[phase]["probe_prefix"],
                "require_zero_multipart_uploads": True,
                "require_zero_objects": True,
            }
            for phase in native_target.PHASES
        },
        "credential_environment": [
            rgw_live_adapter.ACCESS_KEY_ENVIRONMENT,
            rgw_live_adapter.SECRET_KEY_ENVIRONMENT,
            rgw_live_adapter.KMS_KEY_ENVIRONMENT,
        ],
        "execution_source": "pilot",
        "load_plan_file_sha256": request["load_plan"]["file_sha256"],
        "readiness_evidence_sha256": request[
            "readiness_evidence_sha256"
        ],
        "runtime_directory": request["runtime_directory"],
        "schema": SCHEDULE_SCHEMA,
        "synthetic": False,
        "target_sha256": request["target_sha256"],
    }
    return {**schedule, "schedule_sha256": _hash(schedule)}


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PilotScheduleError(
            "pilot schedule output is unavailable"
        ) from error


def _compile(
    request: Mapping[str, Any],
    staging: Path,
) -> dict[str, Any]:
    configs = {
        phase: _phase_config(request, phase)
        for phase in native_target.PHASES
    }
    for phase, config in configs.items():
        _write(staging / PHASE_CONFIG_FILES[phase], config)
    schedule = _schedule(request, configs)
    _write(staging / "schedule.json", schedule)
    files = {
        name: _payload_hash((staging / name).read_bytes())
        for name in RETAINED_FILES
    }
    result = {
        "complete": True,
        "execution_source": "pilot",
        "files_sha256": files,
        "readiness_evidence_sha256": request[
            "readiness_evidence_sha256"
        ],
        "renderer_source_sha256": request["renderer_source_sha256"],
        "request_file_sha256": request["request_file_sha256"],
        "schedule_sha256": schedule["schedule_sha256"],
        "schema": RESULT_SCHEMA,
        "synthetic": False,
        "target_sha256": request["target_sha256"],
    }
    result["result_sha256"] = _hash(result)
    _write(staging / "result.json", result)
    return result


def _validate_existing(
    request: Mapping[str, Any],
    output: Path,
) -> dict[str, Any]:
    try:
        metadata = output.stat(follow_symlinks=False)
        names = {item.name for item in output.iterdir()}
    except OSError as error:
        raise PilotScheduleError(
            "pilot schedule output is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or names != set(OUTPUT_FILES)
    ):
        raise PilotScheduleError("pilot schedule output is unsafe")
    values: dict[str, object] = {}
    payloads: dict[str, bytes] = {}
    file_metadata: list[tuple[Path, os.stat_result]] = []
    for name in OUTPUT_FILES:
        path = output / name
        try:
            value, payload, details = (
                control_artifacts._read_owner_document(path)
            )
        except control_artifacts.ControlArtifactError as error:
            raise PilotScheduleError(
                "pilot schedule output changed"
            ) from error
        if payload != _canonical(value):
            raise PilotScheduleError("pilot schedule output changed")
        values[name] = value
        payloads[name] = payload
        file_metadata.append((path, details))
    try:
        control_artifacts._distinct_inputs(file_metadata)
    except control_artifacts.ControlArtifactError as error:
        raise PilotScheduleError("pilot schedule outputs alias") from error
    result = _exact(
        values["result.json"],
        {
            "complete",
            "execution_source",
            "files_sha256",
            "readiness_evidence_sha256",
            "renderer_source_sha256",
            "request_file_sha256",
            "result_sha256",
            "schedule_sha256",
            "schema",
            "synthetic",
            "target_sha256",
        },
        "pilot schedule result",
    )
    unsigned = {
        key: value for key, value in result.items() if key != "result_sha256"
    }
    if (
        result["schema"] != RESULT_SCHEMA
        or result["complete"] is not True
        or result["execution_source"] != "pilot"
        or result["synthetic"] is not False
        or result["renderer_source_sha256"]
        != request["renderer_source_sha256"]
        or result["request_file_sha256"]
        != request["request_file_sha256"]
        or result["readiness_evidence_sha256"]
        != request["readiness_evidence_sha256"]
        or result["target_sha256"] != request["target_sha256"]
        or result["result_sha256"] != _hash(unsigned)
    ):
        raise PilotScheduleError("pilot schedule result changed")
    files = _exact(
        result["files_sha256"],
        set(RETAINED_FILES),
        "pilot schedule retained files",
    )
    if any(
        _sha256(files[name], f"{name} hash")
        != _payload_hash(payloads[name])
        for name in RETAINED_FILES
    ):
        raise PilotScheduleError("pilot schedule retained file changed")
    schedule = _exact(
        values["schedule.json"],
        {
            "action_count",
            "actions",
            "cleanup_contract",
            "credential_environment",
            "execution_source",
            "load_plan_file_sha256",
            "readiness_evidence_sha256",
            "runtime_directory",
            "schedule_sha256",
            "schema",
            "synthetic",
            "target_sha256",
        },
        "pilot schedule",
    )
    schedule_unsigned = {
        key: value
        for key, value in schedule.items()
        if key != "schedule_sha256"
    }
    if (
        schedule["schema"] != SCHEDULE_SCHEMA
        or schedule["action_count"] != len(schedule["actions"])
        or schedule["schedule_sha256"] != _hash(schedule_unsigned)
        or schedule["schedule_sha256"] != result["schedule_sha256"]
        or set(schedule["cleanup_contract"]) != set(native_target.PHASES)
        or any(
            cleanup
            != {
                "probe_prefix": (
                    values[PHASE_CONFIG_FILES[phase]]["probe_prefix"]
                ),
                "require_zero_multipart_uploads": True,
                "require_zero_objects": True,
            }
            for phase, cleanup in schedule["cleanup_contract"].items()
        )
        or any(
            set(action) != set(ACTION_KEYS)
            for action in schedule["actions"]
        )
    ):
        raise PilotScheduleError("pilot schedule changed")
    for phase, filename in PHASE_CONFIG_FILES.items():
        try:
            checked = rgw_live_adapter._config(values[filename])
        except rgw_live_adapter.RgwLiveAdapterError as error:
            raise PilotScheduleError(
                "pilot phase configuration changed"
            ) from error
        if checked["phase"] != phase:
            raise PilotScheduleError(
                "pilot phase configuration changed"
            )
    return json.loads(
        json.dumps(result, separators=(",", ":"), sort_keys=True)
    )


def _remove_created(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise PilotScheduleError(
            "pilot schedule cleanup failed"
        ) from error


def render_file(request_path: Path) -> dict[str, Any]:
    try:
        request_path = control_artifacts._absolute_path(
            str(request_path),
            "pilot schedule request",
        )
        request_value, request_payload, request_stat = (
            control_artifacts._read_owner_document(request_path)
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotScheduleError(
            "pilot schedule request is unavailable"
        ) from error
    if request_payload != _canonical(request_value):
        raise PilotScheduleError("pilot schedule request changed")
    request, input_metadata = _request(request_value)
    request["request_file_sha256"] = _payload_hash(request_payload)
    try:
        control_artifacts._distinct_inputs(
            [(request_path, request_stat), *input_metadata]
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotScheduleError("pilot schedule inputs alias") from error
    output = Path(request["output_directory"])
    if output.exists() or output.is_symlink():
        return _validate_existing(request, output)
    try:
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.pilot-schedule.",
                dir=output.parent,
            )
        )
        staging.chmod(0o700)
    except OSError as error:
        raise PilotScheduleError(
            "pilot schedule staging is unavailable"
        ) from error
    published = False
    try:
        result = _compile(request, staging)
        os.replace(staging, output)
        published = True
        directory = os.open(
            output.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        validated = _validate_existing(request, output)
        if validated != result:
            raise PilotScheduleError(
                "pilot schedule publication changed"
            )
        return validated
    except BaseException:
        if published and output.exists() and not staging.exists():
            try:
                os.replace(output, staging)
            except OSError as error:
                raise PilotScheduleError(
                    "pilot schedule rollback failed"
                ) from error
        _remove_created(staging)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_hash = renderer_source_sha256()
        except PilotScheduleError:
            print("pilot-schedule-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "renderer_source_sha256": source_hash,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 2 or arguments[0] != "render":
        print("pilot-schedule-refused", file=sys.stderr)
        return 2
    try:
        result = render_file(Path(arguments[1]))
    except (
        PilotScheduleError,
        control_artifacts.ControlArtifactError,
        rgw_live_adapter.RgwLiveAdapterError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("pilot-schedule-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "result_sha256": result["result_sha256"],
                "schedule_sha256": result["schedule_sha256"],
                "schema": RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
