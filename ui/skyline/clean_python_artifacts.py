#!/usr/bin/env python3
"""Remove only disposable Python build outputs from a Skyline source tree."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

GENERATED = (
    "build",
    "dist",
    "skyline_console.egg-info",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    args = parser.parse_args()
    tree = args.tree.resolve()
    if not tree.is_dir() or not (tree / "pyproject.toml").is_file():
        raise SystemExit("coffer-skyline-clean: invalid Skyline source tree")
    for name in GENERATED:
        target = tree / name
        if target.is_symlink():
            raise SystemExit("coffer-skyline-clean: generated path is a link")
        if not target.exists():
            continue
        if target.resolve().parent != tree:
            raise SystemExit("coffer-skyline-clean: generated path escaped source tree")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    print("Disposable Skyline Python build outputs removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
