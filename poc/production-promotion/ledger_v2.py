from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
MIGRATION_SOURCE = DIRECTORY / "migration.py"
PROVIDER_INPUTS_SOURCE = DIRECTORY / "provider_inputs.py"
SCOPE_EVIDENCE_SOURCE = DIRECTORY / "scope_evidence.py"
CHECKPOINT_STATUS_SOURCE = DIRECTORY / "checkpoint_status.py"
PRODUCTION_VERIFIER_REGISTRY_SOURCE = DIRECTORY / "verifier-bundles-v2.json"
PRODUCTION_POLICY_SOURCE = DIRECTORY / "trust-policy-v2.json"

SCHEMA = "coffer.production-promotion-ledger/v2"
CORE_SCOPE = "registry_core"
PROFILE_SCOPES = (
    "storage_backend",
    "rgw_barbican_kms",
    "horizon",
    "skyline",
    "referrers",
)
ALL_SCOPES = (CORE_SCOPE, *PROFILE_SCOPES)
STATUSES = ("blocked", "disabled", "pending", "qualified")
LEDGER_PROVIDER_INPUTS_MAX_BYTES = 16 * 1024 * 1024
LEDGER_SCOPE_MAX_BYTES = 16 * 1024 * 1024
LEDGER_RESULT_MAX_BYTES = 16 * 1024 * 1024


