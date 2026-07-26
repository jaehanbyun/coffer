from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "poc" / "ui-images" / "package_probe.py"
)
SPEC = importlib.util.spec_from_file_location(
    "coffer_ui_parent_package_probe",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


def test_package_inventory_and_direct_reverse_dependencies() -> None:
    packages = PROBE.parse_packages(
        "linux-libc-dev\t6.8.0\tii \t\t\n"
        "libc6-dev\t2.39\tii \tlibc6 (= 2.39), linux-libc-dev\t\n"
        "build-essential\t12.10\tii \tlibc6-dev | libc-dev\t\n"
    )

    reverse = PROBE.reverse_dependencies(packages, "linux-libc-dev")

    assert packages["linux-libc-dev"].version == "6.8.0"
    assert [package.name for package in reverse] == ["libc6-dev"]
    assert PROBE.dependency_mentions(
        "libc6 (= 2.39), linux-libc-dev:any",
        "linux-libc-dev",
    )
    assert not PROBE.dependency_mentions("linux-libc-dev-extra", "linux-libc-dev")


def test_purge_simulation_is_canonical() -> None:
    assert PROBE.parse_removals(
        "NOTE: This is only a simulation!\n"
        "Remv build-essential [12.10ubuntu1]\n"
        "Purg linux-libc-dev:arm64 [6.8.0-136.136]\n"
    ) == [
        {"name": "build-essential", "installed_version": "12.10ubuntu1"},
        {"name": "linux-libc-dev", "installed_version": "6.8.0-136.136"},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "bad line",
        "duplicate\t1\tii \t\t\nduplicate\t2\tii \t\t\n",
    ],
)
def test_invalid_package_inventory_is_rejected(payload: str) -> None:
    with pytest.raises(PROBE.ProbeError):
        PROBE.parse_packages(payload)


def test_invalid_marks_and_removal_identity_are_rejected() -> None:
    with pytest.raises(PROBE.ProbeError, match="mark"):
        PROBE.parse_package_marks("valid\nNOT VALID\n")
    with pytest.raises(PROBE.ProbeError, match="identity"):
        PROBE.parse_removals("Remv ../escape [1]\n")


def test_runner_is_bounded_and_read_only() -> None:
    runner = (
        Path(__file__).resolve().parents[1]
        / "poc"
        / "ui-images"
        / "probe_stock_parents.sh"
    ).read_text()

    assert 'WORK="${ROOT}/work/ui-parent-remediation-probe"' in runner
    assert "refusing existing UI parent probe work directory" in runner
    assert "--network none" in runner
    assert "--read-only" in runner
    assert "--cap-drop all" in runner
    assert "--security-opt no-new-privileges" in runner
    assert "safe_to_apply == false" in runner
    assert 'rm -rf -- "${CONTEXTS:?}"' in runner
    assert "podman image rm --force" in runner
