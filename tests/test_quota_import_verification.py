from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import threading
import uuid

import pytest
from sqlalchemy import event, insert, select, update

from coffer.db import repositories as repository_table
from coffer.quota import (
    project_quotas,
    quota_descriptors,
    quota_inventory_imports,
    quota_manifests,
    quota_reconciliation_claims,
    quota_reservation_descriptors,
    quota_reservations,
)
from coffer.quota_import import import_inventory, load_inventory_artifact
from coffer.quota_import_verification import (
    InventoryVerificationFailed,
    main,
    verify_inventory_import,
)
from test_quota_import import (
    ARTIFACT_DIGEST,
    CHILD_DIGEST,
    PROJECT_ID,
    REPOSITORY_ID,
    artifact,
    canonical_bytes,
    parsed_artifact,
    prepared_database,
)


IMPORTED_AT = datetime(2026, 7, 23, 1, 2, 3, tzinfo=UTC)
OTHER_PROJECT_ID = "22222222-2222-4222-8222-222222222222"
OTHER_REPOSITORY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def imported_store(tmp_path: Path) -> tuple[str, object]:
    database_url, store = prepared_database(tmp_path)
    import_inventory(
        store,
        parsed_artifact(),  # type: ignore[arg-type]
        imported_at=IMPORTED_AT,
    )
    return database_url, store


def test_verifies_complete_imported_ledger_without_dml(tmp_path: Path) -> None:
    _, store = imported_store(tmp_path)
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(store._engine, "before_cursor_execute", capture_statement)
    try:
        result = verify_inventory_import(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )
    finally:
        event.remove(store._engine, "before_cursor_execute", capture_statement)

    assert result.to_dict() == {
        "descriptor_count": 4,
        "inventory_digest": ARTIFACT_DIGEST,
        "manifest_count": 2,
        "over_limit_project_count": 0,
        "project_count": 1,
        "repository_count": 1,
        "reservation_descriptor_count": 5,
        "status": "verified",
    }
    assert not {"DELETE", "INSERT", "UPDATE"}.intersection(statements)


def test_marker_replay_is_not_ledger_verification(tmp_path: Path) -> None:
    _, store = imported_store(tmp_path)
    with store._engine.begin() as connection:
        connection.execute(
            update(quota_manifests)
            .where(quota_manifests.c.digest == CHILD_DIGEST)
            .values(state="released")
        )

    replay = import_inventory(  # type: ignore[arg-type]
        store,
        parsed_artifact(),  # type: ignore[arg-type]
    )
    assert replay.status == "already_imported"
    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )


def test_uses_one_snapshot_during_concurrent_ledger_change(tmp_path: Path) -> None:
    _, store = imported_store(tmp_path)
    with store._engine.connect() as connection:
        journal_mode = connection.exec_driver_sql(
            "PRAGMA journal_mode = WAL"
        ).scalar_one()
        assert journal_mode == "wal"

    writer_started = False
    writer_done = threading.Event()
    writer_errors: list[BaseException] = []

    def mutate_manifest() -> None:
        try:
            with store._engine.begin() as connection:
                connection.execute(
                    update(quota_manifests)
                    .where(quota_manifests.c.digest == CHILD_DIGEST)
                    .values(state="released")
                )
        except BaseException as exc:  # pragma: no cover - surfaced below
            writer_errors.append(exc)
        finally:
            writer_done.set()

    def start_writer_after_snapshot(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal writer_started
        if writer_started or "FROM quota_inventory_imports" not in statement:
            return
        writer_started = True
        threading.Thread(target=mutate_manifest, daemon=True).start()
        assert writer_done.wait(timeout=5)

    event.listen(store._engine, "after_cursor_execute", start_writer_after_snapshot)
    try:
        result = verify_inventory_import(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )
    finally:
        event.remove(
            store._engine,
            "after_cursor_execute",
            start_writer_after_snapshot,
        )

    assert writer_started
    assert writer_errors == []
    assert result.status == "verified"
    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "statement",
    [
        update(quota_inventory_imports).values(manifest_count=3),
        update(repository_table)
        .where(repository_table.c.id == REPOSITORY_ID)
        .values(project_id=OTHER_PROJECT_ID),
        update(project_quotas)
        .where(project_quotas.c.project_id == PROJECT_ID)
        .values(used_bytes=219),
        update(quota_reservations).values(version=2),
        update(quota_reservations).values(
            updated_at=IMPORTED_AT + timedelta(seconds=1)
        ),
        update(quota_reservation_descriptors).values(size=999),
        update(quota_manifests).values(state="released"),
        update(quota_descriptors).values(reference_count=99),
    ],
    ids=(
        "marker",
        "authority",
        "quota",
        "reservation",
        "timestamp",
        "graph",
        "manifest",
        "descriptor",
    ),
)
def test_rejects_each_imported_state_drift(tmp_path: Path, statement: object) -> None:
    _, store = imported_store(tmp_path)
    with store._engine.begin() as connection:
        connection.execute(statement)  # type: ignore[arg-type]

    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )


