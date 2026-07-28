from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "production-promotion"
SOURCE = HARNESS / "ledger_v2.py"
INPUT_TEST_SOURCE = ROOT / "tests" / "test_production_promotion_input_lineage.py"
SCOPE_TEST_SOURCE = ROOT / "tests" / "test_production_promotion_scope_evidence.py"
CURRENT = ROOT / "work" / "production-promotion"


def load(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


ledger = load("coffer_test_production_ledger_v2", SOURCE)
input_test = load("coffer_ledger_input_fixture_helpers", INPUT_TEST_SOURCE)
scope_test = load("coffer_ledger_scope_fixture_helpers", SCOPE_TEST_SOURCE)
trust = ledger.TRUST
TODAY = date(2026, 7, 28)


def loaded(tmp_path: Path, name: str, value: object) -> Any:
    path = tmp_path / name
    input_test.write_json(path, value, private=True)
    return trust.load_private_json(path, name)


def loaded_bytes(tmp_path: Path, name: str, value: bytes) -> Any:
    path = tmp_path / name
    path.write_bytes(value)
    path.chmod(0o600)
    return trust.load_private_json(path, name)


def current_migration(tmp_path: Path) -> dict[str, Any]:
    return ledger.MIGRATION.compile_migration(
        v1_ledger=loaded_bytes(
            tmp_path,
            "ledger-v1.json",
            (CURRENT / "promotion-ledger.json").read_bytes(),
        ),
        release_readiness=loaded_bytes(
            tmp_path,
            "release-v1.json",
            (CURRENT / "release-readiness.json").read_bytes(),
        ),
    )


def current_provider_result(tmp_path: Path) -> dict[str, Any]:
    return ledger.PROVIDER_INPUTS.compile_result(
        migration=loaded(
            tmp_path,
            "migration.json",
            current_migration(tmp_path),
        ),
        inputs={},
    )


def production_ledger(
    tmp_path: Path,
    scope_modes: dict[str, str],
    *,
    failed_scopes: set[str] | None = None,
    mismatched_storage_core: bool = False,
) -> tuple[dict[str, Any], Path]:
    signing_keys = input_test.keys()
    policy_value = input_test.synthetic_policy(
        signing_keys,
        environment="production",
    )
    manifests: dict[str, dict[str, Any]] = {}
    for scope_name, mode in scope_modes.items():
        manifests.update(
            scope_test.provider_manifests(
                scope_name,
                mode,
                environment="production",
            )
        )
    if "oslo_messaging" in manifests:
        scope_test.add_oslo_policy(
            policy_value,
            manifests["oslo_messaging"],
        )
    evidence_authority = input_test.authority(
        "fixture-scope-evidence",
        signing_keys.scope_evidence,
        "scope-evidence",
    )
    evidence_authority["scopes"] = sorted(scope_modes)
    policy_value["authorities"].append(evidence_authority)
    policy_value["scope_evidence_adapters"] = {
        scope_test.ADAPTER_ID: {
            "authority_key_id": "fixture-scope-evidence",
            "built_artifact_sha256": f"sha256:{'5' * 64}",
            "output_schema": ledger.SCOPE_EVIDENCE.EVIDENCE_PREDICATE_SCHEMA,
            "repository": "https://github.com/jaehanbyun/coffer",
            "revision": "6" * 40,
            "scope_source_sha256": {
                scope_name: ledger.SCOPE_EVIDENCE.scope_source_tree_sha256(scope_name)
                for scope_name in sorted(scope_modes)
            },
            "scopes": sorted(scope_modes),
            "valid_from": "2026-07-01",
            "valid_until": "2027-01-31",
            "verifier_source_sha256": f"sha256:{'7' * 64}",
        }
    }
    if {"storage_backend", "rgw_barbican_kms"} & set(scope_modes):
        ceph_manifest = manifests.get("ceph")
        if ceph_manifest is None:
            ceph_manifest = input_test.fixture("vendor-backport.json")
            ceph_manifest["fixture_only"] = False
        distribution_manifest = manifests.get("distribution")
        if distribution_manifest is None:
            distribution_manifest = input_test.fixture("official-upstream.json")
            distribution_manifest["fixture_only"] = False
        backend = scope_test.backend_policy(
            ceph_manifest,
            distribution_manifest,
        )
        if mismatched_storage_core:
            backend["tested_distribution_lineages_sha256"] = [
                f"sha256:{'f' * 64}"
            ]
        policy_value["storage_backends"] = {scope_test.BACKEND_ID: backend}
    policy_path, policy, policy_digest = input_test.policy_file(
        tmp_path,
        policy_value,
    )
    providers = scope_test.compile_providers(
        tmp_path,
        manifests,
        policy_path=policy_path,
        policy=policy,
        policy_digest=policy_digest,
        signing_keys=signing_keys,
        environment="production",
    )
    migration = current_migration(tmp_path)
    provider_result = ledger.PROVIDER_INPUTS.compile_test_result(
        migration=loaded(tmp_path, "migration.json", migration),
        inputs={
            component: loaded(
                tmp_path,
                f"{component}-input-result.json",
                result,
            )
            for component, result in providers.items()
        },
        policy_path=policy_path,
        today=TODAY,
    )
    scope_results: dict[str, Any] = {}
    for scope_name, mode in scope_modes.items():
        required_components = ledger.SCOPE_EVIDENCE.provider_requirements(
            scope_name, mode
        )
        scope_providers = {
            component: result
            for component, result in providers.items()
            if component in required_components
        }
        evidence, qualification = scope_test.attestations(
            scope_name,
            mode,
            scope_providers,
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
            environment="production",
            failed_result=(
                ledger.SCOPE_EVIDENCE.EVIDENCE_KEYS[scope_name][0]
                if scope_name in (failed_scopes or set())
                else None
            ),
        )
        scope_results[scope_name] = ledger.SCOPE_EVIDENCE.compile_test_result(
            evidence_attestation=loaded(
                tmp_path,
                f"{scope_name}-evidence.json",
                evidence,
            ),
            qualification_attestation=loaded(
                tmp_path,
                f"{scope_name}-qualification.json",
                qualification,
            ),
            provider_inputs={
                component: loaded(
                    tmp_path,
                    f"{scope_name}-{component}-provider.json",
                    result,
                )
                for component, result in scope_providers.items()
            },
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
    result = ledger.compile_test_result(
        provider_inputs=loaded(
            tmp_path,
            "provider-inputs.json",
            provider_result,
        ),
        scopes={
            scope_name: loaded(
                tmp_path,
                f"{scope_name}-result.json",
                scope_result,
            )
            for scope_name, scope_result in scope_results.items()
        },
        policy_path=policy_path,
        today=TODAY,
    )
    return result, policy_path


def test_current_ledger_is_independent_and_fail_closed(
    tmp_path: Path,
) -> None:
    result = ledger.compile_result(
        provider_inputs=loaded(
            tmp_path,
            "provider-inputs.json",
            current_provider_result(tmp_path),
        ),
        scopes={},
    )

    assert result["production_candidate"] is False
    assert result["core"]["status"] == "blocked"
    assert {
        name: profile["status"] for name, profile in result["profiles"].items()
    } == {
        "storage_backend": "pending",
        "rgw_barbican_kms": "blocked",
        "horizon": "blocked",
        "skyline": "blocked",
        "referrers": "pending",
    }
    assert result["compatibility"] == {
        "checkpoint_attestation_sha256": None,
        "checkpoint_embedded": False,
        "checkpoint_status": "missing",
        "checkpoint_verified": False,
        "deployment_id": None,
        "migration_sha256": trust.canonical_sha256(
            result["bundle"]["provider_inputs"]["bundle"]["migration"]
        ),
        "reason_codes": ["signed-pre-upgrade-checkpoint-missing"],
        "rollback_authorization_required": True,
        "rollback_authorized": False,
        "rollback_deadline": None,
        "rollback_mode": "signed-exact-v1-byte-replay-only",
        "semantic_replay_eligible": False,
        "v1_ledger_raw_sha256": result["bundle"]["provider_inputs"]["bundle"][
            "migration"
        ]["rollback"]["v1_ledger_raw_sha256"],
        "v1_replay_eligible": False,
        "v2_to_v1_projection": "forbidden",
        "verifier_bundle_id": None,
        "verifier_bundle_sha256": None,
    }
    assert ledger.validate_final_result(result) == result


def test_core_candidate_is_not_blocked_by_missing_ui_kms_or_referrers(
    tmp_path: Path,
) -> None:
    result, policy_path = production_ledger(
        tmp_path,
        {"registry_core": "core"},
    )

    assert result["production_candidate"] is True
    assert result["status"] == "qualified"
    assert result["core"]["production_ready"] is True
    assert result["profiles"]["rgw_barbican_kms"]["status"] == "blocked"
    assert result["profiles"]["horizon"]["status"] == "blocked"
    assert result["profiles"]["skyline"]["status"] == "blocked"
    assert result["profiles"]["referrers"]["status"] == "pending"
    assert result["combination_constraints"]["baseline_deployment_ready"] is False
    assert (
        ledger.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
        )
        == result
    )


def test_disabled_referrers_is_satisfied_without_changing_core_candidate(
    tmp_path: Path,
) -> None:
    result, _ = production_ledger(
        tmp_path,
        {
            "registry_core": "core",
            "referrers": "disabled",
        },
    )

    assert result["production_candidate"] is True
    assert result["profiles"]["referrers"]["status"] == "disabled"
    assert result["profiles"]["referrers"]["production_ready"] is False
    assert result["profiles"]["referrers"]["deployment_satisfied"] is False


def test_signed_negative_core_scope_remains_an_explicit_blocker(
    tmp_path: Path,
) -> None:
    result, _ = production_ledger(
        tmp_path,
        {"registry_core": "core"},
        failed_scopes={"registry_core"},
    )

    assert result["production_candidate"] is False
    assert result["core"]["status"] == "blocked"
    assert result["core"]["reason_codes"] == [
        "evidence:artifacts:explicit-negative-evidence"
    ]


def test_selected_storage_and_kms_are_bound_as_a_deployable_combination(
    tmp_path: Path,
) -> None:
    result, _ = production_ledger(
        tmp_path,
        {
            "registry_core": "core",
            "storage_backend": "s3-compatible",
            "rgw_barbican_kms": "rgw-barbican-sse-kms",
        },
    )

    assert result["production_candidate"] is True
    assert result["combination_constraints"] == {
        "baseline_deployment_ready": True,
        "core_storage_contract_match": True,
        "kms_core_distribution_match": True,
        "kms_storage_binding_match": True,
        "rgw_barbican_kms_deployment_ready": True,
    }


def test_storage_profile_stays_qualified_but_mismatched_core_is_not_deployable(
    tmp_path: Path,
) -> None:
    result, _ = production_ledger(
        tmp_path,
        {
            "registry_core": "core",
            "storage_backend": "s3-compatible",
        },
        mismatched_storage_core=True,
    )

    assert result["production_candidate"] is True
    assert result["profiles"]["storage_backend"]["status"] == "qualified"
    assert result["combination_constraints"]["core_storage_contract_match"] is False
    assert result["combination_constraints"]["baseline_deployment_ready"] is False
    assert ledger._requirements_unmet(
        result,
        require_core=True,
        required_profiles=["storage_backend"],
    )


def test_kms_enforcement_requires_the_full_compatible_combination(
    tmp_path: Path,
) -> None:
    result, _ = production_ledger(
        tmp_path,
        {
            "registry_core": "core",
            "storage_backend": "s3-compatible",
            "rgw_barbican_kms": "rgw-barbican-sse-kms",
        },
        mismatched_storage_core=True,
    )

    assert result["profiles"]["rgw_barbican_kms"]["status"] == "qualified"
    assert (
        result["combination_constraints"][
            "rgw_barbican_kms_deployment_ready"
        ]
        is False
    )
    assert ledger._requirements_unmet(
        result,
        require_core=True,
        required_profiles=["rgw_barbican_kms"],
    )


def test_unknown_scope_and_derived_candidate_tampering_are_rejected(
    tmp_path: Path,
) -> None:
    provider_result = current_provider_result(tmp_path)
    with pytest.raises(
        ledger.ProductionLedgerV2Error,
        match="unknown",
    ):
        ledger.compile_result(
            provider_inputs=loaded(
                tmp_path,
                "provider-inputs.json",
                provider_result,
            ),
            scopes={
                "attacker_scope": loaded(
                    tmp_path,
                    "attacker-scope.json",
                    {},
                )
            },
        )

    result = ledger.compile_result(
        provider_inputs=loaded(
            tmp_path,
            "provider-inputs-second.json",
            provider_result,
        ),
        scopes={},
    )
    tampered = deepcopy(result)
    tampered["production_candidate"] = True
    tampered["status"] = "qualified"
    with pytest.raises(
        ledger.ProductionLedgerV2Error,
        match="was not derived",
    ):
        ledger.validate_final_result(tampered)
    with pytest.raises(TypeError):
        ledger.validate_final_result(result, today=TODAY)


def test_ledger_result_serialized_budget_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ledger, "LEDGER_RESULT_MAX_BYTES", 1)
    with pytest.raises(
        ledger.ProductionLedgerV2Error,
        match="fixed budget",
    ):
        ledger.compile_result(
            provider_inputs=loaded(
                tmp_path,
                "provider-inputs.json",
                current_provider_result(tmp_path),
            ),
            scopes={},
        )


