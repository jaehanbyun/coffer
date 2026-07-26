from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
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


pilot_executor = _module(
    "coffer_stage6_pilot_phase_executor",
    DIRECTORY / "pilot_executor.py",
)
pilot_schedule = pilot_executor.pilot_schedule
rgw_live_adapter = pilot_schedule.rgw_live_adapter
control_artifacts = pilot_schedule.control_artifacts
render_target = pilot_schedule.render_target
native_target = pilot_schedule.native_target
phase_preparation = _module(
    "coffer_stage6_pilot_phase_preparation",
    DIRECTORY / "phase_preparation.py",
)
pilot_rgw_actions = _module(
    "coffer_stage6_pilot_phase_rgw_actions",
    DIRECTORY / "pilot_rgw_actions.py",
)

COLLECTOR_INPUT_SCHEMA = "coffer.stage6-pilot-collector-inputs/v1"
COMPLETION_SCHEMA = "coffer.stage6-pilot-phase-completion/v1"
SOURCE_RESULT_SCHEMA = "coffer.stage6-pilot-phase-actions-source-result/v1"
SUPPORTED_ACTIONS = frozenset(
    {
        "render-phase-preparation-request",
        "prepare-phase-atomically",
        "complete-phase",
    }
)
COLLECTOR_INPUT_NAMES = frozenset(
    {
        "control_baseline",
        "control_config",
        "control_current",
        "galera_config",
        "haproxy_config",
        "prometheus_config",
    }
)
SOURCE_FILES = (
    DIRECTORY / "local_artifacts.py",
    DIRECTORY / "control_artifacts.py",
    DIRECTORY / "galera_artifacts.py",
    DIRECTORY / "rgw_artifacts.py",
    DIRECTORY / "phase_preparation.py",
    DIRECTORY / "rgw_cleanup.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_rgw_actions.py",
    DIRECTORY / "pilot_phase_actions.py",
)


class PilotPhaseActionError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotPhaseActionError(f"{category} boundary changed")
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


def adapter_source_sha256() -> str:
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
        raise PilotPhaseActionError(
            "pilot phase action source is unavailable"
        ) from error
    return _hash({"files": files})


def _owner_document(
    path: Path,
    category: str,
) -> tuple[object, bytes, os.stat_result]:
    try:
        return control_artifacts._read_owner_document(path)
    except control_artifacts.ControlArtifactError as error:
        raise PilotPhaseActionError(f"{category} is unavailable") from error


