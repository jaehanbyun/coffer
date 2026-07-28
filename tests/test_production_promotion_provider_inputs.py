from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "production-promotion"
SOURCE = HARNESS / "provider_inputs.py"
INPUT_TEST_SOURCE = ROOT / "tests" / "test_production_promotion_input_lineage.py"
CURRENT = ROOT / "work" / "production-promotion"


def load(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


provider = load("coffer_test_production_provider_inputs", SOURCE)
input_test = load("coffer_provider_input_fixture_helpers", INPUT_TEST_SOURCE)
trust = provider.TRUST
TODAY = date(2026, 7, 28)


def loaded(tmp_path: Path, name: str, value: object) -> Any:
    path = tmp_path / name
    input_test.write_json(path, value, private=True)
    return trust.load_private_json(path, name)


def current_migration(tmp_path: Path) -> dict[str, Any]:
    ledger = tmp_path / "ledger.json"
    release = tmp_path / "release.json"
    ledger.write_bytes((CURRENT / "promotion-ledger.json").read_bytes())
    release.write_bytes((CURRENT / "release-readiness.json").read_bytes())
    ledger.chmod(0o600)
    release.chmod(0o600)
    return provider.MIGRATION.compile_migration(
        v1_ledger=trust.load_private_json(ledger, "v1 ledger"),
        release_readiness=trust.load_private_json(release, "v1 release"),
    )


def test_current_provider_inputs_remain_all_blocked(tmp_path: Path) -> None:
    result = provider.compile_result(
        migration=loaded(tmp_path, "migration.json", current_migration(tmp_path)),
        inputs={},
    )

    assert {
        component: value["status"]
        for component, value in result["derived"]["components"].items()
    } == {
        "ceph": "blocked",
        "distribution": "blocked",
        "oslo_messaging": "blocked",
    }
    assert result["derived"]["qualified_input_classes"] == []
    assert result["derived"]["valid_until"] is None
    assert provider.validate_final_result(result) == result


def test_exact_source_bound_input_can_replace_only_its_legacy_component(
    tmp_path: Path,
) -> None:
    (tmp_path / "lineage").mkdir()
    input_result, policy_path, _, _ = input_test.compile_fixture(
        tmp_path / "lineage",
        "official-upstream.json",
        environment="production",
    )
    migration = current_migration(tmp_path)
    result = provider.compile_test_result(
        migration=loaded(tmp_path, "migration.json", migration),
        inputs={
            "distribution": loaded(
                tmp_path,
                "distribution.json",
                input_result,
            )
        },
        policy_path=policy_path,
        today=TODAY,
    )

    assert result["derived"]["components"]["distribution"]["status"] == "qualified"
    assert result["derived"]["components"]["ceph"]["status"] == "blocked"
    assert result["derived"]["components"]["oslo_messaging"]["status"] == "blocked"
    assert result["derived"]["qualified_input_classes"] == ["official-upstream"]
    assert (
        provider.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
        )
        == result
    )


def test_signed_current_negative_input_remains_blocked(
    tmp_path: Path,
) -> None:
    (tmp_path / "lineage").mkdir()
    input_result, policy_path, _, _ = input_test.compile_fixture(
        tmp_path / "lineage",
        "official-upstream.json",
        environment="production",
        failed_check="runtime",
    )
    result = provider.compile_test_result(
        migration=loaded(tmp_path, "migration.json", current_migration(tmp_path)),
        inputs={
            "distribution": loaded(
                tmp_path,
                "distribution.json",
                input_result,
            )
        },
        policy_path=policy_path,
        today=TODAY,
    )

    distribution = result["derived"]["components"]["distribution"]
    assert distribution["status"] == "blocked"
    assert distribution["reason_code"] == "input-check-failed:runtime"
    assert result["derived"]["qualified_input_classes"] == []


