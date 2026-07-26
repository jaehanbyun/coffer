#!/usr/bin/env python3
"""Apply the Coffer overlay to one exact, clean Skyline Console checkout."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASELINE_PATH = ROOT / "baseline.json"
OVERLAY_PATH = ROOT / "overlay"
PATCH_PATH = ROOT / "patches" / "0001-coffer-registry.patch"


class OverlayError(RuntimeError):
    pass


def _run(*args: str, cwd: Path | None = None, binary: bool = False):
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode:
        raise OverlayError(f"command failed: {args[0]} {args[1]}")
    return result.stdout


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _load_baseline() -> dict:
    with BASELINE_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def verify_source(source: Path, baseline: dict) -> None:
    if not source.is_dir() or not (source / ".git").exists():
        raise OverlayError("source must be a Skyline Console Git checkout")
    expected = baseline["skyline_console"]
    revision = _run("git", "rev-parse", "HEAD", cwd=source).strip()
    if revision != expected["revision"]:
        raise OverlayError("source revision does not match the pinned baseline")
    if _run("git", "status", "--porcelain", cwd=source):
        raise OverlayError("source checkout must be clean")
    for name, key in (
        ("package.json", "package_json_sha256"),
        ("yarn.lock", "yarn_lock_sha256"),
    ):
        if _digest(source / name) != expected[key]:
            raise OverlayError(f"{name} does not match the pinned baseline")


def _safe_output(source: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise OverlayError("output must not already exist")
    if output == source or source in output.parents:
        raise OverlayError("output must be outside the source checkout")
    parent = output.parent
    if not parent.is_dir() or parent.is_symlink():
        raise OverlayError("output parent must be an existing regular directory")


def _extract_revision(source: Path, revision: str, output: Path) -> None:
    archive = _run(
        "git",
        "archive",
        "--format=tar",
        revision,
        cwd=source,
        binary=True,
    )
    output.mkdir(mode=0o755)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream.getmembers():
            destination = (output / member.name).resolve()
            if output.resolve() not in destination.parents:
                raise OverlayError("source archive contains an unsafe path")
        stream.extractall(output, filter="data")


def _apply_patch(output: Path) -> None:
    for dry_run in (True, False):
        args = ["patch"]
        if dry_run:
            args.append("--dry-run")
        args.extend(("--fuzz=0", "-p1", "-d", str(output)))
        with PATCH_PATH.open("rb") as patch:
            result = subprocess.run(
                args,
                stdin=patch,
                check=False,
                capture_output=True,
            )
        if result.returncode:
            raise OverlayError("central integration patch does not apply exactly")


def apply_overlay(source: Path, output: Path, baseline: dict) -> None:
    _safe_output(source, output)
    try:
        _extract_revision(source, baseline["skyline_console"]["revision"], output)
        shutil.copytree(OVERLAY_PATH, output, dirs_exist_ok=True)
        _apply_patch(output)
    except Exception:
        if output.exists() and output.parent.is_dir():
            quarantine = Path(
                tempfile.mkdtemp(prefix="coffer-skyline-failed-", dir=output.parent)
            )
            failed = quarantine / "tree"
            output.rename(failed)
            shutil.rmtree(quarantine)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    baseline = _load_baseline()
    verify_source(source, baseline)
    if args.check:
        if args.output is not None:
            raise OverlayError("--output cannot be used with --check")
        print("Skyline Console source matches the pinned baseline.")
        return 0
    if args.output is None:
        raise OverlayError("--output is required unless --check is used")
    output = args.output.resolve()
    apply_overlay(source, output, baseline)
    print(f"Coffer Skyline overlay prepared at {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OverlayError as error:
        raise SystemExit(f"coffer-skyline-overlay: {error}") from None
