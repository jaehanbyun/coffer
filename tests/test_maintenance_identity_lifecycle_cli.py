from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "poc" / "maintenance-identity"
TOPOLOGY_PATH = MODULE_DIR / "topology.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "maintenance_identity.json"
INVOCATION_ID = "01k0a1b2c3d4e5f6g7h8j9k0mn"
TARGET_SIGNATURE = "a" * 64


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "state_machine" not in sys.modules:
    _load_module("state_machine", MODULE_DIR / "state_machine.py")
LIFECYCLE = _load_module(
    "coffer_maintenance_identity_lifecycle",
    MODULE_DIR / "lifecycle.py",
)


def base_arguments(action: str) -> list[str]:
    return [
        action,
        "--invocation-id",
        INVOCATION_ID,
        "--target-signature",
        TARGET_SIGNATURE,
        "--topology",
        str(TOPOLOGY_PATH),
    ]


def preflight_arguments() -> list[str]:
    return [
        *base_arguments("preflight"),
        "--workload",
        "reconcile-1",
        "--workload",
        "reconcile-2",
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
    return (
        tmp_path
        / "work"
        / "maintenance-identity"
        / INVOCATION_ID
    )


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
    result, evidence = invoke(tmp_path, capsys, preflight_arguments())

    assert result == 0
    assert evidence["phase"] == "preflighted"
    root = state_root(tmp_path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "state.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "lock").stat().st_mode) == 0o600
    assert sorted(item.name for item in root.iterdir()) == ["lock", "state.json"]
    retained = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert retained["target_signature"] == TARGET_SIGNATURE
    assert retained["selected_workloads"] == ["reconcile-1", "reconcile-2"]


def test_repeated_exact_preflight_is_idempotent(tmp_path: Path, capsys) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, evidence = invoke(tmp_path, capsys, preflight_arguments())

    assert result == 0
    assert evidence["phase"] == "preflighted"
    assert state_path.read_bytes() == before


def test_preflight_target_or_workload_replay_mismatch_is_refused(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()
    changed = preflight_arguments()
    changed[changed.index(TARGET_SIGNATURE)] = "b" * 64

    result, failure = invoke(tmp_path, capsys, changed)

    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before


def test_mutation_requires_the_explicit_fixture_adapter(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, failure = invoke(tmp_path, capsys, base_arguments("create"))

    assert result == 2
    assert failure["category"] == "fixture-refused"
    assert state_path.read_bytes() == before


def test_fixture_lifecycle_reaches_zero_residue_terminal_state(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    phases = [
        ("create", "generation1_created"),
        ("verify", "generation1_verified"),
        ("rotate", "generation2_created"),
        ("verify", "generation2_verified"),
        ("revoke-old", "old_revoked"),
        ("verify-failures", "failures_verified"),
    ]
    for action, phase in phases:
        result, evidence = invoke(
            tmp_path,
            capsys,
            fixture_arguments(action),
        )
        assert result == 0
        assert evidence["phase"] == phase

    result, cleanup = invoke(
        tmp_path,
        capsys,
        base_arguments("cleanup-plan"),
    )
    assert result == 0
    assert cleanup
    assert all(set(item) == {"kind", "name", "id_sha256"} for item in cleanup)
    assert all(len(item["id_sha256"]) == 64 for item in cleanup)
    assert "fixture-" not in json.dumps(cleanup)

    result, evidence = invoke(
        tmp_path,
        capsys,
        fixture_arguments("teardown"),
    )
    assert result == 0
    assert evidence["phase"] == "torn_down"
    assert sum(evidence["resource_counts"].values()) == 1
    assert evidence["resource_counts"]["role"] == 1

    result, status = invoke(tmp_path, capsys, base_arguments("status"))
    assert result == 0
    assert status == evidence


def test_out_of_order_fixture_action_leaves_state_unchanged(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("rotate"),
    )

    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before


def test_fixture_target_mismatch_and_nonzero_residue_are_refused(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    wrong_target = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    wrong_target["target_signature"] = "b" * 64
    wrong_target_path = tmp_path / "wrong-target.json"
    wrong_target_path.write_text(json.dumps(wrong_target), encoding="utf-8")

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create", wrong_target_path),
    )
    assert result == 2
    assert failure["category"] == "fixture-refused"

    residue = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    residue["residue_counts"]["secrets"] = 1
    residue_path = tmp_path / "residue.json"
    residue_path.write_text(json.dumps(residue), encoding="utf-8")
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create", residue_path),
    )
    assert result == 2
    assert failure["category"] == "fixture-refused"


def test_nonblocking_lock_refuses_concurrent_action(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
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
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
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


def test_failure_output_never_contains_parser_or_fixture_details(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, preflight_arguments())[0] == 0
    invalid = tmp_path / "invalid-fixture.json"
    invalid.write_text(
        '{"schema":"wrong","token":"do-not-print-this-value"}',
        encoding="utf-8",
    )

    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create", invalid),
    )

    assert result == 2
    serialized = json.dumps(failure, sort_keys=True)
    assert failure["category"] == "fixture-refused"
    assert "do-not-print-this-value" not in serialized
    assert set(failure) == {"schema", "action", "category"}