def test_signed_lifecycle_negative_propagates_without_becoming_invalid(
    tmp_path: Path,
) -> None:
    (tmp_path / "lineage").mkdir()
    input_result, policy_path, _, _ = input_test.compile_fixture(
        tmp_path / "lineage",
        "official-upstream.json",
        environment="production",
        lifecycle_overrides={"signer_active": False},
    )
    result = provider.compile_test_result(
        migration=loaded(tmp_path, "migration.json", current_migration(tmp_path)),
        inputs={
            "distribution": loaded(
                tmp_path,
                "distribution.json",
                input_result,
            )
        },
        policy_path=policy_path,
        today=TODAY,
    )

    distribution = result["derived"]["components"]["distribution"]
    assert distribution["status"] == "blocked"
    assert distribution["reason_code"] == "retirement-signer-revoked"
    assert result["derived"]["qualified_input_classes"] == []


def test_component_identity_and_synthetic_inputs_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "production").mkdir()
    input_result, policy_path, _, _ = input_test.compile_fixture(
        tmp_path / "production",
        "official-upstream.json",
        environment="production",
    )
    migration = loaded(tmp_path, "migration.json", current_migration(tmp_path))

    with pytest.raises(
        provider.ProviderInputsError,
        match="ceph input identity",
    ):
        provider.compile_test_result(
            migration=migration,
            inputs={"ceph": loaded(tmp_path, "wrong.json", input_result)},
            policy_path=policy_path,
            today=TODAY,
        )

    (tmp_path / "synthetic").mkdir()
    synthetic, synthetic_policy, _, _ = input_test.compile_fixture(
        tmp_path / "synthetic",
        "official-upstream.json",
        environment="synthetic",
    )
    with pytest.raises(provider.ProviderInputsError):
        provider.compile_test_result(
            migration=migration,
            inputs={
                "distribution": loaded(
                    tmp_path,
                    "synthetic.json",
                    synthetic,
                )
            },
            policy_path=synthetic_policy,
            today=TODAY,
        )


def test_final_result_rederives_embedded_migration_and_input(tmp_path: Path) -> None:
    result = provider.compile_result(
        migration=loaded(tmp_path, "migration.json", current_migration(tmp_path)),
        inputs={},
    )
    tampered = deepcopy(result)
    tampered["derived"]["components"]["distribution"]["status"] = "qualified"

    with pytest.raises(
        provider.ProviderInputsError,
        match="was not derived",
    ):
        provider.validate_final_result(tampered)


def test_provider_result_serialized_budget_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "PROVIDER_RESULT_MAX_BYTES", 1)
    with pytest.raises(
        provider.ProviderInputsError,
        match="fixed budget",
    ):
        provider.compile_result(
            migration=loaded(
                tmp_path,
                "migration.json",
                current_migration(tmp_path),
            ),
            inputs={},
        )


def test_production_api_does_not_accept_policy_injection() -> None:
    with pytest.raises(TypeError):
        provider.validate_final_result({}, today=TODAY)
    with pytest.raises(TypeError):
        provider.validate_final_result(
            {},
            policy_path=Path("/tmp/attacker-policy.json"),
        )


def test_cli_revalidates_exact_owner_only_result(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    migration_path = tmp_path / "migration.json"
    input_test.write_json(
        migration_path,
        current_migration(tmp_path),
        private=True,
    )
    output = tmp_path / "providers.json"

    assert (
        provider.main(
            [
                "--migration",
                str(migration_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert (
        json.loads(output.read_text())["derived"]["components"]["ceph"]["status"]
        == "blocked"
    )
    assert (
        provider.main(
            [
                "--migration",
                str(migration_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    changed = json.loads(output.read_text())
    changed["derived"]["status"] = "qualified"
    output.write_bytes(trust.canonical_bytes(changed) + b"\n")
    assert (
        provider.main(
            [
                "--migration",
                str(migration_path),
                "--output",
                str(output),
            ]
        )
        == 2
    )
