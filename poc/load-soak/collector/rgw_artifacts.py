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
    "coffer_load_rgw_control_artifacts",
    DIRECTORY / "control_artifacts.py",
)
source_summaries = control_artifacts.source_summaries
phase_evidence = control_artifacts.phase_evidence
native_target = control_artifacts.native_target
load_contract = control_artifacts.load_contract
observability_contract = control_artifacts.observability_contract

CONFIG_SCHEMA = "coffer.load-telemetry-rgw-artifact-config/v1"
PROBE_SCHEMA = "coffer.load-rgw-probe-result/v1"
MULTIPART_SCHEMA = "coffer.load-rgw-multipart-capture/v1"
RESULT_SCHEMA = "coffer.load-telemetry-rgw-artifact-result/v1"
OPERATION_CLASSES = (
    "copy_positive",
    "copy_zero",
    "get",
    "head",
    "list_multipart",
    "put_positive",
    "put_zero",
)
FAULT_CLASSES = (
    "expected_kms_outage",
    "expected_wrong_key",
)
RESULT_CLASSES = (
    "expected_kms_outage",
    "expected_wrong_key",
    "success",
    "unexpected_kms_error",
    "unexpected_storage_error",
)
MAX_SECONDS = 4_102_444_800
MAX_PAGES = 10_000
SOURCE_FILES = (
    DIRECTORY / "native_surfaces.py",
    DIRECTORY / "native_target.py",
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "source_summaries.py",
    DIRECTORY / "control_artifacts.py",
    DIRECTORY / "rgw_artifacts.py",
)


