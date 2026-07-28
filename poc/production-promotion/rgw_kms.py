from __future__ import annotations

import argparse
import hashlib
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
READINESS_SOURCE = DIRECTORY / "readiness.py"
RUNTIME_SOURCES = {
    "pilot_executor_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "pilot_executor.py"
    ),
    "pilot_fault_actions_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "pilot_fault_actions.py"
    ),
    "pilot_fault_controller_sha256": (
        ROOT
        / "poc"
        / "load-soak"
        / "collector"
        / "pilot_fault_controller.py"
    ),
    "pilot_rgw_actions_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "pilot_rgw_actions.py"
    ),
    "pilot_schedule_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "pilot_schedule.py"
    ),
    "rgw_artifact_collector_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "rgw_artifacts.py"
    ),
    "rgw_cleanup_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "rgw_cleanup.py"
    ),
    "rgw_live_adapter_sha256": (
        ROOT / "poc" / "load-soak" / "collector" / "rgw_live_adapter.py"
    ),
}

SCHEMA = "coffer.production-promotion-rgw-kms-result/v1"
EVIDENCE_SCHEMA = "coffer.production-promotion-rgw-kms-evidence/v1"
RELEASE_SCHEMA = "coffer.production-promotion-release-readiness/v1"
PHASES = ("before", "during", "after")
RELEASE_COMPONENTS = ("distribution", "ceph")
OPERATIONS = (
    "copy_positive",
    "copy_zero",
    "get",
    "head",
    "put_positive",
    "put_zero",
)
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


class RgwKmsResultError(RuntimeError):
    pass


class RgwKmsInputsBlocked(RgwKmsResultError):
    pass


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise RgwKmsResultError(f"unable to hash {path}") from error


def runtime_source_hashes() -> dict[str, str]:
    return {
        name: _sha256(path)
        for name, path in sorted(RUNTIME_SOURCES.items())
    }


