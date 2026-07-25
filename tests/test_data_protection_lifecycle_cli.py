from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "poc" / "data-protection"
TOPOLOGY_PATH = MODULE_DIR / "topology.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "data_protection.json"
INVOCATION_ID = "01k0a1b2c3d4e5f6g7h8j9k0mn"
TARGET_SIGNATURE = "a" * 64
UNRELATED_SIGNATURE = f"sha256:{'b' * 64}"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LIFECYCLE = _load_module(
    "coffer_data_protection_lifecycle",
    MODULE_DIR / "lifecycle.py",
)


def base_arguments(action: str) -> list[str]:
    return [
        action,
        "--invocation-id",
        INVOCATION_ID,
        "--target-signature",
        TARGET_SIGNATURE,
        "--unrelated-signature",
        UNRELATED_SIGNATURE,
        "--topology",
        str(TOPOLOGY_PATH),
    ]


def fixture_arguments(action: str, fixture: Path = FIXTURE_PATH) -> list[str]:
    return [
        *base_arguments(action),
        "--adapter",
        "fixture",
        "--fixture",
        str(fixture),
    ]


def invoke(tmp_path: Path, capsys, arguments: list[str]):
    result = LIFECYCLE.run(arguments, repo_root=tmp_path)
    captured = capsys.readouterr()
    output = captured.out if result == 0 else captured.err
    return result, json.loads(output)


def state_root(tmp_path: Path) -> Path:
    return tmp_path / "work" / "data-protection" / INVOCATION_ID


def advance_to_failures_verified(tmp_path: Path, capsys) -> dict[str, object]:
    actions = (
        ("create-source", "source-created"),
        ("populate-fixture", "fixture-populated"),
        ("exclude-writers", "writers-excluded"),
        ("verify-backups", "backups-verified"),
        ("verify-inventory", "inventory-verified"),
        ("import-baseline", "baseline-imported"),
        ("verify-live", "live-comparison-verified"),
        ("cutover", "admission-cutover"),
        ("verify-cutover", "cutover-verified"),
        ("verify-rollback", "rollback-verified"),
        ("verify-restore", "restore-verified"),
        ("verify-failures", "failures-verified"),
    )
    evidence: dict[str, object] = {}
    for action, phase in actions:
        result, evidence = invoke(
            tmp_path,
            capsys,
            fixture_arguments(action),
        )
        assert result == 0
        assert evidence["phase"] == phase
    return evidence


def test_status_without_preflight_is_read_only(tmp_path: Path, capsys) -> None:
    result, failure = invoke(tmp_path, capsys, base_arguments("status"))

    assert result == 2
    assert failure == {
        "schema": LIFECYCLE.FAILURE_SCHEMA,
        "action": "status",
        "category": "local-state-unavailable",
    }
    assert not (tmp_path / "work").exists()


