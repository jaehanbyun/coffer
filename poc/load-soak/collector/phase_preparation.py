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
ROOT_DIRECTORY = DIRECTORY.parents[2]


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


rgw_artifacts = _module(
    "coffer_load_phase_prepare_rgw",
    DIRECTORY / "rgw_artifacts.py",
)
control_artifacts = rgw_artifacts.control_artifacts
source_summaries = control_artifacts.source_summaries
phase_evidence = control_artifacts.phase_evidence
native_target = control_artifacts.native_target
render_target = control_artifacts.render_target
local_artifacts = _module(
    "coffer_load_phase_prepare_local",
    DIRECTORY / "local_artifacts.py",
)
galera_artifacts = _module(
    "coffer_load_phase_prepare_galera",
    DIRECTORY / "galera_artifacts.py",
)
evidence_server = _module(
    "coffer_load_phase_prepare_server",
    DIRECTORY / "evidence_server.py",
)

REQUEST_SCHEMA = "coffer.load-telemetry-phase-preparation-request/v1"
RESULT_SCHEMA = "coffer.load-telemetry-phase-preparation-result/v1"
SOURCE_RESULT_SCHEMA = (
    "coffer.load-telemetry-phase-preparation-source-result/v1"
)
ARTIFACT_FILES = {
    "prometheus": "prometheus-artifact.json",
    "haproxy": "haproxy-artifact.json",
    "galera": "galera-artifact.json",
    "rgw": "rgw-artifact.json",
    "quota": "quota-artifact.json",
    "reconciliation": "reconciliation-artifact.json",
}
RETAINED_FILES = (
    *ARTIFACT_FILES.values(),
    "source-request.json",
    "bundle.json",
    "evidence-server.json",
)
OUTPUT_FILES = frozenset((*RETAINED_FILES, "result.json"))
SOURCE_FILES = (
    DIRECTORY / "local_artifacts.py",
    DIRECTORY / "control_artifacts.py",
    DIRECTORY / "galera_artifacts.py",
    DIRECTORY / "rgw_artifacts.py",
    DIRECTORY / "source_summaries.py",
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "evidence_server.py",
    DIRECTORY / "phase_preparation.py",
)


class PhasePreparationError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PhasePreparationError(f"{category} boundary changed")
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


def preparer_source_sha256() -> str:
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
        raise PhasePreparationError(
            "phase preparer source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise PhasePreparationError(f"{category} is invalid")
    return value


def _absolute_path(value: object, category: str) -> Path:
    try:
        return control_artifacts._absolute_path(value, category)
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError(f"{category} is invalid") from error


def _document_descriptor(
    value: object,
    category: str,
) -> tuple[dict[str, str], object, bytes, os.stat_result]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    path = _absolute_path(raw["file"], f"{category} file")
    try:
        document, payload, metadata = (
            control_artifacts._read_owner_document(path)
        )
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError(f"{category} is unavailable") from error
    supplied_hash = _sha256(
        raw["file_sha256"],
        f"{category} file hash",
    )
    if supplied_hash != _payload_hash(payload):
        raise PhasePreparationError(f"{category} file hash changed")
    return (
        {"file": str(path), "file_sha256": supplied_hash},
        document,
        payload,
        metadata,
    )


def _tls_descriptor(
    value: object,
    category: str,
) -> tuple[dict[str, str], bytes, os.stat_result]:
    raw = _exact(value, {"file", "file_sha256"}, category)
    path = _absolute_path(raw["file"], f"{category} file")
    try:
        payload, metadata = evidence_server._read_owner_bytes(
            path,
            category=category,
        )
    except evidence_server.EvidenceServerError as error:
        raise PhasePreparationError(f"{category} is unavailable") from error
    supplied_hash = _sha256(
        raw["file_sha256"],
        f"{category} file hash",
    )
    if supplied_hash != _payload_hash(payload):
        raise PhasePreparationError(f"{category} file hash changed")
    return (
        {"file": str(path), "file_sha256": supplied_hash},
        payload,
        metadata,
    )


def _output_directory(value: object) -> Path:
    path = _absolute_path(value, "phase output directory")
    if path.name in {"", ".", ".."}:
        raise PhasePreparationError("phase output directory is invalid")
    try:
        parent = path.parent.stat(follow_symlinks=False)
    except OSError as error:
        raise PhasePreparationError(
            "phase output parent is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.getuid()
    ):
        raise PhasePreparationError("phase output parent is unsafe")
    return path


def _server_settings(value: object) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "bind_address",
            "certificate",
            "max_concurrency",
            "port",
            "private_key",
            "request_timeout_seconds",
            "server_name",
            "server_source_sha256",
        },
        "evidence server settings",
    )
    if raw["server_source_sha256"] != evidence_server.server_source_sha256():
        raise PhasePreparationError("evidence server source changed")
    certificate, _, certificate_metadata = _tls_descriptor(
        raw["certificate"],
        "evidence server certificate",
    )
    private_key, _, private_key_metadata = _tls_descriptor(
        raw["private_key"],
        "evidence server private key",
    )
    return {
        "bind_address": raw["bind_address"],
        "certificate": certificate,
        "certificate_metadata": certificate_metadata,
        "max_concurrency": raw["max_concurrency"],
        "port": raw["port"],
        "private_key": private_key,
        "private_key_metadata": private_key_metadata,
        "request_timeout_seconds": raw["request_timeout_seconds"],
        "server_name": raw["server_name"],
        "server_source_sha256": raw["server_source_sha256"],
    }


