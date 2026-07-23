from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, insert, select, text

from coffer.db import repositories as repository_table
from coffer.inventory import (
    INVENTORY_SCHEMA,
    PINNED_DISTRIBUTION_VERSION,
    PINNED_ENUMERATOR,
)
from coffer.quota import (
    Descriptor,
    OCI_IMAGE_INDEX,
    OCI_IMAGE_MANIFEST,
    QuotaExceeded,
    QuotaStore,
    project_quotas,
    quota_descriptors,
    quota_inventory_imports,
    quota_manifests,
    quota_reconciliation_claims,
    quota_reservation_descriptors,
    quota_reservations,
)
from coffer.quota_import import (
    InvalidInventoryArtifact,
    InventoryImportConflict,
    InventoryImportFailed,
    InventoryImportNotReady,
    import_inventory,
    load_inventory_artifact,
    main,
    parse_inventory_artifact,
)


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CHILD_DIGEST = f"sha256:{'1' * 64}"
INDEX_DIGEST = f"sha256:{'2' * 64}"
CONFIG_DIGEST = f"sha256:{'3' * 64}"
LAYER_DIGEST = f"sha256:{'4' * 64}"
ARTIFACT_DIGEST = f"sha256:{'a' * 64}"
ROOT = Path(__file__).resolve().parents[1]


def descriptor(digest: str, media_type: str, size: int) -> dict[str, object]:
    return {"digest": digest, "media_type": media_type, "size": size}


def artifact() -> dict[str, object]:
    descriptors = [
        descriptor(CHILD_DIGEST, OCI_IMAGE_MANIFEST, 101),
        descriptor(INDEX_DIGEST, OCI_IMAGE_INDEX, 79),
        descriptor(
            CONFIG_DIGEST,
            "application/vnd.oci.image.config.v1+json",
            17,
        ),
        descriptor(
            LAYER_DIGEST,
            "application/vnd.oci.image.layer.v1.tar+gzip",
            23,
        ),
    ]
    descriptors.sort(key=lambda value: value["digest"])  # type: ignore[index]
    return {
        "projects": [
            {
                "descriptor_count": 4,
                "descriptors": descriptors,
                "logical_bytes": 220,
                "project_id": PROJECT_ID,
            }
        ],
        "repositories": [
            {
                "manifests": [
                    {
                        "digest": CHILD_DIGEST,
                        "media_type": OCI_IMAGE_MANIFEST,
                        "references": [
                            descriptor(
                                CONFIG_DIGEST,
                                "application/vnd.oci.image.config.v1+json",
                                17,
                            ),
                            descriptor(
                                LAYER_DIGEST,
                                "application/vnd.oci.image.layer.v1.tar+gzip",
                                23,
                            ),
                        ],
                        "size": 101,
                    },
                    {
                        "digest": INDEX_DIGEST,
                        "media_type": OCI_IMAGE_INDEX,
                        "references": [
                            descriptor(CHILD_DIGEST, OCI_IMAGE_MANIFEST, 101)
                        ],
                        "size": 79,
                    },
                ],
                "project_id": PROJECT_ID,
                "repository_id": REPOSITORY_ID,
            }
        ],
        "schema": INVENTORY_SCHEMA,
        "source": {
            "distribution_version": PINNED_DISTRIBUTION_VERSION,
            "enumerator": PINNED_ENUMERATOR,
            "snapshot_scans": 2,
        },
        "summary": {
            "descriptor_count": 4,
            "logical_bytes": 220,
            "manifest_count": 2,
            "project_count": 1,
            "repository_count": 1,
        },
    }


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def migration_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def prepared_database(
    tmp_path: Path,
    *,
    name: str = "import.sqlite",
    limit_bytes: int = 4096,
    include_quota: bool = True,
    include_repository: bool = True,
) -> tuple[str, QuotaStore]:
    database_url = f"sqlite:///{tmp_path / name}"
    command.upgrade(migration_config(database_url), "head")
    engine = create_engine(database_url)
    now = datetime(2026, 7, 23, tzinfo=UTC)
    with engine.begin() as connection:
        if include_repository:
            connection.execute(
                insert(repository_table).values(
                    id=REPOSITORY_ID,
                    project_id=PROJECT_ID,
                    name="inventory",
                    immutable_tags=False,
                    created_at=now,
                )
            )
        if include_quota:
            connection.execute(
                insert(project_quotas).values(
                    project_id=PROJECT_ID,
                    limit_bytes=limit_bytes,
                    used_bytes=0,
                    reserved_bytes=0,
                    updated_at=now,
                )
            )
    return database_url, QuotaStore(database_url)


