from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
UPSTREAM_SOURCE = ROOT / "poc" / "production-images" / "check_upstream_readiness.py"
UI_SOURCE = ROOT / "poc" / "ui-images" / "oslo_messaging_release_gate.py"
UI_CONTRACT = ROOT / "poc" / "ui-images" / "oslo_messaging_release_gate.json"

SCHEMA = "coffer.production-promotion-release-readiness/v1"
UPSTREAM_SCHEMA = "coffer.upstream-readiness/v1"
UI_SCHEMA = "coffer.ui-oslo-messaging-release-readiness/v1"
STATUS_ORDER = {
    "blocked": 0,
    "candidate-released": 1,
    "candidate-qualified": 2,
}
COMPONENTS = ("distribution", "ceph", "oslo_messaging")


class PromotionReadinessError(RuntimeError):
    pass


@dataclass(frozen=True)
class Modules:
    upstream: Any
    ui: Any


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise PromotionReadinessError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    source_directory = str(path.parent)
    inserted = source_directory not in sys.path
    if inserted:
        sys.path.insert(0, source_directory)
    try:
        specification.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(source_directory)
    return module


def modules() -> Modules:
    return Modules(
        upstream=_load_module(
            "coffer_production_promotion_upstream",
            UPSTREAM_SOURCE,
        ),
        ui=_load_module(
            "coffer_production_promotion_ui",
            UI_SOURCE,
        ),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionReadinessError(f"{label} must be a JSON object")
    return value


def _status(value: object, label: str) -> str:
    status = str(value)
    if status not in STATUS_ORDER:
        raise PromotionReadinessError(f"{label} status is unsupported")
    return status


def _sha256(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise PromotionReadinessError(f"unable to read {path}") from error
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _component(
    name: str,
    value: object,
    *,
    expected_schema: str | None = None,
) -> dict[str, Any]:
    item = _mapping(value, name)
    if expected_schema is not None and item.get("schema") != expected_schema:
        raise PromotionReadinessError(f"{name} schema is unsupported")
    status = _status(item.get("status"), name)
    reasons = item.get("reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) or not reason for reason in reasons
    ):
        raise PromotionReadinessError(f"{name} reasons are invalid")
    return {
        "status": status,
        "version": item.get("latest_stable")
        if name in {"distribution", "ceph"}
        else (
            _mapping(item.get("fixed_stable_release"), name).get("version")
            if item.get("fixed_stable_release") is not None
            else None
        ),
        "revision": item.get("revision")
        if name in {"distribution", "ceph"}
        else (
            _mapping(item.get("fixed_stable_release"), name).get("tag_revision")
            if item.get("fixed_stable_release") is not None
            else None
        ),
        "reasons": list(reasons),
    }


def classify(
    upstream_value: object,
    ui_value: object,
    *,
    ui_observed_on: str,
    today: date | None = None,
) -> dict[str, Any]:
    upstream = _mapping(upstream_value, "upstream readiness")
    ui = _mapping(ui_value, "UI readiness")
    if upstream.get("schema") != UPSTREAM_SCHEMA:
        raise PromotionReadinessError("upstream readiness schema is unsupported")
    if ui.get("schema") != UI_SCHEMA:
        raise PromotionReadinessError("UI readiness schema is unsupported")

    try:
        observed = date.fromisoformat(ui_observed_on)
    except (TypeError, ValueError) as error:
        raise PromotionReadinessError(
            "UI observation date is invalid"
        ) from error
    current = datetime.now(tz=UTC).date() if today is None else today
    if observed > current or (current - observed).days > 1:
        raise PromotionReadinessError(
            "UI release observation is stale; refresh official PyPI and "
            "stable/2026.1 constraints metadata"
        )

    components = {
        "distribution": _component(
            "distribution",
            upstream.get("distribution"),
        ),
        "ceph": _component("ceph", upstream.get("ceph")),
        "oslo_messaging": _component(
            "oslo_messaging",
            ui,
            expected_schema=UI_SCHEMA,
        ),
    }
    overall = min(
        (item["status"] for item in components.values()),
        key=STATUS_ORDER.__getitem__,
    )
    blockers = [
        f"{name}: {reason}"
        for name in COMPONENTS
        for reason in components[name]["reasons"]
    ]
    return {
        "schema": SCHEMA,
        "status": overall,
        "release_inputs_qualified": overall == "candidate-qualified",
        "production_candidate": False,
        "ui_observed_on": observed.isoformat(),
        "components": components,
        "blockers": blockers,
        "source": {
            "upstream_classifier_sha256": _sha256(UPSTREAM_SOURCE),
            "ui_classifier_sha256": _sha256(UI_SOURCE),
            "ui_contract_sha256": _sha256(UI_CONTRACT),
        },
        "next_action": (
            "run immutable image, RGW/KMS, data-protection, load, and "
            "multinode qualification"
            if overall == "candidate-qualified"
            else "wait for changed official release metadata and rerun"
        ),
    }


def _write_owner_only(path: Path, result: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise PromotionReadinessError("output path must be absolute")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def live_result() -> dict[str, Any]:
    loaded = modules()
    try:
        upstream = loaded.upstream.classify(loaded.upstream.live_fixture())
        contract = loaded.ui.load_contract(UI_CONTRACT)
        ui = loaded.ui.classify(contract)
        observation = _mapping(
            contract.get("current_observation"),
            "UI current observation",
        )
        return classify(
            upstream,
            ui,
            ui_observed_on=str(observation.get("as_of")),
        )
    except PromotionReadinessError:
        raise
    except Exception as error:
        raise PromotionReadinessError(
            "unable to classify official release metadata"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Combine Distribution, Ceph, and OpenStack UI release readiness "
            "without weakening any production promotion gate."
        )
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require",
        choices=tuple(STATUS_ORDER),
        default="blocked",
    )
    arguments = parser.parse_args(argv)
    try:
        result = live_result()
        if arguments.output is not None:
            _write_owner_only(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return (
            0
            if STATUS_ORDER[result["status"]] >= STATUS_ORDER[arguments.require]
            else 3
        )
    except PromotionReadinessError as error:
        print(f"production promotion readiness error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