def _request(
    value: object,
) -> tuple[dict[str, Any], list[tuple[Path, os.stat_result]]]:
    raw = _exact(
        value,
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
        "phase preparation request",
    )
    if (
        raw["schema"] != REQUEST_SCHEMA
        or raw["preparer_source_sha256"] != preparer_source_sha256()
        or raw["phase"] not in native_target.PHASES
    ):
        raise PhasePreparationError("phase preparation binding changed")
    target_descriptor, target_value, _, target_metadata = (
        _document_descriptor(raw["target"], "native target")
    )
    try:
        target, _ = control_artifacts._validated_target(target_value)
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError("native target is invalid") from error
    inputs_raw = _exact(
        raw["collector_inputs"],
        {
            "control_baseline",
            "control_config",
            "control_current",
            "galera_config",
            "haproxy_config",
            "prometheus_config",
            "rgw_config",
            "rgw_multipart",
            "rgw_probe",
        },
        "collector input set",
    )
    descriptors: dict[str, dict[str, str]] = {}
    metadata: list[tuple[Path, os.stat_result]] = [
        (Path(target_descriptor["file"]), target_metadata)
    ]
    for name in sorted(inputs_raw):
        descriptor, _, _, details = _document_descriptor(
            inputs_raw[name],
            f"{name.replace('_', ' ')} input",
        )
        descriptors[name] = descriptor
        metadata.append((Path(descriptor["file"]), details))
    server = _server_settings(raw["evidence_server"])
    metadata.extend(
        (
            (
                Path(server["certificate"]["file"]),
                server["certificate_metadata"],
            ),
            (
                Path(server["private_key"]["file"]),
                server["private_key_metadata"],
            ),
        )
    )
    try:
        control_artifacts._distinct_inputs(metadata)
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError(
            "phase preparation inputs alias"
        ) from error
    return (
        {
            "collector_inputs": descriptors,
            "evidence_server": {
                key: server[key]
                for key in (
                    "bind_address",
                    "certificate",
                    "max_concurrency",
                    "port",
                    "private_key",
                    "request_timeout_seconds",
                    "server_name",
                    "server_source_sha256",
                )
            },
            "output_directory": str(
                _output_directory(raw["output_directory"])
            ),
            "phase": raw["phase"],
            "preparer_source_sha256": preparer_source_sha256(),
            "schema": REQUEST_SCHEMA,
            "target": target_descriptor,
            "target_sha256": target["target_sha256"],
            "window_sha256": _sha256(
                raw["window_sha256"],
                "phase window hash",
            ),
        },
        metadata,
    )


def _write(path: Path, value: object) -> None:
    try:
        render_target._atomic_write(path, _canonical(value))
    except render_target.RenderError as error:
        raise PhasePreparationError(
            "phase preparation output is unavailable"
        ) from error


def _server_config(
    request: Mapping[str, Any],
    *,
    bundle_file: Path,
    bundle_payload: bytes,
) -> dict[str, Any]:
    server = request["evidence_server"]
    return {
        "bind_address": server["bind_address"],
        "bundle_file": str(bundle_file),
        "bundle_file_sha256": _payload_hash(bundle_payload),
        "certificate_file": server["certificate"]["file"],
        "certificate_sha256": server["certificate"]["file_sha256"],
        "max_concurrency": server["max_concurrency"],
        "phase": request["phase"],
        "port": server["port"],
        "private_key_file": server["private_key"]["file"],
        "private_key_sha256": server["private_key"]["file_sha256"],
        "request_timeout_seconds": server["request_timeout_seconds"],
        "schema": evidence_server.CONFIG_SCHEMA,
        "server_name": server["server_name"],
        "server_source_sha256": server["server_source_sha256"],
        "target_file": request["target"]["file"],
        "target_file_sha256": request["target"]["file_sha256"],
    }