def parsed_artifact() -> object:
    return parse_inventory_artifact(artifact(), artifact_digest=ARTIFACT_DIGEST)


def table_count(database_url: str, table: object) -> int:
    with create_engine(database_url).connect() as connection:
        return connection.execute(  # type: ignore[arg-type]
            select(func.count()).select_from(table)
        ).scalar_one()


def test_parses_strict_redundant_inventory() -> None:
    parsed = parse_inventory_artifact(artifact(), artifact_digest=ARTIFACT_DIGEST)

    assert parsed.digest == ARTIFACT_DIGEST
    assert parsed.summary.logical_bytes == 220
    assert [item.digest for item in parsed.projects[0].descriptors] == [
        CHILD_DIGEST,
        INDEX_DIGEST,
        CONFIG_DIGEST,
        LAYER_DIGEST,
    ]
    assert [item.digest for item in parsed.repositories[0].manifests] == [
        CHILD_DIGEST,
        INDEX_DIGEST,
    ]


def test_load_binds_canonical_bytes_to_expected_digest(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    payload = canonical_bytes(artifact())
    expected = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    path.write_bytes(payload)

    assert load_inventory_artifact(path, expected_digest=expected).digest == expected

    path.write_bytes(json.dumps(artifact(), indent=2).encode())
    noncanonical = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    with pytest.raises(InvalidInventoryArtifact, match="not canonical"):
        load_inventory_artifact(path, expected_digest=noncanonical)


def test_load_rejects_expected_digest_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_bytes(canonical_bytes(artifact()))
    with pytest.raises(InvalidInventoryArtifact, match="expected digest"):
        load_inventory_artifact(path, expected_digest=ARTIFACT_DIGEST)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["projects"][0].update(logical_bytes=219),
            "logical_bytes does not match",
        ),
        (
            lambda value: value["summary"].update(manifest_count=3),
            "manifest_count does not match",
        ),
        (
            lambda value: value["projects"][0]["descriptors"].pop(),
            "descriptor_count does not match",
        ),
        (
            lambda value: value["repositories"][0]["manifests"][1][
                "references"
            ][0].update(size=100),
            "child descriptor facts do not match",
        ),
    ],
)
def test_rejects_inconsistent_redundant_facts(mutation: object, message: str) -> None:
    value = artifact()
    mutation(value)  # type: ignore[operator]
    with pytest.raises(InvalidInventoryArtifact, match=message):
        parse_inventory_artifact(value, artifact_digest=ARTIFACT_DIGEST)


def test_rejects_repository_without_project_summary() -> None:
    value = artifact()
    value["projects"] = []
    value["summary"]["project_count"] = 0  # type: ignore[index]
    with pytest.raises(InvalidInventoryArtifact, match="match repository projects"):
        parse_inventory_artifact(value, artifact_digest=ARTIFACT_DIGEST)


def test_rejects_project_summary_without_repository() -> None:
    value = artifact()
    value["repositories"] = []
    value["summary"].update(  # type: ignore[union-attr]
        repository_count=0,
        manifest_count=0,
    )
    with pytest.raises(InvalidInventoryArtifact, match="match repository projects"):
        parse_inventory_artifact(value, artifact_digest=ARTIFACT_DIGEST)


def test_rejects_unknown_secret_shaped_field() -> None:
    value = deepcopy(artifact())
    value["database_url"] = "not-retained"
    with pytest.raises(InvalidInventoryArtifact, match="fields are invalid"):
        parse_inventory_artifact(value, artifact_digest=ARTIFACT_DIGEST)


