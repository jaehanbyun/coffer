from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "poc" / "gc-retention"
TOPOLOGY_PATH = MODULE_DIR / "topology.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "gc_retention.json"
INVOCATION_ID = "01j00000000000000000000000"
UNRELATED_SIGNATURE = f"sha256:{'b' * 64}"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LIFECYCLE = _load_module(
    "coffer_gc_retention_lifecycle_tests",
    MODULE_DIR / "lifecycle.py",
)


def base_arguments(action: str) -> list[str]:
    return [
        action,
        "--invocation-id",
        INVOCATION_ID,
        "--unrelated-signature",
        UNRELATED_SIGNATURE,
        "--topology",
        str(TOPOLOGY_PATH),
    ]


def fixture_arguments(
    action: str,
    fixture: Path = FIXTURE_PATH,
) -> list[str]:
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
    return tmp_path / "work" / "gc-retention" / INVOCATION_ID


def advance_to(
    tmp_path: Path,
    capsys,
    target_action: str,
) -> dict:
    output: dict = {}
    for action in LIFECYCLE.state_machine.EXPECTED_ACTIONS[1:]:
        result, output = invoke(
            tmp_path,
            capsys,
            fixture_arguments(action),
        )
        assert result == 0
        if action == target_action:
            return output
    raise AssertionError(f"unknown action {target_action}")


def test_status_without_preflight_is_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    result, failure = invoke(tmp_path, capsys, base_arguments("status"))

    assert result == 2
    assert failure == {
        "schema": LIFECYCLE.FAILURE_SCHEMA,
        "action": "status",
        "category": "local-state-unavailable",
    }
    assert not (tmp_path / "work").exists()


def test_preflight_writes_atomic_owner_only_state(
    tmp_path: Path,
    capsys,
) -> None:
    result, evidence = invoke(
        tmp_path,
        capsys,
        base_arguments("preflight"),
    )

    assert result == 0
    assert evidence["phase"] == "preflighted"
    root = state_root(tmp_path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "state.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "lock").stat().st_mode) == 0o600
    assert sorted(item.name for item in root.iterdir()) == ["lock", "state.json"]
    retained = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert retained["target_class"] == "disposable-fixture"
    assert retained["unrelated_signature"] == UNRELATED_SIGNATURE
    assert INVOCATION_ID not in json.dumps(evidence, sort_keys=True)


def test_repeated_exact_preflight_is_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    result, evidence = invoke(
        tmp_path,
        capsys,
        base_arguments("preflight"),
    )

    assert result == 0
    assert evidence["phase"] == "preflighted"
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


def test_fixture_lifecycle_reaches_idempotent_terminal_state(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    terminal = advance_to(tmp_path, capsys, "teardown")

    assert terminal["phase"] == "torn-down"
    assert terminal["authority"]["consumed"] is True
    assert all(
        value == 0
        for value in terminal["evidence"]["torn-down"]["residue"].values()
    )

    result, plan = invoke(
        tmp_path,
        capsys,
        base_arguments("cleanup-plan"),
    )
    assert result == 0
    assert len(plan) == 11
    assert plan[0]["kind"] == "gc_job"
    assert plan[-1]["kind"] == "network"
    assert all(set(item) == {"kind", "name", "id_sha256"} for item in plan)
    assert all(len(item["id_sha256"]) == 64 for item in plan)
    assert INVOCATION_ID not in json.dumps(plan)

    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()
    result, repeated = invoke(
        tmp_path,
        capsys,
        fixture_arguments("teardown"),
    )
    assert result == 0
    assert repeated == terminal
    assert state_path.read_bytes() == before

    result, status = invoke(tmp_path, capsys, base_arguments("status"))
    assert result == 0
    assert status == terminal


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
        fixture_arguments("verify-baseline"),
    )

    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before


def test_fixture_pin_failure_or_residue_drift_is_refused(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    before = state_path.read_bytes()

    changed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    changed["distribution_revision"] = "f" * 40
    changed_path = tmp_path / "changed-pin.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create-source", changed_path),
    )
    assert result == 2
    assert failure["category"] == "fixture-refused"

    changed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    changed["residue"]["locks"] = 1
    changed_path = tmp_path / "changed-residue.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")
    result, failure = invoke(
        tmp_path,
        capsys,
        fixture_arguments("create-source", changed_path),
    )
    assert result == 2
    assert failure["category"] == "fixture-refused"
    assert state_path.read_bytes() == before


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


def test_preflight_does_not_remediate_unsafe_directory(
    tmp_path: Path,
    capsys,
) -> None:
    root = state_root(tmp_path)
    root.mkdir(mode=0o755, parents=True)

    result, failure = invoke(
        tmp_path,
        capsys,
        base_arguments("preflight"),
    )

    assert result == 2
    assert failure["category"] == "local-state-unavailable"
    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    assert not (root / "state.json").exists()


def test_tampered_state_is_refused_without_rewrite(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, base_arguments("preflight"))[0] == 0
    state_path = state_root(tmp_path) / "state.json"
    retained = json.loads(state_path.read_text(encoding="utf-8"))
    retained["evidence"]["preflighted"]["candidate_limit"] = 999
    state_path.write_text(json.dumps(retained), encoding="utf-8")
    state_path.chmod(0o600)
    before = state_path.read_bytes()

    result, failure = invoke(tmp_path, capsys, base_arguments("status"))

    assert result == 2
    assert failure["category"] == "contract-refused"
    assert state_path.read_bytes() == before


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
    assert failure == {
        "schema": LIFECYCLE.FAILURE_SCHEMA,
        "action": "create-source",
        "category": "fixture-refused",
    }
    assert "do-not-print-this-value" not in json.dumps(failure)


def test_cli_uses_no_registry_s3_sql_network_or_subprocess_adapter() -> None:
    source = (MODULE_DIR / "lifecycle.py").read_text(encoding="utf-8")

    for forbidden in (
        "import boto",
        "import requests",
        "import socket",
        "import sqlalchemy",
        "import subprocess",
        "urllib",
        "registry garbage-collect",
    ):
        assert forbidden not in source
