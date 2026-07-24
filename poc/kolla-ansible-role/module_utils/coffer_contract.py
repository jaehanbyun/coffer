from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _required_path(environment_name: str) -> Path:
    value = os.environ.get(environment_name)
    if value:
        return Path(value)
    defaults = {
        "COFFER_KOLLA_STATE_FILE": Path(
            "/tmp/coffer-stage3-contract/state.json"
        ),
        "COFFER_KOLLA_EVENT_FILE": Path(
            "/tmp/coffer-stage3-contract/events.jsonl"
        ),
    }
    if environment_name not in defaults:
        raise RuntimeError(f"{environment_name} is required")
    return defaults[environment_name]


def load_state() -> dict[str, Any]:
    path = _required_path("COFFER_KOLLA_STATE_FILE")
    if not path.exists():
        return {"containers": {}, "operations": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    path = _required_path("COFFER_KOLLA_STATE_FILE")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def record_event(**event: Any) -> None:
    path = _required_path("COFFER_KOLLA_EVENT_FILE")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
