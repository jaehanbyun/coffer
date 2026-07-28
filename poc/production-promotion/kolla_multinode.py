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
LOAD_SOAK_RESULT_SOURCE = DIRECTORY / "load_soak.py"
PILOT_DIRECTORY = ROOT / "poc" / "kolla-ha"
ROLE_DIRECTORY = ROOT / "ansible" / "roles" / "coffer"
RUNTIME_DIRECTORY = ROOT / "poc" / "kolla-runtime"
CLIENT_DIRECTORY = ROOT / "src" / "cofferclient"
TOPOLOGY_SOURCE = ROOT / "docs" / "architecture" / "kolla-deployment-topology.md"
TOPOLOGY_ADR_SOURCE = ROOT / "docs" / "adrs" / "0014-fix-kolla-deployment-topology.md"

SCHEMA = "coffer.production-promotion-kolla-multinode-result/v1"
EVIDENCE_SCHEMA = "coffer.production-promotion-kolla-multinode-evidence/v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
KOLLA_RELEASE = "2026.1"
PHASES = (
    "preflighted",
    "provisioned",
    "kolla-deployed",
    "coffer-deployed",
    "accepted",
    "faults-complete",
    "upgraded",
    "rolled-back",
    "restored",
    "torn-down",
)
SURFACES = (
    "docker",
    "podman",
    "skopeo",
    "oras",
    "nerdctl",
    "raw-oci",
    "openstackclient",
    "horizon",
    "skyline",
)
FAILURE_CASES = (
    "api-replica",
    "edge-replica",
    "registry-mid-upload",
    "reconciler-replica",
    "controller-host",
    "haproxy-vip-owner",
    "galera-writer",
    "rabbitmq-member",
    "rgw-daemon",
    "rgw-ingress",
    "storage-host",
    "barbican-kms",
    "reconciler-fencing",
)
SERVICE_REPLICAS = {
    "api": 3,
    "edge": 3,
    "reconcile": 3,
    "registry": 3,
}
DEPENDENCY_REPLICAS = {
    "ceph_mgr": 2,
    "ceph_mon": 3,
    "ceph_osd": 3,
    "haproxy": 3,
    "mariadb": 3,
    "rabbitmq": 3,
    "rgw": 3,
    "rgw_ingress": 2,
}
DEPLOYMENT_CHECKS = (
    "bootstrap_registry_separate",
    "bootstrap_servers",
    "config_validation",
    "database_bootstrap",
    "deploy",
    "health_checks",
    "idempotent_reconfigure",
    "image_digests_exact",
    "migration_replay_safe",
    "prechecks",
    "production_profile",
    "service_catalog_created",
)
DATA_PATH_CHECKS = (
    "authenticated_reconciliation",
    "backend_ports_closed",
    "dependency_503",
    "digest_persisted",
    "direct_api_denied",
    "direct_registry_denied",
    "edge_only_ingress",
    "project_b_control_denied",
    "project_b_pull_denied",
    "project_b_push_denied",
    "quota_429",
    "repository_state_equal",
    "restart_persistence",
)
IDENTITY_CHECKS = (
    "application_credential_expiry",
    "application_credential_rotation",
    "catalog_discovery",
    "maintenance_identity_active",
    "reader_member_admin_policy",
    "service_token_required",
    "token_expiry",
    "token_revocation",
)
RESIDUE_KEYS = (
    "application_credentials",
    "barbican_secrets",
    "buckets",
    "certificates",
    "containers",
    "credentials",
    "databases",
    "delete_markers",
    "domains",
    "haproxy_fragments",
    "identities",
    "images",
    "locks",
    "multipart_uploads",
    "networks",
    "object_versions",
    "objects",
    "projects",
    "runtime_files",
    "temporary_files",
    "users",
    "volumes",
)
SOURCE_SUFFIXES = {
    ".cfg",
    ".conf",
    ".j2",
    ".json",
    ".mod",
    ".py",
    ".sh",
    ".sum",
    ".yml",
    ".yaml",
}


class KollaMultinodeResultError(RuntimeError):
    pass


