from __future__ import annotations

import hashlib
import importlib.util
import json
import math
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


native_target = _module(
    "coffer_load_phase_evidence_native_target",
    DIRECTORY / "native_target.py",
)
native_surfaces = _module(
    "coffer_load_phase_evidence_native_surfaces",
    DIRECTORY / "native_surfaces.py",
)
render_target = _module(
    "coffer_load_phase_evidence_target_renderer",
    DIRECTORY / "render_target.py",
)
load_contract = _module(
    "coffer_load_phase_evidence_load_contract",
    LOAD_DIRECTORY / "state_machine.py",
)
observability_contract = _module(
    "coffer_load_phase_evidence_observability_contract",
    POC_DIRECTORY / "observability" / "contract.py",
)

REQUEST_SCHEMA = "coffer.load-telemetry-phase-evidence-request/v1"
SUMMARY_SCHEMA = "coffer.load-telemetry-auxiliary-source-summary/v1"
BUNDLE_SCHEMA = "coffer.load-telemetry-native-evidence-bundle/v1"
RESULT_SCHEMA = "coffer.load-telemetry-phase-evidence-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-telemetry-phase-evidence-source-result/v1"
SURFACES = (
    "prometheus",
    "haproxy",
    "galera",
    "rgw",
    "quota",
    "reconciliation",
)
SOURCE_CLASSES = {
    "prometheus": "secret-scan",
    "haproxy": "workload-error-aggregate",
    "galera": "transaction-attempt-aggregate",
    "rgw": "rgw-load-state-aggregate",
    "quota": "quota-ledger-aggregate",
    "reconciliation": "reconciliation-claim-aggregate",
}
PAYLOAD_KEYS = {
    "prometheus": frozenset({"secret_leaks"}),
    "haproxy": frozenset({"unexpected_errors"}),
    "galera": frozenset(
        {"max_transaction_attempts", "unexpected_errors"}
    ),
    "rgw": frozenset(
        {"kms_errors", "multipart_uploads", "unexpected_errors"}
    ),
    "quota": frozenset(
        {
            "headroom_percent",
            "invariant",
            "limit_usage_percent",
            "max_transaction_attempts",
            "stale_claims",
            "unexpected_errors",
        }
    ),
    "reconciliation": frozenset(
        {
            "claims_exact",
            "fencing_violations",
            "fresh",
            "last_success_age_seconds",
            "stale_claims",
            "workers_total",
            "workers_up",
        }
    ),
}
SOURCE_FILES = (
    DIRECTORY / "native_surfaces.py",
    DIRECTORY / "native_target.py",
    DIRECTORY / "render_target.py",
    DIRECTORY / "phase_evidence.py",
)
MAX_COUNT = 1_000_000
MAX_TRANSACTION_ATTEMPTS = 64
MAX_FRESHNESS_SECONDS = 86_400


class PhaseEvidenceError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise PhaseEvidenceError(f"{category} boundary changed")
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


def compiler_source_sha256() -> str:
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
        raise PhaseEvidenceError("compiler source is unavailable") from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise PhaseEvidenceError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_COUNT,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise PhaseEvidenceError(f"{category} is invalid")
    return value


def _number(
    value: object,
    category: str,
    *,
    minimum: float = 0,
    maximum: float,
) -> float | int:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or float(value) > maximum
    ):
        raise PhaseEvidenceError(f"{category} is invalid")
    return value


def _boolean(value: object, category: str) -> bool:
    if not isinstance(value, bool):
        raise PhaseEvidenceError(f"{category} is invalid")
    return value