def test_preflight_writes_atomic_owner_only_state(tmp_path: Path, capsys) -> None:
    result, evidence = invoke(tmp_path, capsys, base_arguments("preflight"))

    assert result == 0
    assert evidence["phase"] == "preflighted"
    root = state_root(tmp_path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "state.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "lock").stat().st_mode) == 0o600
    assert sorted(item.name for item in root.iterdir()) == ["lock", "state.json"]
    retained = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert retained["target_signature"] == TARGET_SIGNATURE
    assert retained["unrelated_signature"] == UNRELATED_SIGNATURE


def test_repeated_exact_preflight_is_idempotent_and_mismatch_is_refused(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, evidence = invoke(tmp_path, capsys, base_arguments("preflight"))
    assert result == 0
    assert evidence["phase"] == "preflighted"
    assert state_path.read_bytes() == before

    changed = base_arguments("preflight")
    changed[changed.index(TARGET_SIGNATURE)] = "f" * 64
    result, failure = invoke(tmp_path, capsys, changed)
    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before


def test_mutation_requires_explicit_fixture_adapter(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, failure = invoke(
        tmp_path,
        capsys,
        base_arguments("create-source"),
    )

    assert result == 2
    assert failure["category"] == "fixture-refused"
    assert state_path.read_bytes() == before


def test_fixture_lifecycle_reaches_idempotent_zero_residue_terminal_state(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    advance_to_failures_verified(tmp_path, capsys)

    result, cleanup = invoke(
        tmp_path,
        capsys,
        base_arguments("cleanup-plan"),
    )
    assert result == 0
    assert cleanup
    assert cleanup[0]["kind"] == "maintenance_session"
    assert cleanup[-1]["kind"] == "network"
    assert all(set(item) == {"kind", "name", "id_sha256"} for item in cleanup)
    assert all(len(item["id_sha256"]) == 64 for item in cleanup)
    assert "fixture-" not in json.dumps(cleanup)

    result, evidence = invoke(
        tmp_path,
        capsys,
        fixture_arguments("teardown"),
    )
    assert result == 0
    assert evidence["phase"] == "torn-down"
    assert sum(evidence["resource_counts"].values()) == 0

    result, repeated = invoke(
        tmp_path,
        capsys,
        fixture_arguments("teardown"),
    )
    assert result == 0
    assert repeated == evidence
    result, status = invoke(tmp_path, capsys, base_arguments("status"))
    assert result == 0
    assert status == evidence


def test_out_of_order_action_leaves_state_unchanged(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("verify-inventory"),
    )

    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before


def test_fixture_target_residue_and_phase_evidence_mismatch_fail_closed(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    wrong_target = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    wrong_target["target_signature"] = "f" * 64
    wrong_target_path = tmp_path / "wrong-target.json"
    wrong_target_path.write_text(json.dumps(wrong_target), encoding="utf-8")
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create-source", wrong_target_path),
    )
    assert result == 2
    assert failure["category"] == "fixture-refused"

    residue = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    residue["residue_counts"]["buckets"] = 1
    residue_path = tmp_path / "residue.json"
    residue_path.write_text(json.dumps(residue), encoding="utf-8")
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create-source", residue_path),
    )
    assert result == 2
    assert failure["category"] == "fixture-refused"

    drift = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    drift["evidence"]["fixture"]["source_signature"] = f"sha256:{'f' * 64}"
    drift_path = tmp_path / "drift.json"
    drift_path.write_text(json.dumps(drift), encoding="utf-8")
    assert invoke(
        tmp_path,
        capsys,
        fixture_arguments("create-source", drift_path),
    )[0] == 0
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("populate-fixture", drift_path),
    )
    assert result == 0
    before_failure = state_path.read_bytes()
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("exclude-writers", drift_path),
    )
    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before_failure
    assert state_path.read_bytes() != before


def test_read_only_actions_refuse_fixture_arguments(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("status"),
    )

    assert result == 2
    assert failure["category"] == "fixture-refused"


def test_unverified_backup_bundle_cannot_advance_the_lifecycle(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    for action in ("create-source", "populate-fixture", "exclude-writers"):
        assert invoke(
            tmp_path,
            capsys,
            fixture_arguments(action),
        )[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()
    changed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    changed["backup_bundle"]["sql"]["restore"]["content_sha256"] = (
        f"sha256:{'f' * 64}"
    )
    changed_path = tmp_path / "unrestored-backup.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("verify-backups", changed_path),
    )

    assert result == 2
    assert failure["category"] == "fixture-refused"
    assert state_path.read_bytes() == before


def test_nonblocking_lock_refuses_concurrent_action(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    lock_path = state_root(tmp_path) / "lock"
    descriptor = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, failure = invoke(
            tmp_path,
            capsys,
            base_arguments("status"),
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert result == 2
    assert failure["category"] == "lock-unavailable"


def test_unsafe_state_mode_and_symlink_lock_fail_closed(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    root = state_root(tmp_path)
    state_path = root / "state.json"
    state_path.chmod(0o644)

    result, failure = invoke(tmp_path, capsys, base_arguments("status"))
    assert result == 2
    assert failure["category"] == "local-state-unavailable"

    state_path.chmod(0o600)
    lock_path = root / "lock"
    real_lock = root / "real-lock"
    lock_path.rename(real_lock)
    lock_path.symlink_to(real_lock)
    result, failure = invoke(tmp_path, capsys, base_arguments("status"))
    assert result == 2
    assert failure["category"] == "local-state-unavailable"


def test_preflight_does_not_remediate_an_unsafe_existing_directory(
    tmp_path: Path,
    capsys,
) -> None:
    root = state_root(tmp_path)
    root.mkdir(mode=0o755, parents=True)

    result, failure = invoke(tmp_path, capsys, base_arguments("preflight"))

    assert result == 2
    assert failure["category"] == "local-state-unavailable"
    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    assert not (root / "state.json").exists()
    assert not (root / "lock").exists()


def test_failure_output_never_contains_fixture_details(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    invalid = tmp_path / "invalid-fixture.json"
    invalid.write_text(
        '{"schema":"wrong","token":"do-not-print-this-value"}',
        encoding="utf-8",
    )

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create-source", invalid),
    )

    assert result == 2
    serialized = json.dumps(failure, sort_keys=True)
    assert failure["category"] == "fixture-refused"
    assert "do-not-print-this-value" not in serialized
    assert set(failure) == {"schema", "action", "category"}