def _compile(
    request: Mapping[str, Any],
    staging: Path,
) -> dict[str, Any]:
    inputs = request["collector_inputs"]
    artifact_paths = {
        surface: staging / filename
        for surface, filename in ARTIFACT_FILES.items()
    }
    local_artifacts.compile_file(
        Path(inputs["prometheus_config"]["file"]),
        artifact_paths["prometheus"],
    )
    local_artifacts.compile_file(
        Path(inputs["haproxy_config"]["file"]),
        artifact_paths["haproxy"],
    )
    control_artifacts.compile_files(
        Path(inputs["control_config"]["file"]),
        Path(inputs["control_baseline"]["file"]),
        Path(inputs["control_current"]["file"]),
        artifact_paths["quota"],
        artifact_paths["reconciliation"],
    )
    galera_artifacts.compile_file(
        Path(inputs["galera_config"]["file"]),
        Path(inputs["control_baseline"]["file"]),
        Path(inputs["control_current"]["file"]),
        artifact_paths["galera"],
    )
    rgw_artifacts.compile_file(
        Path(inputs["rgw_config"]["file"]),
        Path(inputs["rgw_probe"]["file"]),
        Path(inputs["rgw_multipart"]["file"]),
        artifact_paths["rgw"],
    )
    collector_hashes = {
        "prometheus": local_artifacts.collector_source_sha256(),
        "haproxy": local_artifacts.collector_source_sha256(),
        "galera": galera_artifacts.collector_source_sha256(),
        "rgw": rgw_artifacts.collector_source_sha256(),
        "quota": control_artifacts.collector_source_sha256(),
        "reconciliation": control_artifacts.collector_source_sha256(),
    }
    source_config = {
        "acquisition_source_sha256": (
            source_summaries.acquisition_source_sha256()
        ),
        "artifacts": {
            surface: {
                "collector_source_sha256": collector_hashes[surface],
                "file": str(path),
                "file_sha256": _payload_hash(path.read_bytes()),
            }
            for surface, path in artifact_paths.items()
        },
        "phase": request["phase"],
        "schema": source_summaries.CONFIG_SCHEMA,
        "target_file": request["target"]["file"],
        "target_file_sha256": request["target"]["file_sha256"],
        "window_sha256": request["window_sha256"],
    }
    temporary_source_config = staging / ".source-config.json"
    source_request_path = staging / "source-request.json"
    bundle_path = staging / "bundle.json"
    _write(temporary_source_config, source_config)
    source_summaries.compile_file(
        temporary_source_config,
        source_request_path,
    )
    phase_evidence.compile_file(
        source_request_path,
        Path(request["target"]["file"]),
        bundle_path,
    )
    bundle_payload = bundle_path.read_bytes()
    staging_server_path = staging / ".evidence-server-check.json"
    _write(
        staging_server_path,
        _server_config(
            request,
            bundle_file=bundle_path,
            bundle_payload=bundle_payload,
        ),
    )
    try:
        staged_configuration = evidence_server.load_configuration(
            staging_server_path
        )
    except evidence_server.EvidenceServerError as error:
        raise PhasePreparationError(
            "phase evidence server preflight failed"
        ) from error
    if (
        staged_configuration.phase != request["phase"]
        or staged_configuration.target_sha256
        != request["target_sha256"]
    ):
        raise PhasePreparationError(
            "phase evidence server preflight changed"
        )
    final_directory = Path(request["output_directory"])
    final_server_config = _server_config(
        request,
        bundle_file=final_directory / "bundle.json",
        bundle_payload=bundle_payload,
    )
    server_config_path = staging / "evidence-server.json"
    _write(server_config_path, final_server_config)
    temporary_source_config.unlink()
    staging_server_path.unlink()
    file_hashes = {
        name: _payload_hash((staging / name).read_bytes())
        for name in RETAINED_FILES
    }
    bundle = phase_evidence.validate_bundle(json.loads(bundle_payload))
    result = {
        "bundle_sha256": bundle["bundle_sha256"],
        "complete": True,
        "execution_source": "pilot",
        "files_sha256": file_hashes,
        "phase": request["phase"],
        "preparer_source_sha256": request["preparer_source_sha256"],
        "request_file_sha256": request["request_file_sha256"],
        "schema": RESULT_SCHEMA,
        "server_config_sha256": file_hashes["evidence-server.json"],
        "target_sha256": request["target_sha256"],
        "window_sha256": request["window_sha256"],
    }
    result["result_sha256"] = _hash(result)
    _write(staging / "result.json", result)
    return result


def _read_output_file(
    path: Path,
) -> tuple[object, bytes, os.stat_result]:
    try:
        return control_artifacts._read_owner_document(path)
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError(
            "phase preparation output is invalid"
        ) from error


