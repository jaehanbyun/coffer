from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
OBSERVABILITY_RESULT_SOURCE = DIRECTORY / "observability.py"
GC_RESULT_SOURCE = DIRECTORY / "gc_retention.py"
LOAD_DIRECTORY = ROOT / "poc" / "load-soak"
TOPOLOGY_SOURCE = LOAD_DIRECTORY / "topology.json"
EVIDENCE_SOURCE = LOAD_DIRECTORY / "evidence.py"
RUNTIME_SOURCES = {
    "client_contract_sha256": LOAD_DIRECTORY / "clients" / "contract.py",
    "client_pins_sha256": LOAD_DIRECTORY / "clients" / "pins.json",
    "client_runner_sha256": LOAD_DIRECTORY / "clients" / "run.py",
    "control_driver_sha256": LOAD_DIRECTORY / "control" / "driver.go",
    "data_lifecycle_sha256": LOAD_DIRECTORY / "lifecycle.py",
    "data_state_machine_sha256": LOAD_DIRECTORY / "state_machine.py",
    "data_topology_sha256": TOPOLOGY_SOURCE,
    "evidence_verifier_sha256": EVIDENCE_SOURCE,
    "fault_runner_sha256": LOAD_DIRECTORY / "fault" / "run.py",
    "gc_result_verifier_sha256": GC_RESULT_SOURCE,
    "observability_result_verifier_sha256": (
        OBSERVABILITY_RESULT_SOURCE
    ),
    "pilot_actions_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_actions.py"
    ),
    "pilot_cleanup_sha256": (
        LOAD_DIRECTORY / "collector" / "rgw_cleanup.py"
    ),
    "pilot_executor_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_executor.py"
    ),
    "pilot_fault_actions_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_fault_actions.py"
    ),
    "pilot_fault_controller_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_fault_controller.py"
    ),
    "pilot_inputs_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_inputs.py"
    ),
    "pilot_phase_actions_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_phase_actions.py"
    ),
    "pilot_rgw_actions_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_rgw_actions.py"
    ),
    "pilot_run_sha256": LOAD_DIRECTORY / "collector" / "pilot_run.py",
    "pilot_schedule_sha256": (
        LOAD_DIRECTORY / "collector" / "pilot_schedule.py"
    ),
    "profile_runner_sha256": LOAD_DIRECTORY / "profile" / "run.py",
    "raw_oci_driver_sha256": LOAD_DIRECTORY / "driver" / "invocation.go",
    "telemetry_sha256": LOAD_DIRECTORY / "telemetry.py",
}

SCHEMA = "coffer.production-promotion-load-soak-result/v1"
EVIDENCE_SCHEMA = "coffer.production-promotion-load-soak-evidence/v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
EXECUTOR_ACTION_COUNT = 53
RUNTIME_SOURCE_SUFFIXES = {".go", ".json", ".mod", ".py", ".sum"}


class LoadSoakResultError(RuntimeError):
    pass


