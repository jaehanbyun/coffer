from __future__ import annotations

import importlib.util
import json
import stat
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "readiness.py"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_readiness",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)


def upstream(status: str = "blocked") -> dict[str, object]:
    reason = [] if status == "candidate-qualified" else ["not released"]
    return {
        "schema": readiness.UPSTREAM_SCHEMA,
        "status": status,
        "distribution": {
            "status": status,
            "latest_stable": "v3.1.1",
            "revision": "a" * 40,
            "reasons": reason,
        },
        "ceph": {
            "status": status,
            "latest_stable": "v20.2.2",
            "revision": "b" * 40,
            "reasons": reason,
        },
    }


def ui(status: str = "blocked") -> dict[str, object]:
    reason = [] if status == "candidate-qualified" else ["not released"]
    release = (
        {
            "version": "17.3.1",
            "tag_revision": "c" * 40,
        }
        if status != "blocked"
        else None
    )
    return {
        "schema": readiness.UI_SCHEMA,
        "status": status,
        "fixed_stable_release": release,
        "reasons": reason,
    }


def test_blocked_component_blocks_aggregate() -> None:
    result = readiness.classify(
        upstream(),
        ui(),
        ui_observed_on="2026-07-28",
        today=date(2026, 7, 28),
    )
    assert result["status"] == "blocked"
    assert result["release_inputs_qualified"] is False
    assert result["production_candidate"] is False
    assert result["blockers"] == [
        "distribution: not released",
        "ceph: not released",
        "oslo_messaging: not released",
    ]


def test_every_component_must_be_qualified() -> None:
    result = readiness.classify(
        upstream("candidate-qualified"),
        ui("candidate-qualified"),
        ui_observed_on="2026-07-27",
        today=date(2026, 7, 28),
    )
    assert result["status"] == "candidate-qualified"
    assert result["release_inputs_qualified"] is True
    assert result["production_candidate"] is False
    assert result["blockers"] == []
    assert result["components"]["oslo_messaging"] == {
        "status": "candidate-qualified",
        "version": "17.3.1",
        "revision": "c" * 40,
        "reasons": [],
    }


@pytest.mark.parametrize("observed_on", ["2026-07-26", "2026-07-29"])
def test_stale_or_future_ui_observation_fails(observed_on: str) -> None:
    with pytest.raises(
        readiness.PromotionReadinessError,
        match="observation",
    ):
        readiness.classify(
            upstream(),
            ui(),
            ui_observed_on=observed_on,
            today=date(2026, 7, 28),
        )


def test_unknown_component_status_fails() -> None:
    value = upstream()
    value["distribution"]["status"] = "passed"
    with pytest.raises(
        readiness.PromotionReadinessError,
        match="status",
    ):
        readiness.classify(
            value,
            ui(),
            ui_observed_on="2026-07-28",
            today=date(2026, 7, 28),
        )


def test_output_is_owner_only_and_canonical(tmp_path: Path) -> None:
    output = tmp_path / "evidence" / "release-readiness.json"
    result = readiness.classify(
        upstream(),
        ui(),
        ui_observed_on="2026-07-28",
        today=date(2026, 7, 28),
    )
    readiness._write_owner_only(output.resolve(), result)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_relative_output_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(
        readiness.PromotionReadinessError,
        match="absolute",
    ):
        readiness._write_owner_only(Path("result.json"), {})


def test_live_result_refreshes_official_ui_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Upstream:
        @staticmethod
        def live_fixture() -> dict[str, object]:
            calls.append("upstream-live")
            return {}

        @staticmethod
        def classify(value: object) -> dict[str, object]:
            assert value == {}
            calls.append("upstream-classify")
            return upstream()

    class UI:
        @staticmethod
        def load_contract(path: Path) -> dict[str, object]:
            assert path == readiness.UI_CONTRACT
            calls.append("ui-load")
            return {"current_observation": {"as_of": "stale"}}

        @staticmethod
        def refresh_current_observation(
            value: object,
        ) -> dict[str, object]:
            assert value == {"current_observation": {"as_of": "stale"}}
            calls.append("ui-refresh")
            return {"current_observation": {"as_of": "2026-07-28"}}

        @staticmethod
        def classify(value: object) -> dict[str, object]:
            assert value == {
                "current_observation": {"as_of": "2026-07-28"}
            }
            calls.append("ui-classify")
            return ui()

    monkeypatch.setattr(
        readiness,
        "modules",
        lambda: readiness.Modules(upstream=Upstream, ui=UI),
    )

    result = readiness.live_result()

    assert result["status"] == "blocked"
    assert calls == [
        "upstream-live",
        "upstream-classify",
        "ui-load",
        "ui-refresh",
        "ui-classify",
    ]
