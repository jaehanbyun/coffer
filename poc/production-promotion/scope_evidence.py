from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
INPUT_LINEAGE_SOURCE = DIRECTORY / "input_lineage.py"
PRODUCTION_POLICY_SOURCE = DIRECTORY / "trust-policy-v2.json"

EVIDENCE_PREDICATE_SCHEMA = "coffer.production-scope-evidence-predicate/v2"
QUALIFICATION_PREDICATE_SCHEMA = "coffer.production-scope-qualification-predicate/v2"
STORAGE_PROVIDER_PREDICATE_SCHEMA = "coffer.production-storage-provider-predicate/v2"
RESULT_SCHEMA = "coffer.production-scope-result/v2"
SCOPE_ATTESTATION_MAX_BYTES = 4 * 1024 * 1024
SCOPE_PROVIDER_INPUT_MAX_BYTES = 8 * 1024 * 1024
SCOPE_RESULT_MAX_BYTES = 16 * 1024 * 1024

SCOPES = (
    "horizon",
    "referrers",
    "registry_core",
    "rgw_barbican_kms",
    "skyline",
    "storage_backend",
)
SCOPE_MODES = {
    "horizon": ("horizon",),
    "referrers": ("disabled", "fallback-tag", "native"),
    "registry_core": ("core",),
    "rgw_barbican_kms": ("rgw-barbican-sse-kms",),
    "skyline": ("skyline",),
    "storage_backend": ("s3-compatible",),
}
PROVIDER_REQUIREMENTS = {
    "horizon": ("oslo_messaging",),
    "referrers": ("distribution",),
    "registry_core": ("distribution",),
    "rgw_barbican_kms": ("ceph", "distribution"),
    "skyline": ("oslo_messaging",),
    "storage_backend": (),
}
CHECKS = {
    ("horizon", "horizon"): (
        "browser_tenant_isolation",
        "catalog_gated",
        "client_guides",
        "image_security",
        "live_catalog",
        "multiarch_artifacts",
        "reconfigure_rollback",
        "teardown",
    ),
    ("referrers", "disabled"): (
        "client_guides_disabled",
        "not_advertised",
        "not_required_by_signing",
        "routes_denied",
    ),
    ("referrers", "fallback-tag"): (
        "client_matrix",
        "collision_tests",
        "concurrency_limit_accepted",
        "fallback_scheme",
        "gc_lifecycle",
        "signing_limit_accepted",
        "subject_deletion",
        "teardown",
    ),
    ("referrers", "native"): (
        "client_matrix",
        "concurrent_updates",
        "deletion",
        "filters",
        "gc_lifecycle",
        "native_endpoint",
        "pagination",
        "subject_lifecycle",
        "teardown",
    ),
    ("registry_core", "core"): (
        "core_data_protection",
        "core_observability",
        "distribution_protocol",
        "gc_logical",
        "identity_project_isolation",
        "kolla_ha",
        "load_fault_recovery",
        "multiarch_artifacts",
        "operator_release_review",
        "quota_admission",
        "reconciliation_fencing",
        "teardown",
        "token_security",
        "upgrade_rollback",
    ),
    ("rgw_barbican_kms", "rgw-barbican-sse-kms"): (
        "barbican_sse_kms",
        "cleanup",
        "key_rotation",
        "kms_outage_recovery",
        "least_privilege",
        "positive_size_move",
        "restart_persistence",
        "teardown",
        "wrong_key_recovery",
        "zero_byte_move",
    ),
    ("skyline", "skyline"): (
        "browser_tenant_isolation",
        "catalog_gated",
        "client_guides",
        "image_security",
        "live_catalog",
        "multiarch_artifacts",
        "reconfigure_rollback",
        "teardown",
    ),
    ("storage_backend", "s3-compatible"): (
        "backup_restore",
        "driver_compatibility",
        "least_privilege",
        "load_fault_recovery",
        "multipart_cleanup",
        "persistence",
        "physical_cleanup",
        "shared_replica_state",
        "teardown",
        "upgrade_rollback",
        "verified_tls",
    ),
}
EVIDENCE_KEYS = {
    "horizon": (
        "artifact",
        "browser",
        "image",
        "lifecycle",
        "parent",
        "runtime",
        "teardown",
    ),
    "referrers": ("client", "gc", "lifecycle", "protocol", "teardown"),
    "registry_core": (
        "artifacts",
        "data_protection",
        "gc",
        "identity",
        "kolla",
        "load",
        "observability",
        "operator_release",
        "teardown",
    ),
    "rgw_barbican_kms": (
        "cleanup",
        "faults",
        "restart",
        "rotation",
        "runtime",
        "teardown",
    ),
    "skyline": (
        "artifact",
        "browser",
        "image",
        "lifecycle",
        "parent",
        "runtime",
        "teardown",
    ),
    "storage_backend": (
        "backup_restore",
        "driver",
        "gc",
        "load",
        "runtime",
        "teardown",
    ),
}
FALLBACK_LIMITATIONS = (
    "concurrent-index-update",
    "subject-delete-order",
    "tag-collision",
)