class LoadSoakInputsBlocked(LoadSoakResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise LoadSoakResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise LoadSoakResultError(f"unable to load {path}") from error
    return module


OBSERVABILITY_RESULT = _load_module(
    "coffer_load_promotion_observability",
    OBSERVABILITY_RESULT_SOURCE,
)
GC_RESULT = _load_module(
    "coffer_load_promotion_gc",
    GC_RESULT_SOURCE,
)
RGW_KMS_RESULT = OBSERVABILITY_RESULT.RGW_KMS_RESULT
LOAD_EVIDENCE = _load_module(
    "coffer_load_promotion_evidence",
    EVIDENCE_SOURCE,
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise LoadSoakResultError(f"unable to hash {path}") from error


def _hash(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _runtime_tree_hash() -> str:
    digest = hashlib.sha256()
    sources = [
        path
        for path in LOAD_DIRECTORY.rglob("*")
        if (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in RUNTIME_SOURCE_SUFFIXES
            and not path.name.endswith("_test.go")
        )
    ]
    if not sources:
        raise LoadSoakResultError("load/soak runtime source tree is empty")
    for path in sorted(sources):
        relative = path.relative_to(LOAD_DIRECTORY).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return "sha256:" + digest.hexdigest()


def runtime_source_hashes() -> dict[str, str]:
    return {
        "load_harness_tree_sha256": _runtime_tree_hash(),
        **{
            name: _sha256(path)
            for name, path in sorted(RUNTIME_SOURCES.items())
        },
    }


def source_hashes() -> dict[str, str]:
    return {
        "load_soak_compiler_sha256": _sha256(Path(__file__).resolve()),
        **runtime_source_hashes(),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LoadSoakResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise LoadSoakResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise LoadSoakResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LoadSoakResultError(f"{label} is invalid")
    return value


def _qualified_prerequisites(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    maintenance_result: object,
    maintenance_digest: str,
    data_protection_result: object,
    data_protection_digest: str,
    observability_result: object,
    observability_digest: str,
    gc_result: object,
    gc_digest: str,
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    try:
        base = OBSERVABILITY_RESULT._qualified_prerequisites(
            release_readiness=release_readiness,
            release_digest=release_digest,
            artifact_result=artifact_result,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms_result,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_result=maintenance_result,
            maintenance_digest=maintenance_digest,
            data_protection_result=data_protection_result,
            data_protection_digest=data_protection_digest,
        )
        qualified_observability = (
            OBSERVABILITY_RESULT.validate_final_result(
                observability_result
            )
        )
        qualified_gc = GC_RESULT.validate_final_result(gc_result)
    except OBSERVABILITY_RESULT.ObservabilityInputsBlocked as error:
        raise LoadSoakInputsBlocked(str(error)) from error
    except OBSERVABILITY_RESULT.ObservabilityResultError as error:
        raise LoadSoakInputsBlocked(
            "observability is not candidate-qualified"
        ) from error
    except GC_RESULT.ProductionGCResultError as error:
        raise LoadSoakInputsBlocked(
            "GC retention is not candidate-qualified"
        ) from error
    if qualified_observability["prerequisites"] != base:
        raise LoadSoakInputsBlocked(
            "observability prerequisite binding changed"
        )
    if qualified_gc["prerequisites"] != {
        "artifact_result_sha256": base["artifact_result_sha256"],
        "release_readiness_sha256": base["release_readiness_sha256"],
    }:
        raise LoadSoakInputsBlocked("GC prerequisite binding changed")
    release = dict(_mapping(release_readiness, "release"))
    release_components = _mapping(
        release["components"],
        "release components",
    )
    release_distribution = _mapping(
        release_components["distribution"],
        "Distribution release",
    )
    if qualified_gc["distribution"] != {
        "image": GC_RESULT.GC_RESULT.IMAGE,
        "revision": release_distribution["revision"],
        "version": release_distribution["version"],
    }:
        raise LoadSoakInputsBlocked(
            "GC result does not match the current Distribution release"
        )
    prerequisites = {
        **base,
        "gc_retention_result_sha256": _digest(
            gc_digest,
            "GC retention result",
        ),
        "observability_result_sha256": _digest(
            observability_digest,
            "observability result",
        ),
    }
    return prerequisites, release, dict(
        _mapping(artifact_result, "artifacts")
    )


def _topology() -> dict[str, Any]:
    try:
        return LOAD_EVIDENCE.state_machine.load_topology(TOPOLOGY_SOURCE)
    except LOAD_EVIDENCE.state_machine.LoadSoakError as error:
        raise LoadSoakResultError("load/soak topology is invalid") from error


def _expected_bindings(
    value: object,
    *,
    release: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = _mapping(value, "load/soak runtime bindings")
    _exact_keys(
        runtime,
        {
            "client_versions_hash",
            "configuration_hash",
            "driver_revision",
        },
        "load/soak runtime bindings",
    )
    for name in ("client_versions_hash", "configuration_hash"):
        _digest(runtime[name], f"load/soak {name}")
    if (
        not isinstance(runtime["driver_revision"], str)
        or REVISION.fullmatch(runtime["driver_revision"]) is None
    ):
        raise LoadSoakResultError("load/soak driver revision is invalid")
    components = _mapping(
        release["components"],
        "release components",
    )
    distribution = _mapping(
        components["distribution"],
        "Distribution release",
    )
    ceph = _mapping(components["ceph"], "Ceph release")
    topology = _topology()
    return {
        "architectures": list(topology["required_architectures"]),
        "ceph_revision": ceph["revision"],
        "ceph_version": ceph["version"],
        "client_versions_hash": runtime["client_versions_hash"],
        "configuration_hash": runtime["configuration_hash"],
        "distribution_revision": distribution["revision"],
        "distribution_version": distribution["version"],
        "driver_revision": runtime["driver_revision"],
        "image_set_hash": _hash(artifact),
        "readiness_evidence_hash": release[
            "source_bound_digest"
        ],
        "readiness_status": "qualified",
    }


def _release_with_digest(
    release: Mapping[str, Any],
    release_digest: str,
) -> dict[str, Any]:
    return {**dict(release), "source_bound_digest": release_digest}


def _validate_execution(value: object) -> dict[str, Any]:
    execution = _mapping(value, "load/soak execution")
    _exact_keys(
        execution,
        {
            "adapter",
            "action_count",
            "checkpoint_count",
            "disposable",
            "executor_result_sha256",
            "non_synthetic",
            "resume_verified",
        },
        "load/soak execution",
    )
    action_count = _positive_integer(
        execution["action_count"],
        "load/soak action count",
    )
    checkpoint_count = _positive_integer(
        execution["checkpoint_count"],
        "load/soak checkpoint count",
    )
    if (
        execution["adapter"] != "openstack"
        or execution["disposable"] is not True
        or execution["non_synthetic"] is not True
        or execution["resume_verified"] is not True
        or action_count != EXECUTOR_ACTION_COUNT
        or checkpoint_count != EXECUTOR_ACTION_COUNT
    ):
        raise LoadSoakResultError(
            "load/soak execution is not a complete live pilot"
        )
    return {
        "action_count": action_count,
        "adapter": "openstack",
        "checkpoint_count": checkpoint_count,
        "disposable": True,
        "executor_result_sha256": _digest(
            execution["executor_result_sha256"],
            "load/soak executor result",
        ),
        "non_synthetic": True,
        "resume_verified": True,
    }


def _validate_coverage(value: object) -> dict[str, int]:
    coverage = _mapping(value, "load/soak coverage")
    _exact_keys(
        coverage,
        {
            "architecture_count",
            "client_count",
            "content_class_count",
            "failure_case_count",
            "fault_count",
            "operation_count",
            "phase_count",
            "profile_count",
            "soak_seconds",
        },
        "load/soak coverage",
    )
    topology = _topology()
    expected = {
        "architecture_count": len(topology["required_architectures"]),
        "client_count": len(topology["clients"]),
        "content_class_count": len(topology["content_classes"]),
        "failure_case_count": len(topology["failure_cases"]),
        "fault_count": len(topology["faults"]),
        "operation_count": len(topology["operations"]),
        "phase_count": len(topology["phases"]),
        "profile_count": len(topology["profiles"]),
        "soak_seconds": topology["profiles"]["soak"]["duration_seconds"],
    }
    if coverage != expected:
        raise LoadSoakResultError("load/soak coverage is incomplete")
    return dict(expected)


def _validate_audit(value: object) -> dict[str, int]:
    audit = _mapping(value, "load/soak audit")
    _exact_keys(
        audit,
        {
            "known_secret_matches",
            "log_scan_count",
            "unexpected_errors",
        },
        "load/soak audit",
    )
    log_count = _positive_integer(
        audit["log_scan_count"],
        "load/soak log scan count",
    )
    if (
        audit["known_secret_matches"] != 0
        or audit["unexpected_errors"] != 0
    ):
        raise LoadSoakResultError("load/soak audit found unsafe evidence")
    return {
        "known_secret_matches": 0,
        "log_scan_count": log_count,
        "unexpected_errors": 0,
    }


def _validate_evidence(
    value: object,
    *,
    prerequisites: Mapping[str, str],
    release: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = _mapping(value, "load/soak evidence")
    _exact_keys(
        evidence,
        {
            "audit",
            "coverage",
            "execution",
            "load_document",
            "prerequisites",
            "runtime_bindings",
            "schema",
            "source",
        },
        "load/soak evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["prerequisites"] != prerequisites
        or evidence["source"] != runtime_source_hashes()
    ):
        raise LoadSoakResultError("load/soak evidence binding changed")
    release_bound = _release_with_digest(
        release,
        prerequisites["release_readiness_sha256"],
    )
    expected_bindings = _expected_bindings(
        evidence["runtime_bindings"],
        release=release_bound,
        artifact=artifact,
    )
    try:
        verified = LOAD_EVIDENCE.verify_document(
            evidence["load_document"],
            topology=_topology(),
            expected_bindings=expected_bindings,
        )
    except LOAD_EVIDENCE.EvidenceError as error:
        raise LoadSoakResultError(
            "load/soak lifecycle evidence is not qualified"
        ) from error
    result = {
        "audit": _validate_audit(evidence["audit"]),
        "coverage": _validate_coverage(evidence["coverage"]),
        "execution": _validate_execution(evidence["execution"]),
        "runtime_binding_sha256": _hash(expected_bindings),
        "verified_evidence": verified,
    }
    try:
        LOAD_EVIDENCE.state_machine.validate_retained_evidence(result)
    except LOAD_EVIDENCE.state_machine.LoadSoakError as error:
        raise LoadSoakResultError(
            "load/soak result retained forbidden data"
        ) from error
    return result


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    maintenance_result: object,
    maintenance_digest: str,
    data_protection_result: object,
    data_protection_digest: str,
    observability_result: object,
    observability_digest: str,
    gc_result: object,
    gc_digest: str,
    evidence: object,
    evidence_digest: str,
) -> dict[str, Any]:
    prerequisites, release, artifact = _qualified_prerequisites(
        release_readiness=release_readiness,
        release_digest=release_digest,
        artifact_result=artifact_result,
        artifact_digest=artifact_digest,
        rgw_kms_result=rgw_kms_result,
        rgw_kms_digest=rgw_kms_digest,
        maintenance_result=maintenance_result,
        maintenance_digest=maintenance_digest,
        data_protection_result=data_protection_result,
        data_protection_digest=data_protection_digest,
        observability_result=observability_result,
        observability_digest=observability_digest,
        gc_result=gc_result,
        gc_digest=gc_digest,
    )
    validated = _validate_evidence(
        evidence,
        prerequisites=prerequisites,
        release=release,
        artifact=artifact,
    )
    return {
        **validated,
        "input_evidence_sha256": _digest(
            evidence_digest,
            "load/soak input evidence",
        ),
        "prerequisites": prerequisites,
        "production_candidate": True,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "load/soak result"))
    expected = {
        "audit",
        "coverage",
        "execution",
        "input_evidence_sha256",
        "prerequisites",
        "production_candidate",
        "runtime_binding_sha256",
        "schema",
        "source",
        "verified_evidence",
    }
    _exact_keys(result, expected, "load/soak result")
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise LoadSoakResultError("load/soak result is not qualified")
    prerequisites = _mapping(
        result["prerequisites"],
        "load/soak prerequisites",
    )
    expected_prerequisites = {
        "artifact_result_sha256",
        "data_protection_result_sha256",
        "gc_retention_result_sha256",
        "maintenance_identity_result_sha256",
        "observability_result_sha256",
        "release_readiness_sha256",
        "rgw_kms_result_sha256",
    }
    _exact_keys(
        prerequisites,
        expected_prerequisites,
        "load/soak prerequisites",
    )
    for name in expected_prerequisites:
        _digest(prerequisites[name], f"load/soak prerequisite {name}")
    _digest(result["input_evidence_sha256"], "load/soak input evidence")
    _digest(result["runtime_binding_sha256"], "load/soak runtime binding")
    _validate_execution(result["execution"])
    _validate_coverage(result["coverage"])
    _validate_audit(result["audit"])
    verified = _mapping(
        result["verified_evidence"],
        "verified load/soak evidence",
    )
    _exact_keys(
        verified,
        {
            "binding_hash",
            "evidence_hash",
            "facts_hash",
            "history_hash",
            "phase_count",
            "schema",
            "topology_hash",
        },
        "verified load/soak evidence",
    )
    if (
        verified["schema"] != LOAD_EVIDENCE.VERIFIED_SCHEMA
        or verified["phase_count"] != len(_topology()["phases"])
    ):
        raise LoadSoakResultError(
            "verified load/soak lifecycle is incomplete"
        )
    for name in (
        "binding_hash",
        "evidence_hash",
        "facts_hash",
        "history_hash",
        "topology_hash",
    ):
        _digest(verified[name], f"verified load/soak {name}")
    try:
        LOAD_EVIDENCE.state_machine.validate_retained_evidence(result)
    except LOAD_EVIDENCE.state_machine.LoadSoakError as error:
        raise LoadSoakResultError(
            "load/soak result retained forbidden data"
        ) from error
    return result


def _load_private(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
        ):
            raise LoadSoakResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 32 * 1024 * 1024:
            raise LoadSoakResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except LoadSoakResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LoadSoakResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise LoadSoakResultError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise LoadSoakResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise LoadSoakResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise LoadSoakResultError(
            "output directory ownership is unsafe"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError as error:
        raise LoadSoakResultError(
            "unable to write load/soak result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _load_prerequisite(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], str]:
    try:
        return _load_private(path, label)
    except LoadSoakResultError as error:
        raise LoadSoakInputsBlocked(
            f"{label} is absent or unsafe"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the complete non-synthetic private-TLS/shared-SQL/RGW "
            "client, load, fault, recovery, and teardown matrix only after "
            "all prior production-promotion results qualify."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--artifact-result", type=Path, required=True)
    parser.add_argument("--rgw-kms-result", type=Path, required=True)
    parser.add_argument(
        "--maintenance-identity-result",
        type=Path,
        required=True,
    )
    parser.add_argument("--data-protection-result", type=Path, required=True)
    parser.add_argument("--observability-result", type=Path, required=True)
    parser.add_argument("--gc-retention-result", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness,
            "release readiness",
        )
        try:
            RGW_KMS_RESULT.require_release_qualified(release)
        except RGW_KMS_RESULT.RgwKmsInputsBlocked as error:
            raise LoadSoakInputsBlocked(str(error)) from error
        artifact, artifact_digest = _load_prerequisite(
            arguments.artifact_result,
            "artifact specialist result",
        )
        rgw_kms, rgw_kms_digest = _load_prerequisite(
            arguments.rgw_kms_result,
            "RGW/KMS specialist result",
        )
        maintenance, maintenance_digest = _load_prerequisite(
            arguments.maintenance_identity_result,
            "maintenance identity specialist result",
        )
        data_protection, data_protection_digest = _load_prerequisite(
            arguments.data_protection_result,
            "data-protection specialist result",
        )
        observability, observability_digest = _load_prerequisite(
            arguments.observability_result,
            "observability specialist result",
        )
        gc_result, gc_digest = _load_prerequisite(
            arguments.gc_retention_result,
            "GC retention specialist result",
        )
        prerequisites, _, _ = _qualified_prerequisites(
            release_readiness=release,
            release_digest=release_digest,
            artifact_result=artifact,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_result=maintenance,
            maintenance_digest=maintenance_digest,
            data_protection_result=data_protection,
            data_protection_digest=data_protection_digest,
            observability_result=observability,
            observability_digest=observability_digest,
            gc_result=gc_result,
            gc_digest=gc_digest,
        )
        evidence, evidence_digest = _load_private(
            arguments.evidence,
            "load/soak evidence",
        )
        if evidence.get("prerequisites") != prerequisites:
            raise LoadSoakResultError(
                "load/soak evidence prerequisite binding changed"
            )
        result = compile_result(
            release_readiness=release,
            release_digest=release_digest,
            artifact_result=artifact,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_result=maintenance,
            maintenance_digest=maintenance_digest,
            data_protection_result=data_protection,
            data_protection_digest=data_protection_digest,
            observability_result=observability,
            observability_digest=observability_digest,
            gc_result=gc_result,
            gc_digest=gc_digest,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except LoadSoakInputsBlocked as error:
        print(
            f"production load/soak gate blocked: {error}",
            file=sys.stderr,
        )
        return 3
    except LoadSoakResultError as error:
        print(
            f"production load/soak result error: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