def test_imports_committed_graph_atomically_and_replays_as_noop(
    tmp_path: Path,
) -> None:
    database_url, store = prepared_database(tmp_path)
    parsed = parsed_artifact()

    first = import_inventory(store, parsed)  # type: ignore[arg-type]
    assert first.status == "imported"
    assert first.to_dict() == {
        "descriptor_count": 4,
        "inventory_digest": ARTIFACT_DIGEST,
        "manifest_count": 2,
        "over_limit_project_count": 0,
        "project_count": 1,
        "repository_count": 1,
        "status": "imported",
    }
    assert store.usage(PROJECT_ID).used_bytes == 220
    assert store.usage(PROJECT_ID).reserved_bytes == 0
    assert table_count(database_url, quota_inventory_imports) == 1
    assert table_count(database_url, quota_reservations) == 2
    assert table_count(database_url, quota_reservation_descriptors) == 5
    assert table_count(database_url, quota_manifests) == 2
    assert table_count(database_url, quota_descriptors) == 4
    assert table_count(database_url, quota_reconciliation_claims) == 0
    with create_engine(database_url).connect() as connection:
        rows = connection.execute(
            select(
                quota_descriptors.c.digest,
                quota_descriptors.c.reference_count,
            ).order_by(quota_descriptors.c.digest)
        ).all()
    assert [(row.digest, row.reference_count) for row in rows] == [
        (CHILD_DIGEST, 2),
        (INDEX_DIGEST, 1),
        (CONFIG_DIGEST, 1),
        (LAYER_DIGEST, 1),
    ]

    before = {
        table.name: table_count(database_url, table)
        for table in (
            quota_inventory_imports,
            quota_reservations,
            quota_reservation_descriptors,
            quota_manifests,
            quota_descriptors,
        )
    }
    replay = import_inventory(store, parsed)  # type: ignore[arg-type]
    assert replay.status == "already_imported"
    assert {
        table.name: table_count(database_url, table)
        for table in (
            quota_inventory_imports,
            quota_reservations,
            quota_reservation_descriptors,
            quota_manifests,
            quota_descriptors,
        )
    } == before


def test_rejects_different_baseline_after_commit(tmp_path: Path) -> None:
    _, store = prepared_database(tmp_path)
    parsed = parsed_artifact()
    import_inventory(store, parsed)  # type: ignore[arg-type]

    different = replace(parsed, digest=f"sha256:{'b' * 64}")  # type: ignore[arg-type]
    with pytest.raises(InventoryImportConflict, match="does not match"):
        import_inventory(store, different)


@pytest.mark.parametrize(
    ("include_quota", "include_repository", "message"),
    [
        (False, True, "existing quota"),
        (True, False, "authority"),
    ],
)
def test_requires_existing_quota_and_exact_repository_authority(
    tmp_path: Path,
    include_quota: bool,
    include_repository: bool,
    message: str,
) -> None:
    database_url, store = prepared_database(
        tmp_path,
        include_quota=include_quota,
        include_repository=include_repository,
    )
    with pytest.raises(InventoryImportNotReady, match=message):
        import_inventory(store, parsed_artifact())  # type: ignore[arg-type]
    assert table_count(database_url, quota_inventory_imports) == 0
    assert table_count(database_url, quota_reservations) == 0


def test_rejects_nonempty_ledger_without_marker(tmp_path: Path) -> None:
    database_url, store = prepared_database(tmp_path)
    pending = store.reserve(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        manifest_digest=f"sha256:{'9' * 64}",
        request_id="preexisting",
        descriptors=(Descriptor(f"sha256:{'9' * 64}", 1),),
    )
    assert pending.state == "pending"

    with pytest.raises(InventoryImportConflict, match="not empty"):
        import_inventory(store, parsed_artifact())  # type: ignore[arg-type]
    assert table_count(database_url, quota_inventory_imports) == 0
    assert table_count(database_url, quota_reservations) == 1


def test_rejects_mismatched_repository_owner_and_counter_drift(
    tmp_path: Path,
) -> None:
    owner_url, owner_store = prepared_database(tmp_path, name="owner.sqlite")
    with create_engine(owner_url).begin() as connection:
        connection.execute(
            repository_table.update()
            .where(repository_table.c.id == REPOSITORY_ID)
            .values(project_id="22222222-2222-4222-8222-222222222222")
        )
    with pytest.raises(InventoryImportNotReady, match="authority"):
        import_inventory(owner_store, parsed_artifact())  # type: ignore[arg-type]
    assert table_count(owner_url, quota_inventory_imports) == 0

    drift_url, drift_store = prepared_database(tmp_path, name="drift.sqlite")
    with create_engine(drift_url).begin() as connection:
        connection.execute(
            project_quotas.update()
            .where(project_quotas.c.project_id == PROJECT_ID)
            .values(used_bytes=1)
        )
    with pytest.raises(InventoryImportConflict, match="nonzero quota usage"):
        import_inventory(drift_store, parsed_artifact())  # type: ignore[arg-type]
    assert table_count(drift_url, quota_inventory_imports) == 0


