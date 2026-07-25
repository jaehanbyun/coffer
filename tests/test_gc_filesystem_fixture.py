from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
GC_DIRECTORY = ROOT / "poc" / "gc-retention"
FILESYSTEM_DIRECTORY = GC_DIRECTORY / "filesystem"
TOPOLOGY = GC_DIRECTORY / "topology.json"
RAW_OUTPUT = ROOT / "tests" / "fixtures" / "gc_v3_1_1_dry_run.txt"
DELETED_REPOSITORY = "p/33333333-3333-4333-8333-333333333333/deleted"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = load_module(
    "coffer_gc_filesystem_adapter_tests",
    FILESYSTEM_DIRECTORY / "filesystem_adapter.py",
)


def private_directory(path: Path) -> Path:
    path.mkdir()
    path.chmod(0o700)
    return path


def private_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def private_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def fixture_value() -> dict:
    candidates = [
        {
            "digest": f"sha256:{digit * 64}",
            "kind": "blob",
            "repository": None,
        }
        for digit in "1234"
    ]
    candidates.extend(
        {
            "digest": f"sha256:{digit * 64}",
            "kind": "layer-link",
            "repository": DELETED_REPOSITORY,
        }
        for digit in "23"
    )
    return {
        "candidates": candidates,
        "retained_digests": [f"sha256:{'f' * 64}"],
        "schema": ADAPTER.FIXTURE_SCHEMA,
    }


def normalize(tmp_path: Path, name: str = "normalized.json") -> Path:
    directory = private_directory(tmp_path / name.removesuffix(".json"))
    fixture = private_json(directory / "fixture.json", fixture_value())
    raw = private_text(
        directory / "raw.txt",
        RAW_OUTPUT.read_text(encoding="utf-8"),
    )
    output = directory / name
    ADAPTER.normalize_command(
        argparse.Namespace(
            fixture=fixture,
            output=output,
            raw_output=raw,
            topology=TOPOLOGY,
        )
    )
    return output


def test_normalize_binds_real_fixture_candidate_authority(
    tmp_path: Path,
) -> None:
    output = normalize(tmp_path)
    value = json.loads(output.read_text(encoding="utf-8"))

    assert value["schema"] == "coffer.gc-collector-output/v1"
    assert value["candidate_total"] == 6
    assert output.stat().st_mode & 0o777 == 0o600


def test_two_equal_dry_runs_authorize_once(tmp_path: Path) -> None:
    first = normalize(tmp_path, "first.json")
    second = normalize(tmp_path, "second.json")
    directory = private_directory(tmp_path / "authorization")
    authorization = directory / "authorization.json"
    ADAPTER.authorize_command(
        argparse.Namespace(
            first=first,
            output=authorization,
            second=second,
            topology=TOPOLOGY,
            ttl=900,
        )
    )
    consumption = directory / "consumption.json"
    ADAPTER.consume_command(
        argparse.Namespace(
            authorization=authorization,
            output=consumption,
        )
    )

    state = json.loads(authorization.read_text(encoding="utf-8"))
    assert state["consumed"] is True
    assert json.loads(consumption.read_text(encoding="utf-8"))["schema"] == (
        ADAPTER.CONSUMPTION_SCHEMA
    )
    with pytest.raises(ADAPTER.FilesystemAdapterError, match="invalid"):
        ADAPTER.consume_command(
            argparse.Namespace(
                authorization=authorization,
                output=directory / "replay.json",
            )
        )


def test_dry_run_drift_or_ttl_change_is_refused(tmp_path: Path) -> None:
    first = normalize(tmp_path, "first.json")
    second = normalize(tmp_path, "second.json")
    changed = json.loads(second.read_text(encoding="utf-8"))
    changed["candidate_total"] += 1
    private_json(second, changed)
    directory = private_directory(tmp_path / "authorization")

    with pytest.raises(ADAPTER.FilesystemAdapterError, match="changed"):
        ADAPTER.authorize_command(
            argparse.Namespace(
                first=first,
                output=directory / "drift.json",
                second=second,
                topology=TOPOLOGY,
                ttl=900,
            )
        )
    with pytest.raises(ADAPTER.FilesystemAdapterError, match="lifetime"):
        ADAPTER.authorize_command(
            argparse.Namespace(
                first=first,
                output=directory / "ttl.json",
                second=first,
                topology=TOPOLOGY,
                ttl=901,
            )
        )