def source_hashes() -> dict[str, str]:
    return {
        "release_readiness_verifier_sha256": _sha256(READINESS_SOURCE),
        "rgw_kms_compiler_sha256": _sha256(Path(__file__).resolve()),
        **runtime_source_hashes(),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RgwKmsResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise RgwKmsResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise RgwKmsResultError(f"{label} is invalid")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RgwKmsResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result < 1:
        raise RgwKmsResultError(f"{label} is invalid")
    return result


def _release_sources() -> dict[str, str]:
    return {
        "upstream_classifier_sha256": _sha256(
            ROOT / "poc" / "production-images" / "check_upstream_readiness.py"
        ),
        "ui_classifier_sha256": _sha256(
            ROOT / "poc" / "ui-images" / "oslo_messaging_release_gate.py"
        ),
        "ui_contract_sha256": _sha256(
            ROOT / "poc" / "ui-images" / "oslo_messaging_release_gate.json"
        ),
    }


def require_release_qualified(value: object) -> dict[str, Any]:
    release = dict(_mapping(value, "release readiness"))
    if (
        release.get("schema") != RELEASE_SCHEMA
        or release.get("status") != "candidate-qualified"
        or release.get("release_inputs_qualified") is not True
        or release.get("production_candidate") is not False
        or release.get("blockers") != []
        or release.get("source") != _release_sources()
    ):
        raise RgwKmsInputsBlocked(
            "release inputs are not candidate-qualified"
        )
    components = _mapping(
        release.get("components"),
        "release readiness components",
    )
    if set(components) != {
        "distribution",
        "ceph",
        "oslo_messaging",
    }:
        raise RgwKmsInputsBlocked(
            "release input components are incomplete"
        )
    for name, raw in components.items():
        component = _mapping(raw, f"release readiness {name}")
        if (
            component.get("status") != "candidate-qualified"
            or component.get("reasons") != []
            or not isinstance(component.get("version"), str)
            or not component["version"]
            or not isinstance(component.get("revision"), str)
            or REVISION.fullmatch(component["revision"]) is None
        ):
            raise RgwKmsInputsBlocked(
                f"release input {name} is not candidate-qualified"
            )
    return release


def _release_identity(release: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    components = _mapping(release["components"], "release components")
    return {
        name: {
            "revision": str(_mapping(components[name], name)["revision"]),
            "version": str(_mapping(components[name], name)["version"]),
        }
        for name in RELEASE_COMPONENTS
    }


def _validate_execution(value: object) -> dict[str, Any]:
    execution = _mapping(value, "RGW/KMS execution")
    _exact_keys(
        execution,
        {
            "cleanup_evidence_sha256",
            "least_privilege_evidence_sha256",
            "non_synthetic",
            "phase_completion_sha256",
            "phase_count",
            "restart_evidence_sha256",
            "rotation_evidence_sha256",
        },
        "RGW/KMS execution",
    )
    phases = _mapping(
        execution["phase_completion_sha256"],
        "RGW/KMS phase completion",
    )
    if (
        execution["non_synthetic"] is not True
        or execution["phase_count"] != len(PHASES)
        or set(phases) != set(PHASES)
    ):
        raise RgwKmsResultError("RGW/KMS execution is incomplete")
    return {
        "cleanup_evidence_sha256": _digest(
            execution["cleanup_evidence_sha256"],
            "cleanup evidence",
        ),
        "least_privilege_evidence_sha256": _digest(
            execution["least_privilege_evidence_sha256"],
            "least-privilege evidence",
        ),
        "non_synthetic": True,
        "phase_completion_sha256": {
            phase: _digest(phases[phase], f"{phase} phase completion")
            for phase in PHASES
        },
        "phase_count": len(PHASES),
        "restart_evidence_sha256": _digest(
            execution["restart_evidence_sha256"],
            "restart evidence",
        ),
        "rotation_evidence_sha256": _digest(
            execution["rotation_evidence_sha256"],
            "rotation evidence",
        ),
    }


def _validate_transport(value: object) -> dict[str, Any]:
    transport = _mapping(value, "RGW/KMS transport")
    expected = {
        "barbican_sse_kms",
        "credential_policy_denials_verified",
        "least_privilege_verified",
        "private_tls_verified",
        "s3_addressing_style",
        "s3_signature_version",
        "versioning_enabled",
    }
    _exact_keys(transport, expected, "RGW/KMS transport")
    if (
        any(
            transport[name] is not True
            for name in expected
            - {"s3_addressing_style", "s3_signature_version"}
        )
        or transport["s3_addressing_style"] != "path"
        or transport["s3_signature_version"] != "v4"
    ):
        raise RgwKmsResultError(
            "RGW/KMS private transport or least privilege is not qualified"
        )
    return dict(transport)


def _validate_operations(value: object) -> dict[str, bool]:
    operations = _mapping(value, "RGW/KMS operations")
    if set(operations) != set(OPERATIONS) or any(
        operations[name] is not True for name in OPERATIONS
    ):
        raise RgwKmsResultError("RGW/KMS operation coverage is incomplete")
    return {name: True for name in OPERATIONS}


def _validate_faults(value: object) -> dict[str, dict[str, Any]]:
    faults = _mapping(value, "RGW/KMS faults")
    if set(faults) != {"kms_outage", "wrong_key"}:
        raise RgwKmsResultError("RGW/KMS fault coverage is incomplete")
    result: dict[str, dict[str, Any]] = {}
    for name in ("wrong_key", "kms_outage"):
        fault = _mapping(faults[name], f"RGW/KMS {name}")
        _exact_keys(
            fault,
            {"evidence_sha256", "failed_closed", "recovered"},
            f"RGW/KMS {name}",
        )
        if fault["failed_closed"] is not True or fault["recovered"] is not True:
            raise RgwKmsResultError(
                f"RGW/KMS {name} recovery is not qualified"
            )
        result[name] = {
            "evidence_sha256": _digest(
                fault["evidence_sha256"],
                f"{name} evidence",
            ),
            "failed_closed": True,
            "recovered": True,
        }
    return result


def _validate_unexpected_errors(value: object) -> dict[str, int]:
    errors = _mapping(value, "RGW/KMS unexpected errors")
    _exact_keys(
        errors,
        {"kms", "storage"},
        "RGW/KMS unexpected errors",
    )
    result = {
        name: _nonnegative_integer(
            errors[name],
            f"RGW/KMS unexpected {name} errors",
        )
        for name in ("kms", "storage")
    }
    if any(result.values()):
        raise RgwKmsResultError("RGW/KMS unexpected errors remain")
    return result


def _validate_rotation(value: object) -> dict[str, Any]:
    rotation = _mapping(value, "RGW/KMS rotation")
    _exact_keys(
        rotation,
        {
            "generation_count",
            "new_key_write_read",
            "old_key_readable_during_overlap",
            "old_key_revoked_after_overlap",
            "overlapping",
        },
        "RGW/KMS rotation",
    )
    generation_count = _positive_integer(
        rotation["generation_count"],
        "RGW/KMS rotation generations",
    )
    if (
        generation_count < 2
        or rotation["overlapping"] is not True
        or rotation["old_key_readable_during_overlap"] is not True
        or rotation["new_key_write_read"] is not True
        or rotation["old_key_revoked_after_overlap"] is not True
    ):
        raise RgwKmsResultError("RGW/KMS key rotation is not qualified")
    return {
        "generation_count": generation_count,
        "new_key_write_read": True,
        "old_key_readable_during_overlap": True,
        "old_key_revoked_after_overlap": True,
        "overlapping": True,
    }


def _validate_restart(value: object) -> dict[str, Any]:
    restart = _mapping(value, "RGW/KMS restart")
    _exact_keys(
        restart,
        {
            "distribution_restart_count",
            "positive_object_persisted",
            "rgw_restart_count",
            "zero_object_persisted",
        },
        "RGW/KMS restart",
    )
    distribution_count = _positive_integer(
        restart["distribution_restart_count"],
        "Distribution restart count",
    )
    rgw_count = _positive_integer(
        restart["rgw_restart_count"],
        "RGW restart count",
    )
    if (
        restart["positive_object_persisted"] is not True
        or restart["zero_object_persisted"] is not True
    ):
        raise RgwKmsResultError("RGW/KMS restart persistence is not qualified")
    return {
        "distribution_restart_count": distribution_count,
        "positive_object_persisted": True,
        "rgw_restart_count": rgw_count,
        "zero_object_persisted": True,
    }


def _validate_cleanup(value: object) -> dict[str, int]:
    cleanup = _mapping(value, "RGW/KMS cleanup")
    names = {
        "delete_markers_after",
        "delete_markers_before",
        "multipart_uploads_after",
        "multipart_uploads_before",
        "object_versions_after",
        "object_versions_before",
        "objects_after",
        "objects_before",
    }
    _exact_keys(cleanup, names, "RGW/KMS cleanup")
    result = {
        name: _nonnegative_integer(cleanup[name], f"RGW/KMS cleanup {name}")
        for name in names
    }
    if (
        result["objects_before"] < 2
        or result["object_versions_before"] < 2
        or result["multipart_uploads_before"] < 1
        or any(result[name] != 0 for name in names if name.endswith("_after"))
    ):
        raise RgwKmsResultError("RGW/KMS cleanup is not qualified")
    return {name: result[name] for name in sorted(result)}


def _validate_residue(value: object) -> dict[str, int]:
    residue = _mapping(value, "RGW/KMS residue")
    names = {
        "configuration_secrets",
        "credential_values",
        "delete_markers",
        "host_secrets",
        "key_material",
        "log_secrets",
        "multipart_uploads",
        "object_versions",
        "objects",
        "runtime_files",
        "selected_kms_keys",
        "total",
    }
    _exact_keys(residue, names, "RGW/KMS residue")
    result = {
        name: _nonnegative_integer(residue[name], f"RGW/KMS residue {name}")
        for name in names
    }
    if any(result.values()) or result["total"] != sum(
        result[name] for name in names if name != "total"
    ):
        raise RgwKmsResultError("RGW/KMS residue remains")
    return {name: 0 for name in sorted(names)}


def _validate_evidence(
    value: object,
    *,
    release: Mapping[str, Any],
    release_digest: str,
) -> dict[str, Any]:
    evidence = _mapping(value, "RGW/KMS evidence")
    _exact_keys(
        evidence,
        {
            "cleanup",
            "execution",
            "faults",
            "operations",
            "release_inputs",
            "release_readiness_sha256",
            "residue",
            "restart",
            "rotation",
            "schema",
            "source",
            "transport",
            "unexpected_errors",
        },
        "RGW/KMS evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["release_readiness_sha256"] != release_digest
        or evidence["release_inputs"] != _release_identity(release)
        or evidence["source"] != runtime_source_hashes()
    ):
        raise RgwKmsResultError("RGW/KMS evidence binding changed")
    return {
        "cleanup": _validate_cleanup(evidence["cleanup"]),
        "execution": _validate_execution(evidence["execution"]),
        "faults": _validate_faults(evidence["faults"]),
        "operations": _validate_operations(evidence["operations"]),
        "release_inputs": _release_identity(release),
        "residue": _validate_residue(evidence["residue"]),
        "restart": _validate_restart(evidence["restart"]),
        "rotation": _validate_rotation(evidence["rotation"]),
        "transport": _validate_transport(evidence["transport"]),
        "unexpected_errors": _validate_unexpected_errors(
            evidence["unexpected_errors"]
        ),
    }


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    evidence: object,
    evidence_digest: str,
) -> dict[str, Any]:
    release = require_release_qualified(release_readiness)
    validated = _validate_evidence(
        evidence,
        release=release,
        release_digest=_digest(release_digest, "release readiness"),
    )
    return {
        **validated,
        "evidence_sha256": _digest(evidence_digest, "RGW/KMS evidence"),
        "production_candidate": True,
        "release_readiness_sha256": release_digest,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "RGW/KMS result"))
    _exact_keys(
        result,
        {
            "cleanup",
            "evidence_sha256",
            "execution",
            "faults",
            "operations",
            "production_candidate",
            "release_inputs",
            "release_readiness_sha256",
            "residue",
            "restart",
            "rotation",
            "schema",
            "source",
            "transport",
            "unexpected_errors",
        },
        "RGW/KMS result",
    )
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise RgwKmsResultError("RGW/KMS result is not qualified")
    _digest(result["evidence_sha256"], "RGW/KMS evidence")
    _digest(result["release_readiness_sha256"], "release readiness")
    releases = _mapping(result["release_inputs"], "RGW/KMS release inputs")
    if set(releases) != set(RELEASE_COMPONENTS):
        raise RgwKmsResultError("RGW/KMS release inputs are incomplete")
    for name in RELEASE_COMPONENTS:
        component = _mapping(releases[name], f"RGW/KMS {name}")
        _exact_keys(component, {"revision", "version"}, f"RGW/KMS {name}")
        if (
            not isinstance(component["version"], str)
            or not component["version"]
            or not isinstance(component["revision"], str)
            or REVISION.fullmatch(component["revision"]) is None
        ):
            raise RgwKmsResultError("RGW/KMS release identity is invalid")
    _validate_execution(result["execution"])
    _validate_transport(result["transport"])
    _validate_operations(result["operations"])
    _validate_faults(result["faults"])
    _validate_rotation(result["rotation"])
    _validate_restart(result["restart"])
    _validate_cleanup(result["cleanup"])
    _validate_residue(result["residue"])
    _validate_unexpected_errors(result["unexpected_errors"])
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
            raise RgwKmsResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise RgwKmsResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except RgwKmsResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RgwKmsResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise RgwKmsResultError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise RgwKmsResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise RgwKmsResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise RgwKmsResultError("output directory ownership is unsafe")
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
        raise RgwKmsResultError("unable to write RGW/KMS result") from error
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile released Ceph RGW and Barbican SSE-KMS evidence only "
            "after official release readiness qualifies."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness,
            "release readiness",
        )
        require_release_qualified(release)
        evidence, evidence_digest = _load_private(
            arguments.evidence,
            "RGW/KMS evidence",
        )
        result = compile_result(
            release_readiness=release,
            release_digest=release_digest,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except RgwKmsInputsBlocked as error:
        print(f"production RGW/KMS gate blocked: {error}", file=sys.stderr)
        return 3
    except RgwKmsResultError as error:
        print(f"production RGW/KMS result error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
