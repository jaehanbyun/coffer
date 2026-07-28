from __future__ import annotations

import base64
import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "migration.py"
CURRENT = ROOT / "work" / "production-promotion"
V1_LEDGER = CURRENT / "promotion-ledger.json"
V1_RELEASE = CURRENT / "release-readiness.json"

SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_migration",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)
trust = migration.TRUST


def private_bytes(path: Path, payload: bytes) -> Any:
    path.write_bytes(payload)
    path.chmod(0o600)
    return trust.load_private_json(path, path.name)


def private_json(path: Path, value: object) -> Any:
    return private_bytes(path, trust.canonical_bytes(value) + b"\n")


def compile_current(tmp_path: Path) -> dict[str, Any]:
    return migration.compile_migration(
        v1_ledger=private_bytes(tmp_path / "ledger.json", V1_LEDGER.read_bytes()),
        release_readiness=private_bytes(
            tmp_path / "release.json",
            V1_RELEASE.read_bytes(),
        ),
    )


def test_current_v1_maps_negative_first_without_any_pass(tmp_path: Path) -> None:
    ledger_value = json.loads(V1_LEDGER.read_text())
    result = compile_current(tmp_path)

    assert result["schema"] == migration.SCHEMA
    assert result["checkpoint"] == {
        "attestation_bytes_base64": None,
        "attestation_canonical_sha256": None,
        "attestation_raw_sha256": None,
        "present": False,
        "trust_policy_bytes_base64": None,
        "trust_policy_canonical_sha256": None,
        "trust_policy_raw_sha256": None,
    }
    assert all(
        component["status"] == "blocked" for component in result["components"].values()
    )
    assert result["legacy_gates"]["release_inputs"] == {
        "legacy_evidence": ledger_value["gates"][0]["evidence"],
        "legacy_status": "blocked",
        "v2_default_status": "blocked",
    }
    assert (
        sum(
            gate["v2_default_status"] == "pending"
            for gate in result["legacy_gates"].values()
        )
        == 9
    )
    assert migration.validate_final_result(result) == result


def test_legacy_pass_is_pending_requalification_not_a_v2_pass(
    tmp_path: Path,
) -> None:
    ledger = json.loads(V1_LEDGER.read_text())
    gate = ledger["gates"][1]
    assert gate["id"] == "immutable_artifacts"
    gate.update(
        {
            "evidence": {
                "schema": "coffer.production-artifact-qualification/v1",
                "sha256": f"sha256:{'1' * 64}",
            },
            "reason": None,
            "status": "passed",
        }
    )
    ledger["passed_gate_count"] = 1
    ledger["pending_gates"].remove("immutable_artifacts")

    result = migration.compile_migration(
        v1_ledger=private_json(tmp_path / "ledger.json", ledger),
        release_readiness=private_bytes(
            tmp_path / "release.json",
            V1_RELEASE.read_bytes(),
        ),
    )

    assert result["legacy_gates"]["immutable_artifacts"] == {
        "legacy_evidence": gate["evidence"],
        "legacy_status": "passed",
        "v2_default_status": "pending",
    }


@pytest.mark.parametrize(
    "mutation",
    ("aggregate", "gate_order", "source"),
)
def test_tampered_v1_ledger_is_rejected(
    tmp_path: Path,
    mutation: str,
) -> None:
    ledger = json.loads(V1_LEDGER.read_text())
    if mutation == "aggregate":
        ledger["passed_gate_count"] = 1
    elif mutation == "gate_order":
        ledger["gates"][1], ledger["gates"][2] = (
            ledger["gates"][2],
            ledger["gates"][1],
        )
    else:
        ledger["source"]["ledger_sha256"] = f"sha256:{'f' * 64}"

    with pytest.raises(migration.MigrationError):
        migration.compile_migration(
            v1_ledger=private_json(tmp_path / "ledger.json", ledger),
            release_readiness=private_bytes(
                tmp_path / "release.json",
                V1_RELEASE.read_bytes(),
            ),
        )


def test_release_raw_bytes_are_bound_to_v1_gate(tmp_path: Path) -> None:
    release_bytes = V1_RELEASE.read_bytes() + b"\n"

    with pytest.raises(
        migration.MigrationError,
        match="release gate binding",
    ):
        migration.compile_migration(
            v1_ledger=private_bytes(
                tmp_path / "ledger.json",
                V1_LEDGER.read_bytes(),
            ),
            release_readiness=private_bytes(
                tmp_path / "release.json",
                release_bytes,
            ),
        )


def test_migration_embeds_exact_replay_bytes_and_detects_tampering(
    tmp_path: Path,
) -> None:
    result = compile_current(tmp_path)
    replay = base64.b64decode(
        result["rollback"]["v1_ledger_bytes_base64"],
        validate=True,
    )

    assert replay == V1_LEDGER.read_bytes()
    assert trust.sha256_bytes(replay) == result["rollback"]["v1_ledger_raw_sha256"]

    tampered = deepcopy(result)
    tampered["components"]["distribution"]["status"] = "pending"
    with pytest.raises(
        migration.MigrationError,
        match="was not derived",
    ):
        migration.validate_final_result(tampered)


def test_general_v2_projection_is_always_refused() -> None:
    with pytest.raises(
        migration.MigrationError,
        match="projection is forbidden",
    ):
        migration.project_v2_to_v1({})


def test_direct_replay_is_always_refused() -> None:
    with pytest.raises(
        migration.MigrationError,
        match="signed rollback verifier",
    ):
        migration.replay_exact_v1(
            migration={},
            ledger_v2={},
            output=Path("/tmp/never-created"),
        )


def test_checkpoint_and_archived_policy_are_an_atomic_pair(
    tmp_path: Path,
) -> None:
    checkpoint = {"schema": "fixture-checkpoint"}
    checkpoint_document = private_json(
        tmp_path / "checkpoint.json",
        checkpoint,
    )
    with pytest.raises(
        migration.MigrationError,
        match="supplied together",
    ):
        migration.compile_migration(
            v1_ledger=private_bytes(
                tmp_path / "ledger.json",
                V1_LEDGER.read_bytes(),
            ),
            release_readiness=private_bytes(
                tmp_path / "release.json",
                V1_RELEASE.read_bytes(),
            ),
            checkpoint=checkpoint_document,
        )


def test_migration_serialized_budget_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migration, "MIGRATION_MAX_BYTES", 1)
    with pytest.raises(
        migration.MigrationError,
        match="publication limit",
    ):
        compile_current(tmp_path)


def test_compile_cli_revalidates_exact_owner_only_result(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    ledger = tmp_path / "ledger.json"
    release = tmp_path / "release.json"
    output = tmp_path / "migration.json"
    private_bytes(ledger, V1_LEDGER.read_bytes())
    private_bytes(release, V1_RELEASE.read_bytes())

    assert (
        migration.main(
            [
                "--v1-ledger",
                str(ledger),
                "--release-readiness",
                str(release),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert migration.validate_final_result(json.loads(output.read_text()))

    assert (
        migration.main(
            [
                "--v1-ledger",
                str(ledger),
                "--release-readiness",
                str(release),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    changed = json.loads(output.read_text())
    changed["rollback"]["v2_to_v1_projection"] = "unsafe"
    output.write_bytes(trust.canonical_bytes(changed) + b"\n")
    assert (
        migration.main(
            [
                "--v1-ledger",
                str(ledger),
                "--release-readiness",
                str(release),
                "--output",
                str(output),
            ]
        )
        == 2
    )
