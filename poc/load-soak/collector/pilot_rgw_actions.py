from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable, Mapping, Sequence


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
    "coffer_stage6_pilot_rgw_executor",
    DIRECTORY / "pilot_executor.py",
)
pilot_schedule = pilot_executor.pilot_schedule
rgw_live_adapter = pilot_schedule.rgw_live_adapter
rgw_cleanup = _module(
    "coffer_stage6_pilot_rgw_cleanup",
    DIRECTORY / "rgw_cleanup.py",
)
control_artifacts = rgw_live_adapter.control_artifacts
render_target = pilot_schedule.render_target
native_target = pilot_schedule.native_target

VERIFICATION_SCHEMA = "coffer.load-rgw-prefix-cleanup-verification/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-pilot-rgw-actions-source-result/v1"
SUPPORTED_ACTIONS = frozenset(
    {
        "open-phase",
        "collect-rgw-step",
        "compile-rgw-probe",
        "collect-rgw-multipart",
        "cleanup-rgw-prefix",
        "verify-rgw-cleanup",
    }
)
SOURCE_FILES = (
    DIRECTORY / "rgw_live_adapter.py",
    DIRECTORY / "rgw_cleanup.py",
    DIRECTORY / "pilot_schedule.py",
    DIRECTORY / "pilot_executor.py",
    DIRECTORY / "pilot_rgw_actions.py",
)


class PilotRgwActionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RgwRuntimeClients:
    cleanup: rgw_cleanup.CleanupClient
    evidence: rgw_live_adapter.EvidenceClient


ClientFactory = Callable[[Mapping[str, Any]], RgwRuntimeClients]


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PilotRgwActionError(f"{category} boundary changed")
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
        raise PilotRgwActionError(
            "pilot RGW action source is unavailable"
        ) from error
    return _hash({"files": files})


def default_client_factory(
    config: Mapping[str, Any],
) -> RgwRuntimeClients:
    evidence = rgw_live_adapter.boto3_client(config)
    return RgwRuntimeClients(
        cleanup=rgw_cleanup.Boto3CleanupClient(
            client=evidence.client,
            bucket=evidence.bucket,
        ),
        evidence=evidence,
    )


def _owner_document(
    path: Path,
    category: str,
) -> tuple[object, bytes]:
    try:
        value, payload, _ = control_artifacts._read_owner_document(path)
    except control_artifacts.ControlArtifactError as error:
        raise PilotRgwActionError(f"{category} is unavailable") from error
    return value, payload


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PilotRgwActionError(
            "pilot RGW action output is unavailable"
        ) from error


def _phase_directory(path: Path) -> None:
    try:
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise PilotRgwActionError(
            "pilot RGW phase directory is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise PilotRgwActionError(
            "pilot RGW phase directory is unsafe"
        )


def _runtime_directory(
    schedule: Mapping[str, Any],
) -> Path:
    path = Path(schedule["runtime_directory"])
    try:
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
        metadata = path.stat(follow_symlinks=False)
        children = list(path.iterdir())
    except OSError as error:
        raise PilotRgwActionError(
            "pilot RGW runtime is unavailable"
        ) from error
    allowed = {
        *pilot_executor.RUNTIME_FILES,
        *native_target.PHASES,
    }
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or any(child.name not in allowed for child in children)
    ):
        raise PilotRgwActionError("pilot RGW runtime is unsafe")
    for child in children:
        if child.name in native_target.PHASES:
            _phase_directory(child)
    return path


