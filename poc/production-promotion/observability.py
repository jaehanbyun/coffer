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
DATA_PROTECTION_RESULT_SOURCE = DIRECTORY / "data_protection.py"
OBSERVABILITY_DIRECTORY = ROOT / "poc" / "observability"
TOPOLOGY_SOURCE = OBSERVABILITY_DIRECTORY / "topology.json"
CONTRACT_SOURCE = OBSERVABILITY_DIRECTORY / "contract.py"
RUNTIME_SOURCES = {
    "api_runner_sha256": ROOT / "src" / "coffer" / "api_runner.py",
    "dashboard_sha256": (
        ROOT
        / "ansible"
        / "roles"
        / "coffer"
        / "files"
        / "coffer-operator-dashboard.json"
    ),
    "data_protection_result_verifier_sha256": (
        DATA_PROTECTION_RESULT_SOURCE
    ),
    "edge_runner_sha256": ROOT / "src" / "coffer" / "edge_runner.py",
    "observability_contract_sha256": CONTRACT_SOURCE,
    "observability_runtime_sha256": (
        ROOT / "src" / "coffer" / "observability.py"
    ),
    "observability_topology_sha256": TOPOLOGY_SOURCE,
    "prometheus_rules_sha256": (
        ROOT
        / "ansible"
        / "roles"
        / "coffer"
        / "templates"
        / "prometheus-coffer.rules.j2"
    ),
    "prometheus_targets_sha256": (
        ROOT
        / "ansible"
        / "roles"
        / "coffer"
        / "templates"
        / "prometheus-coffer.yml.j2"
    ),
    "reconciliation_runner_sha256": (
        ROOT / "src" / "coffer" / "reconciliation_runner.py"
    ),
    "registry_metrics_config_sha256": (
        ROOT
        / "ansible"
        / "roles"
        / "coffer"
        / "templates"
        / "registry-metrics.conf.j2"
    ),
    "registry_metrics_runner_sha256": (
        ROOT / "src" / "coffer" / "registry_metrics_runner.py"
    ),
    "runbook_sha256": ROOT / "docs" / "runbooks" / "observability.md",
}

SCHEMA = "coffer.production-promotion-observability-result/v1"
EVIDENCE_SCHEMA = "coffer.production-promotion-observability-evidence/v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
MINIMUM_REPLICAS = {
    "api": 2,
    "edge": 2,
    "reconcile": 1,
    "registry": 2,
}
OBJECTIVES = {
    "control": 9990,
    "publish": 9950,
    "pull": 9990,
    "reconciliation": 9900,
}
RESIDUE_KEYS = {
    "certificates",
    "containers",
    "dashboard_files",
    "monitoring_acls",
    "processes",
    "proxy_files",
    "rule_files",
    "runtime_files",
    "target_files",
    "temporary_files",
}


class ObservabilityResultError(RuntimeError):
    pass