def test_database_failure_rolls_back_marker_and_every_ledger_row(
    tmp_path: Path,
) -> None:
    database_url, store = prepared_database(tmp_path)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_inventory_index BEFORE INSERT ON quota_reservations "
            f"WHEN NEW.manifest_digest = '{INDEX_DIGEST}' "
            "BEGIN SELECT RAISE(ABORT, 'forced import failure'); END"
        )

    with pytest.raises(InventoryImportFailed, match="without a committed marker"):
        import_inventory(store, parsed_artifact())  # type: ignore[arg-type]
    for table in (
        quota_inventory_imports,
        quota_reservations,
        quota_reservation_descriptors,
        quota_manifests,
        quota_descriptors,
    ):
        assert table_count(database_url, table) == 0
    usage = store.usage(PROJECT_ID)
    assert (usage.used_bytes, usage.reserved_bytes) == (0, 0)


def test_import_records_honest_over_limit_usage_and_blocks_new_bytes(
    tmp_path: Path,
) -> None:
    _, store = prepared_database(tmp_path, limit_bytes=10)
    result = import_inventory(store, parsed_artifact())  # type: ignore[arg-type]

    assert result.over_limit_project_count == 1
    usage = store.usage(PROJECT_ID)
    assert (usage.limit_bytes, usage.used_bytes, usage.reserved_bytes) == (10, 220, 0)
    with pytest.raises(QuotaExceeded):
        store.reserve(
            project_id=PROJECT_ID,
            repository_id=REPOSITORY_ID,
            manifest_digest=f"sha256:{'9' * 64}",
            request_id="new-content",
            descriptors=(Descriptor(f"sha256:{'9' * 64}", 1),),
        )


def test_concurrent_exact_import_has_one_writer_and_one_noop(tmp_path: Path) -> None:
    database_url, _ = prepared_database(tmp_path)
    parsed = parsed_artifact()

    def run() -> str:
        return import_inventory(  # type: ignore[arg-type]
            QuotaStore(database_url), parsed
        ).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: run(), range(2)))
    assert statuses == ["already_imported", "imported"]
    assert table_count(database_url, quota_inventory_imports) == 1
    assert table_count(database_url, quota_reservations) == 2


def test_committed_marker_blocks_schema_downgrade(tmp_path: Path) -> None:
    database_url, store = prepared_database(tmp_path)
    import_inventory(store, parsed_artifact())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="cannot downgrade"):
        command.downgrade(migration_config(database_url), "0003_repository_metadata")
    with create_engine(database_url).connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "0004_inventory_import"


def test_cli_requires_environment_only_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "inventory.json"
    path.write_bytes(canonical_bytes(artifact()))
    monkeypatch.delenv("COFFER_DATABASE_URL", raising=False)

    assert main(
        ["--inventory", str(path), "--expected-sha256", ARTIFACT_DIGEST]
    ) == 78
    captured = capsys.readouterr()
    assert "COFFER_DATABASE_URL is required" in captured.err
    assert captured.out == ""


def test_cli_imports_and_emits_only_aggregate_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url, _ = prepared_database(tmp_path)
    path = tmp_path / "inventory.json"
    payload = canonical_bytes(artifact())
    expected = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    path.write_bytes(payload)
    monkeypatch.setenv("COFFER_DATABASE_URL", database_url)

    arguments = ["--inventory", str(path), "--expected-sha256", expected]
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first == {
        "descriptor_count": 4,
        "inventory_digest": expected,
        "manifest_count": 2,
        "over_limit_project_count": 0,
        "project_count": 1,
        "repository_count": 1,
        "status": "imported",
    }
    assert PROJECT_ID not in json.dumps(first)
    assert REPOSITORY_ID not in json.dumps(first)

    assert main(arguments) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "already_imported"


def test_cli_does_not_echo_invalid_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "inventory.json"
    payload = canonical_bytes(artifact())
    expected = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    path.write_bytes(payload)
    secret = "not-a-database-url-with-secret-material"
    monkeypatch.setenv("COFFER_DATABASE_URL", secret)

    assert main(
        ["--inventory", str(path), "--expected-sha256", expected]
    ) == 1
    captured = capsys.readouterr()
    assert "database connection is invalid" in captured.err
    assert secret not in captured.err
    assert captured.out == ""
