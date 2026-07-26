from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
import subprocess

import horizon


HORIZON_REVISION = "0a4439556517cf67be0aa949b6551a14e409af75"
EXPECTED_VERSIONS = {
    "Django": "4.2.28",
    "horizon": "25.7.3",
    "keystoneauth1": "5.13.1",
    "pytest": "9.0.2",
}


class VerificationError(RuntimeError):
    pass


def _git(source: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 or result.stderr:
        raise VerificationError("Horizon source verification failed")
    return result.stdout.strip()


def verify(horizon_source: Path) -> None:
    source = horizon_source.resolve()
    if not source.is_dir():
        raise VerificationError("Horizon source is unavailable")
    if _git(source, "rev-parse", "HEAD") != HORIZON_REVISION:
        raise VerificationError("Horizon source revision is not qualified")
    if _git(source, "status", "--short"):
        raise VerificationError("Horizon source is not clean")

    for distribution, expected in EXPECTED_VERSIONS.items():
        if importlib.metadata.version(distribution) != expected:
            raise VerificationError("Horizon dependency baseline does not match")

    imported = Path(horizon.__file__).resolve()
    try:
        imported.relative_to(source)
    except ValueError:
        raise VerificationError(
            "Horizon is not imported from qualified source"
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the exact Coffer Horizon development baseline"
    )
    parser.add_argument(
        "--horizon-source",
        required=True,
        type=Path,
    )
    arguments = parser.parse_args()
    try:
        verify(arguments.horizon_source)
    except (VerificationError, OSError, subprocess.SubprocessError):
        print("Coffer Horizon baseline: failed")
        return 1
    print("Coffer Horizon baseline: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
