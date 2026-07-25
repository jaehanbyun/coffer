from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "data-protection" / "backup_manifest.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "data_protection.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
BUNDLE = FIXTURE["backup_bundle"]
PROVENANCE = BUNDLE["provenance"]
SOURCE_SIGNATURE = FIXTURE["evidence"]["writer_fence"]["source_signature"]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MANIFEST = _load_module(
    "coffer_data_protection_backup_manifest_tests",
    MODULE_PATH,
)


def bundle():
    return deepcopy(BUNDLE)


def verify(value=None):
    return MANIFEST.verify_backup_bundle(
        bundle() if value is None else value,
        invocation_id=PROVENANCE["invocation_id"],
        target_signature=PROVENANCE["target_signature"],
        topology_digest=PROVENANCE["topology_digest"],
        source_signature=SOURCE_SIGNATURE,
    )


def cli_arguments(path: Path, output: Path | None = None) -> list[str]:
    arguments = [
        str(path),
        "--invocation-id",
        PROVENANCE["invocation_id"],
        "--target-signature",
        PROVENANCE["target_signature"],
        "--topology-digest",
        PROVENANCE["topology_digest"],
        "--source-signature",
        SOURCE_SIGNATURE,
    ]
    if output is not None:
        arguments.extend(["--output", str(output)])
    return arguments


def invoke(capsys, arguments: list[str]):
    result = MANIFEST.run(arguments)
    captured = capsys.readouterr()
    output = captured.out if result == 0 else captured.err
    return result, json.loads(output)


def owner_manifest(tmp_path: Path, value=None) -> Path:
    path = tmp_path / "bundle.json"
    path.write_text(
        json.dumps(bundle() if value is None else value),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_verified_bundle_is_deterministic_and_state_compatible() -> None:
    first = verify()
    second = verify()

    assert first == second
    assert first["schema"] == MANIFEST.EVIDENCE_SCHEMA
    assert first["bundle_sha256"].startswith("sha256:")
    assert first["sql_backup"]["backup_sha256"] == (
        first["sql_backup"]["restore_sha256"]
    )
    assert first["sql_backup"]["artifact_sha256"].startswith("sha256:")
    assert first["rgw_backup"]["source_inventory_sha256"] == (
        first["rgw_backup"]["restore_inventory_sha256"]
    )
    assert first["rgw_backup"]["object_count"] == 2
    assert first["rgw_backup"]["version_count"] == 3
    assert first["rgw_backup"]["bytes"] == 4096
    assert first["rgw_backup"]["multipart_upload_count"] == 0
    assert first["sql_backup"]["provenance_sha256"] == (
        first["rgw_backup"]["provenance_sha256"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("invocation_id", "invalid"),
        ("target_signature", "f" * 64),
        ("topology_digest", f"sha256:{'f' * 64}"),
        ("adapter", "live"),
        ("adapter_version", "2"),
    ],
)
def test_provenance_mismatch_is_refused(field: str, value: object) -> None:
    changed = bundle()
    changed["provenance"][field] = value

    with pytest.raises(MANIFEST.ManifestError, match="provenance"):
        verify(changed)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("restore", "content_sha256"), f"sha256:{'f' * 64}"),
        (("restore", "schema_revision"), "wrong-revision"),
        (("restore", "schema_sha256"), f"sha256:{'f' * 64}"),
        (("restore", "row_count"), 41),
        (("restore", "passed"), False),
        (("source_content_sha256",), "invalid"),
        (("bytes",), 0),
        (("row_count",), True),
    ],
)
def test_sql_restore_or_manifest_mismatch_is_refused(
    path: tuple[str, ...],
    value: object,
) -> None:
    changed = bundle()
    target = changed["sql"]
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value

    with pytest.raises(MANIFEST.ManifestError, match="SQL|canonical|positive"):
        verify(changed)


