from __future__ import annotations

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIRECTORY = ROOT / "poc" / "load-soak"
TOPOLOGY = MODULE_DIRECTORY / "topology.json"
FIXTURE = ROOT / "tests" / "fixtures" / "load_soak.json"
INVOCATION = "01j00000000000000000000000"
UNRELATED = f"sha256:{'b' * 64}"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LIFECYCLE = load_module(
    "coffer_load_soak_lifecycle_tests",
    MODULE_DIRECTORY / "lifecycle.py",
)


def arguments(action: str, *, fixture: bool = False) -> list[str]:
    values = [
        action,
        "--invocation-id",
        INVOCATION,
        "--topology",
        str(TOPOLOGY),
        "--unrelated-signature",
        UNRELATED,
    ]
    if fixture:
        values.extend(["--adapter", "fixture", "--fixture", str(FIXTURE)])
    return values


def invoke(tmp_path: Path, capsys, values: list[str]):
    result = LIFECYCLE.run(values, repo_root=tmp_path)
    captured = capsys.readouterr()
    return result, json.loads(captured.out if result == 0 else captured.err)


def state_root(tmp_path: Path) -> Path:
    return tmp_path / "work" / "load-soak" / INVOCATION


def test_run_replays_complete_synthetic_lifecycle_owner_only(
    tmp_path: Path,
    capsys,
) -> None:
    result, output = invoke(tmp_path, capsys, arguments("run", fixture=True))

    assert result == 0
    assert output == {
        "adapter": "fixture",
        "complete": True,
        "facts_hash": output["facts_hash"],
        "history_entries": 13,
        "history_hash": output["history_hash"],
        "phase": "torn-down",
        "schema": LIFECYCLE.OUTPUT_SCHEMA,
        "synthetic": True,
    }
    root = state_root(tmp_path)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "state.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "lock").stat().st_mode) == 0o600
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert state["complete"] is True
    assert len(state["history"]) == 13
    assert INVOCATION not in json.dumps(output)


def test_exact_rerun_and_status_are_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    first_result, first = invoke(
        tmp_path,
        capsys,
        arguments("run", fixture=True),
    )
    before = (state_root(tmp_path) / "state.json").read_bytes()
    second_result, second = invoke(
        tmp_path,
        capsys,
        arguments("run", fixture=True),
    )
    status_result, status = invoke(
        tmp_path,
        capsys,
        arguments("status"),
    )

    assert first_result == second_result == status_result == 0
    assert first == second == status
    assert (state_root(tmp_path) / "state.json").read_bytes() == before


def test_run_requires_explicit_fixture_adapter(
    tmp_path: Path,
    capsys,
) -> None:
    result, failure = invoke(tmp_path, capsys, arguments("run"))

    assert result == 2
    assert failure["category"] == "fixture-refused"
    assert not (tmp_path / "work").exists()


def test_fixture_release_or_failure_contract_drift_is_refused(
    tmp_path: Path,
    capsys,
) -> None:
    changed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    changed["dependency_mode"] = "real-qualified"
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    values = arguments("run", fixture=True)
    values[-1] = str(path)

    result, failure = invoke(tmp_path, capsys, values)

    assert result == 2
    assert failure["category"] == "fixture-refused"


def test_lock_contention_fails_without_state_change(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, arguments("run", fixture=True))[0] == 0
    root = state_root(tmp_path)
    before = (root / "state.json").read_bytes()
    descriptor = os.open(root / "lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, failure = invoke(
            tmp_path,
            capsys,
            arguments("status"),
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert result == 2
    assert failure["category"] == "lock-unavailable"
    assert (root / "state.json").read_bytes() == before


def test_tampered_state_is_refused(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, arguments("run", fixture=True))[0] == 0
    path = state_root(tmp_path) / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["history"][0]["evidence_hash"] = f"sha256:{'0' * 64}"
    path.write_text(json.dumps(state), encoding="utf-8")
    path.chmod(0o600)

    result, failure = invoke(tmp_path, capsys, arguments("status"))

    assert result == 2
    assert failure["category"] == "contract-refused"


def test_cleanup_is_exact_and_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    assert invoke(tmp_path, capsys, arguments("run", fixture=True))[0] == 0
    result, output = invoke(tmp_path, capsys, arguments("cleanup"))
    second_result, second = invoke(tmp_path, capsys, arguments("cleanup"))

    assert result == second_result == 0
    assert output == second
    assert output["phase"] == "cleaned"
    assert output["residue"] == 0
    assert not (tmp_path / "work").exists()


def test_lifecycle_has_no_external_adapter_or_subprocess() -> None:
    source = (MODULE_DIRECTORY / "lifecycle.py").read_text(encoding="utf-8")

    for forbidden in (
        "import boto",
        "import http",
        "import requests",
        "import socket",
        "import sqlalchemy",
        "import subprocess",
        "urllib",
    ):
        assert forbidden not in source
