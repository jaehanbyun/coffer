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
READINESS_SOURCE = DIRECTORY / "readiness.py"
ARTIFACT_RESULT_SOURCE = DIRECTORY / "artifacts.py"
RGW_KMS_RESULT_SOURCE = DIRECTORY / "rgw_kms.py"
MAINTENANCE_DIRECTORY = ROOT / "poc" / "maintenance-identity"
STATE_MACHINE_SOURCE = MAINTENANCE_DIRECTORY / "state_machine.py"
LIFECYCLE_SOURCE = MAINTENANCE_DIRECTORY / "lifecycle.py"
TOPOLOGY_SOURCE = MAINTENANCE_DIRECTORY / "topology.json"
RUNTIME_SOURCES = {
    "config_validator_sha256": ROOT / "src" / "coffer" / "config_validator.py",
    "haproxy_template_sha256": (
        ROOT
        / "ansible"
        / "roles"
        / "coffer"
        / "templates"
        / "haproxy-maintenance.cfg.j2"
    ),
    "lifecycle_sha256": LIFECYCLE_SOURCE,
    "maintenance_precheck_sha256": (
        ROOT
        / "ansible"
        / "roles"
        / "coffer"
        / "tasks"
        / "maintenance-precheck.yml"
    ),
    "maintenance_token_sha256": (
        ROOT / "src" / "coffer" / "maintenance_token.py"
    ),
    "quota_authority_sha256": ROOT / "src" / "coffer" / "quota.py",
    "reconciliation_runner_sha256": (
        ROOT / "src" / "coffer" / "reconciliation_runner.py"
    ),
    "state_machine_sha256": STATE_MACHINE_SOURCE,
    "topology_sha256": TOPOLOGY_SOURCE,
    "wsgi_sha256": ROOT / "src" / "coffer" / "wsgi.py",
}

SCHEMA = "coffer.production-promotion-maintenance-identity-result/v1"
EVIDENCE_SCHEMA = (
    "coffer.production-promotion-maintenance-identity-evidence/v1"
)
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
FAILURE_CASES = (
    "api_after_keystone_unavailable",
    "barbican_unavailable",
    "deleted_application_credential",
    "disabled_maintenance_user",
    "distribution_failure_classes",
    "expired_application_credential",
    "expired_client_certificate",
    "expired_registry_token",
    "keystone_unavailable",
    "private_replica_loss",
    "removed_maintenance_role",
    "stale_sql_authority",
    "unknown_fingerprint",
    "wrong_client_key",
)
RESIDUE_KEYS = (
    "credentials",
    "environment_values",
    "identities",
    "mappings",
    "materializations",
    "processes",
    "secrets",
    "sessions",
    "temporary_files",
)


class MaintenanceIdentityResultError(RuntimeError):
    pass


