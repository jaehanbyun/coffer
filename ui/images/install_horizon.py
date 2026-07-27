#!/usr/bin/env python3
"""Install Coffer's enabled and policy files into one Kolla Horizon image."""

from __future__ import annotations

import shutil
from pathlib import Path


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise RuntimeError(f"invalid packaged Horizon input: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o644)


def install_dashboard(
    plugin_root: Path,
    horizon_root: Path,
    config_root: Path,
) -> None:
    enabled_root = horizon_root / "local" / "enabled"
    settings_root = horizon_root / "local" / "local_settings.d"
    for name in (
        "_1910_project_registry_panel_group.py",
        "_1920_project_registry_repositories_panel.py",
    ):
        source = plugin_root / "enabled" / name
        copy_file(source, enabled_root / source.name)
    settings = plugin_root / "local_settings.d" / "_1930_coffer_policy.py"
    copy_file(settings, settings_root / settings.name)
    copy_file(
        plugin_root / "conf" / "coffer_policy.yaml",
        config_root / "coffer_policy.yaml",
    )
    copy_file(
        plugin_root / "conf" / "default_policies" / "coffer.yaml",
        config_root / "default_policies" / "coffer.yaml",
    )


def main() -> int:
    import cofferdashboard
    import openstack_dashboard

    plugin_root = Path(cofferdashboard.__file__).resolve().parent
    horizon_root = Path(openstack_dashboard.__file__).resolve().parent
    install_dashboard(
        plugin_root,
        horizon_root,
        Path("/etc/openstack-dashboard"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
