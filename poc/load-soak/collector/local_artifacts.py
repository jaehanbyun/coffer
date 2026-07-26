from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
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


source_summaries = _module(
    "coffer_load_local_artifacts_source_summaries",
    DIRECTORY / "source_summaries.py",
)
phase_evidence = source_summaries.phase_evidence
native_target = source_summaries.native_target
render_target = source_summaries.render_target
load_contract = source_summaries.load_contract
observability_contract = source_summaries.observability_contract

CONFIG_SCHEMA = "coffer.load-telemetry-local-artifact-config/v1"
FINGERPRINT_SCHEMA = "coffer.load-telemetry-local-fingerprint/v1"
RESULT_SCHEMA = "coffer.load-telemetry-local-artifact-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-telemetry-local-artifact-source-result/v1"
SOURCE_FILES = (
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "source_summaries.py",
    DIRECTORY / "local_artifacts.py",
)
PROFILE_SCHEMA = "coffer.load-profile-result/v1"
FAULT_SCHEMA = "coffer.load-fault-result/v1"
SURFACES = ("prometheus", "haproxy")
SOURCE_KINDS = {
    "prometheus": "secret-scan",
    "haproxy": "workload-results",
}
MAX_FILES = 64
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_FINGERPRINTS = 32
MIN_FINGERPRINT_BYTES = 8
MAX_FINGERPRINT_BYTES = 256
ROLLING_BASE = 257
ROLLING_MASK = (1 << 64) - 1
ROLLING_PATTERN = re.compile(r"^rolling64:[0-9a-f]{16}$")
BUILTIN_PATTERNS = (
    re.compile(rb"(?i)\bauthorization\s*:"),
    re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
)
PROFILE_KEYS = frozenset(
    {
        "attempts",
        "duration_seconds",
        "execution_source",
        "kind",
        "last_wave_sha256",
        "maximum_clients",
        "name",
        "operation_counts",
        "order",
        "plan_sha256",
        "profile_binding_sha256",
        "schema",
        "successful_operations",
        "synthetic",
        "transferred_bytes",
        "unexpected_errors",
        "waves",
    }
)
FAULT_KEYS = frozenset(
    {
        "actions_completed",
        "execution_source",
        "fault",
        "fault_binding_sha256",
        "history_sha256",
        "plan_sha256",
        "recovery_seconds",
        "schema",
        "synthetic",
        "target_evidence_sha256",
        "unexpected_errors",
        "window_seconds",
    }
)


class LocalArtifactError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise LocalArtifactError(f"{category} boundary changed")
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


def collector_source_sha256() -> str:
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
        raise LocalArtifactError("collector source is unavailable") from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise LocalArtifactError(f"{category} is invalid")
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
        raise LocalArtifactError(f"{category} is invalid")
    return value


def _absolute_path(value: object, category: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\x00" in value
    ):
        raise LocalArtifactError(f"{category} is invalid")
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or os.path.normpath(value) != value
    ):
        raise LocalArtifactError(f"{category} is not canonical")
    return path


