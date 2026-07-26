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
LOAD_DIRECTORY = DIRECTORY.parent
POC_DIRECTORY = LOAD_DIRECTORY.parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


phase_evidence = _module(
    "coffer_load_source_summaries_phase_evidence",
    DIRECTORY / "phase_evidence.py",
)
native_target = phase_evidence.native_target
render_target = phase_evidence.render_target
load_contract = phase_evidence.load_contract
observability_contract = phase_evidence.observability_contract

CONFIG_SCHEMA = "coffer.load-telemetry-source-summaries-config/v1"
ARTIFACT_SCHEMA = "coffer.load-telemetry-source-artifact/v1"
RESULT_SCHEMA = "coffer.load-telemetry-source-summaries-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-telemetry-source-summaries-source-result/v1"
SOURCE_FILES = (
    DIRECTORY / "native_surfaces.py",
    DIRECTORY / "native_target.py",
    DIRECTORY / "render_target.py",
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "source_summaries.py",
)
MAX_OBSERVATIONS = 1_000_000


class SourceSummaryError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise SourceSummaryError(f"{category} boundary changed")
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


def acquisition_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": path.name,
                    "sha256": _payload_hash(path.read_bytes()),
                }
            )
    except OSError as error:
        raise SourceSummaryError("acquisition source is unavailable") from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise SourceSummaryError(f"{category} is invalid")
    return value


def _absolute_path(value: object, category: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\x00" in value
    ):
        raise SourceSummaryError(f"{category} is invalid")
    path = Path(value)
    if not path.is_absolute() or str(path) != value:
        raise SourceSummaryError(f"{category} is not canonical")
    return path


def _read_owner_document(
    path: Path,
) -> tuple[object, bytes, os.stat_result]:
    try:
        return phase_evidence._read_owner_document(path)
    except phase_evidence.PhaseEvidenceError as error:
        raise SourceSummaryError("source summary input is unavailable") from error


