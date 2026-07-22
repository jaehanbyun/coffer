#!/usr/bin/env python3
"""Persist a small, non-secret Git snapshot before Codex compacts context."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(root: Path, *args: str) -> str:
    result = subprocess.run(
        args,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = result.stdout.strip()
    if result.returncode != 0:
        error = result.stderr.strip() or f"command exited {result.returncode}"
        return f"[unavailable: {error}]"
    return output or "(none)"


def git_root(cwd: Path) -> Path:
    result = subprocess.run(
        ("git", "rev-parse", "--show-toplevel"),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return Path(result.stdout.strip()).resolve()


def active_plans(root: Path) -> list[str]:
    plans_dir = root / "docs" / "exec-plans"
    if not plans_dir.is_dir():
        return []
    return [
        str(path.relative_to(root))
        for path in sorted(plans_dir.glob("*.md"))
        if path.name != "TEMPLATE.md"
    ]


def fenced(value: str) -> str:
    return f"```text\n{value}\n```"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
        root = git_root(cwd)
        output_path = root / ".codex" / "state" / "precompact-snapshot.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        plans = active_plans(root)
        content = "\n".join(
            [
                "# Pre-compact Repository Snapshot",
                "",
                f"- Captured (UTC): `{timestamp}`",
                f"- Trigger: `{payload.get('trigger', 'unknown')}`",
                f"- Model: `{payload.get('model', 'unknown')}`",
                f"- Branch: `{run(root, 'git', 'branch', '--show-current')}`",
                f"- Active plan candidates: `{', '.join(plans) if plans else '(none)'}`",
                "",
                "## Working Tree",
                "",
                fenced(run(root, "git", "status", "--short")),
                "",
                "## Unstaged Diff Summary",
                "",
                fenced(run(root, "git", "diff", "--stat")),
                "",
                "## Staged Diff Summary",
                "",
                fenced(run(root, "git", "diff", "--cached", "--stat")),
                "",
                "## Recent Commits",
                "",
                fenced(run(root, "git", "log", "-5", "--oneline", "--decorate")),
                "",
                "> This generated file records mechanical repository state only. "
                "Decisions and semantic progress belong in the active execution plan and HANDOFF.md.",
                "",
            ]
        )

        fd, temporary_name = tempfile.mkstemp(
            dir=output_path.parent,
            prefix=".precompact-",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                temporary_file.write(content)
            os.replace(temporary_name, output_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

        relative = output_path.relative_to(root)
        print(
            json.dumps(
                {
                    "continue": True,
                    "systemMessage": (
                        f"Pre-compaction snapshot saved to {relative}. After compaction, "
                        "re-read AGENTS.md, the active plan, and HANDOFF.md before continuing."
                    ),
                }
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "continue": True,
                    "systemMessage": f"Pre-compaction snapshot failed without blocking compaction: {error}",
                }
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