ROLE = ROOT / "ansible" / "roles" / "coffer"
ROLE_ENTRYPOINTS = (
    ROOT / "ansible" / "KOLLA_ANSIBLE_COMMIT",
    ROOT / "ansible" / "coffer.yml",
    ROLE / "tasks" / "main.yml",
)
ROLE_COMMON = (
    ROLE / "defaults" / "main.yml",
    ROLE / "handlers" / "main.yml",
    ROLE / "vars" / "main.yml",
)
ROLE_CORE = (
    ROLE / "tasks" / "bootstrap_service.yml",
    ROLE / "tasks" / "bootstrap.yml",
    ROLE / "tasks" / "check-containers.yml",
    ROLE / "tasks" / "check.yml",
    ROLE / "tasks" / "config_validate.yml",
    ROLE / "tasks" / "config.yml",
    ROLE / "tasks" / "deploy-containers.yml",
    ROLE / "tasks" / "deploy.yml",
    ROLE / "tasks" / "loadbalancer.yml",
    ROLE / "tasks" / "maintenance-precheck.yml",
    ROLE / "tasks" / "observability.yml",
    ROLE / "tasks" / "precheck.yml",
    ROLE / "tasks" / "pull.yml",
    ROLE / "tasks" / "reconfigure.yml",
    ROLE / "tasks" / "register.yml",
    ROLE / "tasks" / "stop.yml",
    ROLE / "tasks" / "upgrade.yml",
    ROLE / "tasks" / "validate_config.yml",
    ROLE / "templates" / "coffer.conf.j2",
    ROLE / "templates" / "fluentd-input.conf.j2",
    ROLE / "templates" / "haproxy-maintenance.cfg.j2",
    ROLE / "templates" / "prometheus-coffer.rules.j2",
    ROLE / "templates" / "prometheus-coffer.yml.j2",
    ROLE / "templates" / "registry-config.yml.j2",
    ROLE / "templates" / "registry-metrics.conf.j2",
    ROLE / "files" / "coffer-operator-dashboard.json",
    ROLE / "files" / "cron-logrotate-global.conf.j2",
)
ROLE_UI = (
    ROLE / "tasks" / "ui-finalize.yml",
    ROLE / "tasks" / "ui-prepare.yml",
)
ROLE_STORAGE = (
    ROLE / "tasks" / "bootstrap_service.yml",
    ROLE / "tasks" / "check-containers.yml",
    ROLE / "tasks" / "config_validate.yml",
    ROLE / "tasks" / "config.yml",
    ROLE / "tasks" / "maintenance-precheck.yml",
    ROLE / "tasks" / "precheck.yml",
    ROLE / "tasks" / "upgrade.yml",
    ROLE / "tasks" / "validate_config.yml",
    ROLE / "templates" / "registry-config.yml.j2",
    ROOT / "docker" / "config" / "coffer-registry.json.j2",
)
SOURCE_PATHS = {
    "horizon": (
        *ROLE_ENTRYPOINTS,
        ROOT / "ui" / "horizon",
        ROOT / "ui" / "images" / "horizon.Containerfile",
        *ROLE_COMMON,
        *ROLE_UI,
    ),
    "referrers": (
        *ROLE_ENTRYPOINTS,
        ROOT / "poc" / "load-soak" / "driver",
        ROOT / "src" / "coffer",
    ),
    "registry_core": (
        *ROLE_ENTRYPOINTS,
        *ROLE_COMMON,
        *ROLE_CORE,
        ROOT / "docker",
        ROOT / "poc" / "kolla-ansible-role",
        ROOT / "pyproject.toml",
        ROOT / "requirements" / "production-constraints.txt",
        ROOT / "src",
    ),
    "rgw_barbican_kms": (
        *ROLE_ENTRYPOINTS,
        ROLE / "defaults" / "main.yml",
        *ROLE_STORAGE,
        ROLE / "templates" / "coffer.conf.j2",
        ROOT / "poc" / "kolla-ha",
        ROOT / "poc" / "load-soak" / "collector",
        ROOT / "poc" / "production-promotion" / "rgw_kms.py",
    ),
    "skyline": (
        *ROLE_ENTRYPOINTS,
        ROOT / "ui" / "images" / "skyline-console.Containerfile",
        ROOT / "ui" / "skyline",
        *ROLE_COMMON,
        *ROLE_UI,
        ROLE / "tasks" / "ui-skyline-proxy.yml",
    ),
    "storage_backend": (
        *ROLE_ENTRYPOINTS,
        *ROLE_COMMON,
        *ROLE_STORAGE,
        ROOT / "src" / "coffer" / "inventory.py",
        ROOT / "src" / "coffer" / "db.py",
        ROOT / "src" / "coffer" / "quota.py",
        ROOT / "src" / "coffer" / "quota_import.py",
        ROOT / "src" / "coffer" / "quota_import_verification.py",
        ROOT / "src" / "coffer" / "schema.py",
        ROOT / "src" / "coffer" / "tokens.py",
        ROOT / "src" / "coffer" / "migrations",
    ),
}