class RgwArtifactError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise RgwArtifactError(f"{category} boundary changed")
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
        raise RgwArtifactError(
            "RGW collector source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise RgwArtifactError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int = 0,
    maximum: int = phase_evidence.MAX_COUNT,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise RgwArtifactError(f"{category} is invalid")
    return value


def _number(value: object, category: str) -> float:
    if isinstance(value, bool):
        raise RgwArtifactError(f"{category} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise RgwArtifactError(f"{category} is invalid") from error
    if not 0 <= result <= MAX_SECONDS or result != result:
        raise RgwArtifactError(f"{category} is invalid")
    return result


def _counts(
    value: object,
    classes: Sequence[str],
    category: str,
    *,
    minimum: int = 0,
) -> dict[str, int]:
    raw = _exact(value, set(classes), category)
    return {
        item: _integer(
            raw[item],
            f"{category} {item}",
            minimum=minimum,
        )
        for item in classes
    }


def _config(
    value: object,
    target_value: object,
    *,
    target_file_sha256: str,
) -> tuple[dict[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    raw = _exact(
        value,
        {
            "bucket_scope_sha256",
            "collector_source_sha256",
            "expected_fault_counts",
            "expected_operation_counts",
            "kms_policy_sha256",
            "multipart_source_sha256",
            "phase",
            "probe_source_sha256",
            "rgw_config_sha256",
            "schema",
            "target_file",
            "target_file_sha256",
            "window_completed_at_seconds",
            "window_sha256",
            "window_started_at_seconds",
        },
        "RGW artifact configuration",
    )
    if (
        raw["schema"] != CONFIG_SCHEMA
        or raw["collector_source_sha256"] != collector_source_sha256()
        or raw["phase"] not in native_target.PHASES
        or raw["target_file_sha256"] != target_file_sha256
    ):
        raise RgwArtifactError("RGW artifact binding changed")
    target, load_topology = control_artifacts._validated_target(target_value)
    expected_operations = _counts(
        raw["expected_operation_counts"],
        OPERATION_CLASSES,
        "expected RGW operation counts",
        minimum=1,
    )
    expected_faults = _counts(
        raw["expected_fault_counts"],
        FAULT_CLASSES,
        "expected RGW fault counts",
    )
    if (
        raw["phase"] == "during"
        and any(expected_faults[item] < 1 for item in FAULT_CLASSES)
    ):
        raise RgwArtifactError("RGW during fault coverage changed")
    if (
        raw["phase"] != "during"
        and any(expected_faults.values())
    ):
        raise RgwArtifactError("RGW fault escaped the during window")
    expected_total = sum(expected_operations.values())
    expected_fault_total = sum(expected_faults.values())
    if expected_fault_total >= expected_total:
        raise RgwArtifactError("RGW positive-path coverage changed")
    window_started = _number(
        raw["window_started_at_seconds"],
        "RGW window start",
    )
    window_completed = _number(
        raw["window_completed_at_seconds"],
        "RGW window completion",
    )
    if window_started >= window_completed:
        raise RgwArtifactError("RGW window order changed")
    return (
        {
            "bucket_scope_sha256": _sha256(
                raw["bucket_scope_sha256"],
                "RGW bucket scope hash",
            ),
            "collector_source_sha256": collector_source_sha256(),
            "expected_fault_counts": expected_faults,
            "expected_operation_counts": expected_operations,
            "kms_policy_sha256": _sha256(
                raw["kms_policy_sha256"],
                "RGW KMS policy hash",
            ),
            "multipart_source_sha256": _sha256(
                raw["multipart_source_sha256"],
                "RGW multipart source hash",
            ),
            "phase": raw["phase"],
            "probe_source_sha256": _sha256(
                raw["probe_source_sha256"],
                "RGW probe source hash",
            ),
            "rgw_config_sha256": _sha256(
                raw["rgw_config_sha256"],
                "RGW configuration hash",
            ),
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
            "window_completed_at_seconds": window_completed,
            "window_sha256": _sha256(
                raw["window_sha256"],
                "RGW window hash",
            ),
            "window_started_at_seconds": window_started,
        },
        target,
        load_topology,
    )


def _probe(
    value: object,
    *,
    config: Mapping[str, Any],
    target_sha256: str,
) -> tuple[dict[str, Any], int]:
    raw = _exact(
        value,
        {
            "bucket_scope_sha256",
            "completed_at_seconds",
            "events_sha256",
            "execution_source",
            "kms_policy_sha256",
            "observed_operation_counts",
            "phase",
            "probe_sha256",
            "probe_source_sha256",
            "result_counts",
            "rgw_config_sha256",
            "schema",
            "started_at_seconds",
            "synthetic",
            "target_sha256",
            "window_sha256",
        },
        "RGW probe result",
    )
    unsigned = {key: raw[key] for key in raw if key != "probe_sha256"}
    if (
        raw["schema"] != PROBE_SCHEMA
        or raw["execution_source"] != "pilot"
        or raw["synthetic"] is not False
        or raw["phase"] != config["phase"]
        or raw["window_sha256"] != config["window_sha256"]
        or raw["target_sha256"] != target_sha256
        or raw["probe_source_sha256"]
        != config["probe_source_sha256"]
        or raw["rgw_config_sha256"] != config["rgw_config_sha256"]
        or raw["bucket_scope_sha256"]
        != config["bucket_scope_sha256"]
        or raw["kms_policy_sha256"] != config["kms_policy_sha256"]
        or raw["probe_sha256"] != _hash(unsigned)
    ):
        raise RgwArtifactError("RGW probe binding changed")
    _sha256(raw["events_sha256"], "RGW probe event-set hash")
    observed = _counts(
        raw["observed_operation_counts"],
        OPERATION_CLASSES,
        "observed RGW operation counts",
    )
    if observed != config["expected_operation_counts"]:
        raise RgwArtifactError("RGW probe operation coverage changed")
    results = _counts(
        raw["result_counts"],
        RESULT_CLASSES,
        "RGW probe result counts",
    )
    if any(
        results[item] != config["expected_fault_counts"][item]
        for item in FAULT_CLASSES
    ):
        raise RgwArtifactError("RGW expected fault coverage changed")
    observations = sum(observed.values())
    if observations != sum(results.values()):
        raise RgwArtifactError("RGW probe result coverage changed")
    started = _number(
        raw["started_at_seconds"],
        "RGW probe start",
    )
    completed = _number(
        raw["completed_at_seconds"],
        "RGW probe completion",
    )
    if (
        started > completed
        or started < config["window_started_at_seconds"]
        or completed > config["window_completed_at_seconds"]
    ):
        raise RgwArtifactError("RGW probe escaped its phase window")
    return (
        {
            "probe_sha256": _sha256(
                raw["probe_sha256"],
                "RGW probe hash",
            ),
            "result_counts": results,
        },
        observations,
    )


def _multipart(
    value: object,
    *,
    config: Mapping[str, Any],
    target_sha256: str,
) -> tuple[dict[str, Any], int]:
    raw = _exact(
        value,
        {
            "bucket_scope_sha256",
            "capture_sha256",
            "execution_source",
            "listing_complete",
            "multipart_source_sha256",
            "observed_at_seconds",
            "page_count",
            "page_sha256",
            "phase",
            "rgw_config_sha256",
            "schema",
            "synthetic",
            "target_sha256",
            "upload_count",
            "window_sha256",
        },
        "RGW multipart capture",
    )
    unsigned = {key: raw[key] for key in raw if key != "capture_sha256"}
    if (
        raw["schema"] != MULTIPART_SCHEMA
        or raw["execution_source"] != "pilot"
        or raw["synthetic"] is not False
        or raw["listing_complete"] is not True
        or raw["phase"] != config["phase"]
        or raw["window_sha256"] != config["window_sha256"]
        or raw["target_sha256"] != target_sha256
        or raw["multipart_source_sha256"]
        != config["multipart_source_sha256"]
        or raw["rgw_config_sha256"] != config["rgw_config_sha256"]
        or raw["bucket_scope_sha256"]
        != config["bucket_scope_sha256"]
        or raw["capture_sha256"] != _hash(unsigned)
    ):
        raise RgwArtifactError("RGW multipart binding changed")
    page_count = _integer(
        raw["page_count"],
        "RGW multipart page count",
        minimum=1,
        maximum=MAX_PAGES,
    )
    if (
        not isinstance(raw["page_sha256"], list)
        or len(raw["page_sha256"]) != page_count
    ):
        raise RgwArtifactError("RGW multipart page set changed")
    page_hashes = [
        _sha256(value, "RGW multipart page hash")
        for value in raw["page_sha256"]
    ]
    if len(set(page_hashes)) != len(page_hashes):
        raise RgwArtifactError("RGW multipart page repeated")
    observed_at = _number(
        raw["observed_at_seconds"],
        "RGW multipart observation time",
    )
    if not (
        config["window_started_at_seconds"]
        <= observed_at
        <= config["window_completed_at_seconds"]
    ):
        raise RgwArtifactError(
            "RGW multipart capture escaped its phase window"
        )
    return (
        {
            "capture_sha256": _sha256(
                raw["capture_sha256"],
                "RGW multipart capture hash",
            ),
            "upload_count": _integer(
                raw["upload_count"],
                "RGW multipart upload count",
            ),
        },
        page_count,
    )


def compile_artifact(
    config_value: object,
    target_value: object,
    probe_value: object,
    multipart_value: object,
    *,
    target_file_sha256: str,
) -> dict[str, Any]:
    config, target, load_topology = _config(
        config_value,
        target_value,
        target_file_sha256=target_file_sha256,
    )
    probe, probe_observations = _probe(
        probe_value,
        config=config,
        target_sha256=target["target_sha256"],
    )
    multipart, multipart_observations = _multipart(
        multipart_value,
        config=config,
        target_sha256=target["target_sha256"],
    )
    aggregate = phase_evidence._normalize_payload(
        "rgw",
        {
            "kms_errors": probe["result_counts"][
                "unexpected_kms_error"
            ],
            "multipart_uploads": multipart["upload_count"],
            "unexpected_errors": probe["result_counts"][
                "unexpected_storage_error"
            ],
        },
        load_topology=load_topology,
    )
    observations = probe_observations + multipart_observations
    if not 1 <= observations <= source_summaries.MAX_OBSERVATIONS:
        raise RgwArtifactError("RGW observation count exceeded")
    artifact = {
        "aggregate": aggregate,
        "collector_source_sha256": config["collector_source_sha256"],
        "input_set_sha256": _hash(
            {
                "multipart_capture_sha256": multipart[
                    "capture_sha256"
                ],
                "probe_sha256": probe["probe_sha256"],
            }
        ),
        "observations": observations,
        "phase": config["phase"],
        "schema": source_summaries.ARTIFACT_SCHEMA,
        "source_class": phase_evidence.SOURCE_CLASSES["rgw"],
        "surface": "rgw",
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
        raise RgwArtifactError("RGW artifact is not retainable") from error
    return json.loads(
        json.dumps(artifact, separators=(",", ":"), sort_keys=True)
    )


def compile_file(
    config_path: Path,
    probe_path: Path,
    multipart_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    try:
        config_path = control_artifacts._absolute_path(
            str(config_path),
            "RGW configuration",
        )
        probe_path = control_artifacts._absolute_path(
            str(probe_path),
            "RGW probe result",
        )
        multipart_path = control_artifacts._absolute_path(
            str(multipart_path),
            "RGW multipart capture",
        )
        config_value, _, config_metadata = (
            control_artifacts._read_owner_document(config_path)
        )
        config_raw = _exact(
            config_value,
            {
                "bucket_scope_sha256",
                "collector_source_sha256",
                "expected_fault_counts",
                "expected_operation_counts",
                "kms_policy_sha256",
                "multipart_source_sha256",
                "phase",
                "probe_source_sha256",
                "rgw_config_sha256",
                "schema",
                "target_file",
                "target_file_sha256",
                "window_completed_at_seconds",
                "window_sha256",
                "window_started_at_seconds",
            },
            "RGW artifact configuration",
        )
        target_path = control_artifacts._absolute_path(
            config_raw["target_file"],
            "native target file",
        )
        target_value, target_payload, target_metadata = (
            control_artifacts._read_owner_document(target_path)
        )
        probe_value, _, probe_metadata = (
            control_artifacts._read_owner_document(probe_path)
        )
        multipart_value, _, multipart_metadata = (
            control_artifacts._read_owner_document(multipart_path)
        )
        inputs = [
            (config_path, config_metadata),
            (target_path, target_metadata),
            (probe_path, probe_metadata),
            (multipart_path, multipart_metadata),
        ]
        control_artifacts._distinct_inputs(inputs)
        artifact = compile_artifact(
            config_value,
            target_value,
            probe_value,
            multipart_value,
            target_file_sha256=_payload_hash(target_payload),
        )
        control_artifacts._write_output(
            output_path,
            artifact,
            inputs=inputs,
        )
        return artifact
    except control_artifacts.ControlArtifactError as error:
        raise RgwArtifactError(
            "RGW artifact file boundary is invalid"
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
            RgwArtifactError,
            OSError,
            RuntimeError,
            ValueError,
        ):
            print("rgw-artifact-refused", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "artifact_sha256": artifact["artifact_sha256"],
                    "schema": RESULT_SCHEMA,
                    "surface": "rgw",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    print(
        "usage: rgw_artifacts.py source-hash | "
        "compile CONFIG PROBE MULTIPART OUTPUT",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
