from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
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


control_artifacts = _module(
    "coffer_load_galera_control_artifacts",
    DIRECTORY / "control_artifacts.py",
)
source_summaries = control_artifacts.source_summaries
phase_evidence = control_artifacts.phase_evidence
native_target = control_artifacts.native_target
load_contract = control_artifacts.load_contract
observability_contract = control_artifacts.observability_contract

CONFIG_SCHEMA = "coffer.load-telemetry-galera-artifact-config/v1"
RESULT_SCHEMA = "coffer.load-telemetry-galera-artifact-result/v1"
TERMINAL_ERROR_RESULTS = frozenset(
    {"conflict_exhausted", "database_error"}
)
SOURCE_FILES = (
    ROOT_DIRECTORY / "src" / "coffer" / "observability.py",
    ROOT_DIRECTORY / "src" / "coffer" / "quota.py",
    DIRECTORY / "control_artifacts.py",
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "source_summaries.py",
    DIRECTORY / "galera_artifacts.py",
)


class GaleraArtifactError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise GaleraArtifactError(f"{category} boundary changed")
    return value


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


def collector_source_sha256() -> str:
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
        raise GaleraArtifactError(
            "Galera collector source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise GaleraArtifactError(f"{category} is invalid")
    return value


def _config(
    value: object,
    target_value: object,
    *,
    target_file_sha256: str,
) -> tuple[dict[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    raw = _exact(
        value,
        {
            "collector_source_sha256",
            "control_collector_source_sha256",
            "phase",
            "schema",
            "target_file",
            "target_file_sha256",
            "window_sha256",
        },
        "Galera artifact configuration",
    )
    if (
        raw["schema"] != CONFIG_SCHEMA
        or raw["collector_source_sha256"] != collector_source_sha256()
        or raw["control_collector_source_sha256"]
        != control_artifacts.collector_source_sha256()
        or raw["phase"] not in native_target.PHASES
        or raw["target_file_sha256"] != target_file_sha256
    ):
        raise GaleraArtifactError("Galera artifact binding changed")
    target, load_topology = control_artifacts._validated_target(target_value)
    return (
        {
            "collector_source_sha256": collector_source_sha256(),
            "control_collector_source_sha256": (
                control_artifacts.collector_source_sha256()
            ),
            "phase": raw["phase"],
            "schema": CONFIG_SCHEMA,
            "target_file": str(
                control_artifacts._absolute_path(
                    raw["target_file"],
                    "native target file",
                )
            ),
            "target_file_sha256": _sha256(
                raw["target_file_sha256"],
                "native target file hash",
            ),
            "window_sha256": _sha256(
                raw["window_sha256"],
                "Galera artifact window hash",
            ),
        },
        target,
        load_topology,
    )


def _terminal_errors(
    baseline_samples: Mapping[tuple[tuple[str, str], ...], float],
    current_samples: Mapping[tuple[tuple[str, str], ...], float],
    *,
    edge_instances: set[str],
    reconcile_instances: set[str],
) -> int:
    baseline = control_artifacts._attempt_values(
        baseline_samples,
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    current = control_artifacts._attempt_values(
        current_samples,
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    if not set(baseline) <= set(current):
        raise GaleraArtifactError(
            "Galera transaction-attempt series disappeared"
        )
    total = 0
    for key, current_value in current.items():
        before = baseline.get(key, 0)
        if current_value < before:
            raise GaleraArtifactError(
                "Galera transaction-attempt counter reset"
            )
        result = key[-2]
        bucket = key[-1]
        if result in TERMINAL_ERROR_RESULTS and bucket == "+Inf":
            total += current_value - before
            if total > phase_evidence.MAX_COUNT:
                raise GaleraArtifactError(
                    "Galera terminal error count exceeded"
                )
    return total


def compile_artifact(
    config_value: object,
    target_value: object,
    baseline_value: object,
    current_value: object,
    *,
    target_file_sha256: str,
) -> dict[str, Any]:
    config, target, load_topology = _config(
        config_value,
        target_value,
        target_file_sha256=target_file_sha256,
    )
    control_config = {
        "collector_source_sha256": config[
            "control_collector_source_sha256"
        ],
        "phase": config["phase"],
        "window_sha256": config["window_sha256"],
    }
    try:
        baseline, baseline_observations = control_artifacts._capture(
            baseline_value,
            config=control_config,
            target=target,
            capture_kind="baseline",
        )
        current, current_observations = control_artifacts._capture(
            current_value,
            config=control_config,
            target=target,
            capture_kind="current",
        )
    except control_artifacts.ControlArtifactError as error:
        raise GaleraArtifactError("Galera control capture is invalid") from error
    if baseline["completed_at_seconds"] > current["started_at_seconds"]:
        raise GaleraArtifactError("Galera control capture order changed")
    edge_instances, reconcile_instances = (
        control_artifacts._expected_instances(target)
    )
    try:
        baseline_starts = control_artifacts._process_starts(
            baseline["prometheus"]["process_start"],
            edge_instances=edge_instances,
            reconcile_instances=reconcile_instances,
        )
        current_starts = control_artifacts._process_starts(
            current["prometheus"]["process_start"],
            edge_instances=edge_instances,
            reconcile_instances=reconcile_instances,
        )
        maximum_attempts = control_artifacts._maximum_attempts(
            baseline["prometheus"]["attempts"],
            current["prometheus"]["attempts"],
            edge_instances=edge_instances,
            reconcile_instances=reconcile_instances,
        )
    except control_artifacts.ControlArtifactError as error:
        raise GaleraArtifactError(
            "Galera transaction evidence is invalid"
        ) from error
    if (
        baseline_starts != current_starts
        or any(
            value > baseline["completed_at_seconds"]
            for value in baseline_starts.values()
        )
        or any(
            value > current["completed_at_seconds"]
            for value in current_starts.values()
        )
    ):
        raise GaleraArtifactError(
            "Galera transaction metric process restarted"
        )
    unexpected_errors = _terminal_errors(
        baseline["prometheus"]["attempts"],
        current["prometheus"]["attempts"],
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    aggregate = phase_evidence._normalize_payload(
        "galera",
        {
            "max_transaction_attempts": maximum_attempts,
            "unexpected_errors": unexpected_errors,
        },
        load_topology=load_topology,
    )
    observations = baseline_observations + current_observations
    if not 1 <= observations <= source_summaries.MAX_OBSERVATIONS:
        raise GaleraArtifactError("Galera observation count exceeded")
    artifact = {
        "aggregate": aggregate,
        "collector_source_sha256": config["collector_source_sha256"],
        "input_set_sha256": _hash(
            {
                "baseline_capture_sha256": baseline["capture_sha256"],
                "current_capture_sha256": current["capture_sha256"],
            }
        ),
        "observations": observations,
        "phase": config["phase"],
        "schema": source_summaries.ARTIFACT_SCHEMA,
        "source_class": phase_evidence.SOURCE_CLASSES["galera"],
        "surface": "galera",
        "target_sha256": target["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    artifact["artifact_sha256"] = _hash(artifact)
    try:
        load_contract.validate_retained_evidence(artifact)
        observability_contract.validate_retained_payload(artifact)
    except (
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ) as error:
        raise GaleraArtifactError(
            "Galera artifact is not retainable"
        ) from error
    return json.loads(json.dumps(artifact, separators=(",", ":"), sort_keys=True))


def compile_file(
    config_path: Path,
    baseline_path: Path,
    current_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    try:
        config_path = control_artifacts._absolute_path(
            str(config_path),
            "Galera configuration",
        )
        baseline_path = control_artifacts._absolute_path(
            str(baseline_path),
            "Galera baseline capture",
        )
        current_path = control_artifacts._absolute_path(
            str(current_path),
            "Galera current capture",
        )
        config_value, _, config_metadata = (
            control_artifacts._read_owner_document(config_path)
        )
        config_raw = _exact(
            config_value,
            {
                "collector_source_sha256",
                "control_collector_source_sha256",
                "phase",
                "schema",
                "target_file",
                "target_file_sha256",
                "window_sha256",
            },
            "Galera artifact configuration",
        )
        target_path = control_artifacts._absolute_path(
            config_raw["target_file"],
            "native target file",
        )
        target_value, target_payload, target_metadata = (
            control_artifacts._read_owner_document(target_path)
        )
        baseline_value, _, baseline_metadata = (
            control_artifacts._read_owner_document(baseline_path)
        )
        current_value, _, current_metadata = (
            control_artifacts._read_owner_document(current_path)
        )
        inputs = [
            (config_path, config_metadata),
            (target_path, target_metadata),
            (baseline_path, baseline_metadata),
            (current_path, current_metadata),
        ]
        control_artifacts._distinct_inputs(inputs)
        artifact = compile_artifact(
            config_value,
            target_value,
            baseline_value,
            current_value,
            target_file_sha256=_payload_hash(target_payload),
        )
        control_artifacts._write_output(
            output_path,
            artifact,
            inputs=inputs,
        )
        return artifact
    except control_artifacts.ControlArtifactError as error:
        raise GaleraArtifactError(
            "Galera artifact file boundary is invalid"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        print(
            json.dumps(
                {
                    "collector_source_sha256": collector_source_sha256(),
                    "schema": RESULT_SCHEMA,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    if len(arguments) == 5 and arguments[0] == "compile":
        try:
            artifact = compile_file(
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
                Path(arguments[4]),
            )
        except (
            GaleraArtifactError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            print("galera-artifact-refused", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "artifact_sha256": artifact["artifact_sha256"],
                    "schema": RESULT_SCHEMA,
                    "surface": "galera",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    print(
        "usage: galera_artifacts.py source-hash | "
        "compile CONFIG BASELINE CURRENT OUTPUT",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