class KollaMultinodeInputsBlocked(KollaMultinodeResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise KollaMultinodeResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise KollaMultinodeResultError(f"unable to load {path}") from error
    return module


LOAD_SOAK_RESULT = _load_module(
    "coffer_kolla_promotion_load_soak",
    LOAD_SOAK_RESULT_SOURCE,
)
RGW_KMS_RESULT = LOAD_SOAK_RESULT.RGW_KMS_RESULT


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise KollaMultinodeResultError(f"unable to hash {path}") from error


def _hash(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    sources = [
        path
        for path in root.rglob("*")
        if (
            path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
            and ".pytest_cache" not in path.parts
            and path.suffix in SOURCE_SUFFIXES
            and not path.name.endswith("_test.go")
        )
    ]
    if not sources:
        raise KollaMultinodeResultError(
            f"runtime source tree is empty: {root}"
        )
    try:
        for path in sorted(sources):
            relative = path.relative_to(root).as_posix().encode()
            payload = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    except OSError as error:
        raise KollaMultinodeResultError(
            f"unable to hash runtime source tree: {root}"
        ) from error
    return "sha256:" + digest.hexdigest()


def runtime_source_hashes() -> dict[str, str]:
    return {
        "client_tree_sha256": _tree_hash(CLIENT_DIRECTORY),
        "kolla_ha_tree_sha256": _tree_hash(PILOT_DIRECTORY),
        "kolla_runtime_tree_sha256": _tree_hash(RUNTIME_DIRECTORY),
        "operator_role_tree_sha256": _tree_hash(ROLE_DIRECTORY),
        "topology_adr_sha256": _sha256(TOPOLOGY_ADR_SOURCE),
        "topology_contract_sha256": _sha256(TOPOLOGY_SOURCE),
    }


def source_hashes() -> dict[str, str]:
    return {
        "kolla_multinode_compiler_sha256": _sha256(
            Path(__file__).resolve()
        ),
        "load_soak_result_verifier_sha256": _sha256(
            LOAD_SOAK_RESULT_SOURCE
        ),
        **runtime_source_hashes(),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KollaMultinodeResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise KollaMultinodeResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise KollaMultinodeResultError(f"{label} is invalid")
    return value


def _revision(value: object, label: str) -> str:
    if not isinstance(value, str) or REVISION.fullmatch(value) is None:
        raise KollaMultinodeResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise KollaMultinodeResultError(f"{label} is invalid")
    return value


def _true_map(
    value: object,
    *,
    expected: Sequence[str],
    label: str,
) -> dict[str, bool]:
    item = _mapping(value, label)
    _exact_keys(item, set(expected), label)
    if any(item[name] is not True for name in expected):
        raise KollaMultinodeResultError(f"{label} is incomplete")
    return {name: True for name in expected}


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
    load_soak_result: object,
    load_soak_digest: str,
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    try:
        base, release, artifact = (
            LOAD_SOAK_RESULT._qualified_prerequisites(
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
        )
        qualified_load = LOAD_SOAK_RESULT.validate_final_result(
            load_soak_result
        )
    except LOAD_SOAK_RESULT.LoadSoakInputsBlocked as error:
        raise KollaMultinodeInputsBlocked(str(error)) from error
    except LOAD_SOAK_RESULT.LoadSoakResultError as error:
        raise KollaMultinodeInputsBlocked(
            "load/soak is not candidate-qualified"
        ) from error
    if qualified_load["prerequisites"] != base:
        raise KollaMultinodeInputsBlocked(
            "load/soak prerequisite binding changed"
        )
    return (
        {
            **base,
            "load_soak_result_sha256": _digest(
                load_soak_digest,
                "load/soak result",
            ),
        },
        release,
        artifact,
    )


def _validate_execution(
    value: object,
    *,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    execution = _mapping(value, "Kolla multinode execution")
    _exact_keys(
        execution,
        {
            "adapter",
            "coffer_revision",
            "disposable",
            "fresh",
            "kolla_ansible_revision",
            "kolla_release",
            "non_synthetic",
            "phase_count",
            "run_duration_seconds",
        },
        "Kolla multinode execution",
    )
    cross_architecture = _mapping(
        artifact["cross_architecture"],
        "artifact cross-architecture result",
    )
    coffer_revision = _revision(
        execution["coffer_revision"],
        "Coffer revision",
    )
    if (
        execution["adapter"] != "openstack"
        or execution["disposable"] is not True
        or execution["fresh"] is not True
        or execution["non_synthetic"] is not True
        or execution["kolla_release"] != KOLLA_RELEASE
        or execution["phase_count"] != len(PHASES)
        or coffer_revision != cross_architecture["core_revision"]
    ):
        raise KollaMultinodeResultError(
            "Kolla multinode execution is not a fresh production pilot"
        )
    return {
        "adapter": "openstack",
        "coffer_revision": coffer_revision,
        "disposable": True,
        "fresh": True,
        "kolla_ansible_revision": _revision(
            execution["kolla_ansible_revision"],
            "Kolla-Ansible revision",
        ),
        "kolla_release": KOLLA_RELEASE,
        "non_synthetic": True,
        "phase_count": len(PHASES),
        "run_duration_seconds": _positive_integer(
            execution["run_duration_seconds"],
            "Kolla multinode run duration",
        ),
    }


def _validate_topology(value: object) -> dict[str, Any]:
    topology = _mapping(value, "Kolla multinode topology")
    _exact_keys(
        topology,
        {
            "backend_tls_verified",
            "ceph_crush_failure_domain",
            "ceph_min_size",
            "ceph_replication_size",
            "client_network_backend_ports_closed",
            "controller_count",
            "controller_failure_domain_count",
            "controller_storage_colocated",
            "dependency_replicas",
            "external_rgw",
            "internal_tls_verified",
            "load_balancer_ha",
            "service_replicas",
            "single_public_origin",
            "storage_count",
            "storage_failure_domain_count",
        },
        "Kolla multinode topology",
    )
    expected = {
        "backend_tls_verified": True,
        "ceph_crush_failure_domain": "host",
        "ceph_min_size": 2,
        "ceph_replication_size": 3,
        "client_network_backend_ports_closed": True,
        "controller_count": 3,
        "controller_failure_domain_count": 3,
        "controller_storage_colocated": False,
        "dependency_replicas": DEPENDENCY_REPLICAS,
        "external_rgw": True,
        "internal_tls_verified": True,
        "load_balancer_ha": True,
        "service_replicas": SERVICE_REPLICAS,
        "single_public_origin": True,
        "storage_count": 3,
        "storage_failure_domain_count": 3,
    }
    if topology != expected:
        raise KollaMultinodeResultError(
            "Kolla multinode topology is not production-shaped"
        )
    return {
        **expected,
        "dependency_replicas": dict(DEPENDENCY_REPLICAS),
        "service_replicas": dict(SERVICE_REPLICAS),
    }


def _validate_identity(value: object) -> dict[str, Any]:
    identity = _mapping(value, "Kolla identity and catalog")
    _exact_keys(
        identity,
        {
            "checks",
            "endpoint_count",
            "region",
            "service_type",
        },
        "Kolla identity and catalog",
    )
    if (
        identity["endpoint_count"] != 3
        or identity["region"] != "RegionOne"
        or identity["service_type"] != "oci-registry"
    ):
        raise KollaMultinodeResultError(
            "Kolla identity and catalog are incomplete"
        )
    return {
        "checks": _true_map(
            identity["checks"],
            expected=IDENTITY_CHECKS,
            label="Kolla identity checks",
        ),
        "endpoint_count": 3,
        "region": "RegionOne",
        "service_type": "oci-registry",
    }


def _validate_acceptance(value: object) -> dict[str, Any]:
    acceptance = _mapping(value, "Kolla multinode acceptance")
    _exact_keys(
        acceptance,
        {
            "data_path",
            "surfaces",
            "ui_consistency",
        },
        "Kolla multinode acceptance",
    )
    surfaces = _mapping(acceptance["surfaces"], "acceptance surfaces")
    _exact_keys(surfaces, set(SURFACES), "acceptance surfaces")
    retained: dict[str, dict[str, Any]] = {}
    for name in SURFACES:
        item = _mapping(surfaces[name], f"acceptance surface {name}")
        _exact_keys(
            item,
            {"evidence_sha256", "passed"},
            f"acceptance surface {name}",
        )
        if item["passed"] is not True:
            raise KollaMultinodeResultError(
                f"acceptance surface {name} did not pass"
            )
        retained[name] = {
            "evidence_sha256": _digest(
                item["evidence_sha256"],
                f"acceptance surface {name}",
            ),
            "passed": True,
        }
    ui = _mapping(acceptance["ui_consistency"], "UI consistency")
    _exact_keys(
        ui,
        {
            "horizon_skyline_same_quota",
            "horizon_skyline_same_repository",
            "server_side_catalog_resolution",
        },
        "UI consistency",
    )
    if any(value is not True for value in ui.values()):
        raise KollaMultinodeResultError("UI consistency is incomplete")
    return {
        "data_path": _true_map(
            acceptance["data_path"],
            expected=DATA_PATH_CHECKS,
            label="Kolla data-path checks",
        ),
        "surfaces": retained,
        "ui_consistency": {
            "horizon_skyline_same_quota": True,
            "horizon_skyline_same_repository": True,
            "server_side_catalog_resolution": True,
        },
    }


def _validate_failures(value: object) -> dict[str, dict[str, Any]]:
    failures = _mapping(value, "Kolla multinode failures")
    _exact_keys(failures, set(FAILURE_CASES), "Kolla multinode failures")
    retained: dict[str, dict[str, Any]] = {}
    for name in FAILURE_CASES:
        item = _mapping(failures[name], f"Kolla failure {name}")
        _exact_keys(
            item,
            {
                "applied",
                "data_integrity",
                "evidence_sha256",
                "expected_behavior_verified",
                "recovered",
                "security_preserved",
            },
            f"Kolla failure {name}",
        )
        if any(
            item[field] is not True
            for field in (
                "applied",
                "data_integrity",
                "expected_behavior_verified",
                "recovered",
                "security_preserved",
            )
        ):
            raise KollaMultinodeResultError(
                f"Kolla failure {name} is incomplete"
            )
        retained[name] = {
            "applied": True,
            "data_integrity": True,
            "evidence_sha256": _digest(
                item["evidence_sha256"],
                f"Kolla failure {name}",
            ),
            "expected_behavior_verified": True,
            "recovered": True,
            "security_preserved": True,
        }
    return retained


def _validate_upgrade(value: object) -> dict[str, Any]:
    upgrade = _mapping(value, "Kolla upgrade and rollback")
    expected = {
        "availability_maintained",
        "compatible_schema_verified",
        "configuration_rollback",
        "digest_persisted",
        "evidence_sha256",
        "image_rollback",
        "key_overlap_verified",
        "migration_replay_safe",
        "old_key_retired",
        "quota_state_equal",
        "rolling_rollback",
        "rolling_upgrade",
        "serial",
    }
    _exact_keys(upgrade, expected, "Kolla upgrade and rollback")
    for name in expected - {"evidence_sha256", "serial"}:
        if upgrade[name] is not True:
            raise KollaMultinodeResultError(
                "Kolla upgrade and rollback are incomplete"
            )
    if upgrade["serial"] != 1:
        raise KollaMultinodeResultError(
            "Kolla upgrade and rollback must be serial"
        )
    return {
        **{
            name: True
            for name in expected - {"evidence_sha256", "serial"}
        },
        "evidence_sha256": _digest(
            upgrade["evidence_sha256"],
            "Kolla upgrade and rollback",
        ),
        "serial": 1,
    }


def _validate_backup_restore(value: object) -> dict[str, Any]:
    expected = (
        "authenticated_comparison",
        "backup_verified",
        "digest_readable",
        "inventory_equal",
        "isolated_restore",
        "no_source_mutation",
        "rgw_restored",
        "rollback_verified",
        "sql_restored",
        "sse_kms",
        "writer_exclusion",
    )
    item = _mapping(value, "Kolla backup and restore")
    _exact_keys(
        item,
        {*expected, "evidence_sha256"},
        "Kolla backup and restore",
    )
    retained = _true_map(
        {name: item[name] for name in expected},
        expected=expected,
        label="Kolla backup and restore checks",
    )
    return {
        **retained,
        "evidence_sha256": _digest(
            item["evidence_sha256"],
            "Kolla backup and restore",
        ),
    }


def _validate_audit(value: object) -> dict[str, int]:
    audit = _mapping(value, "Kolla multinode audit")
    _exact_keys(
        audit,
        {
            "forbidden_backend_exposures",
            "known_secret_matches",
            "log_scan_count",
            "secret_scan_count",
            "unexpected_errors",
        },
        "Kolla multinode audit",
    )
    log_scan_count = _positive_integer(
        audit["log_scan_count"],
        "Kolla log scan count",
    )
    secret_scan_count = _positive_integer(
        audit["secret_scan_count"],
        "Kolla secret scan count",
    )
    if (
        audit["forbidden_backend_exposures"] != 0
        or audit["known_secret_matches"] != 0
        or audit["unexpected_errors"] != 0
    ):
        raise KollaMultinodeResultError(
            "Kolla multinode audit found unsafe evidence"
        )
    return {
        "forbidden_backend_exposures": 0,
        "known_secret_matches": 0,
        "log_scan_count": log_scan_count,
        "secret_scan_count": secret_scan_count,
        "unexpected_errors": 0,
    }


def _validate_teardown(value: object) -> dict[str, Any]:
    teardown = _mapping(value, "Kolla multinode teardown")
    _exact_keys(
        teardown,
        {
            "after_unrelated_sha256",
            "before_unrelated_sha256",
            "evidence_sha256",
            "executed",
            "final_audit",
            "preflight",
            "repeat_safe",
            "residue",
            "terminal_phase",
            "unrelated_state_unchanged",
        },
        "Kolla multinode teardown",
    )
    residue = _mapping(teardown["residue"], "Kolla teardown residue")
    _exact_keys(residue, {*RESIDUE_KEYS, "total"}, "Kolla teardown residue")
    if (
        teardown["terminal_phase"] != PHASES[-1]
        or any(
            teardown[name] is not True
            for name in (
                "executed",
                "final_audit",
                "preflight",
                "repeat_safe",
                "unrelated_state_unchanged",
            )
        )
        or any(residue[name] != 0 for name in (*RESIDUE_KEYS, "total"))
    ):
        raise KollaMultinodeResultError(
            "Kolla multinode teardown left residue"
        )
    before = _digest(
        teardown["before_unrelated_sha256"],
        "Kolla unrelated state before",
    )
    after = _digest(
        teardown["after_unrelated_sha256"],
        "Kolla unrelated state after",
    )
    if before != after:
        raise KollaMultinodeResultError(
            "Kolla multinode teardown changed unrelated state"
        )
    return {
        "evidence_sha256": _digest(
            teardown["evidence_sha256"],
            "Kolla teardown evidence",
        ),
        "residue": {
            **{name: 0 for name in RESIDUE_KEYS},
            "total": 0,
        },
        "terminal_phase": PHASES[-1],
        "unrelated_state_sha256": before,
    }


def _validate_evidence_hashes(value: object) -> dict[str, str]:
    names = (
        "acceptance_sha256",
        "audit_sha256",
        "backup_restore_sha256",
        "deployment_sha256",
        "failures_sha256",
        "identity_sha256",
        "teardown_sha256",
        "topology_sha256",
        "upgrade_rollback_sha256",
    )
    values = _mapping(value, "Kolla evidence hashes")
    _exact_keys(values, set(names), "Kolla evidence hashes")
    return {
        name: _digest(values[name], f"Kolla evidence {name}")
        for name in names
    }


def _validate_evidence(
    value: object,
    *,
    prerequisites: Mapping[str, str],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = _mapping(value, "Kolla multinode evidence")
    _exact_keys(
        evidence,
        {
            "acceptance",
            "audit",
            "backup_restore",
            "deployment",
            "evidence_sha256",
            "execution",
            "failures",
            "identity_catalog",
            "prerequisites",
            "schema",
            "source",
            "teardown",
            "topology",
            "upgrade_rollback",
        },
        "Kolla multinode evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["prerequisites"] != prerequisites
        or evidence["source"] != runtime_source_hashes()
    ):
        raise KollaMultinodeResultError(
            "Kolla multinode evidence binding changed"
        )
    execution = _validate_execution(
        evidence["execution"],
        artifact=artifact,
    )
    topology = _validate_topology(evidence["topology"])
    deployment = _true_map(
        evidence["deployment"],
        expected=DEPLOYMENT_CHECKS,
        label="Kolla deployment checks",
    )
    identity = _validate_identity(evidence["identity_catalog"])
    acceptance = _validate_acceptance(evidence["acceptance"])
    failures = _validate_failures(evidence["failures"])
    upgrade = _validate_upgrade(evidence["upgrade_rollback"])
    backup_restore = _validate_backup_restore(
        evidence["backup_restore"]
    )
    audit = _validate_audit(evidence["audit"])
    teardown = _validate_teardown(evidence["teardown"])
    return {
        "acceptance": {
            "data_path_check_count": len(acceptance["data_path"]),
            "surface_count": len(acceptance["surfaces"]),
            "ui_consistency": True,
        },
        "audit": audit,
        "evidence_sha256": _validate_evidence_hashes(
            evidence["evidence_sha256"]
        ),
        "execution": execution,
        "lifecycle": {
            "backup_restore_verified": all(
                value is True
                for name, value in backup_restore.items()
                if name != "evidence_sha256"
            ),
            "deployment_check_count": len(deployment),
            "failure_case_count": len(failures),
            "identity_check_count": len(identity["checks"]),
            "upgrade_rollback_verified": all(
                value is True
                for name, value in upgrade.items()
                if name not in {"evidence_sha256", "serial"}
            ),
        },
        "residue": dict(teardown["residue"]),
        "topology": {
            "controller_count": topology["controller_count"],
            "controller_failure_domain_count": topology[
                "controller_failure_domain_count"
            ],
            "service_replica_count": sum(
                topology["service_replicas"].values()
            ),
            "storage_count": topology["storage_count"],
            "storage_failure_domain_count": topology[
                "storage_failure_domain_count"
            ],
        },
    }


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
    load_soak_result: object,
    load_soak_digest: str,
    evidence: object,
    evidence_digest: str,
) -> dict[str, Any]:
    prerequisites, _, artifact = _qualified_prerequisites(
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
        load_soak_result=load_soak_result,
        load_soak_digest=load_soak_digest,
    )
    validated = _validate_evidence(
        evidence,
        prerequisites=prerequisites,
        artifact=artifact,
    )
    return {
        **validated,
        "input_evidence_sha256": _digest(
            evidence_digest,
            "Kolla multinode input evidence",
        ),
        "prerequisites": prerequisites,
        "production_candidate": True,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "Kolla multinode result"))
    expected = {
        "acceptance",
        "audit",
        "evidence_sha256",
        "execution",
        "input_evidence_sha256",
        "lifecycle",
        "prerequisites",
        "production_candidate",
        "residue",
        "schema",
        "source",
        "topology",
    }
    _exact_keys(result, expected, "Kolla multinode result")
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise KollaMultinodeResultError(
            "Kolla multinode result is not qualified"
        )
    prerequisites = _mapping(
        result["prerequisites"],
        "Kolla multinode prerequisites",
    )
    expected_prerequisites = {
        "artifact_result_sha256",
        "data_protection_result_sha256",
        "gc_retention_result_sha256",
        "load_soak_result_sha256",
        "maintenance_identity_result_sha256",
        "observability_result_sha256",
        "release_readiness_sha256",
        "rgw_kms_result_sha256",
    }
    _exact_keys(
        prerequisites,
        expected_prerequisites,
        "Kolla multinode prerequisites",
    )
    for name in expected_prerequisites:
        _digest(prerequisites[name], f"Kolla prerequisite {name}")
    _digest(
        result["input_evidence_sha256"],
        "Kolla multinode input evidence",
    )
    execution = _mapping(result["execution"], "Kolla execution summary")
    _exact_keys(
        execution,
        {
            "adapter",
            "coffer_revision",
            "disposable",
            "fresh",
            "kolla_ansible_revision",
            "kolla_release",
            "non_synthetic",
            "phase_count",
            "run_duration_seconds",
        },
        "Kolla execution summary",
    )
    if (
        execution["adapter"] != "openstack"
        or execution["disposable"] is not True
        or execution["fresh"] is not True
        or execution["non_synthetic"] is not True
        or execution["kolla_release"] != KOLLA_RELEASE
        or execution["phase_count"] != len(PHASES)
    ):
        raise KollaMultinodeResultError(
            "Kolla execution summary is incomplete"
        )
    _revision(execution["coffer_revision"], "Coffer revision")
    _revision(
        execution["kolla_ansible_revision"],
        "Kolla-Ansible revision",
    )
    _positive_integer(
        execution["run_duration_seconds"],
        "Kolla run duration",
    )
    topology = _mapping(result["topology"], "Kolla topology summary")
    if topology != {
        "controller_count": 3,
        "controller_failure_domain_count": 3,
        "service_replica_count": sum(SERVICE_REPLICAS.values()),
        "storage_count": 3,
        "storage_failure_domain_count": 3,
    }:
        raise KollaMultinodeResultError(
            "Kolla topology summary is incomplete"
        )
    acceptance = _mapping(
        result["acceptance"],
        "Kolla acceptance summary",
    )
    if acceptance != {
        "data_path_check_count": len(DATA_PATH_CHECKS),
        "surface_count": len(SURFACES),
        "ui_consistency": True,
    }:
        raise KollaMultinodeResultError(
            "Kolla acceptance summary is incomplete"
        )
    lifecycle = _mapping(
        result["lifecycle"],
        "Kolla lifecycle summary",
    )
    if lifecycle != {
        "backup_restore_verified": True,
        "deployment_check_count": len(DEPLOYMENT_CHECKS),
        "failure_case_count": len(FAILURE_CASES),
        "identity_check_count": len(IDENTITY_CHECKS),
        "upgrade_rollback_verified": True,
    }:
        raise KollaMultinodeResultError(
            "Kolla lifecycle summary is incomplete"
        )
    _validate_audit(result["audit"])
    residue = _mapping(result["residue"], "Kolla result residue")
    if residue != {
        **{name: 0 for name in RESIDUE_KEYS},
        "total": 0,
    }:
        raise KollaMultinodeResultError(
            "Kolla multinode result retained residue"
        )
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
            raise KollaMultinodeResultError(
                f"{label} ownership is unsafe"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > 32 * 1024 * 1024:
            raise KollaMultinodeResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except KollaMultinodeResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise KollaMultinodeResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise KollaMultinodeResultError(
            f"{label} must be a JSON object"
        )
    return value, _sha256_bytes(payload)


def _load_prerequisite(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], str]:
    try:
        return _load_private(path, label)
    except KollaMultinodeResultError as error:
        raise KollaMultinodeInputsBlocked(
            f"{label} is absent or unsafe"
        ) from error


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise KollaMultinodeResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise KollaMultinodeResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise KollaMultinodeResultError(
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
        raise KollaMultinodeResultError(
            "unable to write Kolla multinode result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile a fresh production-shaped Kolla multinode, HA, "
            "acceptance, upgrade, restore, and teardown result only after "
            "all first eight production-promotion gates qualify."
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
    parser.add_argument("--load-soak-result", type=Path, required=True)
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
            raise KollaMultinodeInputsBlocked(str(error)) from error
        inputs: dict[str, object] = {
            "release_digest": release_digest,
            "release_readiness": release,
        }
        for argument, label, value_name, digest_name in (
            (
                arguments.artifact_result,
                "artifact specialist result",
                "artifact_result",
                "artifact_digest",
            ),
            (
                arguments.rgw_kms_result,
                "RGW/KMS specialist result",
                "rgw_kms_result",
                "rgw_kms_digest",
            ),
            (
                arguments.maintenance_identity_result,
                "maintenance identity specialist result",
                "maintenance_result",
                "maintenance_digest",
            ),
            (
                arguments.data_protection_result,
                "data-protection specialist result",
                "data_protection_result",
                "data_protection_digest",
            ),
            (
                arguments.observability_result,
                "observability specialist result",
                "observability_result",
                "observability_digest",
            ),
            (
                arguments.gc_retention_result,
                "GC retention specialist result",
                "gc_result",
                "gc_digest",
            ),
            (
                arguments.load_soak_result,
                "load/soak specialist result",
                "load_soak_result",
                "load_soak_digest",
            ),
        ):
            loaded, digest = _load_prerequisite(argument, label)
            inputs[value_name] = loaded
            inputs[digest_name] = digest
        prerequisites, _, _ = _qualified_prerequisites(**inputs)
        evidence, evidence_digest = _load_private(
            arguments.evidence,
            "Kolla multinode evidence",
        )
        if evidence.get("prerequisites") != prerequisites:
            raise KollaMultinodeResultError(
                "Kolla multinode evidence prerequisite binding changed"
            )
        result = compile_result(
            **inputs,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except KollaMultinodeInputsBlocked as error:
        print(
            f"production Kolla multinode gate blocked: {error}",
            file=sys.stderr,
        )
        return 3
    except KollaMultinodeResultError as error:
        print(
            f"production Kolla multinode result error: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