def _validate_existing(
    request: Mapping[str, Any],
    output: Path,
) -> dict[str, Any]:
    try:
        metadata = output.stat(follow_symlinks=False)
        names = {item.name for item in output.iterdir()}
    except OSError as error:
        raise PhasePreparationError(
            "phase preparation output is unavailable"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or names != set(OUTPUT_FILES)
    ):
        raise PhasePreparationError("phase preparation output is unsafe")
    result_value, _, result_metadata = _read_output_file(
        output / "result.json"
    )
    result = _exact(
        result_value,
        {
            "bundle_sha256",
            "complete",
            "execution_source",
            "files_sha256",
            "phase",
            "preparer_source_sha256",
            "request_file_sha256",
            "result_sha256",
            "schema",
            "server_config_sha256",
            "target_sha256",
            "window_sha256",
        },
        "phase preparation result",
    )
    unsigned = {
        key: value for key, value in result.items() if key != "result_sha256"
    }
    if (
        result["schema"] != RESULT_SCHEMA
        or result["complete"] is not True
        or result["execution_source"] != "pilot"
        or result["phase"] != request["phase"]
        or result["preparer_source_sha256"]
        != request["preparer_source_sha256"]
        or result["request_file_sha256"]
        != request["request_file_sha256"]
        or result["target_sha256"] != request["target_sha256"]
        or result["window_sha256"] != request["window_sha256"]
        or result["result_sha256"] != _hash(unsigned)
    ):
        raise PhasePreparationError(
            "phase preparation result binding changed"
        )
    files = _exact(
        result["files_sha256"],
        set(RETAINED_FILES),
        "phase preparation retained files",
    )
    file_metadata = [(output / "result.json", result_metadata)]
    for name in RETAINED_FILES:
        _, payload, details = _read_output_file(output / name)
        if _sha256(files[name], f"{name} hash") != _payload_hash(payload):
            raise PhasePreparationError(
                "phase preparation retained file changed"
            )
        file_metadata.append((output / name, details))
    try:
        control_artifacts._distinct_inputs(file_metadata)
        server = evidence_server.load_configuration(
            output / "evidence-server.json"
        )
    except (
        control_artifacts.ControlArtifactError,
        evidence_server.EvidenceServerError,
    ) as error:
        raise PhasePreparationError(
            "phase preparation retained state is invalid"
        ) from error
    if (
        result["server_config_sha256"]
        != files["evidence-server.json"]
        or result["bundle_sha256"] != server.bundle_sha256
        or result["target_sha256"] != server.target_sha256
    ):
        raise PhasePreparationError(
            "phase preparation retained result changed"
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
        raise PhasePreparationError(
            "phase preparation cleanup failed"
        ) from error


def prepare_file(request_path: Path) -> dict[str, Any]:
    request_path = _absolute_path(
        str(request_path),
        "phase preparation request",
    )
    try:
        request_value, request_payload, request_metadata = (
            control_artifacts._read_owner_document(request_path)
        )
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError(
            "phase preparation request is unavailable"
        ) from error
    request, input_metadata = _request(request_value)
    request["request_file_sha256"] = _payload_hash(request_payload)
    try:
        control_artifacts._distinct_inputs(
            [(request_path, request_metadata), *input_metadata]
        )
    except control_artifacts.ControlArtifactError as error:
        raise PhasePreparationError(
            "phase preparation request aliases an input"
        ) from error
    output = Path(request["output_directory"])
    if output.exists() or output.is_symlink():
        return _validate_existing(request, output)
    try:
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output.name}.phase-preparation.",
                dir=output.parent,
            )
        )
        staging.chmod(0o700)
    except OSError as error:
        raise PhasePreparationError(
            "phase preparation staging is unavailable"
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
            raise PhasePreparationError(
                "phase preparation publication changed"
            )
        return validated
    except BaseException:
        if published and output.exists() and not staging.exists():
            try:
                os.replace(output, staging)
            except OSError as error:
                raise PhasePreparationError(
                    "phase preparation rollback failed"
                ) from error
        _remove_created(staging)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = preparer_source_sha256()
        except PhasePreparationError:
            print("phase-preparation-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "preparer_source_sha256": source_sha256,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 2 or arguments[0] != "prepare":
        print("phase-preparation-refused", file=sys.stderr)
        return 2
    try:
        result = prepare_file(Path(arguments[1]))
    except (
        PhasePreparationError,
        local_artifacts.LocalArtifactError,
        control_artifacts.ControlArtifactError,
        galera_artifacts.GaleraArtifactError,
        rgw_artifacts.RgwArtifactError,
        source_summaries.SourceSummaryError,
        phase_evidence.PhaseEvidenceError,
        evidence_server.EvidenceServerError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("phase-preparation-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "bundle_sha256": result["bundle_sha256"],
                "phase": result["phase"],
                "result_sha256": result["result_sha256"],
                "schema": RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