def test_rejects_claim_and_extra_ledger_state(tmp_path: Path) -> None:
    _, claim_store = imported_store(tmp_path)
    with claim_store._engine.begin() as connection:
        reservation_id = connection.execute(
            select(quota_reservations.c.id).limit(1)
        ).scalar_one()
        connection.execute(
            insert(quota_reconciliation_claims).values(
                reservation_id=reservation_id,
                claim_token=str(uuid.uuid4()),
                worker_id="verification-test",
                claimed_at=IMPORTED_AT,
                expires_at=IMPORTED_AT + timedelta(seconds=30),
            )
        )
    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import(  # type: ignore[arg-type]
            claim_store,
            parsed_artifact(),  # type: ignore[arg-type]
        )

    extra_path = tmp_path / "extra"
    extra_path.mkdir()
    _, extra_store = imported_store(extra_path)
    with extra_store._engine.begin() as connection:
        connection.execute(
            insert(quota_reservations).values(
                id=str(uuid.uuid4()),
                project_id=PROJECT_ID,
                repository_id=REPOSITORY_ID,
                manifest_digest=f"sha256:{'9' * 64}",
                request_id="unexpected-ledger-row",
                state="pending",
                version=1,
                delta_bytes=0,
                created_at=IMPORTED_AT,
                updated_at=IMPORTED_AT,
            )
        )
    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import(  # type: ignore[arg-type]
            extra_store,
            parsed_artifact(),  # type: ignore[arg-type]
        )


def test_allows_unrelated_empty_control_authority_only(tmp_path: Path) -> None:
    _, store = imported_store(tmp_path)
    with store._engine.begin() as connection:
        connection.execute(
            insert(project_quotas).values(
                project_id=OTHER_PROJECT_ID,
                limit_bytes=100,
                used_bytes=0,
                reserved_bytes=0,
                updated_at=IMPORTED_AT,
            )
        )
        connection.execute(
            insert(repository_table).values(
                id=OTHER_REPOSITORY_ID,
                project_id=OTHER_PROJECT_ID,
                name="empty-control-repository",
                immutable_tags=False,
                created_at=IMPORTED_AT,
            )
        )
    result = verify_inventory_import(  # type: ignore[arg-type]
        store,
        parsed_artifact(),  # type: ignore[arg-type]
    )
    assert result.status == "verified"

    with store._engine.begin() as connection:
        connection.execute(
            update(project_quotas)
            .where(project_quotas.c.project_id == OTHER_PROJECT_ID)
            .values(used_bytes=1)
        )
    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )


def test_cli_emits_only_aggregate_evidence_and_fixed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url, store = prepared_database(tmp_path)
    path = tmp_path / "inventory.json"
    payload = canonical_bytes(artifact())
    expected = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    path.write_bytes(payload)
    parsed = load_inventory_artifact(path, expected_digest=expected)
    import_inventory(store, parsed, imported_at=IMPORTED_AT)
    monkeypatch.setenv("COFFER_DATABASE_URL", database_url)
    arguments = ["--inventory", str(path), "--expected-sha256", expected]
    capsys.readouterr()

    assert main(arguments) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["status"] == "verified"
    assert result["reservation_descriptor_count"] == 5
    serialized = json.dumps(result)
    assert PROJECT_ID not in serialized
    assert REPOSITORY_ID not in serialized
    assert CHILD_DIGEST not in serialized
    assert output.err == ""

    with store._engine.begin() as connection:
        connection.execute(update(quota_descriptors).values(reference_count=99))
    assert main(arguments) == 1
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err.strip() == (
        "inventory verification failed: imported quota ledger does not match "
        "the verified inventory"
    )
    for forbidden in (database_url, PROJECT_ID, REPOSITORY_ID, CHILD_DIGEST):
        assert forbidden not in refused.err


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
    assert captured.out == ""
    assert "COFFER_DATABASE_URL is required" in captured.err