def _read_owner_bytes(
    path: Path,
    *,
    maximum_bytes: int = MAX_FILE_BYTES,
    minimum_bytes: int = 1,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise LocalArtifactError("local artifact input is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or not minimum_bytes <= metadata.st_size <= maximum_bytes
        ):
            raise LocalArtifactError("local artifact input is unsafe")
        payload = os.read(descriptor, maximum_bytes + 1)
        if len(payload) != metadata.st_size:
            raise LocalArtifactError("local artifact input changed")
    except OSError as error:
        raise LocalArtifactError("local artifact input is unavailable") from error
    finally:
        os.close(descriptor)
    return payload, metadata


def _rolling_value(payload: bytes) -> int:
    value = 0
    for byte in payload:
        value = (
            value * ROLLING_BASE + byte + 1
        ) & ROLLING_MASK
    return value


def fingerprint(payload: bytes) -> dict[str, Any]:
    if not MIN_FINGERPRINT_BYTES <= len(payload) <= MAX_FINGERPRINT_BYTES:
        raise LocalArtifactError("fingerprint input size is invalid")
    return {
        "length": len(payload),
        "rolling64": f"rolling64:{_rolling_value(payload):016x}",
        "schema": FINGERPRINT_SCHEMA,
        "sha256": _payload_hash(payload),
    }


def _fingerprint(value: object) -> dict[str, Any]:
    checked = _exact(
        value,
        {"length", "rolling64", "schema", "sha256"},
        "local fingerprint",
    )
    if (
        checked["schema"] != FINGERPRINT_SCHEMA
        or not isinstance(checked["rolling64"], str)
        or ROLLING_PATTERN.fullmatch(checked["rolling64"]) is None
    ):
        raise LocalArtifactError("local fingerprint is invalid")
    return {
        "length": _integer(
            checked["length"],
            "fingerprint length",
            minimum=MIN_FINGERPRINT_BYTES,
            maximum=MAX_FINGERPRINT_BYTES,
        ),
        "rolling64": checked["rolling64"],
        "schema": FINGERPRINT_SCHEMA,
        "sha256": _sha256(checked["sha256"], "fingerprint"),
    }


def _fingerprint_hits(
    payload: bytes,
    fingerprints: Sequence[Mapping[str, Any]],
) -> int:
    by_length: dict[int, dict[int, set[str]]] = {}
    for item in fingerprints:
        length = int(item["length"])
        rolling = int(str(item["rolling64"]).removeprefix("rolling64:"), 16)
        by_length.setdefault(length, {}).setdefault(rolling, set()).add(
            str(item["sha256"])
        )
    hits = 0
    for length, expected in by_length.items():
        if len(payload) < length:
            continue
        power = pow(ROLLING_BASE, length - 1, 1 << 64)
        rolling = _rolling_value(payload[:length])
        for offset in range(0, len(payload) - length + 1):
            hashes = expected.get(rolling)
            if hashes is not None:
                candidate = payload[offset : offset + length]
                if _payload_hash(candidate) in hashes:
                    hits += 1
                    if hits > phase_evidence.MAX_COUNT:
                        raise LocalArtifactError(
                            "local artifact count is excessive"
                        )
            if offset + length < len(payload):
                rolling = (
                    (
                        rolling
                        - (payload[offset] + 1) * power
                    )
                    * ROLLING_BASE
                    + payload[offset + length]
                    + 1
                ) & ROLLING_MASK
    return hits


def _secret_scan(
    payloads: Sequence[bytes],
    fingerprints: Sequence[Mapping[str, Any]],
) -> int:
    hits = 0
    for payload in payloads:
        hits += sum(
            len(pattern.findall(payload))
            for pattern in BUILTIN_PATTERNS
        )
        hits += _fingerprint_hits(payload, fingerprints)
        if hits > phase_evidence.MAX_COUNT:
            raise LocalArtifactError("local artifact count is excessive")
    return hits


def _canonical_document(payload: bytes, category: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LocalArtifactError(f"{category} is invalid") from error
    if payload != _canonical(value) or not isinstance(value, Mapping):
        raise LocalArtifactError(f"{category} is not canonical")
    return value


def _profile_result(
    value: object,
    *,
    topology: Mapping[str, Any],
) -> tuple[int, str]:
    result = _exact(value, PROFILE_KEYS, "profile result")
    if (
        result["schema"] != PROFILE_SCHEMA
        or result["execution_source"] != "pilot"
        or result["synthetic"] is not False
        or result["kind"] not in ("profile", "ramp")
    ):
        raise LocalArtifactError("profile result source changed")
    name = result["name"]
    if not isinstance(name, str):
        raise LocalArtifactError("profile result identity is invalid")
    if result["kind"] == "profile":
        if name not in topology["profiles"]:
            raise LocalArtifactError("profile result identity is invalid")
    else:
        if not name.startswith("clients-"):
            raise LocalArtifactError("profile result identity is invalid")
        try:
            clients = int(name.removeprefix("clients-"))
        except ValueError as error:
            raise LocalArtifactError(
                "profile result identity is invalid"
            ) from error
        if clients not in topology["ramp_clients"]:
            raise LocalArtifactError("profile result identity is invalid")
    counts = _exact(
        result["operation_counts"],
        set(topology["operations"]),
        "profile operation counts",
    )
    operation_total = sum(
        _integer(value, "profile operation count")
        for value in counts.values()
    )
    attempts = _integer(
        result["attempts"],
        "profile attempts",
        minimum=1,
    )
    successful = _integer(
        result["successful_operations"],
        "profile successful operations",
        minimum=1,
    )
    if (
        operation_total != successful
        or not attempts <= successful <= attempts * 3
    ):
        raise LocalArtifactError("profile operation totals changed")
    for key in (
        "duration_seconds",
        "maximum_clients",
        "order",
        "waves",
    ):
        _integer(result[key], f"profile {key}", minimum=1)
    _integer(
        result["transferred_bytes"],
        "profile transferred bytes",
        maximum=topology["profiles"]["soak"]["transfer_ceiling_bytes"],
    )
    for key in (
        "last_wave_sha256",
        "plan_sha256",
        "profile_binding_sha256",
    ):
        _sha256(result[key], f"profile {key}")
    try:
        load_contract.validate_retained_evidence(result)
    except load_contract.LoadSoakError as error:
        raise LocalArtifactError("profile result is not retainable") from error
    return (
        _integer(result["unexpected_errors"], "profile unexpected errors"),
        str(result["plan_sha256"]),
    )


def _fault_result(
    value: object,
    *,
    topology: Mapping[str, Any],
) -> tuple[int, str]:
    result = _exact(value, FAULT_KEYS, "fault result")
    fault = result["fault"]
    if (
        result["schema"] != FAULT_SCHEMA
        or result["execution_source"] != "pilot"
        or result["synthetic"] is not False
        or not isinstance(fault, str)
        or fault not in topology["faults"]
        or result["actions_completed"] != 5
        or result["window_seconds"]
        != topology["faults"][fault]["window_seconds"]
        or result["recovery_seconds"]
        != topology["faults"][fault]["recovery_seconds"]
    ):
        raise LocalArtifactError("fault result source changed")
    for key in (
        "fault_binding_sha256",
        "history_sha256",
        "plan_sha256",
        "target_evidence_sha256",
    ):
        _sha256(result[key], f"fault {key}")
    try:
        load_contract.validate_retained_evidence(result)
    except load_contract.LoadSoakError as error:
        raise LocalArtifactError("fault result is not retainable") from error
    return (
        _integer(result["unexpected_errors"], "fault unexpected errors"),
        str(result["plan_sha256"]),
    )


def _descriptors(
    value: object,
    *,
    workload: bool,
) -> list[Mapping[str, Any]]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_FILES
    ):
        raise LocalArtifactError("local input file set is invalid")
    keys = (
        {"file", "file_sha256", "kind"}
        if workload
        else {"file", "file_sha256"}
    )
    descriptors = [
        _exact(item, keys, "local input descriptor")
        for item in value
    ]
    hashes = [
        _sha256(item["file_sha256"], "local input file")
        for item in descriptors
    ]
    if len(set(hashes)) != len(hashes):
        raise LocalArtifactError("local input file set is duplicated")
    if workload and any(
        item["kind"] not in ("profile", "fault")
        for item in descriptors
    ):
        raise LocalArtifactError("workload result kind is invalid")
    return descriptors


def compile_artifact(
    config_value: object,
    target_value: object,
    payloads: Sequence[bytes],
    *,
    target_file_sha256: str,
) -> dict[str, Any]:
    config = _exact(
        config_value,
        {
            "collector_source_sha256",
            "phase",
            "schema",
            "source",
            "surface",
            "target_file",
            "target_file_sha256",
            "window_sha256",
        },
        "local artifact configuration",
    )
    surface = config["surface"]
    if (
        config["schema"] != CONFIG_SCHEMA
        or config["collector_source_sha256"] != collector_source_sha256()
        or surface not in SURFACES
        or config["phase"] not in native_target.PHASES
        or config["target_file_sha256"] != target_file_sha256
    ):
        raise LocalArtifactError("local artifact binding changed")
    window_sha256 = _sha256(
        config["window_sha256"],
        "local artifact window",
    )
    source = _exact(
        config["source"],
        (
            {"files", "fingerprints", "kind"}
            if surface == "prometheus"
            else {"files", "kind"}
        ),
        "local artifact source",
    )
    if source["kind"] != SOURCE_KINDS[surface]:
        raise LocalArtifactError("local artifact source kind changed")
    descriptors = _descriptors(
        source["files"],
        workload=surface == "haproxy",
    )
    if len(payloads) != len(descriptors):
        raise LocalArtifactError("local input file set changed")
    total_bytes = sum(len(payload) for payload in payloads)
    if not 1 <= total_bytes <= MAX_TOTAL_BYTES:
        raise LocalArtifactError("local input byte total is invalid")
    for descriptor, payload in zip(descriptors, payloads):
        if (
            not 1 <= len(payload) <= MAX_FILE_BYTES
            or descriptor["file_sha256"] != _payload_hash(payload)
        ):
            raise LocalArtifactError("local input file hash changed")
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
        raise LocalArtifactError("native target is invalid") from error
    safe_source: dict[str, Any]
    if surface == "prometheus":
        raw_fingerprints = source["fingerprints"]
        if (
            not isinstance(raw_fingerprints, list)
            or len(raw_fingerprints) > MAX_FINGERPRINTS
        ):
            raise LocalArtifactError("local fingerprint set is invalid")
        fingerprints = [
            _fingerprint(item) for item in raw_fingerprints
        ]
        identities = [
            (item["length"], item["rolling64"], item["sha256"])
            for item in fingerprints
        ]
        if len(set(identities)) != len(identities):
            raise LocalArtifactError("local fingerprint set is duplicated")
        aggregate = {
            "secret_leaks": _secret_scan(payloads, fingerprints),
        }
        safe_source = {
            "files": [
                {"file_sha256": item["file_sha256"]}
                for item in descriptors
            ],
            "fingerprints": fingerprints,
            "kind": source["kind"],
        }
    else:
        unexpected_errors = 0
        plan_sha256: str | None = None
        safe_files = []
        for descriptor, payload in zip(descriptors, payloads):
            value = _canonical_document(payload, "workload result")
            if descriptor["kind"] == "profile":
                errors, current_plan = _profile_result(
                    value,
                    topology=load_topology,
                )
            else:
                errors, current_plan = _fault_result(
                    value,
                    topology=load_topology,
                )
            if plan_sha256 is None:
                plan_sha256 = current_plan
            elif current_plan != plan_sha256:
                raise LocalArtifactError("workload result plan changed")
            unexpected_errors += errors
            if unexpected_errors > phase_evidence.MAX_COUNT:
                raise LocalArtifactError(
                    "local artifact count is excessive"
                )
            safe_files.append(
                {
                    "file_sha256": descriptor["file_sha256"],
                    "kind": descriptor["kind"],
                }
            )
        aggregate = {"unexpected_errors": unexpected_errors}
        safe_source = {
            "files": safe_files,
            "kind": source["kind"],
            "plan_sha256": plan_sha256,
        }
    normalized = phase_evidence._normalize_payload(
        str(surface),
        aggregate,
        load_topology=load_topology,
    )
    artifact = {
        "aggregate": normalized,
        "collector_source_sha256": collector_source_sha256(),
        "input_set_sha256": _hash(safe_source),
        "observations": len(payloads),
        "phase": config["phase"],
        "schema": source_summaries.ARTIFACT_SCHEMA,
        "source_class": phase_evidence.SOURCE_CLASSES[str(surface)],
        "surface": surface,
        "target_sha256": target["target_sha256"],
        "window_sha256": window_sha256,
    }
    artifact["artifact_sha256"] = _hash(artifact)
    try:
        load_contract.validate_retained_evidence(artifact)
        observability_contract.validate_retained_payload(artifact)
    except (
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ) as error:
        raise LocalArtifactError("local artifact is not retainable") from error
    return json.loads(
        json.dumps(artifact, separators=(",", ":"), sort_keys=True)
    )


def _distinct_files(
    files: Sequence[tuple[Path, os.stat_result]],
) -> None:
    paths = [path for path, _ in files]
    identities = [
        (metadata.st_dev, metadata.st_ino)
        for _, metadata in files
    ]
    if len(set(paths)) != len(paths) or len(set(identities)) != len(identities):
        raise LocalArtifactError("local artifact input files alias")


def compile_file(config_path: Path, output_path: Path) -> dict[str, Any]:
    config_path = _absolute_path(str(config_path), "configuration file")
    output_path = _absolute_path(str(output_path), "artifact output")
    try:
        config_value, _, config_metadata = (
            source_summaries._read_owner_document(config_path)
        )
    except source_summaries.SourceSummaryError as error:
        raise LocalArtifactError(
            "local artifact configuration is unavailable"
        ) from error
    config = _exact(
        config_value,
        {
            "collector_source_sha256",
            "phase",
            "schema",
            "source",
            "surface",
            "target_file",
            "target_file_sha256",
            "window_sha256",
        },
        "local artifact configuration",
    )
    target_file = _absolute_path(config["target_file"], "target file")
    try:
        target_value, target_payload, target_metadata = (
            source_summaries._read_owner_document(target_file)
        )
    except source_summaries.SourceSummaryError as error:
        raise LocalArtifactError("native target is unavailable") from error
    surface = config["surface"]
    if surface not in SURFACES:
        raise LocalArtifactError("local artifact surface changed")
    source = _exact(
        config["source"],
        (
            {"files", "fingerprints", "kind"}
            if surface == "prometheus"
            else {"files", "kind"}
        ),
        "local artifact source",
    )
    descriptors = _descriptors(
        source["files"],
        workload=surface == "haproxy",
    )
    payloads = []
    files: list[tuple[Path, os.stat_result]] = [
        (config_path, config_metadata),
        (target_file, target_metadata),
    ]
    total_bytes = 0
    for descriptor in descriptors:
        input_file = _absolute_path(
            descriptor["file"],
            "local input file",
        )
        payload, metadata = _read_owner_bytes(input_file)
        total_bytes += len(payload)
        if total_bytes > MAX_TOTAL_BYTES:
            raise LocalArtifactError("local input byte total is invalid")
        payloads.append(payload)
        files.append((input_file, metadata))
    _distinct_files(files)
    try:
        render_target._safe_output(output_path, request_path=config_path)
    except render_target.RenderError as error:
        raise LocalArtifactError("local artifact output is unsafe") from error
    try:
        output_metadata = output_path.stat(follow_symlinks=False)
    except FileNotFoundError:
        output_metadata = None
    except OSError as error:
        raise LocalArtifactError("local artifact output is unavailable") from error
    if output_metadata is not None and (
        output_metadata.st_dev,
        output_metadata.st_ino,
    ) in {
        (metadata.st_dev, metadata.st_ino)
        for _, metadata in files
    }:
        raise LocalArtifactError("local artifact output aliases an input")
    artifact = compile_artifact(
        config,
        target_value,
        payloads,
        target_file_sha256=_payload_hash(target_payload),
    )
    payload = _canonical(artifact)
    try:
        if output_path.exists() and output_path.read_bytes() == payload:
            return artifact
    except OSError as error:
        raise LocalArtifactError(
            "local artifact output is unavailable"
        ) from error
    try:
        render_target._atomic_write(output_path, payload)
    except render_target.RenderError as error:
        raise LocalArtifactError(
            "local artifact output is unavailable"
        ) from error
    return artifact


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = collector_source_sha256()
        except LocalArtifactError:
            print("local-artifact-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "collector_source_sha256": source_sha256,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) == 2 and arguments[0] == "fingerprint":
        try:
            input_path = _absolute_path(
                arguments[1],
                "fingerprint input",
            )
            payload, _ = _read_owner_bytes(
                input_path,
                maximum_bytes=MAX_FINGERPRINT_BYTES,
                minimum_bytes=MIN_FINGERPRINT_BYTES,
            )
            result = fingerprint(payload)
        except LocalArtifactError:
            print("local-artifact-refused", file=sys.stderr)
            return 2
        print(_canonical(result).decode("utf-8"), end="")
        return 0
    if len(arguments) != 3 or arguments[0] != "compile":
        print("local-artifact-refused", file=sys.stderr)
        return 2
    try:
        artifact = compile_file(
            Path(arguments[1]),
            Path(arguments[2]),
        )
    except (
        LocalArtifactError,
        source_summaries.SourceSummaryError,
        phase_evidence.PhaseEvidenceError,
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ):
        print("local-artifact-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "artifact_sha256": artifact["artifact_sha256"],
                "schema": RESULT_SCHEMA,
                "surface": artifact["surface"],
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