class MaintenanceIdentityInputsBlocked(MaintenanceIdentityResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise MaintenanceIdentityResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise MaintenanceIdentityResultError(f"unable to load {path}") from error
    return module


ARTIFACT_RESULT = _load_module(
    "coffer_maintenance_promotion_artifacts",
    ARTIFACT_RESULT_SOURCE,
)
RGW_KMS_RESULT = _load_module(
    "coffer_maintenance_promotion_rgw_kms",
    RGW_KMS_RESULT_SOURCE,
)
STATE_MACHINE = _load_module(
    "coffer_maintenance_promotion_state_machine",
    STATE_MACHINE_SOURCE,
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise MaintenanceIdentityResultError(
            f"unable to hash {path}"
        ) from error


def runtime_source_hashes() -> dict[str, str]:
    return {
        name: _sha256(path)
        for name, path in sorted(RUNTIME_SOURCES.items())
    }


def source_hashes() -> dict[str, str]:
    return {
        "artifact_result_verifier_sha256": _sha256(ARTIFACT_RESULT_SOURCE),
        "maintenance_identity_compiler_sha256": _sha256(
            Path(__file__).resolve()
        ),
        "release_readiness_verifier_sha256": _sha256(READINESS_SOURCE),
        "rgw_kms_result_verifier_sha256": _sha256(RGW_KMS_RESULT_SOURCE),
        **runtime_source_hashes(),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MaintenanceIdentityResultError(
            f"{label} must be a JSON object"
        )
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MaintenanceIdentityResultError(
            f"{label} must be a JSON array"
        )
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise MaintenanceIdentityResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise MaintenanceIdentityResultError(f"{label} is invalid")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MaintenanceIdentityResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result < 1:
        raise MaintenanceIdentityResultError(f"{label} is invalid")
    return result


def _qualified_prerequisites(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
) -> dict[str, str]:
    try:
        RGW_KMS_RESULT.require_release_qualified(release_readiness)
    except RGW_KMS_RESULT.RgwKmsInputsBlocked as error:
        raise MaintenanceIdentityInputsBlocked(str(error)) from error
    release_hash = _digest(release_digest, "release readiness")
    try:
        artifact = ARTIFACT_RESULT.validate_final_result(artifact_result)
    except ARTIFACT_RESULT.ArtifactResultError as error:
        raise MaintenanceIdentityInputsBlocked(
            "immutable artifacts are not candidate-qualified"
        ) from error
    if artifact["release_readiness_sha256"] != release_hash:
        raise MaintenanceIdentityInputsBlocked(
            "immutable artifact release binding changed"
        )
    try:
        rgw_kms = RGW_KMS_RESULT.validate_final_result(rgw_kms_result)
    except RGW_KMS_RESULT.RgwKmsResultError as error:
        raise MaintenanceIdentityInputsBlocked(
            "RGW/KMS is not candidate-qualified"
        ) from error
    if rgw_kms["release_readiness_sha256"] != release_hash:
        raise MaintenanceIdentityInputsBlocked(
            "RGW/KMS release binding changed"
        )
    return {
        "artifact_result_sha256": _digest(
            artifact_digest,
            "artifact result",
        ),
        "release_readiness_sha256": release_hash,
        "rgw_kms_result_sha256": _digest(
            rgw_kms_digest,
            "RGW/KMS result",
        ),
    }


def _validate_lifecycle(value: object) -> dict[str, Any]:
    lifecycle = _mapping(value, "maintenance lifecycle evidence")
    _exact_keys(
        lifecycle,
        {
            "fixed_failure_category",
            "http_status_class",
            "immutable_id_hashes",
            "invocation_id",
            "log_scan_count",
            "phase",
            "residue_counts",
            "resource_counts",
            "schema",
            "target_signature",
            "topology_digest",
        },
        "maintenance lifecycle evidence",
    )
    try:
        topology = STATE_MACHINE.load_topology(TOPOLOGY_SOURCE)
    except STATE_MACHINE.LifecycleError as error:
        raise MaintenanceIdentityResultError(
            "maintenance topology is invalid"
        ) from error
    if (
        lifecycle["schema"] != STATE_MACHINE.EVIDENCE_SCHEMA
        or lifecycle["topology_digest"] != topology.digest
        or lifecycle["phase"] != "torn_down"
        or lifecycle["fixed_failure_category"] != "none"
        or lifecycle["http_status_class"] != "2xx"
        or STATE_MACHINE.INVOCATION_PATTERN.fullmatch(
            str(lifecycle["invocation_id"])
        )
        is None
        or HEX_SHA256.fullmatch(str(lifecycle["target_signature"])) is None
        or _positive_integer(
            lifecycle["log_scan_count"],
            "maintenance lifecycle log scan count",
        )
        < 1
    ):
        raise MaintenanceIdentityResultError(
            "maintenance lifecycle did not reach a qualified terminal state"
        )
    resources = _mapping(
        lifecycle["resource_counts"],
        "maintenance lifecycle resource counts",
    )
    if set(resources) != set(STATE_MACHINE.EXPECTED_CLEANUP_ORDER):
        raise MaintenanceIdentityResultError(
            "maintenance lifecycle resource counts are incomplete"
        )
    normalized_resources = {
        name: _nonnegative_integer(
            resources[name],
            f"maintenance lifecycle {name} count",
        )
        for name in STATE_MACHINE.EXPECTED_CLEANUP_ORDER
    }
    if any(
        count != 0
        for name, count in normalized_resources.items()
        if name != "role"
    ) or normalized_resources["role"] not in {0, 1}:
        raise MaintenanceIdentityResultError(
            "maintenance lifecycle owned resources remain"
        )
    identifiers = _array(
        lifecycle["immutable_id_hashes"],
        "maintenance lifecycle immutable ID hashes",
    )
    if (
        len(identifiers) != sum(normalized_resources.values())
        or len(identifiers) != len(set(identifiers))
        or any(
            not isinstance(item, str)
            or HEX_SHA256.fullmatch(item) is None
            for item in identifiers
        )
    ):
        raise MaintenanceIdentityResultError(
            "maintenance lifecycle retained identity set is invalid"
        )
    residue = _mapping(
        lifecycle["residue_counts"],
        "maintenance lifecycle residue",
    )
    expected_residue = {
        "credentials",
        "identities",
        "mappings",
        "materializations",
        "secrets",
        "sessions",
    }
    if set(residue) != expected_residue or any(
        _nonnegative_integer(
            residue[name],
            f"maintenance lifecycle {name} residue",
        )
        != 0
        for name in expected_residue
    ):
        raise MaintenanceIdentityResultError(
            "maintenance lifecycle residue remains"
        )
    try:
        STATE_MACHINE.validate_retained_payload(lifecycle)
    except STATE_MACHINE.LifecycleError as error:
        raise MaintenanceIdentityResultError(
            "maintenance lifecycle retained forbidden data"
        ) from error
    return {
        "log_scan_count": lifecycle["log_scan_count"],
        "preexisting_role_count": normalized_resources["role"],
        "terminal_phase": "torn_down",
    }


def _validate_execution(value: object) -> dict[str, Any]:
    execution = _mapping(value, "maintenance execution")
    _exact_keys(
        execution,
        {
            "adapter",
            "generation_count",
            "non_synthetic",
            "selected_workload_count",
        },
        "maintenance execution",
    )
    workload_count = _positive_integer(
        execution["selected_workload_count"],
        "maintenance workload count",
    )
    if (
        execution["adapter"] != "openstack"
        or execution["non_synthetic"] is not True
        or execution["generation_count"] != 2
        or workload_count != 3
    ):
        raise MaintenanceIdentityResultError(
            "maintenance execution is not a complete non-synthetic run"
        )
    return {
        "adapter": "openstack",
        "generation_count": 2,
        "non_synthetic": True,
        "selected_workload_count": workload_count,
    }


def _validate_authority(value: object) -> dict[str, Any]:
    authority = _mapping(value, "maintenance authority")
    boolean_fields = {
        "access_rule_exact",
        "application_credential_restricted",
        "pull_only_registry_jwt",
        "required_roles_exact",
        "runtime_secret_retrieval_denied",
        "server_side_sql_authority",
        "service_project_scoped",
        "user_password_disabled",
    }
    _exact_keys(
        authority,
        {
            *boolean_fields,
            "application_credential_lifetime_seconds",
            "client_certificate_lifetime_seconds",
            "registry_token_lifetime_seconds",
        },
        "maintenance authority",
    )
    if any(authority[name] is not True for name in boolean_fields):
        raise MaintenanceIdentityResultError(
            "maintenance authority is broader than the accepted contract"
        )
    try:
        topology = STATE_MACHINE.load_topology(TOPOLOGY_SOURCE)
    except STATE_MACHINE.LifecycleError as error:
        raise MaintenanceIdentityResultError(
            "maintenance topology is invalid"
        ) from error
    credential_lifetime = _positive_integer(
        authority["application_credential_lifetime_seconds"],
        "application credential lifetime",
    )
    certificate_lifetime = _positive_integer(
        authority["client_certificate_lifetime_seconds"],
        "client certificate lifetime",
    )
    token_lifetime = _positive_integer(
        authority["registry_token_lifetime_seconds"],
        "registry token lifetime",
    )
    if (
        not topology.minimum_lifetime_seconds
        <= credential_lifetime
        <= topology.maximum_lifetime_seconds
        or certificate_lifetime > credential_lifetime
        or token_lifetime > 300
        or token_lifetime >= credential_lifetime
    ):
        raise MaintenanceIdentityResultError(
            "maintenance credential lifetime is outside the accepted bounds"
        )
    return {
        **{name: True for name in sorted(boolean_fields)},
        "application_credential_lifetime_seconds": credential_lifetime,
        "client_certificate_lifetime_seconds": certificate_lifetime,
        "registry_token_lifetime_seconds": token_lifetime,
    }


def _validate_transport(value: object) -> dict[str, bool]:
    transport = _mapping(value, "maintenance transport")
    fields = {
        "correct_workload_succeeded",
        "private_mtls_verified",
        "public_internal_path_denied",
        "unknown_fingerprint_denied",
        "wrong_client_certificate_denied",
        "wrong_method_denied",
        "wrong_path_denied",
        "wrong_workload_denied",
    }
    _exact_keys(transport, fields, "maintenance transport")
    if any(transport[name] is not True for name in fields):
        raise MaintenanceIdentityResultError(
            "maintenance private transport is not qualified"
        )
    return {name: True for name in sorted(fields)}


def _validate_rotation(value: object) -> dict[str, Any]:
    rotation = _mapping(value, "maintenance rotation")
    _exact_keys(
        rotation,
        {
            "generation_count",
            "keystone_cache_seconds",
            "old_credential_revoked",
            "old_mapping_removed",
            "old_secret_removed",
            "overlap_verified",
            "registry_token_seconds",
            "rotation_elapsed_seconds",
        },
        "maintenance rotation",
    )
    elapsed = _nonnegative_integer(
        rotation["rotation_elapsed_seconds"],
        "maintenance rotation elapsed seconds",
    )
    keystone = _nonnegative_integer(
        rotation["keystone_cache_seconds"],
        "Keystone cache seconds",
    )
    token = _nonnegative_integer(
        rotation["registry_token_seconds"],
        "registry token seconds",
    )
    if (
        rotation["generation_count"] != 2
        or rotation["overlap_verified"] is not True
        or rotation["old_credential_revoked"] is not True
        or rotation["old_mapping_removed"] is not True
        or rotation["old_secret_removed"] is not True
        or elapsed < max(keystone, token)
    ):
        raise MaintenanceIdentityResultError(
            "maintenance rotation or revocation is not qualified"
        )
    return {
        "generation_count": 2,
        "keystone_cache_seconds": keystone,
        "old_credential_revoked": True,
        "old_mapping_removed": True,
        "old_secret_removed": True,
        "overlap_verified": True,
        "registry_token_seconds": token,
        "rotation_elapsed_seconds": elapsed,
    }


def _validate_failures(value: object) -> dict[str, bool]:
    failures = _mapping(value, "maintenance failure matrix")
    if set(failures) != set(FAILURE_CASES) or any(
        failures[name] is not True for name in FAILURE_CASES
    ):
        raise MaintenanceIdentityResultError(
            "maintenance failure matrix is incomplete"
        )
    return {name: True for name in FAILURE_CASES}


def _validate_audit(value: object) -> dict[str, int]:
    audit = _mapping(value, "maintenance audit")
    _exact_keys(
        audit,
        {
            "audit_event_count",
            "known_secret_matches",
            "unexpected_errors",
        },
        "maintenance audit",
    )
    events = _positive_integer(
        audit["audit_event_count"],
        "maintenance audit event count",
    )
    secrets = _nonnegative_integer(
        audit["known_secret_matches"],
        "maintenance known-secret matches",
    )
    errors = _nonnegative_integer(
        audit["unexpected_errors"],
        "maintenance unexpected errors",
    )
    if secrets != 0 or errors != 0:
        raise MaintenanceIdentityResultError(
            "maintenance audit contains secrets or unexpected errors"
        )
    return {
        "audit_event_count": events,
        "known_secret_matches": 0,
        "unexpected_errors": 0,
    }


def _validate_residue(value: object) -> dict[str, int]:
    residue = _mapping(value, "maintenance residue")
    if set(residue) != set(RESIDUE_KEYS) | {"total"}:
        raise MaintenanceIdentityResultError(
            "maintenance residue fields are invalid"
        )
    result = {
        name: _nonnegative_integer(
            residue[name],
            f"maintenance {name} residue",
        )
        for name in (*RESIDUE_KEYS, "total")
    }
    if any(result.values()) or result["total"] != sum(
        result[name] for name in RESIDUE_KEYS
    ):
        raise MaintenanceIdentityResultError(
            "maintenance identity residue remains"
        )
    return {name: 0 for name in (*RESIDUE_KEYS, "total")}


def _validate_evidence_hashes(value: object) -> dict[str, str]:
    hashes = _mapping(value, "maintenance evidence hashes")
    names = {
        "audit_sha256",
        "authority_sha256",
        "failure_matrix_sha256",
        "lifecycle_sha256",
        "rotation_sha256",
        "teardown_sha256",
        "transport_sha256",
    }
    _exact_keys(hashes, names, "maintenance evidence hashes")
    return {
        name: _digest(hashes[name], f"maintenance {name}")
        for name in sorted(names)
    }


def _validate_evidence(
    value: object,
    *,
    prerequisites: Mapping[str, str],
) -> dict[str, Any]:
    evidence = _mapping(value, "maintenance identity evidence")
    _exact_keys(
        evidence,
        {
            "audit",
            "authority",
            "evidence_sha256",
            "execution",
            "failure_matrix",
            "lifecycle",
            "prerequisites",
            "residue",
            "rotation",
            "schema",
            "source",
            "transport",
        },
        "maintenance identity evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["prerequisites"] != prerequisites
        or evidence["source"] != runtime_source_hashes()
    ):
        raise MaintenanceIdentityResultError(
            "maintenance identity evidence binding changed"
        )
    lifecycle = _validate_lifecycle(evidence["lifecycle"])
    hashes = _validate_evidence_hashes(evidence["evidence_sha256"])
    return {
        "audit": _validate_audit(evidence["audit"]),
        "authority": _validate_authority(evidence["authority"]),
        "evidence_sha256": hashes,
        "execution": _validate_execution(evidence["execution"]),
        "failure_matrix": _validate_failures(evidence["failure_matrix"]),
        "lifecycle": lifecycle,
        "residue": _validate_residue(evidence["residue"]),
        "rotation": _validate_rotation(evidence["rotation"]),
        "transport": _validate_transport(evidence["transport"]),
    }


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    evidence: object,
    evidence_digest: str,
) -> dict[str, Any]:
    prerequisites = _qualified_prerequisites(
        release_readiness=release_readiness,
        release_digest=release_digest,
        artifact_result=artifact_result,
        artifact_digest=artifact_digest,
        rgw_kms_result=rgw_kms_result,
        rgw_kms_digest=rgw_kms_digest,
    )
    validated = _validate_evidence(
        evidence,
        prerequisites=prerequisites,
    )
    return {
        **validated,
        "input_evidence_sha256": _digest(
            evidence_digest,
            "maintenance identity evidence",
        ),
        "prerequisites": prerequisites,
        "production_candidate": True,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "maintenance identity result"))
    _exact_keys(
        result,
        {
            "audit",
            "authority",
            "evidence_sha256",
            "execution",
            "failure_matrix",
            "input_evidence_sha256",
            "lifecycle",
            "prerequisites",
            "production_candidate",
            "residue",
            "rotation",
            "schema",
            "source",
            "transport",
        },
        "maintenance identity result",
    )
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise MaintenanceIdentityResultError(
            "maintenance identity result is not qualified"
        )
    prerequisites = _mapping(
        result["prerequisites"],
        "maintenance identity prerequisites",
    )
    expected_prerequisites = {
        "artifact_result_sha256",
        "release_readiness_sha256",
        "rgw_kms_result_sha256",
    }
    _exact_keys(
        prerequisites,
        expected_prerequisites,
        "maintenance identity prerequisites",
    )
    for name in expected_prerequisites:
        _digest(prerequisites[name], f"maintenance prerequisite {name}")
    _digest(result["input_evidence_sha256"], "maintenance input evidence")
    lifecycle = _mapping(result["lifecycle"], "maintenance lifecycle")
    _exact_keys(
        lifecycle,
        {"log_scan_count", "preexisting_role_count", "terminal_phase"},
        "maintenance lifecycle",
    )
    if (
        lifecycle["terminal_phase"] != "torn_down"
        or lifecycle["preexisting_role_count"] not in {0, 1}
        or _positive_integer(
            lifecycle["log_scan_count"],
            "maintenance lifecycle log scan count",
        )
        < 1
    ):
        raise MaintenanceIdentityResultError(
            "maintenance terminal lifecycle is not qualified"
        )
    _validate_execution(result["execution"])
    _validate_authority(result["authority"])
    _validate_transport(result["transport"])
    _validate_rotation(result["rotation"])
    _validate_failures(result["failure_matrix"])
    _validate_audit(result["audit"])
    _validate_residue(result["residue"])
    _validate_evidence_hashes(result["evidence_sha256"])
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
            raise MaintenanceIdentityResultError(
                f"{label} ownership is unsafe"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise MaintenanceIdentityResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except MaintenanceIdentityResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MaintenanceIdentityResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise MaintenanceIdentityResultError(
            f"{label} must be a JSON object"
        )
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise MaintenanceIdentityResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise MaintenanceIdentityResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise MaintenanceIdentityResultError(
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
        raise MaintenanceIdentityResultError(
            "unable to write maintenance identity result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile non-synthetic maintenance identity lifecycle evidence "
            "only after release, artifact, and RGW/KMS prerequisites qualify."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--artifact-result", type=Path, required=True)
    parser.add_argument("--rgw-kms-result", type=Path, required=True)
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
            raise MaintenanceIdentityInputsBlocked(str(error)) from error

        try:
            artifact, artifact_digest = _load_private(
                arguments.artifact_result,
                "artifact specialist result",
            )
        except MaintenanceIdentityResultError as error:
            raise MaintenanceIdentityInputsBlocked(
                "immutable artifact specialist result is absent or unsafe"
            ) from error
        try:
            qualified_artifact = ARTIFACT_RESULT.validate_final_result(
                artifact
            )
        except ARTIFACT_RESULT.ArtifactResultError as error:
            raise MaintenanceIdentityInputsBlocked(
                "immutable artifacts are not candidate-qualified"
            ) from error
        if qualified_artifact["release_readiness_sha256"] != release_digest:
            raise MaintenanceIdentityInputsBlocked(
                "immutable artifact release binding changed"
            )

        try:
            rgw_kms, rgw_kms_digest = _load_private(
                arguments.rgw_kms_result,
                "RGW/KMS specialist result",
            )
        except MaintenanceIdentityResultError as error:
            raise MaintenanceIdentityInputsBlocked(
                "RGW/KMS specialist result is absent or unsafe"
            ) from error
        try:
            qualified_rgw_kms = RGW_KMS_RESULT.validate_final_result(rgw_kms)
        except RGW_KMS_RESULT.RgwKmsResultError as error:
            raise MaintenanceIdentityInputsBlocked(
                "RGW/KMS is not candidate-qualified"
            ) from error
        if qualified_rgw_kms["release_readiness_sha256"] != release_digest:
            raise MaintenanceIdentityInputsBlocked(
                "RGW/KMS release binding changed"
            )

        evidence, evidence_digest = _load_private(
            arguments.evidence,
            "maintenance identity evidence",
        )
        result = compile_result(
            release_readiness=release,
            release_digest=release_digest,
            artifact_result=artifact,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms,
            rgw_kms_digest=rgw_kms_digest,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except MaintenanceIdentityInputsBlocked as error:
        print(
            f"production maintenance identity gate blocked: {error}",
            file=sys.stderr,
        )
        return 3
    except MaintenanceIdentityResultError as error:
        print(
            f"production maintenance identity result error: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
