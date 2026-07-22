from __future__ import annotations

import json
import os
import sys

from coffer.quota import QuotaStore


def render(store: QuotaStore, project_id: str) -> None:
    usage = store.usage(project_id)
    print(
        json.dumps(
            {
                "limit_bytes": usage.limit_bytes,
                "reserved_bytes": usage.reserved_bytes,
                "used_bytes": usage.used_bytes,
            },
            sort_keys=True,
        )
    )


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: fixture_admin.py usage | set-headroom BYTES")
    store = QuotaStore(
        os.environ["COFFER_QUOTA_DATABASE"], bootstrap_schema=True
    )
    project_id = os.environ["COFFER_QUOTA_PROJECT_A"]
    if sys.argv[1] == "usage" and len(sys.argv) == 2:
        render(store, project_id)
    elif sys.argv[1] == "set-headroom" and len(sys.argv) == 3:
        headroom = int(sys.argv[2])
        if headroom < 0 or headroom > 4 * 1024 * 1024:
            raise ValueError("headroom is outside the manifest bound")
        usage = store.usage(project_id)
        store.set_limit(
            project_id, usage.used_bytes + usage.reserved_bytes + headroom
        )
        render(store, project_id)
    else:
        raise SystemExit("unsupported fixture admin command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