def test_cli_enforces_core_and_revalidates_exact_owner_only_result(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    provider_path = tmp_path / "provider-inputs.json"
    input_test.write_json(
        provider_path,
        current_provider_result(tmp_path),
        private=True,
    )
    core_output = tmp_path / "core-ledger.json"

    assert (
        ledger.main(
            [
                "--provider-inputs",
                str(provider_path),
                "--output",
                str(core_output),
                "--require-core",
            ]
        )
        == 3
    )
    assert stat.S_IMODE(core_output.stat().st_mode) == 0o600
    assert json.loads(core_output.read_text())["production_candidate"] is False
    assert (
        ledger.main(
            [
                "--provider-inputs",
                str(provider_path),
                "--output",
                str(core_output),
            ]
        )
        == 0
    )

    changed = json.loads(core_output.read_text())
    changed["status"] = "qualified"
    core_output.write_bytes(trust.canonical_bytes(changed) + b"\n")
    assert (
        ledger.main(
            [
                "--provider-inputs",
                str(provider_path),
                "--output",
                str(core_output),
            ]
        )
        == 2
    )

    profile_output = tmp_path / "profile-ledger.json"
    assert (
        ledger.main(
            [
                "--provider-inputs",
                str(provider_path),
                "--output",
                str(profile_output),
                "--require-profile",
                "storage_backend",
            ]
        )
        == 3
    )
    assert stat.S_IMODE(profile_output.stat().st_mode) == 0o600
    assert (
        json.loads(profile_output.read_text())["profiles"]["storage_backend"]["status"]
        == "pending"
    )


def test_make_v2_targets_revalidate_only_the_requested_stage() -> None:
    checkpoint = "/nonexistent/requested-checkpoint.json"
    core = "/nonexistent/requested-core.json"
    migration_dry_run = subprocess.run(
        [
            "make",
            "-n",
            "-C",
            str(HARNESS),
            "migration-v2",
            f"MIGRATION_V2_CHECKPOINT={checkpoint}",
            f"MIGRATION_V2_CHECKPOINT_POLICY={checkpoint}.policy",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    provider_dry_run = subprocess.run(
        [
            "make",
            "-n",
            "-C",
            str(HARNESS),
            "provider-inputs-v2",
            f"DISTRIBUTION_INPUT_V2={checkpoint}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    ledger_dry_run = subprocess.run(
        [
            "make",
            "-n",
            "-C",
            str(HARNESS),
            "ledger-v2",
            f"REGISTRY_CORE_SCOPE_V2={core}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "poc/production-promotion/migration.py" in migration_dry_run.stdout
    assert f'--checkpoint "{checkpoint}"' in migration_dry_run.stdout
    assert "provider_inputs.py" not in migration_dry_run.stdout
    assert "ledger_v2.py" not in migration_dry_run.stdout
    assert "poc/production-promotion/provider_inputs.py" in provider_dry_run.stdout
    assert f'--distribution-input "{checkpoint}"' in provider_dry_run.stdout
    assert "migration.py" not in provider_dry_run.stdout
    assert "ledger_v2.py" not in provider_dry_run.stdout
    assert "poc/production-promotion/ledger_v2.py" in ledger_dry_run.stdout
    assert f'--registry-core "{core}"' in ledger_dry_run.stdout
    assert "migration.py" not in ledger_dry_run.stdout
    assert "provider_inputs.py" not in ledger_dry_run.stdout