def _artifact(
    value: object,
    *,
    collector_source_sha256: str,
    phase: str,
    source_artifact_sha256: str,
    surface: str,
    target_sha256: str,
    window_sha256: str,
    load_topology: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = _exact(
        value,
        {
            "aggregate",
            "artifact_sha256",
            "collector_source_sha256",
            "observations",
            "phase",
            "schema",
            "source_class",
            "surface",
            "target_sha256",
            "window_sha256",
        },
        f"{surface} source artifact",
    )
    if (
        artifact["schema"] != ARTIFACT_SCHEMA
        or artifact["phase"] != phase
        or artifact["surface"] != surface
        or artifact["source_class"]
        != phase_evidence.SOURCE_CLASSES[surface]
        or artifact["collector_source_sha256"]
        != collector_source_sha256
        or artifact["target_sha256"] != target_sha256
        or artifact["window_sha256"] != window_sha256
        or not isinstance(artifact["observations"], int)
        or isinstance(artifact["observations"], bool)
        or not 1 <= artifact["observations"] <= MAX_OBSERVATIONS
    ):
        raise SourceSummaryError(f"{surface} source artifact binding changed")
    aggregate = phase_evidence._normalize_payload(
        surface,
        artifact["aggregate"],
        load_topology=load_topology,
    )
    unsigned = {
        "aggregate": aggregate,
        "collector_source_sha256": collector_source_sha256,
        "observations": artifact["observations"],
        "phase": phase,
        "schema": ARTIFACT_SCHEMA,
        "source_class": phase_evidence.SOURCE_CLASSES[surface],
        "surface": surface,
        "target_sha256": target_sha256,
        "window_sha256": window_sha256,
    }
    artifact_sha256 = _sha256(
        artifact["artifact_sha256"],
        f"{surface} artifact hash",
    )
    if artifact_sha256 != _hash(unsigned):
        raise SourceSummaryError(f"{surface} source artifact hash changed")
    normalized = {**unsigned, "artifact_sha256": artifact_sha256}
    try:
        load_contract.validate_retained_evidence(normalized)
        observability_contract.validate_retained_payload(normalized)
    except (
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ) as error:
        raise SourceSummaryError(
            f"{surface} source artifact is not retainable"
        ) from error
    summary = {
        "collector_source_sha256": collector_source_sha256,
        "payload": aggregate,
        "phase": phase,
        "schema": phase_evidence.SUMMARY_SCHEMA,
        "source_artifact_sha256": source_artifact_sha256,
        "source_class": phase_evidence.SOURCE_CLASSES[surface],
        "surface": surface,
        "window_sha256": window_sha256,
    }
    summary["summary_sha256"] = phase_evidence._hash(summary)
    return summary


def compile_request(
    config_value: object,
    target_value: object,
    artifacts: Mapping[str, tuple[object, bytes]],
    *,
    target_file_sha256: str,
) -> dict[str, Any]:
    config = _exact(
        config_value,
        {
            "acquisition_source_sha256",
            "artifacts",
            "phase",
            "schema",
            "target_file",
            "target_file_sha256",
            "window_sha256",
        },
        "source summary configuration",
    )
    if (
        config["schema"] != CONFIG_SCHEMA
        or config["acquisition_source_sha256"]
        != acquisition_source_sha256()
        or config["phase"] not in native_target.PHASES
        or config["target_file_sha256"] != target_file_sha256
    ):
        raise SourceSummaryError("source summary binding changed")
    window_sha256 = _sha256(
        config["window_sha256"],
        "source summary window hash",
    )
    load_topology = load_contract.load_topology(
        LOAD_DIRECTORY / "topology.json"
    )
    observability_topology = observability_contract.load_topology(
        POC_DIRECTORY / "observability" / "topology.json"
    )
    topology_sha256 = native_target._hash(load_topology)
    try:
        target = native_target.validate_target(
            target_value,
            topology_sha256=topology_sha256,
            load_topology=load_topology,
            observability_topology=observability_topology,
        ).raw
    except native_target.NativeTargetError as error:
        raise SourceSummaryError("native target is invalid") from error
    descriptors = _exact(
        config["artifacts"],
        set(phase_evidence.SURFACES),
        "source artifact descriptors",
    )
    if set(artifacts) != set(phase_evidence.SURFACES):
        raise SourceSummaryError("source artifact set changed")
    summaries: dict[str, Any] = {}
    for surface in phase_evidence.SURFACES:
        descriptor = _exact(
            descriptors[surface],
            {"collector_source_sha256", "file", "file_sha256"},
            f"{surface} artifact descriptor",
        )
        collector_source_sha256 = _sha256(
            descriptor["collector_source_sha256"],
            f"{surface} collector source hash",
        )
        source_artifact_sha256 = _sha256(
            descriptor["file_sha256"],
            f"{surface} artifact file hash",
        )
        artifact_value, artifact_payload = artifacts[surface]
        if source_artifact_sha256 != _payload_hash(artifact_payload):
            raise SourceSummaryError(
                f"{surface} source artifact file hash changed"
            )
        summaries[surface] = _artifact(
            artifact_value,
            collector_source_sha256=collector_source_sha256,
            phase=config["phase"],
            source_artifact_sha256=source_artifact_sha256,
            surface=surface,
            target_sha256=target["target_sha256"],
            window_sha256=window_sha256,
            load_topology=load_topology,
        )
    request = {
        "compiler_source_sha256": phase_evidence.compiler_source_sha256(),
        "load_topology_sha256": topology_sha256,
        "phase": config["phase"],
        "schema": phase_evidence.REQUEST_SCHEMA,
        "summaries": summaries,
        "target_file_sha256": target_file_sha256,
        "target_sha256": target["target_sha256"],
        "window_sha256": window_sha256,
    }
    phase_evidence.compile_bundle(
        request,
        target,
        target_file_sha256=target_file_sha256,
    )
    return json.loads(
        json.dumps(request, separators=(",", ":"), sort_keys=True)
    )


def _distinct_files(
    files: Sequence[tuple[Path, os.stat_result]],
) -> None:
    paths = [path for path, _ in files]
    inodes = [
        (metadata.st_dev, metadata.st_ino)
        for _, metadata in files
    ]
    if len(set(paths)) != len(paths) or len(set(inodes)) != len(inodes):
        raise SourceSummaryError("source summary input files alias")


def compile_file(config_path: Path, output_path: Path) -> dict[str, Any]:
    config_value, _, config_metadata = _read_owner_document(config_path)
    config = _exact(
        config_value,
        {
            "acquisition_source_sha256",
            "artifacts",
            "phase",
            "schema",
            "target_file",
            "target_file_sha256",
            "window_sha256",
        },
        "source summary configuration",
    )
    target_file = _absolute_path(config["target_file"], "target file")
    target_value, target_payload, target_metadata = _read_owner_document(
        target_file
    )
    descriptors = _exact(
        config["artifacts"],
        set(phase_evidence.SURFACES),
        "source artifact descriptors",
    )
    artifacts: dict[str, tuple[object, bytes]] = {}
    file_metadata: list[tuple[Path, os.stat_result]] = [
        (config_path, config_metadata),
        (target_file, target_metadata),
    ]
    for surface in phase_evidence.SURFACES:
        descriptor = _exact(
            descriptors[surface],
            {"collector_source_sha256", "file", "file_sha256"},
            f"{surface} artifact descriptor",
        )
        artifact_file = _absolute_path(
            descriptor["file"],
            f"{surface} artifact file",
        )
        value, payload, metadata = _read_owner_document(artifact_file)
        artifacts[surface] = (value, payload)
        file_metadata.append((artifact_file, metadata))
    _distinct_files(file_metadata)
    try:
        render_target._safe_output(output_path, request_path=config_path)
    except render_target.RenderError as error:
        raise SourceSummaryError("source summary output is unsafe") from error
    try:
        output_metadata = output_path.stat(follow_symlinks=False)
    except FileNotFoundError:
        output_metadata = None
    except OSError as error:
        raise SourceSummaryError("source summary output is unavailable") from error
    if output_metadata is not None:
        output_identity = (
            output_metadata.st_dev,
            output_metadata.st_ino,
        )
        if output_identity in {
            (metadata.st_dev, metadata.st_ino)
            for _, metadata in file_metadata
        }:
            raise SourceSummaryError("source summary output aliases an input")
    request = compile_request(
        config,
        target_value,
        artifacts,
        target_file_sha256=_payload_hash(target_payload),
    )
    payload = _canonical(request)
    try:
        if output_path.exists() and output_path.read_bytes() == payload:
            return request
    except OSError as error:
        raise SourceSummaryError("source summary output is unavailable") from error
    try:
        render_target._atomic_write(output_path, payload)
    except render_target.RenderError as error:
        raise SourceSummaryError("source summary output is unavailable") from error
    return request


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = acquisition_source_sha256()
        except SourceSummaryError:
            print("source-summaries-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "acquisition_source_sha256": source_sha256,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 3 or arguments[0] != "compile":
        print("source-summaries-refused", file=sys.stderr)
        return 2
    try:
        request = compile_file(
            Path(arguments[1]),
            Path(arguments[2]),
        )
    except (
        SourceSummaryError,
        phase_evidence.PhaseEvidenceError,
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ):
        print("source-summaries-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "phase": request["phase"],
                "request_sha256": _hash(request),
                "schema": RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
