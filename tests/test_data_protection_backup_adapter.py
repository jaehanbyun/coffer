from __future__ import annotations

import ast
from copy import deepcopy
import importlib.util
import inspect
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "data-protection" / "backup_adapter.py"
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


ADAPTER = _load_module(
    "coffer_data_protection_backup_adapter_tests",
    MODULE_PATH,
)


def build(
    bundle=None,
    *,
    page_size: int = 2,
    repeat_cursor: bool = False,
    copy_digest_override: str | None = None,
    max_pages: int = ADAPTER.MAX_PAGES,
):
    selected = deepcopy(BUNDLE if bundle is None else bundle)
    return ADAPTER.build_backup_bundle(
        invocation_id=PROVENANCE["invocation_id"],
        target_signature=PROVENANCE["target_signature"],
        topology_digest=PROVENANCE["topology_digest"],
        source_signature=SOURCE_SIGNATURE,
        sql_client=ADAPTER.FixtureMariaDBClient(selected["sql"]),
        s3_client=ADAPTER.FixtureVersionedS3Client(
            selected["rgw"],
            page_size=page_size,
            repeat_cursor=repeat_cursor,
            copy_digest_override=copy_digest_override,
        ),
        max_pages=max_pages,
    )


def test_fixture_adapter_reconstructs_the_exact_verified_bundle() -> None:
    result = ADAPTER.build_fixture_backup(
        FIXTURE,
        invocation_id=PROVENANCE["invocation_id"],
        target_signature=PROVENANCE["target_signature"],
        topology_digest=PROVENANCE["topology_digest"],
        source_signature=SOURCE_SIGNATURE,
    )

    assert result.bundle == BUNDLE
    assert result.evidence == build().evidence
    assert result.trace == (
        "sql.inspect-source",
        "sql.create-backup",
        "sql.restore-and-inspect",
        "s3.inspect-source",
        "s3.list-versions",
        "s3.list-versions",
        "s3.copy-versions",
        "s3.restore-and-inspect",
        "bundle.verify",
    )
    assert result == ADAPTER.build_fixture_backup(
        FIXTURE,
        invocation_id=PROVENANCE["invocation_id"],
        target_signature=PROVENANCE["target_signature"],
        topology_digest=PROVENANCE["topology_digest"],
        source_signature=SOURCE_SIGNATURE,
    )


def test_sql_fixture_client_enforces_backup_restore_order() -> None:
    client = ADAPTER.FixtureMariaDBClient(BUNDLE["sql"])

    with pytest.raises(ADAPTER.AdapterError, match="out of order"):
        client.create_backup()
    assert client.inspect_source()
    with pytest.raises(ADAPTER.AdapterError, match="out of order"):
        client.inspect_source()
    assert client.create_backup()
    assert client.restore_and_inspect()
    with pytest.raises(ADAPTER.AdapterError, match="out of order"):
        client.restore_and_inspect()


def test_s3_fixture_client_enforces_list_copy_restore_order() -> None:
    client = ADAPTER.FixtureVersionedS3Client(BUNDLE["rgw"])

    with pytest.raises(ADAPTER.AdapterError, match="out of order"):
        client.list_versions(None)
    assert client.inspect_source()
    first = client.list_versions(None)
    with pytest.raises(ADAPTER.AdapterError, match="cursor"):
        client.list_versions(None)
    second = client.list_versions(first["next_cursor"])
    versions = [*first["objects"], *second["objects"]]
    assert client.copy_versions(versions)
    assert client.restore_and_inspect()


def test_only_exact_fixture_client_types_are_accepted() -> None:
    class Impostor:
        adapter_kind = ADAPTER.ADAPTER_KIND

    with pytest.raises(ADAPTER.AdapterError, match="only"):
        ADAPTER.build_backup_bundle(
            invocation_id=PROVENANCE["invocation_id"],
            target_signature=PROVENANCE["target_signature"],
            topology_digest=PROVENANCE["topology_digest"],
            source_signature=SOURCE_SIGNATURE,
            sql_client=Impostor(),
            s3_client=ADAPTER.FixtureVersionedS3Client(BUNDLE["rgw"]),
        )


def test_repeated_or_excessive_pagination_is_refused() -> None:
    with pytest.raises(ADAPTER.AdapterError, match="cursor"):
        build(repeat_cursor=True)

    with pytest.raises(ADAPTER.AdapterError, match="bound"):
        build(max_pages=1)

    with pytest.raises(ADAPTER.AdapterError, match="bound"):
        build(max_pages=0)


def test_copy_result_must_cover_the_exact_version_listing() -> None:
    with pytest.raises(ADAPTER.AdapterError, match="copy"):
        build(copy_digest_override=f"sha256:{'f' * 64}")


def test_sql_restore_drift_is_refused_by_the_canonical_verifier() -> None:
    changed = deepcopy(BUNDLE)
    changed["sql"]["restore"]["content_sha256"] = f"sha256:{'f' * 64}"

    with pytest.raises(ADAPTER.AdapterError, match="refused"):
        build(changed)


def test_s3_restore_or_object_drift_is_refused() -> None:
    changed = deepcopy(BUNDLE)
    changed["rgw"]["restore"]["restore_inventory_sha256"] = (
        f"sha256:{'f' * 64}"
    )
    with pytest.raises(ADAPTER.AdapterError, match="refused"):
        build(changed)

    changed = deepcopy(BUNDLE)
    changed["rgw"]["objects"].reverse()
    with pytest.raises(ADAPTER.AdapterError, match="refused"):
        build(changed)

    changed = deepcopy(BUNDLE)
    changed["rgw"]["objects"] = []
    with pytest.raises(ADAPTER.AdapterError, match="empty"):
        build(changed)


def test_fixture_wrapper_refuses_any_bundle_difference() -> None:
    changed = deepcopy(FIXTURE)
    changed["backup_bundle"]["rgw"]["page_count"] = 3

    with pytest.raises(ADAPTER.AdapterError, match="exact bundle|refused"):
        ADAPTER.build_fixture_backup(
            changed,
            invocation_id=PROVENANCE["invocation_id"],
            target_signature=PROVENANCE["target_signature"],
            topology_digest=PROVENANCE["topology_digest"],
            source_signature=SOURCE_SIGNATURE,
        )


def test_adapter_surfaces_contain_no_credential_parameters_or_results() -> None:
    parameters = {
        name
        for callable_value in (
            ADAPTER.build_backup_bundle,
            ADAPTER.build_fixture_backup,
            ADAPTER.FixtureMariaDBClient,
            ADAPTER.FixtureVersionedS3Client,
        )
        for name in inspect.signature(callable_value).parameters
    }
    serialized = json.dumps(build().bundle, sort_keys=True).lower()

    assert not parameters & {
        "access_key",
        "authorization",
        "database_url",
        "password",
        "secret",
        "secret_key",
        "token",
    }
    assert all(
        marker not in serialized
        for marker in (
            "authorization",
            "bearer ",
            "password",
            "private_key",
            "secret_key",
        )
    )


def test_first_adapter_milestone_has_no_external_runtime_import() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name.split(".", maxsplit=1)[0]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", maxsplit=1)[0])

    assert not imports & {
        "boto3",
        "botocore",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