class ScopeEvidenceError(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise ScopeEvidenceError(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ScopeEvidenceError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise ScopeEvidenceError(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)
INPUT_LINEAGE = _load_module(
    "coffer_production_input_lineage_v2",
    INPUT_LINEAGE_SOURCE,
)


def _sha256(path: Path) -> str:
    try:
        return TRUST.sha256_file(path)
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error


def _canonical_digest(value: object) -> str:
    try:
        return TRUST.canonical_sha256(value)
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error


def _require_serialized_size(
    value: object,
    *,
    maximum_bytes: int,
    label: str,
) -> None:
    try:
        size = len(TRUST.canonical_bytes(value)) + 1
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    if size > maximum_bytes:
        raise ScopeEvidenceError(f"{label} size exceeds the fixed budget")


def source_hashes() -> dict[str, str]:
    return {
        "input_lineage_verifier_sha256": _sha256(INPUT_LINEAGE_SOURCE),
        "scope_evidence_verifier_sha256": _sha256(Path(__file__).resolve()),
        "trust_policy_verifier_sha256": _sha256(TRUST_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ScopeEvidenceError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScopeEvidenceError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ScopeEvidenceError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    try:
        return TRUST.digest(value, label)
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error


def _identifier(value: object, label: str) -> str:
    try:
        return TRUST.identifier(value, label)
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error


def _date(value: object, label: str) -> date:
    try:
        return TRUST.parse_date(value, label)
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error


def _tracked_source_files(paths: Sequence[Path]) -> list[Path]:
    all_names: set[str] = set()
    relative_paths: list[str] = []
    for path in paths:
        try:
            relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError as error:
            raise ScopeEvidenceError("scope source path escaped repository") from error
        relative_paths.append(relative)
        try:
            tracked = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "-z", "--", relative],
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise ScopeEvidenceError(
                "unable to inspect tracked scope sources"
            ) from error
        names = {name for name in tracked.stdout.decode().split("\0") if name}
        if not names:
            raise ScopeEvidenceError(f"scope source path is not tracked: {relative}")
        all_names.update(names)
    try:
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--",
                *relative_paths,
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ScopeEvidenceError("unable to inspect tracked scope sources") from error
    if dirty.stdout:
        raise ScopeEvidenceError("tracked scope source is not clean")
    files = [ROOT / name for name in sorted(all_names)]
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ScopeEvidenceError("scope source manifest contains an unsafe file")
    return files


def scope_source_tree_sha256(scope: str) -> str:
    if scope not in SCOPES:
        raise ScopeEvidenceError("scope source tree is unknown")
    result = hashlib.sha256()
    for path in _tracked_source_files(SOURCE_PATHS[scope]):
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix().encode()
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ScopeEvidenceError(f"unable to read scope source {path}") from error
        result.update(len(relative).to_bytes(4, "big"))
        result.update(relative)
        result.update(len(payload).to_bytes(8, "big"))
        result.update(payload)
    return "sha256:" + result.hexdigest()


def provider_requirements(scope: str, mode: str) -> tuple[str, ...]:
    if (scope, mode) == ("referrers", "disabled"):
        return ()
    return PROVIDER_REQUIREMENTS[scope]


def _provider_inputs(
    value: object,
    *,
    scope: str,
    mode: str,
    policy_path: Path,
    today: date,
    injected_policy: bool,
    allow_synthetic_policy: bool,
) -> tuple[dict[str, Any], dict[str, Any], list[date]]:
    inputs = _mapping(value, "scope provider inputs")
    required = set(provider_requirements(scope, mode))
    _exact_keys(inputs, required, "scope provider inputs")
    parsed_inputs: dict[str, Any] = {}
    bindings: dict[str, Any] = {}
    expiry: list[date] = []
    for component in sorted(required):
        raw = inputs[component]
        try:
            if injected_policy:
                result = INPUT_LINEAGE.validate_test_result(
                    raw,
                    policy_path=policy_path,
                    today=today,
                    allow_synthetic_policy=allow_synthetic_policy,
                )
            else:
                result = INPUT_LINEAGE.validate_final_result(raw)
        except INPUT_LINEAGE.InputLineageError as error:
            raise ScopeEvidenceError(f"{component} input result is invalid") from error
        derived = result["derived"]
        if derived["component"] != component:
            raise ScopeEvidenceError(f"{component} provider identity changed")
        result_digest = _canonical_digest(result)
        parsed_inputs[component] = result
        bindings[component] = {
            "input_class": derived["input_class"],
            "input_result_sha256": result_digest,
            "lineage_sha256": derived["lineage_sha256"],
            "policy_sha256": derived["policy_sha256"],
            "valid_until": derived["valid_until"],
        }
        expiry.extend(
            (
                _date(derived["valid_until"], f"{component} valid_until"),
                _date(
                    derived["effective_support_ends_on"],
                    f"{component} support_ends_on",
                ),
            )
        )
    return parsed_inputs, bindings, expiry


def _backend(
    value: object,
    *,
    scope: str,
    policy: Mapping[str, Any],
    policy_sha256: str,
    provider_inputs: Mapping[str, Any],
    today: date,
) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[date],
    Mapping[str, Any] | None,
]:
    requires_backend = scope in {"rgw_barbican_kms", "storage_backend"}
    if not requires_backend:
        if value is not None:
            raise ScopeEvidenceError("storage backend attestation is not allowed")
        return None, None, [], None
    raw_attestation = _mapping(value, "storage backend attestation")
    predicate = _mapping(
        raw_attestation.get("predicate"),
        "storage backend predicate",
    )
    _exact_keys(
        predicate,
        {
            "backend_id",
            "backend_sha256",
            "observed_on",
            "policy_sha256",
            "schema",
            "valid_until",
        },
        "storage backend predicate",
    )
    backend_id = _identifier(predicate["backend_id"], "storage backend ID")
    backend = policy["storage_backends"].get(backend_id)
    if backend is None:
        raise ScopeEvidenceError("storage backend is not policy-approved")
    if scope == "rgw_barbican_kms" and backend["provider_name"] != "ceph-rgw":
        raise ScopeEvidenceError("RGW and Barbican require a Ceph RGW backend")
    observed = _date(predicate["observed_on"], "storage backend observed_on")
    valid_until = _date(
        predicate["valid_until"],
        "storage backend valid_until",
    )
    backend_sha256 = _canonical_digest(backend)
    if (
        predicate["schema"] != STORAGE_PROVIDER_PREDICATE_SCHEMA
        or predicate["backend_sha256"] != backend_sha256
        or predicate["policy_sha256"] != policy_sha256
        or observed > today
        or today - observed > timedelta(days=1)
        or valid_until < today
        or valid_until - observed > timedelta(days=7)
        or valid_until > _date(backend["support_ends_on"], "backend support end")
    ):
        raise ScopeEvidenceError("storage backend evidence is invalid")
    subjects = {
        "backend-catalog": backend_sha256,
        "driver-contract": backend["driver_contract_sha256"],
        "provider-artifact": backend["provider_artifact_sha256"],
        "provider-lineage": backend["provider_lineage_sha256"],
        "provider-source": backend["provider_source_sha256"],
    }
    try:
        attestation = TRUST.verify_attestation(
            raw_attestation,
            policy=policy,
            role="storage-provider",
            predicate_type=policy["predicate_types"]["storage_provider"],
            subjects=dict(sorted(subjects.items())),
            today=today,
        )
        authority = TRUST.policy_authority(
            policy,
            key_id=attestation["key_id"],
            role="storage-provider",
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    if attestation["key_id"] != backend["authority_key_id"]:
        raise ScopeEvidenceError("storage backend signer changed")
    if scope == "rgw_barbican_kms":
        ceph_input = _mapping(
            provider_inputs.get("ceph"),
            "Ceph provider input",
        )
        ceph_lineage = _mapping(
            _mapping(ceph_input.get("bundle"), "Ceph input bundle").get("lineage"),
            "Ceph input lineage",
        )
        ceph_release = _mapping(
            ceph_lineage.get("release"),
            "Ceph input release",
        )
        expected_backend = {
            "provider_artifact_sha256": _canonical_digest(
                ceph_lineage.get("artifacts")
            ),
            "provider_lineage_sha256": _canonical_digest(ceph_lineage),
            "provider_revision": ceph_release.get("revision"),
            "provider_source_sha256": ceph_release.get("source_sha256"),
            "provider_version": ceph_release.get("version"),
        }
        if any(
            backend[name] != expected for name, expected in expected_backend.items()
        ):
            raise ScopeEvidenceError(
                "RGW backend lineage does not match the Ceph input"
            )
    normalized_predicate = {
        "backend_id": backend_id,
        "backend_sha256": backend_sha256,
        "observed_on": observed.isoformat(),
        "policy_sha256": policy_sha256,
        "schema": STORAGE_PROVIDER_PREDICATE_SCHEMA,
        "valid_until": valid_until.isoformat(),
    }
    normalized_attestation = dict(attestation)
    normalized_attestation["predicate"] = normalized_predicate
    normalized_backend = {
        "backend_id": backend_id,
        **backend,
        "provider_attestation_sha256": _canonical_digest(normalized_attestation),
    }
    return (
        normalized_backend,
        normalized_attestation,
        [
            valid_until,
            _date(attestation["expires_on"], "storage backend expiry"),
            _date(backend["support_ends_on"], "backend support end"),
        ],
        authority,
    )


def _referrers(
    value: object,
    *,
    scope: str,
    mode: str,
) -> dict[str, Any] | None:
    if scope != "referrers":
        if value is not None:
            raise ScopeEvidenceError("Referrers metadata is not allowed")
        return None
    details = _mapping(value, "Referrers metadata")
    _exact_keys(details, {"advertised", "limitations"}, "Referrers metadata")
    if mode == "fallback-tag":
        expected = (True, list(FALLBACK_LIMITATIONS))
    elif mode == "native":
        expected = (True, [])
    else:
        expected = (False, [])
    if (
        details["advertised"] is not expected[0]
        or details["limitations"] != expected[1]
    ):
        raise ScopeEvidenceError("Referrers disposition is invalid")
    return {"advertised": expected[0], "limitations": expected[1]}


def _evidence_result_schema(scope: str, name: str) -> str:
    return f"coffer.production-{scope.replace('_', '-')}-{name.replace('_', '-')}/v2"


def _evidence_results(
    value: object,
    *,
    scope: str,
    mode: str,
    adapter_id: str,
    adapter: Mapping[str, Any],
    policy_sha256: str,
    source_tree_sha256: str,
    provider_bindings: Mapping[str, Any],
    backend: Mapping[str, Any] | None,
    today: date,
) -> tuple[dict[str, Any], list[date]]:
    results = _mapping(value, "scope evidence results")
    _exact_keys(results, set(EVIDENCE_KEYS[scope]), "scope evidence results")
    provider_digest = _canonical_digest(provider_bindings)
    expected_subjects = {
        "adapter": _canonical_digest(adapter),
        "policy": policy_sha256,
        "provider-bindings": provider_digest,
        "scope-source": source_tree_sha256,
    }
    if backend is not None:
        expected_subjects["backend-lineage"] = _canonical_digest(backend)
    parsed: dict[str, Any] = {}
    validity: list[date] = []
    covered: list[str] = []
    for name in EVIDENCE_KEYS[scope]:
        result = _mapping(results[name], f"scope evidence result {name}")
        _exact_keys(
            result,
            {
                "bundle_manifest_sha256",
                "checks",
                "failure_codes",
                "observed_on",
                "schema",
                "source",
                "status",
                "subjects",
                "valid_until",
            },
            f"scope evidence result {name}",
        )
        checks = _array(result["checks"], f"scope evidence result {name} checks")
        status = result["status"]
        failure_codes = [
            _identifier(code, f"scope evidence result {name} failure code")
            for code in _array(
                result["failure_codes"],
                f"scope evidence result {name} failure codes",
            )
        ]
        if checks != sorted(set(checks)) or any(
            check not in CHECKS[(scope, mode)] for check in checks
        ) or failure_codes != sorted(set(failure_codes)):
            raise ScopeEvidenceError("scope evidence check coverage is invalid")
        source = _mapping(result["source"], f"scope evidence result {name} source")
        _exact_keys(
            source,
            {
                "adapter_id",
                "built_artifact_sha256",
                "verifier_source_sha256",
            },
            f"scope evidence result {name} source",
        )
        subjects = _mapping(
            result["subjects"],
            f"scope evidence result {name} subjects",
        )
        _exact_keys(
            subjects,
            set(expected_subjects),
            f"scope evidence result {name} subjects",
        )
        normalized_subjects = {
            subject: _digest(
                subjects[subject],
                f"scope evidence result {name} subject {subject}",
            )
            for subject in sorted(subjects)
        }
        observed = _date(
            result["observed_on"],
            f"scope evidence result {name} observed_on",
        )
        valid_until = _date(
            result["valid_until"],
            f"scope evidence result {name} valid_until",
        )
        if (
            result["schema"] != _evidence_result_schema(scope, name)
            or status not in {"failed", "passed"}
            or (status == "passed" and failure_codes)
            or (status == "failed" and not failure_codes)
            or source
            != {
                "adapter_id": adapter_id,
                "built_artifact_sha256": adapter["built_artifact_sha256"],
                "verifier_source_sha256": adapter["verifier_source_sha256"],
            }
            or normalized_subjects != dict(sorted(expected_subjects.items()))
            or observed > today
            or today - observed > timedelta(days=1)
            or observed < _date(adapter["valid_from"], "scope adapter valid_from")
            or valid_until < today
            or valid_until - observed > timedelta(days=7)
            or valid_until > _date(adapter["valid_until"], "scope adapter valid_until")
        ):
            raise ScopeEvidenceError("scope evidence result is invalid")
        parsed[name] = {
            "bundle_manifest_sha256": _digest(
                result["bundle_manifest_sha256"],
                f"scope evidence result {name} bundle",
            ),
            "checks": checks,
            "failure_codes": failure_codes,
            "observed_on": observed.isoformat(),
            "schema": _evidence_result_schema(scope, name),
            "source": dict(source),
            "status": status,
            "subjects": normalized_subjects,
            "valid_until": valid_until.isoformat(),
        }
        covered.extend(checks)
        validity.append(valid_until)
    if sorted(covered) != sorted(CHECKS[(scope, mode)]) or len(covered) != len(
        set(covered)
    ):
        raise ScopeEvidenceError("scope evidence does not cover the fixed checks")
    return parsed, validity


def _evidence_subjects(
    *,
    adapter: Mapping[str, Any],
    policy_sha256: str,
    source_tree_sha256: str,
    provider_bindings: Mapping[str, Any],
    backend: Mapping[str, Any] | None,
    results: Mapping[str, Any],
) -> dict[str, str]:
    subjects = {
        "adapter": _canonical_digest(adapter),
        "policy": policy_sha256,
        "source-tree": source_tree_sha256,
    }
    subjects.update(
        {
            f"provider:{component}": binding["input_result_sha256"]
            for component, binding in provider_bindings.items()
        }
    )
    subjects.update(
        {
            f"result:{name}": _canonical_digest(result)
            for name, result in results.items()
        }
    )
    if backend is not None:
        subjects["backend-lineage"] = _canonical_digest(backend)
    return dict(sorted(subjects.items()))


def _derive(
    *,
    evidence_attestation_value: object,
    qualification_attestation_value: object,
    provider_inputs_value: object,
    policy: Mapping[str, Any],
    policy_sha256: str,
    policy_path: Path,
    today: date,
    injected_policy: bool,
    allow_synthetic_policy: bool,
) -> dict[str, Any]:
    raw_evidence_attestation = _mapping(
        evidence_attestation_value,
        "scope evidence attestation",
    )
    raw_predicate = _mapping(
        raw_evidence_attestation.get("predicate"),
        "scope evidence predicate",
    )
    scope = raw_predicate.get("scope")
    mode = raw_predicate.get("mode")
    if scope not in SCOPES or mode not in SCOPE_MODES[scope]:
        raise ScopeEvidenceError("scope evidence identity is invalid")
    inputs, provider_bindings, provider_expiry = _provider_inputs(
        provider_inputs_value,
        scope=scope,
        mode=mode,
        policy_path=policy_path,
        today=today,
        injected_policy=injected_policy,
        allow_synthetic_policy=allow_synthetic_policy,
    )
    predicate = raw_predicate
    _exact_keys(
        predicate,
        {
            "adapter_id",
            "backend_attestation",
            "evidence_results",
            "fixture_only",
            "mode",
            "observed_on",
            "policy_sha256",
            "provider_bindings",
            "referrers",
            "residue",
            "schema",
            "scope",
            "source_tree_sha256",
            "valid_until",
        },
        "scope evidence predicate",
    )
    adapter_id = _identifier(predicate["adapter_id"], "scope adapter ID")
    adapter = policy["scope_evidence_adapters"].get(adapter_id)
    if (
        adapter is None
        or scope not in adapter["scopes"]
        or adapter["output_schema"] != EVIDENCE_PREDICATE_SCHEMA
        or not isinstance(predicate["fixture_only"], bool)
        or (
            policy["environment"] == "production"
            and predicate["fixture_only"] is not False
        )
    ):
        raise ScopeEvidenceError("scope evidence adapter is not approved")
    source_tree = scope_source_tree_sha256(scope)
    if (
        predicate["source_tree_sha256"] != source_tree
        or adapter["scope_source_sha256"].get(scope) != source_tree
        or predicate["provider_bindings"] != provider_bindings
        or predicate["policy_sha256"] != policy_sha256
        or predicate["schema"] != EVIDENCE_PREDICATE_SCHEMA
    ):
        raise ScopeEvidenceError("scope source or provider binding changed")
    (
        backend,
        backend_attestation,
        backend_expiry,
        backend_authority,
    ) = _backend(
        predicate["backend_attestation"],
        scope=scope,
        policy=policy,
        policy_sha256=policy_sha256,
        provider_inputs=inputs,
        today=today,
    )
    referrers = _referrers(predicate["referrers"], scope=scope, mode=mode)
    results, result_expiry = _evidence_results(
        predicate["evidence_results"],
        scope=scope,
        mode=mode,
        adapter_id=adapter_id,
        adapter=adapter,
        policy_sha256=policy_sha256,
        source_tree_sha256=source_tree,
        provider_bindings=provider_bindings,
        backend=backend,
        today=today,
    )
    observed = _date(predicate["observed_on"], "scope evidence observed_on")
    declared_valid_until = _date(
        predicate["valid_until"],
        "scope evidence valid_until",
    )
    residue = _mapping(predicate["residue"], "scope evidence residue")
    _exact_keys(
        residue,
        {"known_secret_matches", "total", "unexpected_errors"},
        "scope evidence residue",
    )
    if (
        observed > today
        or today - observed > timedelta(days=1)
        or observed < _date(adapter["valid_from"], "scope adapter valid_from")
        or declared_valid_until < today
        or declared_valid_until - observed > timedelta(days=7)
        or declared_valid_until
        > _date(adapter["valid_until"], "scope adapter valid_until")
        or residue
        != {
            "known_secret_matches": 0,
            "total": 0,
            "unexpected_errors": 0,
        }
    ):
        raise ScopeEvidenceError("scope operational evidence is invalid")
    if any(
        _date(result["observed_on"], f"scope result {name} observed_on") > observed
        for name, result in results.items()
    ):
        raise ScopeEvidenceError("scope evidence temporal order is invalid")
    evidence_subjects = _evidence_subjects(
        adapter=adapter,
        policy_sha256=policy_sha256,
        source_tree_sha256=source_tree,
        provider_bindings=provider_bindings,
        backend=backend,
        results=results,
    )
    try:
        evidence_attestation = TRUST.verify_attestation(
            raw_evidence_attestation,
            policy=policy,
            role="scope-evidence",
            predicate_type=policy["predicate_types"]["scope_evidence"],
            subjects=evidence_subjects,
            today=today,
            scope=scope,
        )
        evidence_authority = TRUST.policy_authority(
            policy,
            key_id=evidence_attestation["key_id"],
            role="scope-evidence",
            scope=scope,
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    if (
        evidence_attestation["key_id"] != adapter["authority_key_id"]
        or _date(evidence_attestation["issued_on"], "scope evidence issued_on")
        < _date(adapter["valid_from"], "scope adapter valid_from")
        or _date(evidence_attestation["issued_on"], "scope evidence issued_on")
        < observed
        or _date(evidence_attestation["expires_on"], "scope evidence expiry")
        > _date(adapter["valid_until"], "scope adapter valid_until")
    ):
        raise ScopeEvidenceError("scope evidence adapter signer changed")
    normalized_evidence_predicate = {
        "adapter_id": adapter_id,
        "backend_attestation": backend_attestation,
        "evidence_results": results,
        "fixture_only": predicate["fixture_only"],
        "mode": mode,
        "observed_on": observed.isoformat(),
        "policy_sha256": policy_sha256,
        "provider_bindings": provider_bindings,
        "referrers": referrers,
        "residue": {
            "known_secret_matches": 0,
            "total": 0,
            "unexpected_errors": 0,
        },
        "schema": EVIDENCE_PREDICATE_SCHEMA,
        "scope": scope,
        "source_tree_sha256": source_tree,
        "valid_until": declared_valid_until.isoformat(),
    }
    normalized_evidence_attestation = dict(evidence_attestation)
    normalized_evidence_attestation["predicate"] = normalized_evidence_predicate
    evidence_digest = _canonical_digest(normalized_evidence_attestation)

    raw_qualification = _mapping(
        qualification_attestation_value,
        "scope qualification attestation",
    )
    qualification_predicate = _mapping(
        raw_qualification.get("predicate"),
        "scope qualification predicate",
    )
    _exact_keys(
        qualification_predicate,
        {
            "adapter_id",
            "evidence_attestation_sha256",
            "mode",
            "policy_sha256",
            "provider_bindings",
            "reviewed_on",
            "schema",
            "scope",
            "valid_until",
        },
        "scope qualification predicate",
    )
    reviewed = _date(
        qualification_predicate["reviewed_on"],
        "scope qualification reviewed_on",
    )
    qualification_valid_until = _date(
        qualification_predicate["valid_until"],
        "scope qualification valid_until",
    )
    if (
        qualification_predicate["schema"] != QUALIFICATION_PREDICATE_SCHEMA
        or qualification_predicate["adapter_id"] != adapter_id
        or qualification_predicate["evidence_attestation_sha256"] != evidence_digest
        or qualification_predicate["mode"] != mode
        or qualification_predicate["policy_sha256"] != policy_sha256
        or qualification_predicate["provider_bindings"] != provider_bindings
        or qualification_predicate["scope"] != scope
        or reviewed > today
        or today - reviewed > timedelta(days=1)
        or reviewed
        < _date(evidence_attestation["issued_on"], "scope evidence issued_on")
        or qualification_valid_until < today
        or qualification_valid_until - reviewed > timedelta(days=7)
    ):
        raise ScopeEvidenceError("scope qualification predicate is invalid")
    qualification_subjects = {
        "adapter": _canonical_digest(adapter),
        "policy": policy_sha256,
        "scope-evidence": evidence_digest,
    }
    qualification_subjects.update(
        {
            f"provider:{component}": binding["input_result_sha256"]
            for component, binding in provider_bindings.items()
        }
    )
    if backend is not None:
        qualification_subjects["backend-lineage"] = _canonical_digest(backend)
    try:
        qualification_attestation = TRUST.verify_attestation(
            raw_qualification,
            policy=policy,
            role="scope-qualification",
            predicate_type=policy["predicate_types"]["scope_qualification"],
            subjects=dict(sorted(qualification_subjects.items())),
            today=today,
            scope=scope,
        )
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_attestation["key_id"],
            role="scope-qualification",
            scope=scope,
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    if (
        evidence_authority["trust_domain"] == qualification_authority["trust_domain"]
        or evidence_authority["operator_id"] == qualification_authority["operator_id"]
        or (
            backend_authority is not None
            and (
                backend_authority["trust_domain"]
                in {
                    evidence_authority["trust_domain"],
                    qualification_authority["trust_domain"],
                }
                or backend_authority["operator_id"]
                in {
                    evidence_authority["operator_id"],
                    qualification_authority["operator_id"],
                }
            )
        )
    ):
        raise ScopeEvidenceError("scope evidence authorities are not independent")
    normalized_qualification = dict(qualification_attestation)
    normalized_qualification["predicate"] = {
        "adapter_id": adapter_id,
        "evidence_attestation_sha256": evidence_digest,
        "mode": mode,
        "policy_sha256": policy_sha256,
        "provider_bindings": provider_bindings,
        "reviewed_on": reviewed.isoformat(),
        "schema": QUALIFICATION_PREDICATE_SCHEMA,
        "scope": scope,
        "valid_until": qualification_valid_until.isoformat(),
    }
    validity = [
        declared_valid_until,
        qualification_valid_until,
        _date(evidence_attestation["expires_on"], "scope evidence expiry"),
        _date(
            qualification_attestation["expires_on"],
            "scope qualification expiry",
        ),
        _date(adapter["valid_until"], "scope adapter validity"),
        _date(policy["valid_until"], "scope policy validity"),
        *backend_expiry,
        *provider_expiry,
        *result_expiry,
    ]
    valid_until = min(validity)
    if valid_until < today:
        raise ScopeEvidenceError("scope qualification validity has expired")
    disabled = (scope, mode) == ("referrers", "disabled")
    failures = [
        f"evidence:{name}:{failure_code}"
        for name, result in results.items()
        for failure_code in result["failure_codes"]
    ]
    blocked = bool(failures)
    production = (
        policy["environment"] == "production" and predicate["fixture_only"] is False
    )
    if disabled:
        status = "disabled" if production else "synthetic-disabled"
    elif blocked:
        status = "blocked" if production else "synthetic-blocked"
    else:
        status = "qualified" if production else "synthetic-qualified"
    return {
        "bundle": {
            "backend_attestation": backend_attestation,
            "evidence_attestation": normalized_evidence_attestation,
            "provider_inputs": inputs,
            "qualification_attestation": normalized_qualification,
        },
        "derived": {
            "adapter_id": adapter_id,
            "adapter_sha256": _canonical_digest(adapter),
            "backend": backend,
            "evidence_attestation_sha256": evidence_digest,
            "evidence_results": {
                name: {
                    "result_sha256": _canonical_digest(result),
                    "schema": result["schema"],
                    "valid_until": result["valid_until"],
                }
                for name, result in results.items()
            },
            "mode": mode,
            "policy_id": policy["policy_id"],
            "policy_sha256": policy_sha256,
            "production_ready": production and not disabled and not blocked,
            "provider_bindings": provider_bindings,
            "qualification_sha256": _canonical_digest(normalized_qualification),
            "referrers": referrers,
            "reason_codes": failures,
            "scope": scope,
            "source_tree_sha256": source_tree,
            "status": status,
            "valid_until": valid_until.isoformat(),
        },
        "schema": RESULT_SCHEMA,
        "source": source_hashes(),
    }


def _compile_result_with_policy(
    *,
    evidence_attestation: Any,
    qualification_attestation: Any,
    provider_inputs: Mapping[str, Any],
    policy_path: Path,
    today: date | None,
    allow_synthetic_policy: bool,
    injected_policy: bool,
) -> dict[str, Any]:
    try:
        evidence_attestation_value = TRUST.verify_loaded_document(
            evidence_attestation,
            "scope evidence attestation",
            maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        )
        qualification_attestation_value = TRUST.verify_loaded_document(
            qualification_attestation,
            "scope qualification attestation",
            maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        )
        provider_input_values = {
            component: TRUST.verify_loaded_document(
                item,
                f"{component} provider input",
                maximum_bytes=SCOPE_PROVIDER_INPUT_MAX_BYTES,
            )
            for component, item in provider_inputs.items()
        }
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    _require_serialized_size(
        evidence_attestation_value,
        maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        label="scope evidence attestation",
    )
    _require_serialized_size(
        qualification_attestation_value,
        maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        label="scope qualification attestation",
    )
    for component, item in provider_input_values.items():
        _require_serialized_size(
            item,
            maximum_bytes=SCOPE_PROVIDER_INPUT_MAX_BYTES,
            label=f"{component} provider input",
        )
    current = datetime.now(tz=UTC).date() if today is None else today
    try:
        policy, policy_sha256 = TRUST.load_policy(
            policy_path,
            today=current,
            allow_synthetic=allow_synthetic_policy,
        )
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    result = _derive(
        evidence_attestation_value=evidence_attestation_value,
        qualification_attestation_value=qualification_attestation_value,
        provider_inputs_value=provider_input_values,
        policy=policy,
        policy_sha256=policy_sha256,
        policy_path=policy_path,
        today=current,
        injected_policy=injected_policy,
        allow_synthetic_policy=allow_synthetic_policy,
    )
    _require_serialized_size(
        result,
        maximum_bytes=SCOPE_RESULT_MAX_BYTES,
        label="scope result",
    )
    return result


def compile_result(
    *,
    evidence_attestation: Any,
    qualification_attestation: Any,
    provider_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    return _compile_result_with_policy(
        evidence_attestation=evidence_attestation,
        qualification_attestation=qualification_attestation,
        provider_inputs=provider_inputs,
        policy_path=PRODUCTION_POLICY_SOURCE,
        today=None,
        allow_synthetic_policy=False,
        injected_policy=False,
    )


def compile_test_result(
    *,
    evidence_attestation: Any,
    qualification_attestation: Any,
    provider_inputs: Mapping[str, Any],
    policy_path: Path,
    today: date,
    allow_synthetic_policy: bool,
) -> dict[str, Any]:
    """Exercise an injected policy in tests; never consume this in a ledger."""
    return _compile_result_with_policy(
        evidence_attestation=evidence_attestation,
        qualification_attestation=qualification_attestation,
        provider_inputs=provider_inputs,
        policy_path=policy_path,
        today=today,
        allow_synthetic_policy=allow_synthetic_policy,
        injected_policy=True,
    )


def _validate_result_with_policy(
    value: object,
    *,
    policy_path: Path,
    today: date | None,
    allow_synthetic_policy: bool,
    injected_policy: bool,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    _require_serialized_size(
        value,
        maximum_bytes=SCOPE_RESULT_MAX_BYTES,
        label="scope result",
    )
    result = dict(_mapping(value, "scope result"))
    _exact_keys(
        result,
        {"bundle", "derived", "schema", "source"},
        "scope result",
    )
    if result["schema"] != RESULT_SCHEMA or result["source"] != source_hashes():
        raise ScopeEvidenceError("scope result source is invalid")
    bundle = _mapping(result["bundle"], "scope result bundle")
    _exact_keys(
        bundle,
        {
            "backend_attestation",
            "evidence_attestation",
            "provider_inputs",
            "qualification_attestation",
        },
        "scope result bundle",
    )
    _require_serialized_size(
        bundle["evidence_attestation"],
        maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        label="scope evidence attestation",
    )
    _require_serialized_size(
        bundle["qualification_attestation"],
        maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        label="scope qualification attestation",
    )
    embedded_provider_inputs = _mapping(
        bundle["provider_inputs"],
        "scope provider inputs",
    )
    for component, item in embedded_provider_inputs.items():
        _require_serialized_size(
            item,
            maximum_bytes=SCOPE_PROVIDER_INPUT_MAX_BYTES,
            label=f"{component} provider input",
        )
    try:
        policy, policy_sha256 = TRUST.load_policy(
            policy_path,
            today=current,
            allow_synthetic=allow_synthetic_policy,
        )
    except TRUST.TrustPolicyError as error:
        raise ScopeEvidenceError(str(error)) from error
    expected = _derive(
        evidence_attestation_value=bundle["evidence_attestation"],
        qualification_attestation_value=bundle["qualification_attestation"],
        provider_inputs_value=embedded_provider_inputs,
        policy=policy,
        policy_sha256=policy_sha256,
        policy_path=policy_path,
        today=current,
        injected_policy=injected_policy,
        allow_synthetic_policy=allow_synthetic_policy,
    )
    if result != expected:
        raise ScopeEvidenceError("scope result was not derived")
    if not allow_synthetic_policy and expected["derived"]["status"] not in {
        "blocked",
        "disabled",
        "qualified",
    }:
        raise ScopeEvidenceError("scope result is not production evidence")
    return result


def validate_final_result(
    value: object,
) -> dict[str, Any]:
    return _validate_result_with_policy(
        value,
        policy_path=PRODUCTION_POLICY_SOURCE,
        today=None,
        allow_synthetic_policy=False,
        injected_policy=False,
    )


def validate_test_result(
    value: object,
    *,
    policy_path: Path,
    today: date,
    allow_synthetic_policy: bool,
) -> dict[str, Any]:
    """Validate an injected-policy result in tests; never use in a ledger."""
    return _validate_result_with_policy(
        value,
        policy_path=policy_path,
        today=today,
        allow_synthetic_policy=allow_synthetic_policy,
        injected_policy=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify one source-bound independent production scope."
    )
    parser.add_argument("--scope", choices=SCOPES, required=True)
    parser.add_argument("--evidence-attestation", type=Path, required=True)
    parser.add_argument("--qualification-attestation", type=Path, required=True)
    parser.add_argument("--distribution-input", type=Path)
    parser.add_argument("--ceph-input", type=Path)
    parser.add_argument("--oslo-messaging-input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    paths = {
        "ceph": arguments.ceph_input,
        "distribution": arguments.distribution_input,
        "oslo_messaging": arguments.oslo_messaging_input,
    }
    try:
        evidence_attestation = TRUST.load_private_json(
            arguments.evidence_attestation,
            "scope evidence attestation",
            maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
        )
        predicate = _mapping(
            evidence_attestation.value.get("predicate"),
            "scope evidence predicate",
        )
        if predicate.get("scope") != arguments.scope:
            raise ScopeEvidenceError("scope argument and evidence differ")
        mode = predicate.get("mode")
        if mode not in SCOPE_MODES[arguments.scope]:
            raise ScopeEvidenceError("scope mode is invalid")
        required = set(provider_requirements(arguments.scope, mode))
        if any(paths[name] is None for name in required) or any(
            paths[name] is not None for name in set(paths) - required
        ):
            raise ScopeEvidenceError("scope provider paths are invalid")
        inputs = {
            component: TRUST.load_private_json(
                paths[component],
                f"{component} input result",
                maximum_bytes=SCOPE_PROVIDER_INPUT_MAX_BYTES,
            )
            for component in sorted(required)
        }
        result = compile_result(
            evidence_attestation=evidence_attestation,
            qualification_attestation=TRUST.load_private_json(
                arguments.qualification_attestation,
                "scope qualification attestation",
                maximum_bytes=SCOPE_ATTESTATION_MAX_BYTES,
            ),
            provider_inputs=inputs,
        )
        TRUST.write_owner_only(
            arguments.output,
            result,
            maximum_bytes=SCOPE_RESULT_MAX_BYTES,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ScopeEvidenceError, TRUST.TrustPolicyError) as error:
        print(f"scope evidence error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