class ObservabilityInputsBlocked(ObservabilityResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ObservabilityResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise ObservabilityResultError(f"unable to load {path}") from error
    return module


DATA_PROTECTION_RESULT = _load_module(
    "coffer_observability_promotion_data_protection",
    DATA_PROTECTION_RESULT_SOURCE,
)
MAINTENANCE_RESULT = DATA_PROTECTION_RESULT.MAINTENANCE_RESULT
RGW_KMS_RESULT = DATA_PROTECTION_RESULT.RGW_KMS_RESULT
OBSERVABILITY_CONTRACT = _load_module(
    "coffer_observability_promotion_contract",
    CONTRACT_SOURCE,
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ObservabilityResultError(f"unable to hash {path}") from error


def runtime_source_hashes() -> dict[str, str]:
    return {
        name: _sha256(path)
        for name, path in sorted(RUNTIME_SOURCES.items())
    }


def source_hashes() -> dict[str, str]:
    return {
        "observability_compiler_sha256": _sha256(Path(__file__).resolve()),
        **runtime_source_hashes(),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservabilityResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ObservabilityResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ObservabilityResultError(f"{label} is invalid")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ObservabilityResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    result = _nonnegative_integer(value, label)
    if result < 1:
        raise ObservabilityResultError(f"{label} is invalid")
    return result


def _all_true(
    value: object,
    fields: set[str],
    label: str,
) -> dict[str, bool]:
    item = _mapping(value, label)
    _exact_keys(item, fields, label)
    if any(item[name] is not True for name in fields):
        raise ObservabilityResultError(f"{label} is incomplete")
    return {name: True for name in sorted(fields)}


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
) -> dict[str, str]:
    try:
        base = DATA_PROTECTION_RESULT._qualified_prerequisites(
            release_readiness=release_readiness,
            release_digest=release_digest,
            artifact_result=artifact_result,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms_result,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_result=maintenance_result,
            maintenance_digest=maintenance_digest,
        )
        qualified_data = DATA_PROTECTION_RESULT.validate_final_result(
            data_protection_result
        )
    except DATA_PROTECTION_RESULT.DataProtectionInputsBlocked as error:
        raise ObservabilityInputsBlocked(str(error)) from error
    except DATA_PROTECTION_RESULT.DataProtectionResultError as error:
        raise ObservabilityInputsBlocked(
            "data protection is not candidate-qualified"
        ) from error
    if qualified_data["prerequisites"] != base:
        raise ObservabilityInputsBlocked(
            "data-protection prerequisite binding changed"
        )
    return {
        **base,
        "data_protection_result_sha256": _digest(
            data_protection_digest,
            "data-protection result",
        ),
    }


def _topology() -> Any:
    try:
        return OBSERVABILITY_CONTRACT.load_topology(TOPOLOGY_SOURCE)
    except OBSERVABILITY_CONTRACT.ContractError as error:
        raise ObservabilityResultError(
            "observability topology is invalid"
        ) from error


def _validate_execution(value: object) -> dict[str, Any]:
    execution = _mapping(value, "observability execution")
    _exact_keys(
        execution,
        {
            "adapter",
            "disposable",
            "non_synthetic",
            "pilot_window_seconds",
        },
        "observability execution",
    )
    window = _positive_integer(
        execution["pilot_window_seconds"],
        "observability pilot window",
    )
    if (
        execution["adapter"] != "openstack"
        or execution["disposable"] is not True
        or execution["non_synthetic"] is not True
        or window < 900
    ):
        raise ObservabilityResultError(
            "observability execution is not a complete live pilot"
        )
    return {
        "adapter": "openstack",
        "disposable": True,
        "non_synthetic": True,
        "pilot_window_seconds": window,
    }


def _validate_targets(value: object) -> dict[str, Any]:
    targets = _mapping(value, "observability targets")
    _exact_keys(
        targets,
        {
            "component_counts",
            "direct_target_count",
            "expected_target_count",
            "scrapes_successful",
            "target_set_sha256",
            "unique_target_count",
        },
        "observability targets",
    )
    components = _mapping(
        targets["component_counts"],
        "observability target component counts",
    )
    _exact_keys(
        components,
        set(MINIMUM_REPLICAS),
        "observability target component counts",
    )
    normalized = {
        name: _positive_integer(
            components[name],
            f"observability {name} replica count",
        )
        for name in sorted(MINIMUM_REPLICAS)
    }
    if any(
        normalized[name] < minimum
        for name, minimum in MINIMUM_REPLICAS.items()
    ):
        raise ObservabilityResultError(
            "observability replica coverage is incomplete"
        )
    expected = _positive_integer(
        targets["expected_target_count"],
        "observability expected target count",
    )
    direct = _positive_integer(
        targets["direct_target_count"],
        "observability direct target count",
    )
    unique = _positive_integer(
        targets["unique_target_count"],
        "observability unique target count",
    )
    total = sum(normalized.values())
    if (
        total != expected
        or direct != expected
        or unique != expected
        or targets["scrapes_successful"] is not True
    ):
        raise ObservabilityResultError(
            "observability direct target coverage is incomplete"
        )
    return {
        "component_counts": normalized,
        "direct_target_count": direct,
        "expected_target_count": expected,
        "scrapes_successful": True,
        "target_set_sha256": _digest(
            targets["target_set_sha256"],
            "observability target set",
        ),
        "unique_target_count": unique,
    }


def _validate_transport(value: object) -> dict[str, bool]:
    return _all_true(
        value,
        {
            "direct_per_replica",
            "monitoring_network_only",
            "no_forwarded_client_headers",
            "profiling_denied",
            "public_operational_paths_denied",
            "public_target_refused",
            "registry_allowlist_proxy",
            "registry_loopback_debug",
            "verified_backend_tls",
            "vip_target_refused",
        },
        "observability transport",
    )


def _validate_metric_schema(value: object) -> dict[str, Any]:
    metrics = _mapping(value, "observability metric schema")
    _exact_keys(
        metrics,
        {
            "alert_count",
            "bounded_labels",
            "counter_reset_requires_new_start",
            "dashboard_row_count",
            "duplicate_healthy_series",
            "forbidden_label_count",
            "process_start_present",
            "recording_rule_count",
            "required_series_present",
            "schema_consistent",
            "scrape_interval_seconds",
            "stale_after_seconds",
            "stale_series_removed",
            "worker_count_per_container",
        },
        "observability metric schema",
    )
    topology = _topology()
    expected_rules = len(topology.raw["recording_rules"])
    expected_alerts = len(topology.raw["alerts"])
    expected_rows = len(topology.raw["dashboard_rows"])
    if (
        metrics["recording_rule_count"] != expected_rules
        or metrics["alert_count"] != expected_alerts
        or metrics["dashboard_row_count"] != expected_rows
        or metrics["scrape_interval_seconds"]
        != topology.raw["scrape_interval_seconds"]
        or metrics["stale_after_seconds"]
        != topology.raw["stale_after_seconds"]
        or metrics["worker_count_per_container"] != 1
        or metrics["forbidden_label_count"] != 0
        or metrics["duplicate_healthy_series"] != 0
        or any(
            metrics[name] is not True
            for name in (
                "bounded_labels",
                "counter_reset_requires_new_start",
                "process_start_present",
                "required_series_present",
                "schema_consistent",
                "stale_series_removed",
            )
        )
    ):
        raise ObservabilityResultError(
            "observability metric schema is not qualified"
        )
    return dict(metrics)


def _validate_restarts(value: object) -> dict[str, Any]:
    restarts = _mapping(value, "observability restart evidence")
    _exact_keys(
        restarts,
        {
            "availability_maintained",
            "component_restart_counts",
            "counter_resets_valid",
            "no_duplicate_healthy_series",
            "recording_rules_continuous",
            "rolling_restart",
            "rolling_rollback",
            "rolling_upgrade",
            "stale_series_removed",
        },
        "observability restart evidence",
    )
    counts = _mapping(
        restarts["component_restart_counts"],
        "observability component restart counts",
    )
    _exact_keys(
        counts,
        set(MINIMUM_REPLICAS),
        "observability component restart counts",
    )
    normalized = {
        name: _positive_integer(
            counts[name],
            f"observability {name} restart count",
        )
        for name in sorted(MINIMUM_REPLICAS)
    }
    if any(
        restarts[name] is not True
        for name in (
            "availability_maintained",
            "counter_resets_valid",
            "no_duplicate_healthy_series",
            "recording_rules_continuous",
            "rolling_restart",
            "rolling_rollback",
            "rolling_upgrade",
            "stale_series_removed",
        )
    ):
        raise ObservabilityResultError(
            "observability restart lifecycle is incomplete"
        )
    return {**dict(restarts), "component_restart_counts": normalized}


def _validate_alerts(value: object) -> dict[str, dict[str, Any]]:
    alerts = _mapping(value, "observability alert evidence")
    expected = tuple(str(name) for name in _topology().raw["alerts"])
    _exact_keys(alerts, set(expected), "observability alert evidence")
    result: dict[str, dict[str, Any]] = {}
    for name in expected:
        item = _mapping(alerts[name], f"observability alert {name}")
        _exact_keys(
            item,
            {"evidence_sha256", "fired", "recovered"},
            f"observability alert {name}",
        )
        if item["fired"] is not True or item["recovered"] is not True:
            raise ObservabilityResultError(
                "observability alert lifecycle is incomplete"
            )
        result[name] = {
            "evidence_sha256": _digest(
                item["evidence_sha256"],
                f"observability alert {name}",
            ),
            "fired": True,
            "recovered": True,
        }
    return result


def _validate_failure_budget(value: object) -> dict[str, Any]:
    budget = _mapping(value, "observability failure budget")
    _exact_keys(
        budget,
        {
            "client_failures_excluded",
            "dependency_failures_counted",
            "fast_burn_verified",
            "maintenance_fences_excluded",
            "objective_basis_points",
            "policy_days",
            "recovery_cleared",
            "slow_burn_verified",
            "work_freeze_verified",
        },
        "observability failure budget",
    )
    objectives = _mapping(
        budget["objective_basis_points"],
        "observability objectives",
    )
    if objectives != OBJECTIVES or budget["policy_days"] != 30:
        raise ObservabilityResultError(
            "observability objectives changed"
        )
    for name in (
        "client_failures_excluded",
        "dependency_failures_counted",
        "fast_burn_verified",
        "maintenance_fences_excluded",
        "recovery_cleared",
        "slow_burn_verified",
        "work_freeze_verified",
    ):
        if budget[name] is not True:
            raise ObservabilityResultError(
                "observability failure-budget proof is incomplete"
            )
    return {**dict(budget), "objective_basis_points": dict(OBJECTIVES)}


def _validate_dependencies(value: object) -> dict[str, bool]:
    fields = set(_topology().raw["application_labels"]["dependency"])
    return _all_true(
        value,
        fields,
        "observability dependency correlation",
    )


def _validate_audit(value: object) -> dict[str, int]:
    audit = _mapping(value, "observability audit")
    _exact_keys(
        audit,
        {
            "alert_evaluation_count",
            "forbidden_label_matches",
            "known_secret_matches",
            "log_scan_count",
            "sample_count",
            "unexpected_errors",
        },
        "observability audit",
    )
    result = {
        "alert_evaluation_count": _positive_integer(
            audit["alert_evaluation_count"],
            "observability alert evaluation count",
        ),
        "forbidden_label_matches": _nonnegative_integer(
            audit["forbidden_label_matches"],
            "observability forbidden label matches",
        ),
        "known_secret_matches": _nonnegative_integer(
            audit["known_secret_matches"],
            "observability known secret matches",
        ),
        "log_scan_count": _positive_integer(
            audit["log_scan_count"],
            "observability log scan count",
        ),
        "sample_count": _positive_integer(
            audit["sample_count"],
            "observability sample count",
        ),
        "unexpected_errors": _nonnegative_integer(
            audit["unexpected_errors"],
            "observability unexpected errors",
        ),
    }
    if (
        result["forbidden_label_matches"] != 0
        or result["known_secret_matches"] != 0
        or result["unexpected_errors"] != 0
    ):
        raise ObservabilityResultError(
            "observability audit found unsafe evidence"
        )
    return result


def _validate_residue(value: object) -> dict[str, int]:
    residue = _mapping(value, "observability residue")
    names = RESIDUE_KEYS | {"known_secret_matches", "total"}
    _exact_keys(residue, names, "observability residue")
    result = {
        name: _nonnegative_integer(
            residue[name],
            f"observability {name} residue",
        )
        for name in names
    }
    if any(result.values()) or result["total"] != sum(
        result[name] for name in names if name != "total"
    ):
        raise ObservabilityResultError("observability residue remains")
    return {name: 0 for name in sorted(names)}


def _validate_evidence_hashes(value: object) -> dict[str, str]:
    hashes = _mapping(value, "observability evidence hashes")
    names = {
        "alerts_sha256",
        "audit_sha256",
        "dependencies_sha256",
        "failure_budget_sha256",
        "metric_schema_sha256",
        "restarts_sha256",
        "targets_sha256",
        "teardown_sha256",
        "transport_sha256",
    }
    _exact_keys(hashes, names, "observability evidence hashes")
    return {
        name: _digest(hashes[name], f"observability {name}")
        for name in sorted(names)
    }


def _validate_evidence(
    value: object,
    *,
    prerequisites: Mapping[str, str],
) -> dict[str, Any]:
    evidence = _mapping(value, "observability evidence")
    _exact_keys(
        evidence,
        {
            "alerts",
            "audit",
            "dependencies",
            "evidence_sha256",
            "execution",
            "failure_budget",
            "metric_schema",
            "prerequisites",
            "residue",
            "restarts",
            "schema",
            "source",
            "targets",
            "transport",
        },
        "observability evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["prerequisites"] != prerequisites
        or evidence["source"] != runtime_source_hashes()
    ):
        raise ObservabilityResultError(
            "observability evidence binding changed"
        )
    result = {
        "alerts": _validate_alerts(evidence["alerts"]),
        "audit": _validate_audit(evidence["audit"]),
        "dependencies": _validate_dependencies(evidence["dependencies"]),
        "evidence_sha256": _validate_evidence_hashes(
            evidence["evidence_sha256"]
        ),
        "execution": _validate_execution(evidence["execution"]),
        "failure_budget": _validate_failure_budget(
            evidence["failure_budget"]
        ),
        "metric_schema": _validate_metric_schema(
            evidence["metric_schema"]
        ),
        "residue": _validate_residue(evidence["residue"]),
        "restarts": _validate_restarts(evidence["restarts"]),
        "targets": _validate_targets(evidence["targets"]),
        "transport": _validate_transport(evidence["transport"]),
    }
    try:
        OBSERVABILITY_CONTRACT.validate_retained_payload(result)
    except OBSERVABILITY_CONTRACT.ContractError as error:
        raise ObservabilityResultError(
            "observability result retained forbidden data"
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
        maintenance_result=maintenance_result,
        maintenance_digest=maintenance_digest,
        data_protection_result=data_protection_result,
        data_protection_digest=data_protection_digest,
    )
    validated = _validate_evidence(
        evidence,
        prerequisites=prerequisites,
    )
    return {
        **validated,
        "input_evidence_sha256": _digest(
            evidence_digest,
            "observability input evidence",
        ),
        "prerequisites": prerequisites,
        "production_candidate": True,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "observability result"))
    expected = {
        "alerts",
        "audit",
        "dependencies",
        "evidence_sha256",
        "execution",
        "failure_budget",
        "input_evidence_sha256",
        "metric_schema",
        "prerequisites",
        "production_candidate",
        "residue",
        "restarts",
        "schema",
        "source",
        "targets",
        "transport",
    }
    _exact_keys(result, expected, "observability result")
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise ObservabilityResultError(
            "observability result is not qualified"
        )
    prerequisites = _mapping(
        result["prerequisites"],
        "observability prerequisites",
    )
    expected_prerequisites = {
        "artifact_result_sha256",
        "data_protection_result_sha256",
        "maintenance_identity_result_sha256",
        "release_readiness_sha256",
        "rgw_kms_result_sha256",
    }
    _exact_keys(
        prerequisites,
        expected_prerequisites,
        "observability prerequisites",
    )
    for name in expected_prerequisites:
        _digest(prerequisites[name], f"observability prerequisite {name}")
    _digest(result["input_evidence_sha256"], "observability input evidence")
    _validate_execution(result["execution"])
    _validate_targets(result["targets"])
    _validate_transport(result["transport"])
    _validate_metric_schema(result["metric_schema"])
    _validate_restarts(result["restarts"])
    _validate_alerts(result["alerts"])
    _validate_failure_budget(result["failure_budget"])
    _validate_dependencies(result["dependencies"])
    _validate_audit(result["audit"])
    _validate_residue(result["residue"])
    _validate_evidence_hashes(result["evidence_sha256"])
    try:
        OBSERVABILITY_CONTRACT.validate_retained_payload(result)
    except OBSERVABILITY_CONTRACT.ContractError as error:
        raise ObservabilityResultError(
            "observability result retained forbidden data"
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
            raise ObservabilityResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise ObservabilityResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except ObservabilityResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservabilityResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise ObservabilityResultError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise ObservabilityResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise ObservabilityResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ObservabilityResultError(
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
        raise ObservabilityResultError(
            "unable to write observability result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _load_prerequisite(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], str]:
    try:
        return _load_private(path, label)
    except ObservabilityResultError as error:
        raise ObservabilityInputsBlocked(
            f"{label} is absent or unsafe"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile live direct-per-replica, restart-correct metrics, "
            "alert, failure-budget, audit, and teardown evidence only after "
            "every earlier promotion prerequisite qualifies."
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
            raise ObservabilityInputsBlocked(str(error)) from error
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
        prerequisites = _qualified_prerequisites(
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
        )
        evidence, evidence_digest = _load_private(
            arguments.evidence,
            "observability evidence",
        )
        if evidence.get("prerequisites") != prerequisites:
            raise ObservabilityResultError(
                "observability evidence prerequisite binding changed"
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
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ObservabilityInputsBlocked as error:
        print(
            f"production observability gate blocked: {error}",
            file=sys.stderr,
        )
        return 3
    except ObservabilityResultError as error:
        print(
            f"production observability result error: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