def test_sql_restore_must_be_isolated() -> None:
    changed = bundle()
    changed["sql"]["restore"]["isolated_database_sha256"] = (
        changed["sql"]["source_database_sha256"]
    )

    with pytest.raises(MANIFEST.ManifestError, match="isolated SQL"):
        verify(changed)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("pagination_complete",), False, "listing"),
        (("multipart_upload_count",), 1, "multipart"),
        (("restore", "object_count"), 1, "restore"),
        (
            ("restore", "restore_inventory_sha256"),
            f"sha256:{'f' * 64}",
            "restore",
        ),
        (
            ("restore", "metadata_sha256"),
            f"sha256:{'f' * 64}",
            "restore",
        ),
        (
            ("restore", "restore_pull_sha256"),
            f"sha256:{'e' * 64}",
            "restore",
        ),
        (("restore", "passed"), False, "restore"),
        (("source_signature",), f"sha256:{'f' * 64}", "source signature"),
    ],
)
def test_rgw_listing_or_restore_mismatch_is_refused(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    changed = bundle()
    target = changed["rgw"]
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value

    with pytest.raises(MANIFEST.ManifestError, match=message):
        verify(changed)


def test_rgw_object_versions_require_order_uniqueness_encryption_and_sizes() -> None:
    changed = bundle()
    changed["rgw"]["objects"].reverse()
    with pytest.raises(MANIFEST.ManifestError, match="ordered"):
        verify(changed)

    changed = bundle()
    changed["rgw"]["objects"][1] = deepcopy(changed["rgw"]["objects"][0])
    with pytest.raises(MANIFEST.ManifestError, match="repeated"):
        verify(changed)

    changed = bundle()
    changed["rgw"]["objects"][0]["encryption"] = "AES256"
    with pytest.raises(MANIFEST.ManifestError, match="SSE-KMS"):
        verify(changed)

    changed = bundle()
    changed["rgw"]["objects"][0]["size"] = 1
    changed["rgw"]["restore"]["bytes"] = 4097
    with pytest.raises(MANIFEST.ManifestError, match="zero or positive"):
        verify(changed)

    changed = bundle()
    marker = changed["rgw"]["objects"][2]
    marker["kms_key_sha256"] = f"sha256:{'7' * 64}"
    with pytest.raises(MANIFEST.ManifestError, match="delete marker"):
        verify(changed)


def test_extra_fields_and_secret_patterns_are_refused() -> None:
    changed = bundle()
    changed["sql"]["token"] = "do-not-retain-this-value"

    with pytest.raises(MANIFEST.ManifestError, match="prohibited|fields"):
        verify(changed)


def test_cli_requires_owner_only_regular_single_link_input(
    tmp_path: Path,
    capsys,
) -> None:
    path = owner_manifest(tmp_path)
    path.chmod(0o644)
    result, failure = invoke(capsys, cli_arguments(path))
    assert result == 2
    assert failure["category"] == "local-file-unavailable"

    path.chmod(0o600)
    symlink = tmp_path / "bundle-symlink.json"
    symlink.symlink_to(path)
    result, failure = invoke(capsys, cli_arguments(symlink))
    assert result == 2
    assert failure["category"] == "local-file-unavailable"

    hardlink = tmp_path / "bundle-hardlink.json"
    os.link(path, hardlink)
    result, failure = invoke(capsys, cli_arguments(path))
    assert result == 2
    assert failure["category"] == "local-file-unavailable"


def test_cli_writes_atomic_owner_only_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    path = owner_manifest(tmp_path)
    output_root = tmp_path / "evidence"
    output_root.mkdir(mode=0o700)
    output = output_root / "backup-evidence.json"

    result, evidence = invoke(capsys, cli_arguments(path, output))

    assert result == 0
    assert evidence == json.loads(output.read_text(encoding="utf-8"))
    assert stat.S_IMODE(output_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert sorted(item.name for item in output_root.iterdir()) == [
        "backup-evidence.json"
    ]


def test_cli_does_not_create_or_remediate_an_output_directory(
    tmp_path: Path,
    capsys,
) -> None:
    path = owner_manifest(tmp_path)
    missing_output = tmp_path / "missing" / "evidence.json"
    result, failure = invoke(capsys, cli_arguments(path, missing_output))
    assert result == 2
    assert failure["category"] == "local-file-unavailable"
    assert not missing_output.parent.exists()

    unsafe_root = tmp_path / "unsafe"
    unsafe_root.mkdir(mode=0o755)
    result, failure = invoke(
        capsys,
        cli_arguments(path, unsafe_root / "evidence.json"),
    )
    assert result == 2
    assert failure["category"] == "local-file-unavailable"
    assert stat.S_IMODE(unsafe_root.stat().st_mode) == 0o755


def test_cli_failure_is_fixed_and_never_exposes_manifest_details(
    tmp_path: Path,
    capsys,
) -> None:
    changed = bundle()
    changed["sql"]["token"] = "do-not-print-this-value"
    path = owner_manifest(tmp_path, changed)

    result, failure = invoke(capsys, cli_arguments(path))

    assert result == 2
    assert failure == {
        "schema": MANIFEST.FAILURE_SCHEMA,
        "category": "manifest-refused",
    }
    assert "do-not-print-this-value" not in json.dumps(failure)
