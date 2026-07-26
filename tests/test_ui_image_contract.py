from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "ui" / "images" / "write_contract.py"
)
SPEC = importlib.util.spec_from_file_location("coffer_ui_image_contract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)
INSTALLER_PATH = (
    Path(__file__).resolve().parents[1] / "ui" / "images" / "install_horizon.py"
)
INSTALLER_SPEC = importlib.util.spec_from_file_location(
    "coffer_horizon_image_installer",
    INSTALLER_PATH,
)
assert INSTALLER_SPEC is not None and INSTALLER_SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(INSTALLER_SPEC)
INSTALLER_SPEC.loader.exec_module(INSTALLER)


def wheel(path: Path, name: str, version: str) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"{name.replace('-', '_')}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n",
        )
    return path


def image(name: str, digit: str) -> str:
    return f"registry.example/{name}@sha256:{digit * 64}"


@pytest.mark.parametrize(
    ("surface", "name", "version"),
    [
        ("horizon", "coffer-horizon", "0.1.0"),
        ("skyline", "skyline-console", "8.0.0+coffer.1"),
    ],
)
def test_contract_binds_exact_artifact_and_images(
    tmp_path: Path,
    surface: str,
    name: str,
    version: str,
) -> None:
    artifact = wheel(tmp_path / f"{surface}.whl", name, version)
    document = CONTRACT.build_contract(
        surface=surface,
        artifact=artifact,
        image=image(f"coffer-{surface}", "a"),
        base_image=image(surface, "b"),
    )

    assert document["schema_version"] == 1
    assert document["surface"] == surface
    assert document["artifact"]["name"] == name
    assert document["artifact"]["version"] == version
    assert len(document["artifact"]["sha256"]) == 64
    assert document["image"].endswith("a" * 64)
    assert document["base_image"].endswith("b" * 64)


def test_contract_refuses_tags_wrong_wheels_and_equal_images(
    tmp_path: Path,
) -> None:
    artifact = wheel(tmp_path / "plugin.whl", "coffer-horizon", "0.1.0")
    with pytest.raises(CONTRACT.ContractError, match="exact sha256"):
        CONTRACT.build_contract(
            surface="horizon",
            artifact=artifact,
            image="registry.example/coffer-horizon:latest",
            base_image=image("horizon", "b"),
        )
    with pytest.raises(CONTRACT.ContractError, match="must differ"):
        CONTRACT.build_contract(
            surface="horizon",
            artifact=artifact,
            image=image("horizon", "b"),
            base_image=image("horizon", "b"),
        )
    wrong = wheel(tmp_path / "wrong.whl", "other-package", "0.1.0")
    with pytest.raises(CONTRACT.ContractError, match="name or version"):
        CONTRACT.build_contract(
            surface="horizon",
            artifact=wrong,
            image=image("coffer-horizon", "a"),
            base_image=image("horizon", "b"),
        )


def test_contract_write_is_owner_controlled_and_idempotent(
    tmp_path: Path,
) -> None:
    artifact = wheel(
        tmp_path / "skyline.whl",
        "skyline-console",
        "8.0.0+coffer.1",
    )
    document = CONTRACT.build_contract(
        surface="skyline",
        artifact=artifact,
        image=image("coffer-skyline", "a"),
        base_image=image("skyline", "b"),
    )
    output = tmp_path / "contract.json"

    CONTRACT.write_contract(output, document)
    first_stat = output.stat()
    CONTRACT.write_contract(output, document)

    assert output.stat().st_ino == first_stat.st_ino
    assert output.stat().st_mode & 0o777 == 0o640
    assert json.loads(output.read_text(encoding="utf-8")) == document

    different = dict(document)
    different["image"] = image("coffer-skyline", "c")
    with pytest.raises(CONTRACT.ContractError, match="refusing to replace"):
        CONTRACT.write_contract(output, different)


def test_horizon_image_installer_copies_only_runtime_registration(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugin"
    horizon = tmp_path / "horizon"
    config = tmp_path / "config"
    inputs = {
        "enabled/_1910_project_registry_panel_group.py": "group\n",
        "enabled/_1920_project_registry_repositories_panel.py": "panel\n",
        "enabled/_9999_unrelated.py": "unrelated\n",
        "local_settings.d/_1930_coffer_policy.py": "settings\n",
        "local_settings.d/_9999_unrelated.py": "unrelated\n",
        "conf/coffer_policy.yaml": "policy\n",
    }
    for relative, content in inputs.items():
        path = plugin / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    INSTALLER.install_dashboard(plugin, horizon, config)

    copied = {
        str(path.relative_to(tmp_path)): path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and plugin not in path.parents
    }
    assert copied == {
        "config/coffer_policy.yaml": "policy\n",
        "horizon/local/enabled/_1910_project_registry_panel_group.py": "group\n",
        "horizon/local/enabled/_1920_project_registry_repositories_panel.py": (
            "panel\n"
        ),
        "horizon/local/local_settings.d/_1930_coffer_policy.py": "settings\n",
    }
    assert all(
        path.stat().st_mode & 0o777 == 0o644
        for path in tmp_path.rglob("*")
        if path.is_file() and plugin not in path.parents
    )