def _normalize_payload(
    surface: str,
    value: object,
    *,
    load_topology: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _exact(value, PAYLOAD_KEYS[surface], f"{surface} payload")
    if surface == "prometheus":
        return {
            "secret_leaks": _integer(
                payload["secret_leaks"],
                "secret leak count",
            )
        }
    if surface == "haproxy":
        return {
            "unexpected_errors": _integer(
                payload["unexpected_errors"],
                "HAProxy unexpected error count",
            )
        }
    if surface == "galera":
        return {
            "max_transaction_attempts": _integer(
                payload["max_transaction_attempts"],
                "Galera transaction attempts",
                minimum=1,
                maximum=MAX_TRANSACTION_ATTEMPTS,
            ),
            "unexpected_errors": _integer(
                payload["unexpected_errors"],
                "Galera unexpected error count",
            ),
        }
    if surface == "rgw":
        return {
            "kms_errors": _integer(
                payload["kms_errors"],
                "KMS error count",
            ),
            "multipart_uploads": _integer(
                payload["multipart_uploads"],
                "multipart upload count",
            ),
            "unexpected_errors": _integer(
                payload["unexpected_errors"],
                "RGW unexpected error count",
            ),
        }
    if surface == "quota":
        try:
            native_surfaces.parse_quota_surface(payload)
        except native_surfaces.NativeSurfaceError as error:
            raise PhaseEvidenceError("quota payload is invalid") from error
        attempts = _integer(
            payload["max_transaction_attempts"],
            "quota transaction attempts",
            minimum=1,
            maximum=MAX_TRANSACTION_ATTEMPTS,
        )
        headroom = _number(
            payload["headroom_percent"],
            "quota headroom",
            maximum=100,
        )
        usage = _number(
            payload["limit_usage_percent"],
            "quota usage",
            maximum=100,
        )
        if abs(float(headroom) + float(usage) - 100) > 0.001:
            raise PhaseEvidenceError("quota percentages are inconsistent")
        return {
            "headroom_percent": headroom,
            "invariant": _boolean(
                payload["invariant"],
                "quota invariant",
            ),
            "limit_usage_percent": usage,
            "max_transaction_attempts": attempts,
            "stale_claims": _integer(
                payload["stale_claims"],
                "quota stale claims",
            ),
            "unexpected_errors": _integer(
                payload["unexpected_errors"],
                "quota unexpected errors",
            ),
        }
    try:
        normalized = native_surfaces.parse_reconciliation_surface(payload)
    except native_surfaces.NativeSurfaceError as error:
        raise PhaseEvidenceError(
            "reconciliation payload is invalid"
        ) from error
    expected_workers = int(load_topology["replicas"]["reconcile"])
    if normalized["workers_total"] != expected_workers:
        raise PhaseEvidenceError("reconciliation worker topology changed")
    return {
        "claims_exact": _boolean(
            payload["claims_exact"],
            "reconciliation claim invariant",
        ),
        "fencing_violations": _integer(
            payload["fencing_violations"],
            "reconciliation fencing violations",
        ),
        "fresh": _boolean(
            payload["fresh"],
            "reconciliation freshness",
        ),
        "last_success_age_seconds": _number(
            payload["last_success_age_seconds"],
            "reconciliation last success age",
            maximum=MAX_FRESHNESS_SECONDS,
        ),
        "stale_claims": _integer(
            payload["stale_claims"],
            "reconciliation stale claims",
        ),
        "workers_total": expected_workers,
        "workers_up": _integer(
            payload["workers_up"],
            "reconciliation workers up",
            maximum=expected_workers,
        ),
    }


def _summary(
    value: object,
    *,
    phase: str,
    surface: str,
    window_sha256: str,
    load_topology: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    summary = _exact(
        value,
        {
            "payload",
            "phase",
            "schema",
            "source_class",
            "summary_sha256",
            "surface",
            "window_sha256",
        },
        f"{surface} source summary",
    )
    if (
        summary["schema"] != SUMMARY_SCHEMA
        or summary["phase"] != phase
        or summary["surface"] != surface
        or summary["source_class"] != SOURCE_CLASSES[surface]
        or summary["window_sha256"] != window_sha256
    ):
        raise PhaseEvidenceError(f"{surface} source summary binding changed")
    payload = _normalize_payload(
        surface,
        summary["payload"],
        load_topology=load_topology,
    )
    unsigned = {
        "payload": payload,
        "phase": phase,
        "schema": SUMMARY_SCHEMA,
        "source_class": SOURCE_CLASSES[surface],
        "surface": surface,
        "window_sha256": window_sha256,
    }
    summary_sha256 = _sha256(
        summary["summary_sha256"],
        f"{surface} source summary hash",
    )
    if summary_sha256 != _hash(unsigned):
        raise PhaseEvidenceError(f"{surface} source summary hash changed")
    return payload, summary_sha256


def compile_bundle(
    request_value: object,
    target_value: object,
    *,
    target_file_sha256: str,
) -> dict[str, Any]:
    request = _exact(
        request_value,
        {
            "compiler_source_sha256",
            "load_topology_sha256",
            "phase",
            "schema",
            "summaries",
            "target_file_sha256",
            "target_sha256",
            "window_sha256",
        },
        "phase evidence request",
    )
    load_topology = load_contract.load_topology(
        LOAD_DIRECTORY / "topology.json"
    )
    observability_topology = observability_contract.load_topology(
        POC_DIRECTORY / "observability" / "topology.json"
    )
    topology_sha256 = native_target._hash(load_topology)
    phase = request["phase"]
    if (
        request["schema"] != REQUEST_SCHEMA
        or phase not in native_target.PHASES
        or request["compiler_source_sha256"] != compiler_source_sha256()
        or request["load_topology_sha256"] != topology_sha256
        or request["target_file_sha256"] != target_file_sha256
        or request["target_sha256"]
        != (
            target_value.get("target_sha256")
            if isinstance(target_value, Mapping)
            else None
        )
    ):
        raise PhaseEvidenceError("phase evidence request binding changed")
    _sha256(request["window_sha256"], "phase window hash")
    _sha256(request["target_file_sha256"], "target file hash")
    try:
        validated_target = native_target.validate_target(
            target_value,
            topology_sha256=topology_sha256,
            load_topology=load_topology,
            observability_topology=observability_topology,
        )
    except native_target.NativeTargetError as error:
        raise PhaseEvidenceError("native target is invalid") from error
    if validated_target.target_sha256 != request["target_sha256"]:
        raise PhaseEvidenceError("native target hash changed")
    summaries = _exact(
        request["summaries"],
        set(SURFACES),
        "phase evidence summaries",
    )
    documents: dict[str, Any] = {}
    for surface in SURFACES:
        payload, summary_sha256 = _summary(
            summaries[surface],
            phase=phase,
            surface=surface,
            window_sha256=request["window_sha256"],
            load_topology=load_topology,
        )
        document = {
            "payload": payload,
            "phase": phase,
            "schema": native_target.EVIDENCE_SCHEMA,
            "surface": surface,
        }
        document_sha256 = _hash(document)
        documents[surface] = {
            "document": document,
            "document_sha256": document_sha256,
            "source_summary_sha256": summary_sha256,
        }
    unsigned = {
        "compiler_contract_sha256": _hash(
            {
                "compiler_source_sha256": request[
                    "compiler_source_sha256"
                ],
                "load_topology_sha256": topology_sha256,
                "schema": BUNDLE_SCHEMA,
            }
        ),
        "documents": documents,
        "phase": phase,
        "schema": BUNDLE_SCHEMA,
        "target_file_sha256": target_file_sha256,
        "target_sha256": validated_target.target_sha256,
        "topology_sha256": topology_sha256,
        "window_sha256": request["window_sha256"],
    }
    bundle = {**unsigned, "bundle_sha256": _hash(unsigned)}
    try:
        load_contract.validate_retained_evidence(bundle)
        observability_contract.validate_retained_payload(bundle)
    except (
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ) as error:
        raise PhaseEvidenceError("phase evidence is not retainable") from error
    return validate_bundle(bundle)


def validate_bundle(value: object) -> dict[str, Any]:
    bundle = _exact(
        value,
        {
            "bundle_sha256",
            "compiler_contract_sha256",
            "documents",
            "phase",
            "schema",
            "target_file_sha256",
            "target_sha256",
            "topology_sha256",
            "window_sha256",
        },
        "phase evidence bundle",
    )
    load_topology = load_contract.load_topology(
        LOAD_DIRECTORY / "topology.json"
    )
    topology_sha256 = native_target._hash(load_topology)
    phase = bundle["phase"]
    if (
        bundle["schema"] != BUNDLE_SCHEMA
        or phase not in native_target.PHASES
        or bundle["topology_sha256"] != topology_sha256
        or bundle["compiler_contract_sha256"]
        != _hash(
            {
                "compiler_source_sha256": compiler_source_sha256(),
                "load_topology_sha256": topology_sha256,
                "schema": BUNDLE_SCHEMA,
            }
        )
    ):
        raise PhaseEvidenceError("phase evidence bundle binding changed")
    _sha256(bundle["target_file_sha256"], "target file hash")
    _sha256(bundle["target_sha256"], "native target hash")
    _sha256(bundle["window_sha256"], "phase window hash")
    documents = _exact(
        bundle["documents"],
        set(SURFACES),
        "phase evidence documents",
    )
    normalized_documents: dict[str, Any] = {}
    for surface in SURFACES:
        retained = _exact(
            documents[surface],
            {
                "document",
                "document_sha256",
                "source_summary_sha256",
            },
            f"{surface} retained evidence",
        )
        document = _exact(
            retained["document"],
            {"payload", "phase", "schema", "surface"},
            f"{surface} evidence document",
        )
        if (
            document["schema"] != native_target.EVIDENCE_SCHEMA
            or document["phase"] != phase
            or document["surface"] != surface
        ):
            raise PhaseEvidenceError(
                f"{surface} evidence document binding changed"
            )
        payload = _normalize_payload(
            surface,
            document["payload"],
            load_topology=load_topology,
        )
        normalized_document = {
            "payload": payload,
            "phase": phase,
            "schema": native_target.EVIDENCE_SCHEMA,
            "surface": surface,
        }
        document_sha256 = _sha256(
            retained["document_sha256"],
            f"{surface} evidence document hash",
        )
        if document_sha256 != _hash(normalized_document):
            raise PhaseEvidenceError(
                f"{surface} evidence document hash changed"
            )
        normalized_documents[surface] = {
            "document": normalized_document,
            "document_sha256": document_sha256,
            "source_summary_sha256": _sha256(
                retained["source_summary_sha256"],
                f"{surface} source summary hash",
            ),
        }
    unsigned = {
        "compiler_contract_sha256": bundle[
            "compiler_contract_sha256"
        ],
        "documents": normalized_documents,
        "phase": phase,
        "schema": BUNDLE_SCHEMA,
        "target_file_sha256": bundle["target_file_sha256"],
        "target_sha256": bundle["target_sha256"],
        "topology_sha256": topology_sha256,
        "window_sha256": bundle["window_sha256"],
    }
    bundle_sha256 = _sha256(
        bundle["bundle_sha256"],
        "phase evidence bundle hash",
    )
    if bundle_sha256 != _hash(unsigned):
        raise PhaseEvidenceError("phase evidence bundle hash changed")
    normalized = {**unsigned, "bundle_sha256": bundle_sha256}
    try:
        load_contract.validate_retained_evidence(normalized)
        observability_contract.validate_retained_payload(normalized)
    except (
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ) as error:
        raise PhaseEvidenceError("phase evidence is not retainable") from error
    return json.loads(
        json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    )


def _read_owner_document(path: Path) -> tuple[object, bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise PhaseEvidenceError("phase evidence input is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= render_target.MAX_REQUEST_BYTES
        ):
            raise PhaseEvidenceError("phase evidence input is unsafe")
        payload = os.read(descriptor, render_target.MAX_REQUEST_BYTES + 1)
        if len(payload) != metadata.st_size:
            raise PhaseEvidenceError("phase evidence input changed")
    except OSError as error:
        raise PhaseEvidenceError("phase evidence input is unavailable") from error
    finally:
        os.close(descriptor)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PhaseEvidenceError("phase evidence input is invalid") from error
    if payload != _canonical(value):
        raise PhaseEvidenceError("phase evidence input is not canonical")
    return value, payload, metadata


def _same_file(
    left_path: Path,
    left_metadata: os.stat_result,
    right_path: Path,
    right_metadata: os.stat_result,
) -> bool:
    return (
        left_path == right_path
        or (
            left_metadata.st_dev,
            left_metadata.st_ino,
        )
        == (
            right_metadata.st_dev,
            right_metadata.st_ino,
        )
    )


def compile_file(
    request_path: Path,
    target_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    request, _, request_metadata = _read_owner_document(request_path)
    target, target_payload, target_metadata = _read_owner_document(target_path)
    if _same_file(
        request_path,
        request_metadata,
        target_path,
        target_metadata,
    ):
        raise PhaseEvidenceError("phase evidence inputs alias")
    try:
        render_target._safe_output(output_path, request_path=request_path)
    except render_target.RenderError as error:
        raise PhaseEvidenceError("phase evidence output is unsafe") from error
    try:
        output_metadata = output_path.stat(follow_symlinks=False)
    except FileNotFoundError:
        output_metadata = None
    except OSError as error:
        raise PhaseEvidenceError("phase evidence output is unavailable") from error
    if output_metadata is not None and (
        _same_file(
            target_path,
            target_metadata,
            output_path,
            output_metadata,
        )
        or _same_file(
            request_path,
            request_metadata,
            output_path,
            output_metadata,
        )
    ):
        raise PhaseEvidenceError("phase evidence output aliases an input")
    bundle = compile_bundle(
        request,
        target,
        target_file_sha256=_payload_hash(target_payload),
    )
    payload = _canonical(bundle)
    try:
        if output_path.exists() and output_path.read_bytes() == payload:
            return bundle
    except OSError as error:
        raise PhaseEvidenceError("phase evidence output is unavailable") from error
    try:
        render_target._atomic_write(output_path, payload)
    except render_target.RenderError as error:
        raise PhaseEvidenceError("phase evidence output is unavailable") from error
    return bundle


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = compiler_source_sha256()
        except PhaseEvidenceError:
            print("phase-evidence-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "compiler_source_sha256": source_sha256,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 3:
        print("phase-evidence-refused", file=sys.stderr)
        return 2
    try:
        bundle = compile_file(
            Path(arguments[0]),
            Path(arguments[1]),
            Path(arguments[2]),
        )
    except (
        PhaseEvidenceError,
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ):
        print("phase-evidence-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "bundle_sha256": bundle["bundle_sha256"],
                "phase": bundle["phase"],
                "schema": RESULT_SCHEMA,
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
