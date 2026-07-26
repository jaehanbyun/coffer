from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_DIRECTORY = ROOT / "poc" / "load-soak" / "collector"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


EXECUTOR = load_module(
    "coffer_load_pilot_executor_tests",
    COLLECTOR_DIRECTORY / "pilot_executor.py",
)
SCHEDULE_TESTS = load_module(
    "coffer_load_pilot_executor_schedule_fixtures",
    ROOT / "tests" / "test_load_pilot_schedule.py",
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def owner_document(path: Path, value: object) -> None:
    path.write_bytes(canonical(value))
    path.chmod(0o600)


def fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    request_path, schedule_output, runtime, request = (
        SCHEDULE_TESTS.fixture(tmp_path)
    )
    SCHEDULE_TESTS.RENDERER.render_file(request_path)
    return (
        schedule_output,
        Path(request["readiness"]["file"]),
        runtime,
    )


def test_executes_all_actions_with_durable_fixture_checkpoints(
    tmp_path: Path,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    adapter = EXECUTOR.FixtureActionAdapter()

    result = EXECUTOR.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert result["complete"] is True
    assert result["synthetic"] is True
    assert adapter.execute_calls == list(range(1, 54))
    assert adapter.reconcile_calls == []
    assert set(path.name for path in runtime.iterdir()) == {
        EXECUTOR.LOCK_FILE,
        EXECUTOR.STATE_FILE,
        EXECUTOR.RESULT_FILE,
    }
    for path in runtime.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
    state = json.loads(
        (runtime / EXECUTOR.STATE_FILE).read_bytes()
    )
    assert state["complete"] is True
    assert state["next_order"] == 54
    assert state["pending_order"] is None
    assert len(state["history"]) == 53
    assert [item["order"] for item in state["history"]] == list(
        range(1, 54)
    )


def test_complete_repeat_validates_without_reexecution(
    tmp_path: Path,
) -> None:
    schedule, readiness, _ = fixture(tmp_path)
    first_adapter = EXECUTOR.FixtureActionAdapter()
    first = EXECUTOR.execute(
        schedule,
        readiness,
        adapter=first_adapter,
    )
    second_adapter = EXECUTOR.FixtureActionAdapter()

    second = EXECUTOR.execute(
        schedule,
        readiness,
        adapter=second_adapter,
    )

    assert second == first
    assert second_adapter.execute_calls == []
    assert second_adapter.reconcile_calls == []


def test_failure_before_apply_resumes_from_exact_pending_action(
    tmp_path: Path,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    first_adapter = EXECUTOR.FixtureActionAdapter(
        fail_before_order=19
    )

    with pytest.raises(EXECUTOR.PilotExecutorError):
        EXECUTOR.execute(
            schedule,
            readiness,
            adapter=first_adapter,
        )

    state = json.loads(
        (runtime / EXECUTOR.STATE_FILE).read_bytes()
    )
    assert state["pending_order"] == 19
    assert state["next_order"] == 19
    assert len(state["history"]) == 18
    assert first_adapter.execute_calls == list(range(1, 20))
    resumed = EXECUTOR.FixtureActionAdapter()

    result = EXECUTOR.execute(
        schedule,
        readiness,
        adapter=resumed,
    )

    assert result["complete"] is True
    assert resumed.reconcile_calls == [19]
    assert resumed.execute_calls == list(range(19, 54))


def test_ambiguous_apply_is_reconciled_without_duplicate_execution(
    tmp_path: Path,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    adapter = EXECUTOR.FixtureActionAdapter(
        apply_then_raise_order=31
    )

    with pytest.raises(EXECUTOR.PilotExecutorError, match="ambiguous"):
        EXECUTOR.execute(
            schedule,
            readiness,
            adapter=adapter,
        )

    state = json.loads(
        (runtime / EXECUTOR.STATE_FILE).read_bytes()
    )
    assert state["pending_order"] == 31
    assert adapter.execute_calls.count(31) == 1

    result = EXECUTOR.execute(
        schedule,
        readiness,
        adapter=adapter,
    )

    assert result["complete"] is True
    assert adapter.reconcile_calls == [31]
    assert adapter.execute_calls.count(31) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "state-hash",
        "state-pending",
        "state-history",
        "result",
    ],
)
def test_checkpoint_or_result_tamper_is_refused(
    tmp_path: Path,
    mutation: str,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    EXECUTOR.execute(
        schedule,
        readiness,
        adapter=EXECUTOR.FixtureActionAdapter(),
    )
    if mutation == "result":
        path = runtime / EXECUTOR.RESULT_FILE
        value = json.loads(path.read_bytes())
        value["history_sha256"] = f"sha256:{'0' * 64}"
    else:
        path = runtime / EXECUTOR.STATE_FILE
        value = json.loads(path.read_bytes())
        if mutation == "state-hash":
            value["state_sha256"] = f"sha256:{'0' * 64}"
        elif mutation == "state-pending":
            value["pending_order"] = 53
        else:
            value["history"][0]["order"] = 2
            value["state_sha256"] = EXECUTOR._hash(
                EXECUTOR._state_unsigned(value)
            )
    owner_document(path, value)

    with pytest.raises(EXECUTOR.PilotExecutorError):
        EXECUTOR.execute(
            schedule,
            readiness,
            adapter=EXECUTOR.FixtureActionAdapter(),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "readiness",
        "schedule",
        "config",
        "extra-schedule-file",
        "unsafe-runtime-file",
    ],
)
def test_input_and_runtime_drift_is_refused(
    tmp_path: Path,
    mutation: str,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    if mutation == "readiness":
        value = json.loads(readiness.read_bytes())
        value["status"] = "blocked"
        owner_document(readiness, value)
    elif mutation == "schedule":
        path = schedule / "schedule.json"
        value = json.loads(path.read_bytes())
        value["actions"][0]["order"] = 2
        owner_document(path, value)
    elif mutation == "config":
        path = schedule / "during-rgw-live-config.json"
        value = json.loads(path.read_bytes())
        value["steps"][-1], value["steps"][-2] = (
            value["steps"][-2],
            value["steps"][-1],
        )
        owner_document(path, value)
    elif mutation == "extra-schedule-file":
        owner_document(schedule / "extra.json", {})
    else:
        runtime.mkdir(mode=0o700)
        owner_document(runtime / "unexpected.json", {})

    with pytest.raises(
        (
            EXECUTOR.PilotExecutorError,
            EXECUTOR.pilot_schedule.PilotScheduleError,
        )
    ):
        EXECUTOR.execute(
            schedule,
            readiness,
            adapter=EXECUTOR.FixtureActionAdapter(),
        )


def test_spoofed_pilot_adapter_contract_is_refused(
    tmp_path: Path,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    adapter = EXECUTOR.FixtureActionAdapter(
        name="pilot",
        synthetic=False,
    )

    with pytest.raises(
        EXECUTOR.PilotExecutorError,
        match="unsupported",
    ):
        EXECUTOR.execute(
            schedule,
            readiness,
            adapter=adapter,
        )

    assert runtime.exists() is False


def test_nonblocking_lock_refuses_concurrent_execution(
    tmp_path: Path,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    schedule_value, _ = EXECUTOR._schedule_output(schedule, readiness)
    runtime_path = EXECUTOR._runtime(schedule_value)

    with EXECUTOR._lock(runtime_path):
        with pytest.raises(EXECUTOR.CommandError) as raised:
            EXECUTOR.execute(
                schedule,
                readiness,
                adapter=EXECUTOR.FixtureActionAdapter(),
            )

    assert raised.value.category == "lock-unavailable"
    assert set(path.name for path in runtime.iterdir()) == {
        EXECUTOR.LOCK_FILE
    }


def test_cli_reports_fixed_results_and_can_resume(
    tmp_path: Path,
) -> None:
    schedule, readiness, runtime = fixture(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    failed = EXECUTOR.run(
        [
            "--fixture",
            "--schedule",
            str(schedule),
            "--readiness",
            str(readiness),
            "--fail-before-order",
            "7",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert failed == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "pilot executor failed: execution-unavailable\n"
    )
    state = json.loads(
        (runtime / EXECUTOR.STATE_FILE).read_bytes()
    )
    assert state["pending_order"] == 7

    stdout = io.StringIO()
    stderr = io.StringIO()
    completed = EXECUTOR.run(
        [
            "--fixture",
            "--schedule",
            str(schedule),
            "--readiness",
            str(readiness),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert completed == 0
    assert stderr.getvalue() == ""
    response = json.loads(stdout.getvalue())
    assert response["schema"] == EXECUTOR.RESULT_SCHEMA
    assert response["synthetic"] is True


def test_cli_arguments_and_source_hash_are_fixed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert EXECUTOR.run([], stdout=stdout, stderr=stderr) == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "pilot executor failed: invalid-arguments\n"
    )

    assert EXECUTOR.main(["source-hash"]) == 0
    source = capsys.readouterr()
    assert source.err == ""
    assert json.loads(source.out)["schema"] == (
        EXECUTOR.SOURCE_RESULT_SCHEMA
    )