def _absent(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise PilotRgwActionError("pilot RGW action output already exists")
    _phase_directory(path.parent)


def _cleanup_verification(
    cleanup_value: object,
    *,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        cleaned = rgw_cleanup.validate_result(
            cleanup_value,
            config_value=config,
        )
    except rgw_cleanup.RgwCleanupError as error:
        raise PilotRgwActionError(
            "pilot RGW cleanup result changed"
        ) from error
    unsigned = {
        "cleanup_sha256": cleaned["cleanup_sha256"],
        "phase": config["phase"],
        "schema": VERIFICATION_SCHEMA,
        "target_sha256": config["target_sha256"],
        "verified": True,
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "verification_sha256": _hash(unsigned)}


def _validate_cleanup_verification(
    value: object,
    *,
    config: Mapping[str, Any],
    cleanup_value: object,
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "cleanup_sha256",
            "phase",
            "schema",
            "target_sha256",
            "verification_sha256",
            "verified",
            "window_sha256",
        },
        "RGW cleanup verification",
    )
    expected = _cleanup_verification(cleanup_value, config=config)
    if raw != expected:
        raise PilotRgwActionError(
            "pilot RGW cleanup verification changed"
        )
    return dict(raw)


@dataclass
class PilotRgwActionAdapter:
    schedule_directory: Path
    schedule: Mapping[str, Any]
    clients: Mapping[str, RgwRuntimeClients]
    clock: rgw_live_adapter.Clock = time.time
    name: str = "pilot-rgw"
    synthetic: bool = False

    @classmethod
    def load(
        cls,
        schedule_directory: Path,
        readiness_path: Path,
        *,
        client_factory: ClientFactory = default_client_factory,
        clock: rgw_live_adapter.Clock = time.time,
    ) -> PilotRgwActionAdapter:
        try:
            schedule_directory = control_artifacts._absolute_path(
                str(schedule_directory),
                "pilot RGW schedule directory",
            )
            schedule, _ = pilot_executor._schedule_output(
                schedule_directory,
                readiness_path,
            )
            configs = {
                phase: rgw_live_adapter._read_config(
                    schedule_directory
                    / pilot_schedule.PHASE_CONFIG_FILES[phase]
                )[0]
                for phase in native_target.PHASES
            }
            clients = {
                phase: client_factory(config)
                for phase, config in configs.items()
            }
        except (
            control_artifacts.ControlArtifactError,
            pilot_executor.PilotExecutorError,
            pilot_schedule.PilotScheduleError,
            rgw_live_adapter.RgwLiveAdapterError,
        ) as error:
            raise PilotRgwActionError(
                "pilot RGW adapter inputs are unavailable"
            ) from error
        if (
            set(clients) != set(native_target.PHASES)
            or any(
                not isinstance(client, RgwRuntimeClients)
                for client in clients.values()
            )
        ):
            raise PilotRgwActionError(
                "pilot RGW client factory changed"
            )
        return cls(
            schedule_directory=schedule_directory,
            schedule=schedule,
            clients=clients,
            clock=clock,
        )

    def _action(
        self,
        value: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw = dict(
            _exact(
                value,
                pilot_schedule.ACTION_KEYS,
                "pilot RGW action",
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
            raise PilotRgwActionError(
                "pilot RGW action is unsupported"
            )
        config_path = (
            self.schedule_directory
            / pilot_schedule.PHASE_CONFIG_FILES[raw["phase"]]
        )
        if Path(raw["config_file"]) != config_path:
            raise PilotRgwActionError(
                "pilot RGW action configuration changed"
            )
        try:
            config, _, _ = rgw_live_adapter._read_config(config_path)
        except rgw_live_adapter.RgwLiveAdapterError as error:
            raise PilotRgwActionError(
                "pilot RGW action configuration changed"
            ) from error
        return raw, config

    def _steps(
        self,
        action: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> tuple[list[Path], list[object]]:
        phase_directory = (
            Path(self.schedule["runtime_directory"]) / action["phase"]
        )
        paths = [
            phase_directory / f"rgw-step-{index}.json"
            for index in range(len(config["steps"]))
        ]
        values = [
            _owner_document(path, "pilot RGW step")[0]
            for path in paths
        ]
        return paths, values

    def _validate_output(
        self,
        action: Mapping[str, Any],
        config: Mapping[str, Any],
    ) -> None:
        output = Path(action["output_file"])
        kind = action["action"]
        if kind == "open-phase":
            _phase_directory(output)
            return
        value, payload = _owner_document(output, "pilot RGW action output")
        if kind == "collect-rgw-step":
            try:
                rgw_live_adapter._validated_step(
                    value,
                    config=config,
                    index=action["step_index"],
                )
            except rgw_live_adapter.RgwLiveAdapterError as error:
                raise PilotRgwActionError(
                    "pilot RGW step output changed"
                ) from error
        elif kind == "compile-rgw-probe":
            _, step_values = self._steps(action, config)
            expected = rgw_live_adapter.compile_probe(
                config,
                step_values,
            )
            if value != expected or payload != _canonical(expected):
                raise PilotRgwActionError(
                    "pilot RGW probe output changed"
                )
        elif kind == "collect-rgw-multipart":
            try:
                rgw_live_adapter.rgw_artifacts._multipart(
                    value,
                    config=config,
                    target_sha256=config["target_sha256"],
                )
            except rgw_live_adapter.rgw_artifacts.RgwArtifactError as error:
                raise PilotRgwActionError(
                    "pilot RGW multipart output changed"
                ) from error
        elif kind == "cleanup-rgw-prefix":
            try:
                rgw_cleanup.validate_result(
                    value,
                    config_value=config,
                )
            except rgw_cleanup.RgwCleanupError as error:
                raise PilotRgwActionError(
                    "pilot RGW cleanup output changed"
                ) from error
        elif kind == "verify-rgw-cleanup":
            cleanup_value, _ = _owner_document(
                Path(action["input_file"]),
                "pilot RGW cleanup input",
            )
            _validate_cleanup_verification(
                value,
                config=config,
                cleanup_value=cleanup_value,
            )
        else:
            raise PilotRgwActionError(
                "pilot RGW action is unsupported"
            )

    def execute(
        self,
        action_value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        action, config = self._action(action_value)
        output = Path(action["output_file"])
        phase = action["phase"]
        kind = action["action"]
        if kind == "open-phase":
            if output != Path(self.schedule["runtime_directory"]) / phase:
                raise PilotRgwActionError(
                    "pilot RGW phase path changed"
                )
            _runtime_directory(self.schedule)
            _phase_directory(output)
        else:
            _absent(output)
            clients = self.clients[phase]
            config_path = Path(action["config_file"])
            if kind == "collect-rgw-step":
                rgw_live_adapter.collect_step_file(
                    config_path,
                    action["step_index"],
                    output,
                    client=clients.evidence,
                    clock=self.clock,
                )
            elif kind == "compile-rgw-probe":
                step_paths, _ = self._steps(action, config)
                rgw_live_adapter.compile_probe_files(
                    config_path,
                    step_paths,
                    output,
                )
            elif kind == "collect-rgw-multipart":
                rgw_live_adapter.collect_multipart_file(
                    config_path,
                    output,
                    client=clients.evidence,
                    clock=self.clock,
                )
            elif kind == "cleanup-rgw-prefix":
                rgw_cleanup.cleanup_file(
                    config_path,
                    output,
                    client=clients.cleanup,
                    clock=self.clock,
                )
            elif kind == "verify-rgw-cleanup":
                cleanup_value, _ = _owner_document(
                    Path(action["input_file"]),
                    "pilot RGW cleanup input",
                )
                _write(
                    output,
                    _cleanup_verification(
                        cleanup_value,
                        config=config,
                    ),
                )
            else:
                raise PilotRgwActionError(
                    "pilot RGW action is unsupported"
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
        print("pilot-rgw-actions-refused", file=sys.stderr)
        return 2
    try:
        source_hash = adapter_source_sha256()
    except PilotRgwActionError:
        print("pilot-rgw-actions-refused", file=sys.stderr)
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