def test_unsafe_fixture_input_mode_is_refused(tmp_path: Path) -> None:
    directory = private_directory(tmp_path / "unsafe")
    fixture = private_json(directory / "fixture.json", fixture_value())
    fixture.chmod(0o644)
    raw = private_text(
        directory / "raw.txt",
        RAW_OUTPUT.read_text(encoding="utf-8"),
    )

    with pytest.raises(ADAPTER.FilesystemAdapterError, match="ownership"):
        ADAPTER.normalize_command(
            argparse.Namespace(
                fixture=fixture,
                output=directory / "output.json",
                raw_output=raw,
                topology=TOPOLOGY,
            )
        )


def test_storage_reclaim_and_restore_are_bound(tmp_path: Path) -> None:
    directory = private_directory(tmp_path / "tree")
    before_root = private_directory(directory / "before")
    after_root = private_directory(directory / "after")
    restored_root = private_directory(directory / "restored")
    (before_root / "keep").write_bytes(b"keep")
    (before_root / "delete").write_bytes(b"delete")
    (after_root / "keep").write_bytes(b"keep")
    (restored_root / "keep").write_bytes(b"keep")
    (restored_root / "delete").write_bytes(b"delete")
    summaries = {}
    for name, root in (
        ("before", before_root),
        ("after", after_root),
        ("restored", restored_root),
    ):
        output = directory / f"{name}.json"
        ADAPTER.summarize_command(
            argparse.Namespace(root=root, output=output)
        )
        summaries[name] = output
    reclaim = directory / "reclaim.json"
    ADAPTER.verify_reclaim_command(
        argparse.Namespace(output=reclaim, **summaries)
    )

    value = json.loads(reclaim.read_text(encoding="utf-8"))
    assert value["tree_files_reclaimed"] == 1
    assert value["logical_bytes_reclaimed"] == len(b"delete")


def test_restore_drift_is_refused(tmp_path: Path) -> None:
    directory = private_directory(tmp_path / "tree")
    summaries = {}
    for name, body in (
        ("before", b"before"),
        ("after", b"a"),
        ("restored", b"changed"),
    ):
        root = private_directory(directory / name)
        (root / "content").write_bytes(body)
        output = directory / f"{name}.json"
        ADAPTER.summarize_command(
            argparse.Namespace(root=root, output=output)
        )
        summaries[name] = output

    with pytest.raises(ADAPTER.FilesystemAdapterError, match="restore"):
        ADAPTER.verify_reclaim_command(
            argparse.Namespace(
                output=directory / "reclaim.json",
                **summaries,
            )
        )


def test_compose_pins_exact_image_and_temporary_bind_mount() -> None:
    compose = yaml.safe_load(
        (FILESYSTEM_DIRECTORY / "compose.yaml").read_text(encoding="utf-8")
    )
    registry = compose["services"]["registry"]

    assert registry["image"].endswith(
        "@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
    )
    assert registry["ports"] == ["127.0.0.1:${COFFER_GC_PORT:-55008}:5000"]
    assert registry["volumes"][1] == (
        "${COFFER_GC_STORAGE:?set COFFER_GC_STORAGE}:/var/lib/registry:z"
    )
    assert registry["restart"] == "no"


def test_live_harness_has_no_s3_or_untagged_delete_path() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in FILESYSTEM_DIRECTORY.iterdir()
        if path.is_file()
    )

    assert "--delete-untagged" not in sources
    for forbidden in (
        "AWS_ACCESS_KEY",
        "REGISTRY_STORAGE_S3",
        "radosgw-admin",
        "s3://",
    ):
        assert forbidden not in sources
    assert "--network none" in sources
    assert "--cap-drop=all" in sources
    assert "--cap-add=DAC_OVERRIDE" in sources


def test_python_fixture_adapters_do_not_spawn_or_connect_externally() -> None:
    adapter_source = (
        FILESYSTEM_DIRECTORY / "filesystem_adapter.py"
    ).read_text(encoding="utf-8")
    prepare_source = (
        FILESYSTEM_DIRECTORY / "prepare_fixture.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "import boto",
        "import requests",
        "import socket",
        "import sqlalchemy",
        "import subprocess",
        "urllib.request",
    ):
        assert forbidden not in adapter_source
        assert forbidden not in prepare_source
    assert "parsed.scheme != \"http\"" in prepare_source