def _descriptor(
    value: object,
    category: str,
) -> tuple[dict[str, str], object, os.stat_result]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    try:
        path = control_artifacts._absolute_path(
            raw["file"],
            f"{category} file",
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotPhaseActionError(f"{category} is invalid") from error
    document, payload, metadata = _owner_document(path, category)
    descriptor = {
        "file": str(path),
        "file_sha256": _payload_hash(payload),
    }
    if raw != descriptor:
        raise PilotPhaseActionError(f"{category} hash changed")
    return descriptor, document, metadata


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PilotPhaseActionError(
            "pilot phase action output is unavailable"
        ) from error


def _absent(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise PilotPhaseActionError(
            "pilot phase action output already exists"
        )
    try:
        metadata = path.parent.stat(follow_symlinks=False)
    except OSError as error:
        raise PilotPhaseActionError(
            "pilot phase action output parent is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise PilotPhaseActionError(
            "pilot phase action output parent is unsafe"
        )


def _phase_paths(
    schedule: Mapping[str, Any],
    phase: str,
) -> dict[str, Path]:
    root = Path(schedule["runtime_directory"]) / phase
    return {
        "cleanup": root / "rgw-cleanup.json",
        "cleanup_verification": root / "rgw-cleanup-verified.json",
        "collector_inputs": root / "collector-inputs.json",
        "completion": root / "phase-complete.json",
        "multipart": root / "rgw-multipart.json",
        "preparation_request": root / "phase-preparation-request.json",
        "preparation_result": root / "phase-evidence" / "result.json",
        "probe": root / "rgw-probe.json",
        "rgw_artifact_config": root / "rgw-artifact-config.json",
    }


def _collector_input_request(
    value: object,
    *,
    action: Mapping[str, Any],
    config: Mapping[str, Any],
    schedule: Mapping[str, Any],
    materialize_rgw_config: bool = False,
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "collector_inputs",
            "evidence_server",
            "materializer_source_sha256",
            "phase",
            "preparer_source_sha256",
            "schedule_sha256",
            "schema",
            "target",
            "window_sha256",
        },
        "pilot collector inputs",
    )
    phase = action["phase"]
    if (
        raw["schema"] != COLLECTOR_INPUT_SCHEMA
        or raw["materializer_source_sha256"] != adapter_source_sha256()
        or raw["preparer_source_sha256"]
        != phase_preparation.preparer_source_sha256()
        or raw["phase"] != phase
        or raw["schedule_sha256"] != schedule["schedule_sha256"]
        or raw["window_sha256"] != config["window_sha256"]
    ):
        raise PilotPhaseActionError(
            "pilot collector input binding changed"
        )
    target, target_value, target_metadata = _descriptor(
        raw["target"],
        "pilot collector native target",
    )
    try:
        validated_target, _ = control_artifacts._validated_target(
            target_value
        )
    except control_artifacts.ControlArtifactError as error:
        raise PilotPhaseActionError(
            "pilot collector target is invalid"
        ) from error
    if validated_target["target_sha256"] != config["target_sha256"]:
        raise PilotPhaseActionError(
            "pilot collector target changed"
        )
    inputs_raw = _exact(
        raw["collector_inputs"],
        COLLECTOR_INPUT_NAMES,
        "pilot collector input set",
    )
    inputs: dict[str, dict[str, str]] = {}
    metadata: list[tuple[Path, os.stat_result]] = [
        (Path(target["file"]), target_metadata)
    ]
    for name in sorted(inputs_raw):
        descriptor, _, details = _descriptor(
            inputs_raw[name],
            f"pilot collector {name.replace('_', ' ')}",
        )
        inputs[name] = descriptor
        metadata.append((Path(descriptor["file"]), details))
    paths = _phase_paths(schedule, phase)
    expected_faults = {
        result: sum(
            step["result"] == result for step in config["steps"]
        )
        for result in rgw_live_adapter.rgw_artifacts.FAULT_CLASSES
    }
    expected_rgw_config = {
        "bucket_scope_sha256": config["bucket_scope_sha256"],
        "collector_source_sha256": (
            rgw_live_adapter.rgw_artifacts.collector_source_sha256()
        ),
        "expected_fault_counts": expected_faults,
        "expected_operation_counts": config[
            "expected_operation_counts"
        ],
        "kms_policy_sha256": config["kms_policy_sha256"],
        "multipart_source_sha256": config[
            "multipart_source_sha256"
        ],
        "phase": phase,
        "probe_source_sha256": config["probe_source_sha256"],
        "rgw_config_sha256": config["rgw_config_sha256"],
        "schema": rgw_live_adapter.rgw_artifacts.CONFIG_SCHEMA,
        "target_file": target["file"],
        "target_file_sha256": target["file_sha256"],
        "window_completed_at_seconds": config[
            "window_completed_at_seconds"
        ],
        "window_sha256": config["window_sha256"],
        "window_started_at_seconds": config[
            "window_started_at_seconds"
        ],
    }
    rgw_config_path = paths["rgw_artifact_config"]
    if not rgw_config_path.exists() and not rgw_config_path.is_symlink():
        if not materialize_rgw_config:
            raise PilotPhaseActionError(
                "pilot RGW artifact configuration is unavailable"
            )
        _write(rgw_config_path, expected_rgw_config)
    rgw_config_value, rgw_config_payload, rgw_config_metadata = (
        _owner_document(
            rgw_config_path,
            "pilot collector RGW artifact configuration",
        )
    )
    if (
        rgw_config_value != expected_rgw_config
        or rgw_config_payload != _canonical(expected_rgw_config)
    ):
        raise PilotPhaseActionError(
            "pilot RGW artifact configuration changed"
        )
    inputs.update(
        {
            "rgw_config": {
                "file": str(rgw_config_path),
                "file_sha256": _payload_hash(rgw_config_payload),
            },
            "rgw_multipart": {
                "file": str(paths["multipart"]),
                "file_sha256": _payload_hash(
                    paths["multipart"].read_bytes()
                ),
            },
            "rgw_probe": {
                "file": str(paths["probe"]),
                "file_sha256": _payload_hash(paths["probe"].read_bytes()),
            },
        }
    )
    metadata.append((rgw_config_path, rgw_config_metadata))
    try:
        control_artifacts._distinct_inputs(metadata)
    except control_artifacts.ControlArtifactError as error:
        raise PilotPhaseActionError(
            "pilot collector inputs alias"
        ) from error
    request = {
        "collector_inputs": inputs,
        "evidence_server": raw["evidence_server"],
        "output_directory": str(paths["preparation_result"].parent),
        "phase": phase,
        "preparer_source_sha256": raw["preparer_source_sha256"],
        "schema": phase_preparation.REQUEST_SCHEMA,
        "target": target,
        "window_sha256": raw["window_sha256"],
    }
    try:
        phase_preparation._request(request)
    except (
        phase_preparation.PhasePreparationError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise PilotPhaseActionError(
            "pilot phase preparation request is invalid"
        ) from error
    return request


def _completion(
    *,
    action: Mapping[str, Any],
    config: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    paths = _phase_paths(schedule, action["phase"])
    try:
        phase_result = phase_preparation.prepare_file(
            paths["preparation_request"]
        )
        cleanup_value, _, _ = _owner_document(
            paths["cleanup"],
            "pilot phase cleanup",
        )
        verification_value, _, _ = _owner_document(
            paths["cleanup_verification"],
            "pilot phase cleanup verification",
        )
        verification = pilot_rgw_actions._validate_cleanup_verification(
            verification_value,
            config=config,
            cleanup_value=cleanup_value,
        )
    except (
        phase_preparation.PhasePreparationError,
        pilot_rgw_actions.PilotRgwActionError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        raise PilotPhaseActionError(
            "pilot phase completion evidence is invalid"
        ) from error
    if (
        Path(action["input_file"]) != paths["preparation_result"]
        or phase_result["complete"] is not True
        or phase_result["phase"] != action["phase"]
        or phase_result["target_sha256"] != config["target_sha256"]
        or phase_result["window_sha256"] != config["window_sha256"]
    ):
        raise PilotPhaseActionError(
            "pilot phase completion binding changed"
        )
    unsigned = {
        "bundle_sha256": phase_result["bundle_sha256"],
        "cleanup_verification_sha256": verification[
            "verification_sha256"
        ],
        "complete": True,
        "phase": action["phase"],
        "phase_result_sha256": phase_result["result_sha256"],
        "schedule_sha256": schedule["schedule_sha256"],
        "schema": COMPLETION_SCHEMA,
        "target_sha256": config["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "completion_sha256": _hash(unsigned)}


def _validate_completion(
    value: object,
    *,
    action: Mapping[str, Any],
    config: Mapping[str, Any],
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "bundle_sha256",
            "cleanup_verification_sha256",
            "complete",
            "completion_sha256",
            "phase",
            "phase_result_sha256",
            "schedule_sha256",
            "schema",
            "target_sha256",
            "window_sha256",
        },
        "pilot phase completion",
    )
    expected = _completion(
        action=action,
        config=config,
        schedule=schedule,
    )
    if raw != expected:
        raise PilotPhaseActionError(
            "pilot phase completion changed"
        )
    return dict(raw)


class PilotPhaseActionAdapter:
    name = "pilot-phase"
    synthetic = False

    def __init__(
        self,
        *,
        schedule_directory: Path,
        schedule: Mapping[str, Any],
    ) -> None:
        self.schedule_directory = schedule_directory
        self.schedule = schedule

    @classmethod
    def load(
        cls,
        schedule_directory: Path,
        readiness_path: Path,
    ) -> PilotPhaseActionAdapter:
        try:
            schedule_directory = control_artifacts._absolute_path(
                str(schedule_directory),
                "pilot phase schedule directory",
            )
            schedule, _ = pilot_executor._schedule_output(
                schedule_directory,
                readiness_path,
            )
        except (
            control_artifacts.ControlArtifactError,
            pilot_executor.PilotExecutorError,
        ) as error:
            raise PilotPhaseActionError(
                "pilot phase adapter inputs are unavailable"
            ) from error
        return cls(
            schedule_directory=schedule_directory,
            schedule=schedule,
        )

    def _action(
        self,
        value: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw = dict(
            _exact(
                value,
                pilot_schedule.ACTION_KEYS,
                "pilot phase action",
            )
        )
        order = raw["order"]
        if (
            not isinstance(order, int)
            or isinstance(order, bool)
            or not 1 <= order <= len(self.schedule["actions"])
            or raw != self.schedule["actions"][order - 1]
            or raw["action"] not in SUPPORTED_ACTIONS
        ):
            raise PilotPhaseActionError(
                "pilot phase action is unsupported"
            )
        config_path = (
            self.schedule_directory
            / pilot_schedule.PHASE_CONFIG_FILES[raw["phase"]]
        )
        if Path(raw["config_file"]) != config_path:
            raise PilotPhaseActionError(
                "pilot phase action configuration changed"
            )
        try:
            config, _, _ = rgw_live_adapter._read_config(config_path)
        except rgw_live_adapter.RgwLiveAdapterError as error:
            raise PilotPhaseActionError(
                "pilot phase action configuration changed"
            ) from error
        return raw, config

    def _validate_output(
        self,
        action: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> None:
        output = Path(action["output_file"])
        kind = action["action"]
        if kind == "render-phase-preparation-request":
            value, payload, _ = _owner_document(
                Path(action["input_file"]),
                "pilot collector inputs",
            )
            expected = _collector_input_request(
                value,
                action=action,
                config=config,
                schedule=self.schedule,
            )
            actual, actual_payload, _ = _owner_document(
                output,
                "pilot phase preparation request",
            )
            if actual != expected or actual_payload != _canonical(expected):
                raise PilotPhaseActionError(
                    "pilot phase preparation request changed"
                )
            if payload != _canonical(value):
                raise PilotPhaseActionError(
                    "pilot collector inputs are not canonical"
                )
        elif kind == "prepare-phase-atomically":
            request_value, _, _ = _owner_document(
                Path(action["input_file"]),
                "pilot phase preparation request",
            )
            request = _exact(
                request_value,
                {
                    "collector_inputs",
                    "evidence_server",
                    "output_directory",
                    "phase",
                    "preparer_source_sha256",
                    "schema",
                    "target",
                    "window_sha256",
                },
                "pilot phase preparation request",
            )
            try:
                result = phase_preparation.prepare_file(
                    Path(action["input_file"])
                )
            except (
                phase_preparation.PhasePreparationError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                raise PilotPhaseActionError(
                    "pilot phase preparation failed"
                ) from error
            if (
                output
                != Path(request["output_directory"]) / "result.json"
                or output.name != "result.json"
                or output.parent
                != Path(self.schedule["runtime_directory"])
                / action["phase"]
                / "phase-evidence"
            ):
                raise PilotPhaseActionError(
                    "pilot phase preparation output changed"
                )
            value, payload, _ = _owner_document(
                output,
                "pilot phase preparation result",
            )
            if value != result or payload != _canonical(result):
                raise PilotPhaseActionError(
                    "pilot phase preparation result changed"
                )
        elif kind == "complete-phase":
            value, payload, _ = _owner_document(
                output,
                "pilot phase completion",
            )
            completion = _validate_completion(
                value,
                action=action,
                config=config,
                schedule=self.schedule,
            )
            if payload != _canonical(completion):
                raise PilotPhaseActionError(
                    "pilot phase completion is not canonical"
                )
        else:
            raise PilotPhaseActionError(
                "pilot phase action is unsupported"
            )

    def execute(
        self,
        action_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        action, config = self._action(action_value)
        output = Path(action["output_file"])
        kind = action["action"]
        if kind == "render-phase-preparation-request":
            _absent(output)
            value, payload, _ = _owner_document(
                Path(action["input_file"]),
                "pilot collector inputs",
            )
            if payload != _canonical(value):
                raise PilotPhaseActionError(
                    "pilot collector inputs are not canonical"
                )
            _write(
                output,
                _collector_input_request(
                    value,
                action=action,
                config=config,
                schedule=self.schedule,
                materialize_rgw_config=True,
            ),
            )
        elif kind == "prepare-phase-atomically":
            if output.exists() or output.is_symlink():
                raise PilotPhaseActionError(
                    "pilot phase action output already exists"
                )
            request_value, _, _ = _owner_document(
                Path(action["input_file"]),
                "pilot phase preparation request",
            )
            request = _exact(
                request_value,
                {
                    "collector_inputs",
                    "evidence_server",
                    "output_directory",
                    "phase",
                    "preparer_source_sha256",
                    "schema",
                    "target",
                    "window_sha256",
                },
                "pilot phase preparation request",
            )
            try:
                result = phase_preparation.prepare_file(
                    Path(action["input_file"])
                )
            except (
                phase_preparation.PhasePreparationError,
                OSError,
                RuntimeError,
                ValueError,
            ) as error:
                raise PilotPhaseActionError(
                    "pilot phase preparation failed"
                ) from error
            if output != Path(request["output_directory"]) / "result.json":
                raise PilotPhaseActionError(
                    "pilot phase preparation output changed"
                )
            if result["complete"] is not True:
                raise PilotPhaseActionError(
                    "pilot phase preparation did not complete"
                )
        elif kind == "complete-phase":
            _absent(output)
            _write(
                output,
                _completion(
                    action=action,
                    config=config,
                    schedule=self.schedule,
                ),
            )
        else:
            raise PilotPhaseActionError(
                "pilot phase action is unsupported"
            )
        self._validate_output(action, config)
        return pilot_executor._result_for(
            action,
            adapter_name=self.name,
            synthetic=self.synthetic,
        )

    def reconcile(
        self,
        action_value: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        action, config = self._action(action_value)
        output = Path(action["output_file"])
        if not output.exists() and not output.is_symlink():
            return None
        self._validate_output(action, config)
        return pilot_executor._result_for(
            action,
            adapter_name=self.name,
            synthetic=self.synthetic,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments != ["source-hash"]:
        print("pilot-phase-actions-refused", file=sys.stderr)
        return 2
    try:
        source_hash = adapter_source_sha256()
    except PilotPhaseActionError:
        print("pilot-phase-actions-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "adapter_source_sha256": source_hash,
                "schema": SOURCE_RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