class ProductionLedgerV2Error(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise ProductionLedgerV2Error(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ProductionLedgerV2Error(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise ProductionLedgerV2Error(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)
MIGRATION = _load_module(
    "coffer_production_ledger_migration_v2",
    MIGRATION_SOURCE,
)
PROVIDER_INPUTS = _load_module(
    "coffer_production_provider_inputs_v2",
    PROVIDER_INPUTS_SOURCE,
)
SCOPE_EVIDENCE = _load_module(
    "coffer_production_scope_evidence_v2",
    SCOPE_EVIDENCE_SOURCE,
)
CHECKPOINT_STATUS = _load_module(
    "coffer_production_checkpoint_status_v2",
    CHECKPOINT_STATUS_SOURCE,
)


def _sha256(path: Path) -> str:
    try:
        return TRUST.sha256_file(path)
    except TRUST.TrustPolicyError as error:
        raise ProductionLedgerV2Error(str(error)) from error


def _canonical_digest(value: object) -> str:
    try:
        return TRUST.canonical_sha256(value)
    except TRUST.TrustPolicyError as error:
        raise ProductionLedgerV2Error(str(error)) from error


def _require_serialized_size(
    value: object,
    *,
    maximum_bytes: int,
    label: str,
) -> None:
    try:
        size = len(TRUST.canonical_bytes(value)) + 1
    except TRUST.TrustPolicyError as error:
        raise ProductionLedgerV2Error(str(error)) from error
    if size > maximum_bytes:
        raise ProductionLedgerV2Error(
            f"{label} size exceeds the fixed budget"
        )


def source_hashes() -> dict[str, str]:
    return {
        "ledger_v2_verifier_sha256": _sha256(Path(__file__).resolve()),
        "migration_verifier_sha256": _sha256(MIGRATION_SOURCE),
        "provider_inputs_verifier_sha256": _sha256(PROVIDER_INPUTS_SOURCE),
        "scope_evidence_verifier_sha256": _sha256(SCOPE_EVIDENCE_SOURCE),
        "checkpoint_status_verifier_sha256": _sha256(
            CHECKPOINT_STATUS_SOURCE
        ),
        "trust_policy_verifier_sha256": _sha256(TRUST_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionLedgerV2Error(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ProductionLedgerV2Error(f"{label} fields are invalid")


def _missing_scope(
    scope: str,
    providers: Mapping[str, Any],
) -> dict[str, Any]:
    if scope == "referrers":
        requirements: tuple[str, ...] = ()
    else:
        mode = SCOPE_EVIDENCE.SCOPE_MODES[scope][0]
        requirements = SCOPE_EVIDENCE.provider_requirements(scope, mode)
    provider_status = {
        component: providers["components"][component]["status"]
        for component in requirements
    }
    blockers = [
        f"provider:{component}:blocked"
        for component, status in provider_status.items()
        if status == "blocked"
    ]
    status = "blocked" if blockers else "pending"
    reasons = [*blockers, "scope-evidence-missing"]
    return {
        "backend": None,
        "deployment_satisfied": False,
        "evidence": None,
        "mode": "unselected" if scope == "referrers" else None,
        "production_ready": False,
        "provider_bindings": {},
        "provider_requirements": list(requirements),
        "reason_codes": reasons,
        "status": status,
        "valid_until": None,
    }


def _qualified_scope(
    *,
    scope_name: str,
    result: Mapping[str, Any],
    providers: Mapping[str, Any],
) -> dict[str, Any]:
    derived = result["derived"]
    if derived["scope"] != scope_name or derived["status"] not in {
        "blocked",
        "disabled",
        "qualified",
    }:
        raise ProductionLedgerV2Error(f"{scope_name} is not production evidence")
    requirements = SCOPE_EVIDENCE.provider_requirements(
        scope_name,
        derived["mode"],
    )
    if set(derived["provider_bindings"]) != set(requirements):
        raise ProductionLedgerV2Error(f"{scope_name} provider set changed")
    for component in requirements:
        provider = providers["components"][component]
        binding = derived["provider_bindings"][component]
        if (
            provider["status"] != "qualified"
            or provider["input"] is None
            or provider["input"]["input_result_sha256"]
            != binding["input_result_sha256"]
            or provider["input"]["lineage_sha256"] != binding["lineage_sha256"]
        ):
            raise ProductionLedgerV2Error(
                f"{scope_name} provider binding is not current"
            )
    return {
        "backend": derived["backend"],
        "deployment_satisfied": derived["production_ready"] is True,
        "evidence": {
            "result_sha256": _canonical_digest(result),
            "schema": result["schema"],
            "source": result["source"],
        },
        "mode": derived["mode"],
        "production_ready": derived["production_ready"],
        "provider_bindings": derived["provider_bindings"],
        "provider_requirements": list(requirements),
        "reason_codes": derived["reason_codes"],
        "status": derived["status"],
        "valid_until": derived["valid_until"],
    }


def _combination_constraints(
    *,
    core: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> dict[str, Any]:
    storage = profiles["storage_backend"]
    kms = profiles["rgw_barbican_kms"]
    core_storage = None
    if core["status"] == "qualified" and storage["status"] == "qualified":
        core_storage = (
            core["provider_bindings"]["distribution"]["lineage_sha256"]
            in storage["backend"]["tested_distribution_lineages_sha256"]
        )
    kms_storage = None
    kms_core_distribution = None
    if kms["status"] == "qualified" and storage["status"] == "qualified":
        kms_storage = (
            kms["backend"] is not None
            and storage["backend"] is not None
            and kms["backend"]["backend_id"] == storage["backend"]["backend_id"]
        )
    if kms["status"] == "qualified" and core["status"] == "qualified":
        kms_core_distribution = (
            kms["provider_bindings"]["distribution"]["input_result_sha256"]
            == core["provider_bindings"]["distribution"]["input_result_sha256"]
        )
    baseline = (
        core["status"] == "qualified"
        and storage["deployment_satisfied"] is True
        and core_storage is True
    )
    return {
        "baseline_deployment_ready": baseline,
        "core_storage_contract_match": core_storage,
        "kms_core_distribution_match": kms_core_distribution,
        "kms_storage_binding_match": kms_storage,
        "rgw_barbican_kms_deployment_ready": (
            baseline
            and kms["deployment_satisfied"] is True
            and kms_storage is True
            and kms_core_distribution is True
        ),
    }


def _derive(
    *,
    provider_inputs_value: object,
    scope_values: object,
    policy: Mapping[str, Any],
    policy_sha256: str,
    policy_path: Path,
    verifier_registry_path: Path,
    today: date,
    injected_policy: bool,
) -> dict[str, Any]:
    try:
        if injected_policy:
            providers_result = PROVIDER_INPUTS.validate_test_result(
                provider_inputs_value,
                policy_path=policy_path,
                today=today,
            )
        else:
            providers_result = PROVIDER_INPUTS.validate_final_result(
                provider_inputs_value
            )
    except PROVIDER_INPUTS.ProviderInputsError as error:
        raise ProductionLedgerV2Error("provider input result is invalid") from error
    providers = providers_result["derived"]
    if providers["policy_sha256"] != policy_sha256:
        raise ProductionLedgerV2Error("provider policy binding changed")
    raw_scopes = _mapping(scope_values, "scope results")
    if any(scope not in ALL_SCOPES for scope in raw_scopes):
        raise ProductionLedgerV2Error("scope result name is unknown")
    parsed_scopes: dict[str, Any] = {}
    decisions: dict[str, Any] = {}
    for scope_name in ALL_SCOPES:
        if scope_name not in raw_scopes:
            decisions[scope_name] = _missing_scope(scope_name, providers)
            continue
        raw = raw_scopes[scope_name]
        try:
            if injected_policy:
                result = SCOPE_EVIDENCE.validate_test_result(
                    raw,
                    policy_path=policy_path,
                    today=today,
                    allow_synthetic_policy=False,
                )
            else:
                result = SCOPE_EVIDENCE.validate_final_result(raw)
        except SCOPE_EVIDENCE.ScopeEvidenceError as error:
            raise ProductionLedgerV2Error(
                f"{scope_name} scope result is invalid"
            ) from error
        if result["derived"]["policy_sha256"] != policy_sha256:
            raise ProductionLedgerV2Error(f"{scope_name} policy binding changed")
        parsed_scopes[scope_name] = result
        decisions[scope_name] = _qualified_scope(
            scope_name=scope_name,
            result=result,
            providers=providers,
        )
    core = decisions[CORE_SCOPE]
    profiles = {scope: decisions[scope] for scope in PROFILE_SCOPES}
    production_candidate = core["status"] == "qualified"
    counts = Counter(decision["status"] for decision in decisions.values())
    semantic_replay_base = (
        not production_candidate
        and not parsed_scopes
        and not providers["qualified_input_classes"]
    )
    compatibility_reasons: list[str] = []
    if production_candidate:
        compatibility_reasons.append("core-production-candidate")
    if parsed_scopes:
        compatibility_reasons.append("v2-scope-evidence-present")
    if providers["qualified_input_classes"]:
        compatibility_reasons.append("v2-qualified-provider-input-present")
    migration = providers_result["bundle"]["migration"]
    checkpoint_status = CHECKPOINT_STATUS.evaluate_checkpoint(
        migration=migration,
        current_policy=policy,
        at=today,
        registry_path=verifier_registry_path,
    )
    compatibility_reasons.extend(checkpoint_status["reason_codes"])
    semantic_replay_eligible = (
        semantic_replay_base
        and checkpoint_status["checkpoint_verified"] is True
    )
    return {
        "bundle": {
            "provider_inputs": providers_result,
            "scopes": parsed_scopes,
        },
        "candidate_valid_until": core["valid_until"] if production_candidate else None,
        "combination_constraints": _combination_constraints(
            core=core,
            profiles=profiles,
        ),
        "compatibility": {
            "checkpoint_attestation_sha256": checkpoint_status[
                "checkpoint_attestation_sha256"
            ],
            "checkpoint_embedded": checkpoint_status[
                "checkpoint_embedded"
            ],
            "checkpoint_status": checkpoint_status["checkpoint_status"],
            "checkpoint_verified": checkpoint_status[
                "checkpoint_verified"
            ],
            "deployment_id": checkpoint_status["deployment_id"],
            "migration_sha256": _canonical_digest(migration),
            "reason_codes": compatibility_reasons,
            "rollback_authorization_required": True,
            "rollback_authorized": False,
            "rollback_deadline": checkpoint_status["rollback_deadline"],
            "rollback_mode": "signed-exact-v1-byte-replay-only",
            "semantic_replay_eligible": semantic_replay_eligible,
            "v1_ledger_raw_sha256": migration["rollback"]["v1_ledger_raw_sha256"],
            "v1_replay_eligible": False,
            "v2_to_v1_projection": "forbidden",
            "verifier_bundle_id": checkpoint_status[
                "verifier_bundle_id"
            ],
            "verifier_bundle_sha256": checkpoint_status[
                "verifier_bundle_sha256"
            ],
        },
        "core": core,
        "production_candidate": production_candidate,
        "profiles": profiles,
        "provider_inputs": providers["components"],
        "schema": SCHEMA,
        "scope_counts": {status: counts.get(status, 0) for status in STATUSES},
        "source": source_hashes(),
        "status": core["status"],
        "trust": {
            "policy_id": policy["policy_id"],
            "policy_sha256": policy_sha256,
            "policy_valid_until": policy["valid_until"],
        },
    }


def _compile_with_policy(
    *,
    provider_inputs: Any,
    scopes: Mapping[str, Any],
    policy_path: Path,
    verifier_registry_path: Path,
    today: date | None,
    injected_policy: bool,
) -> dict[str, Any]:
    try:
        provider_inputs_value = TRUST.verify_loaded_document(
            provider_inputs,
            "provider inputs",
            maximum_bytes=LEDGER_PROVIDER_INPUTS_MAX_BYTES,
        )
        scope_values = {
            scope: TRUST.verify_loaded_document(
                item,
                f"{scope} scope",
                maximum_bytes=LEDGER_SCOPE_MAX_BYTES,
            )
            for scope, item in scopes.items()
        }
    except TRUST.TrustPolicyError as error:
        raise ProductionLedgerV2Error(str(error)) from error
    _require_serialized_size(
        provider_inputs_value,
        maximum_bytes=LEDGER_PROVIDER_INPUTS_MAX_BYTES,
        label="provider inputs",
    )
    for scope_name, item in scope_values.items():
        _require_serialized_size(
            item,
            maximum_bytes=LEDGER_SCOPE_MAX_BYTES,
            label=f"{scope_name} scope",
        )
    current = datetime.now(tz=UTC).date() if today is None else today
    try:
        policy, policy_sha256 = TRUST.load_policy(policy_path, today=current)
    except TRUST.TrustPolicyError as error:
        raise ProductionLedgerV2Error(str(error)) from error
    result = _derive(
        provider_inputs_value=provider_inputs_value,
        scope_values=scope_values,
        policy=policy,
        policy_sha256=policy_sha256,
        policy_path=policy_path,
        verifier_registry_path=verifier_registry_path,
        today=current,
        injected_policy=injected_policy,
    )
    _require_serialized_size(
        result,
        maximum_bytes=LEDGER_RESULT_MAX_BYTES,
        label="production ledger v2",
    )
    return result


def compile_result(
    *,
    provider_inputs: Any,
    scopes: Mapping[str, Any],
) -> dict[str, Any]:
    return _compile_with_policy(
        provider_inputs=provider_inputs,
        scopes=scopes,
        policy_path=PRODUCTION_POLICY_SOURCE,
        verifier_registry_path=PRODUCTION_VERIFIER_REGISTRY_SOURCE,
        today=None,
        injected_policy=False,
    )


def compile_test_result(
    *,
    provider_inputs: Any,
    scopes: Mapping[str, Any],
    policy_path: Path,
    today: date,
    verifier_registry_path: Path = PRODUCTION_VERIFIER_REGISTRY_SOURCE,
) -> dict[str, Any]:
    """Exercise an injected production policy in tests; never use in release."""
    return _compile_with_policy(
        provider_inputs=provider_inputs,
        scopes=scopes,
        policy_path=policy_path,
        verifier_registry_path=verifier_registry_path,
        today=today,
        injected_policy=True,
    )


def _validate_with_policy(
    value: object,
    *,
    policy_path: Path,
    verifier_registry_path: Path,
    today: date | None,
    injected_policy: bool,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    _require_serialized_size(
        value,
        maximum_bytes=LEDGER_RESULT_MAX_BYTES,
        label="production ledger v2",
    )
    result = dict(_mapping(value, "production ledger v2"))
    _exact_keys(
        result,
        {
            "bundle",
            "candidate_valid_until",
            "combination_constraints",
            "compatibility",
            "core",
            "production_candidate",
            "profiles",
            "provider_inputs",
            "schema",
            "scope_counts",
            "source",
            "status",
            "trust",
        },
        "production ledger v2",
    )
    if result["schema"] != SCHEMA or result["source"] != source_hashes():
        raise ProductionLedgerV2Error("production ledger v2 source is invalid")
    bundle = _mapping(result["bundle"], "production ledger v2 bundle")
    _exact_keys(bundle, {"provider_inputs", "scopes"}, "production ledger v2 bundle")
    _require_serialized_size(
        bundle["provider_inputs"],
        maximum_bytes=LEDGER_PROVIDER_INPUTS_MAX_BYTES,
        label="provider inputs",
    )
    embedded_scopes = _mapping(bundle["scopes"], "production ledger v2 scopes")
    for scope_name, item in embedded_scopes.items():
        _require_serialized_size(
            item,
            maximum_bytes=LEDGER_SCOPE_MAX_BYTES,
            label=f"{scope_name} scope",
        )
    try:
        policy, policy_sha256 = TRUST.load_policy(policy_path, today=current)
    except TRUST.TrustPolicyError as error:
        raise ProductionLedgerV2Error(str(error)) from error
    expected = _derive(
        provider_inputs_value=bundle["provider_inputs"],
        scope_values=embedded_scopes,
        policy=policy,
        policy_sha256=policy_sha256,
        policy_path=policy_path,
        verifier_registry_path=verifier_registry_path,
        today=current,
        injected_policy=injected_policy,
    )
    if result != expected:
        raise ProductionLedgerV2Error("production ledger v2 was not derived")
    return result


def validate_final_result(
    value: object,
) -> dict[str, Any]:
    return _validate_with_policy(
        value,
        policy_path=PRODUCTION_POLICY_SOURCE,
        verifier_registry_path=PRODUCTION_VERIFIER_REGISTRY_SOURCE,
        today=None,
        injected_policy=False,
    )


def validate_test_result(
    value: object,
    *,
    policy_path: Path,
    today: date,
    verifier_registry_path: Path = PRODUCTION_VERIFIER_REGISTRY_SOURCE,
) -> dict[str, Any]:
    """Validate an injected-policy result in tests; never use in release."""
    return _validate_with_policy(
        value,
        policy_path=policy_path,
        verifier_registry_path=verifier_registry_path,
        today=today,
        injected_policy=True,
    )


def _requirements_unmet(
    result: Mapping[str, Any],
    *,
    require_core: bool,
    required_profiles: Sequence[str],
) -> bool:
    requested = set(required_profiles)
    if require_core and result["production_candidate"] is not True:
        return True
    if any(
        result["profiles"][profile]["deployment_satisfied"] is not True
        for profile in requested
    ):
        return True
    constraints = result["combination_constraints"]
    if (
        require_core
        and "storage_backend" in requested
        and constraints["baseline_deployment_ready"] is not True
    ):
        return True
    if (
        "rgw_barbican_kms" in requested
        and constraints["rgw_barbican_kms_deployment_ready"] is not True
    ):
        return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile the independent Coffer production ledger v2."
    )
    parser.add_argument("--provider-inputs", type=Path, required=True)
    for scope_name in ALL_SCOPES:
        parser.add_argument(
            f"--{scope_name.replace('_', '-')}",
            type=Path,
        )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-core", action="store_true")
    parser.add_argument(
        "--require-profile",
        action="append",
        choices=PROFILE_SCOPES,
        default=[],
    )
    arguments = parser.parse_args(argv)
    try:
        scope_paths = {
            scope_name: getattr(arguments, scope_name)
            for scope_name in ALL_SCOPES
            if getattr(arguments, scope_name) is not None
        }
        result = compile_result(
            provider_inputs=TRUST.load_private_json(
                arguments.provider_inputs,
                "provider inputs",
                maximum_bytes=LEDGER_PROVIDER_INPUTS_MAX_BYTES,
            ),
            scopes={
                scope_name: TRUST.load_private_json(
                    path,
                    f"{scope_name} scope",
                    maximum_bytes=LEDGER_SCOPE_MAX_BYTES,
                )
                for scope_name, path in scope_paths.items()
            },
        )
        TRUST.write_or_verify_owner_only(
            arguments.output,
            result,
            label="production ledger v2 result",
            maximum_bytes=LEDGER_RESULT_MAX_BYTES,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        unmet = _requirements_unmet(
            result,
            require_core=arguments.require_core,
            required_profiles=arguments.require_profile,
        )
        return 3 if unmet else 0
    except (
        ProductionLedgerV2Error,
        TRUST.TrustPolicyError,
    ) as error:
        print(f"production ledger v2 error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
