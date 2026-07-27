from __future__ import annotations

import argparse
import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import Iterable

HORIZON_MEMBERS = {
    "cofferdashboard/enabled/_1910_project_registry_panel_group.py": (
        "local/enabled/_1910_project_registry_panel_group.py"
    ),
    "cofferdashboard/enabled/_1920_project_registry_repositories_panel.py": (
        "local/enabled/_1920_project_registry_repositories_panel.py"
    ),
    "cofferdashboard/local_settings.d/_1930_coffer_policy.py": (
        "local/local_settings.d/_1930_coffer_policy.py"
    ),
}
HORIZON_POLICY_MEMBER = "cofferdashboard/conf/coffer_policy.yaml"
HORIZON_DEFAULT_POLICY_MEMBER = (
    "cofferdashboard/conf/default_policies/coffer.yaml"
)
HORIZON_ABSENT = (
    "/tmp/coffer_horizon-0.1.0-py3-none-any.whl",
    "/tmp/install-coffer-horizon.py",
)
SKYLINE_ABSENT = (
    "/tmp/skyline_console-8.0.0+coffer.1-py3-none-any.whl",
)


class RuntimeCollectionError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeCollectionError(f"invalid runtime file: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prove_absent(paths: Iterable[str]) -> list[str]:
    values = list(paths)
    if any(Path(path).exists() or Path(path).is_symlink() for path in values):
        raise RuntimeCollectionError("container build input remains in runtime")
    return values


def collect_horizon(
    *,
    horizon_root: Path,
    config_root: Path,
    package_version: str,
) -> dict[str, object]:
    files = {
        member: file_sha256(horizon_root / destination)
        for member, destination in HORIZON_MEMBERS.items()
    }
    files[HORIZON_POLICY_MEMBER] = file_sha256(config_root / "coffer_policy.yaml")
    files[HORIZON_DEFAULT_POLICY_MEMBER] = file_sha256(
        config_root / "default_policies" / "coffer.yaml"
    )
    return {
        "package": {"name": "coffer-horizon", "version": package_version},
        "files": files,
        "absent": prove_absent(HORIZON_ABSENT),
    }


def collect_skyline(
    *,
    package_root: Path,
    package_version: str,
) -> dict[str, object]:
    bundles = sorted((package_root / "static").glob("coffer.bundle.*.js"))
    if len(bundles) != 1:
        raise RuntimeCollectionError("runtime must contain one Coffer Skyline bundle")
    bundle = bundles[0]
    member = str(bundle.relative_to(package_root.parent))
    return {
        "package": {"name": "skyline-console", "version": package_version},
        "files": {member: file_sha256(bundle)},
        "absent": prove_absent(SKYLINE_ABSENT),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=("horizon", "skyline"))
    arguments = parser.parse_args()
    try:
        if arguments.surface == "horizon":
            import openstack_dashboard

            result = collect_horizon(
                horizon_root=Path(openstack_dashboard.__file__).resolve().parent,
                config_root=Path("/etc/openstack-dashboard"),
                package_version=metadata.version("coffer-horizon"),
            )
        else:
            import skyline_console

            result = collect_skyline(
                package_root=Path(skyline_console.__file__).resolve().parent,
                package_version=metadata.version("skyline-console"),
            )
    except (RuntimeCollectionError, metadata.PackageNotFoundError):
        print("coffer-ui-image-runtime: invalid runtime")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
