from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, NamedTuple

SCHEMA = "coffer.ui-parent-package-probe/v1"
PACKAGE_LINE = re.compile(r"^([^\t]+)\t([^\t]+)\t([^\t]+)\t([^\t]*)\t([^\t]*)$")
REMOVAL_LINE = re.compile(r"^(?:Remv|Purg)\s+(\S+)(?:\s+\[([^\]]+)])?")
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")


class ProbeError(RuntimeError):
    pass


class Package(NamedTuple):
    name: str
    version: str
    status: str
    depends: str
    pre_depends: str


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as error:
        raise ProbeError(f"required command is unavailable: {command[0]}") from error


def parse_packages(payload: str) -> dict[str, Package]:
    packages: dict[str, Package] = {}
    for line in payload.splitlines():
        match = PACKAGE_LINE.fullmatch(line)
        if match is None:
            raise ProbeError("dpkg package inventory is malformed")
        package = Package(*match.groups())
        if (
            not PACKAGE_NAME.fullmatch(package.name)
            or not package.version
            or package.name in packages
        ):
            raise ProbeError("dpkg package identity is invalid")
        packages[package.name] = package
    if not packages:
        raise ProbeError("dpkg package inventory is empty")
    return packages


def parse_package_marks(payload: str) -> frozenset[str]:
    marks = frozenset(line.strip() for line in payload.splitlines() if line.strip())
    if any(not PACKAGE_NAME.fullmatch(package) for package in marks):
        raise ProbeError("apt package mark is invalid")
    return marks


def dependency_mentions(payload: str, target: str) -> bool:
    pattern = re.compile(
        rf"(?:^|[,\s|]){re.escape(target)}"
        rf"(?::[a-z0-9]+)?(?:\s*\([^)]*\))?(?=\s*[,|]|$)"
    )
    return bool(pattern.search(payload))


def reverse_dependencies(
    packages: dict[str, Package],
    target: str,
) -> list[Package]:
    return sorted(
        (
            package
            for package in packages.values()
            if dependency_mentions(package.depends, target)
            or dependency_mentions(package.pre_depends, target)
        ),
        key=lambda package: package.name,
    )


def parse_removals(payload: str) -> list[dict[str, str]]:
    removals: dict[str, str] = {}
    for line in payload.splitlines():
        match = REMOVAL_LINE.match(line)
        if match is None:
            continue
        name, version = match.groups()
        name = name.split(":", 1)[0]
        if not PACKAGE_NAME.fullmatch(name):
            raise ProbeError("apt removal package identity is invalid")
        removals[name] = version or ""
    return [
        {"name": name, "installed_version": removals[name]}
        for name in sorted(removals)
    ]


def _package_record(
    package: Package,
    manual: frozenset[str],
    automatic: frozenset[str],
) -> dict[str, Any]:
    return {
        "name": package.name,
        "version": package.version,
        "status": package.status,
        "manual": package.name in manual,
        "automatic": package.name in automatic,
        "depends": package.depends,
        "pre_depends": package.pre_depends,
    }


def _os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.is_file():
        raise ProbeError("OS release metadata is unavailable")
    if path.is_symlink() and path.resolve() != Path("/usr/lib/os-release"):
        raise ProbeError("OS release metadata link is unexpected")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    identifier = values.get("ID", "")
    version = values.get("VERSION_ID", "")
    if not identifier or not version:
        raise ProbeError("OS release identity is incomplete")
    return {"id": identifier, "version_id": version}


def collect(target: str) -> dict[str, Any]:
    if not PACKAGE_NAME.fullmatch(target):
        raise ProbeError("target package name is invalid")
    inventory = _run(
        [
            "dpkg-query",
            "-W",
            "-f=${Package}\\t${Version}\\t${db:Status-Abbrev}"
            "\\t${Depends}\\t${Pre-Depends}\\n",
        ]
    )
    if inventory.returncode != 0:
        raise ProbeError("dpkg package inventory failed")
    packages = parse_packages(inventory.stdout)
    if target not in packages:
        raise ProbeError("target package is not installed")

    manual_result = _run(["apt-mark", "showmanual"])
    automatic_result = _run(["apt-mark", "showauto"])
    if manual_result.returncode != 0 or automatic_result.returncode != 0:
        raise ProbeError("apt package marks are unavailable")
    manual = parse_package_marks(manual_result.stdout)
    automatic = parse_package_marks(automatic_result.stdout)
    if manual & automatic:
        raise ProbeError("apt package marks overlap")

    files_result = _run(["dpkg-query", "-L", target])
    if files_result.returncode != 0:
        raise ProbeError("target package file inventory failed")
    files = sorted({line.strip() for line in files_result.stdout.splitlines() if line})
    if not files or any(not path.startswith("/") for path in files):
        raise ProbeError("target package file inventory is invalid")

    dependency_check = _run(
        ["apt-get", "-s", "-o", "Debug::NoLocking=true", "check"]
    )
    audit = _run(["dpkg", "--audit"])
    purge = _run(
        [
            "apt-get",
            "-s",
            "-o",
            "Debug::NoLocking=true",
            "purge",
            target,
        ]
    )
    if purge.returncode != 0:
        raise ProbeError("apt purge simulation failed")
    removed = parse_removals(purge.stdout)
    if target not in {item["name"] for item in removed}:
        raise ProbeError("apt purge simulation did not remove the target")

    target_package = packages[target]
    reverse = reverse_dependencies(packages, target)
    architecture = _run(["dpkg", "--print-architecture"])
    if architecture.returncode != 0 or not architecture.stdout.strip():
        raise ProbeError("dpkg architecture is unavailable")
    return {
        "schema": SCHEMA,
        "architecture": architecture.stdout.strip(),
        "os": _os_release(),
        "target": {
            **_package_record(target_package, manual, automatic),
            "file_count": len(files),
            "header_file_count": len(
                [path for path in files if path.startswith("/usr/include/")]
            ),
            "shared_object_file_count": len(
                [path for path in files if ".so" in Path(path).name]
            ),
            "executable_path_count": len(
                [
                    path
                    for path in files
                    if path.startswith(("/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/"))
                ]
            ),
            "direct_reverse_dependencies": [
                _package_record(package, manual, automatic) for package in reverse
            ],
        },
        "package_database": {
            "dpkg_audit_clean": audit.returncode == 0 and not audit.stdout.strip(),
            "apt_dependency_check_clean": dependency_check.returncode == 0,
        },
        "purge_simulation": {
            "removed": removed,
            "safe_to_apply": False,
            "reason": (
                "read-only dependency evidence does not prove dashboard runtime, "
                "rebuild, upgrade, or rollback safety"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="linux-libc-dev")
    arguments = parser.parse_args()
    try:
        report = collect(arguments.target)
    except ProbeError as error:
        print(f"coffer-ui-parent-package-probe: {error}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
