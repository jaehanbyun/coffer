from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest
from sqlalchemy import event, update

from coffer.db import repositories as repository_table
from coffer.live_inventory_verification import (
    LiveInventoryAuthenticationRequired,
    LiveInventoryVerificationFailed,
    LiveRepositoryTarget,
    verify_live_inventory,
)
from coffer.quota import QuotaStore
from coffer.quota_import import import_inventory
from coffer.quota_import_verification import (
    InventoryRepositoryRoute,
    InventoryVerificationFailed,
    verify_inventory_import_snapshot,
)
from coffer.quota_reconciliation import (
    HTTPDistributionManifestProbe,
    ManifestPresence,
    ProbeObservation,
)
from test_quota_import import (
    ARTIFACT_DIGEST,
    CHILD_DIGEST,
    INDEX_DIGEST,
    PROJECT_ID,
    REPOSITORY_ID,
    parsed_artifact,
    prepared_database,
)
from test_quota_import_verification import IMPORTED_AT


def imported_store(tmp_path: Path) -> QuotaStore:
    _, store = prepared_database(tmp_path)
    import_inventory(
        store,
        parsed_artifact(),  # type: ignore[arg-type]
        imported_at=IMPORTED_AT,
    )
    return store


def test_resolves_routes_with_exact_ledger_in_one_read_only_snapshot(
    tmp_path: Path,
) -> None:
    store = imported_store(tmp_path)
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
        snapshot = verify_inventory_import_snapshot(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )
    finally:
        event.remove(store._engine, "before_cursor_execute", capture_statement)

    assert snapshot.result.status == "verified"
    assert snapshot.repositories == (
        InventoryRepositoryRoute(
            repository_id=REPOSITORY_ID,
            canonical_name=f"p/{PROJECT_ID}/inventory",
            manifest_digests=(CHILD_DIGEST, INDEX_DIGEST),
        ),
    )
    assert not {"DELETE", "INSERT", "UPDATE"}.intersection(statements)


def test_route_resolution_stays_on_snapshot_during_concurrent_rename(
    tmp_path: Path,
) -> None:
    store = imported_store(tmp_path)
    with store._engine.connect() as connection:
        journal_mode = connection.exec_driver_sql(
            "PRAGMA journal_mode = WAL"
        ).scalar_one()
        assert journal_mode == "wal"

    writer_started = False
    writer_done = threading.Event()
    writer_errors: list[BaseException] = []

    def rename_repository() -> None:
        try:
            with store._engine.begin() as connection:
                connection.execute(
                    update(repository_table)
                    .where(repository_table.c.id == REPOSITORY_ID)
                    .values(name="renamed")
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
        threading.Thread(target=rename_repository, daemon=True).start()
        assert writer_done.wait(timeout=5)

    event.listen(store._engine, "after_cursor_execute", start_writer_after_snapshot)
    try:
        snapshot = verify_inventory_import_snapshot(  # type: ignore[arg-type]
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
    assert snapshot.repositories[0].canonical_name.endswith("/inventory")
    later = verify_inventory_import_snapshot(  # type: ignore[arg-type]
        store,
        parsed_artifact(),  # type: ignore[arg-type]
    )
    assert later.repositories[0].canonical_name.endswith("/renamed")


def test_rejects_noncanonical_route_from_control_schema(tmp_path: Path) -> None:
    store = imported_store(tmp_path)
    with store._engine.begin() as connection:
        connection.execute(
            update(repository_table)
            .where(repository_table.c.id == REPOSITORY_ID)
            .values(name="Not-Canonical")
        )

    with pytest.raises(InventoryVerificationFailed, match="does not match"):
        verify_inventory_import_snapshot(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
        )


class FakeAuthenticatedProbe:
    def __init__(
        self,
        observations: dict[str, ManifestPresence | BaseException],
        *,
        prepare_error: BaseException | None = None,
    ) -> None:
        self.observations = observations
        self.prepare_error = prepare_error
        self.prepared: tuple[LiveRepositoryTarget, ...] | None = None
        self.calls: list[tuple[str, str, str]] = []

    def prepare(self, repositories: tuple[LiveRepositoryTarget, ...]) -> None:
        if self.prepare_error is not None:
            raise self.prepare_error
        self.prepared = repositories

    def probe(
        self,
        *,
        repository_id: str,
        repository: str,
        digest: str,
    ) -> ProbeObservation:
        assert self.prepared is not None
        self.calls.append((repository_id, repository, digest))
        observation = self.observations[digest]
        if isinstance(observation, BaseException):
            raise observation
        status = 200 if observation == ManifestPresence.PRESENT else 404
        return ProbeObservation(observation, status)


def test_verifies_every_manifest_with_prepared_authenticated_probe(
    tmp_path: Path,
) -> None:
    store = imported_store(tmp_path)
    probe = FakeAuthenticatedProbe(
        {
            CHILD_DIGEST: ManifestPresence.PRESENT,
            INDEX_DIGEST: ManifestPresence.PRESENT,
        }
    )

    result = verify_live_inventory(  # type: ignore[arg-type]
        store,
        parsed_artifact(),  # type: ignore[arg-type]
        probe,
    )

    assert result.to_dict() == {
        "absent_count": 0,
        "indeterminate_count": 0,
        "inventory_digest": ARTIFACT_DIGEST,
        "manifest_count": 2,
        "present_count": 2,
        "repository_count": 1,
        "status": "verified",
    }
    assert probe.prepared == (
        LiveRepositoryTarget(REPOSITORY_ID, f"p/{PROJECT_ID}/inventory"),
    )
    assert [call[2] for call in probe.calls] == [CHILD_DIGEST, INDEX_DIGEST]
    serialized = json.dumps(result.to_dict())
    assert PROJECT_ID not in serialized
    assert REPOSITORY_ID not in serialized
    assert CHILD_DIGEST not in serialized


@pytest.mark.parametrize(
    ("observation", "absent", "indeterminate"),
    [
        (ManifestPresence.ABSENT, 1, 0),
        (ManifestPresence.INDETERMINATE, 0, 1),
        (RuntimeError("secret-token-value"), 0, 1),
    ],
    ids=("absent", "indeterminate", "probe-exception"),
)
def test_refuses_fixed_secret_safe_result_after_probing_every_manifest(
    tmp_path: Path,
    observation: ManifestPresence | BaseException,
    absent: int,
    indeterminate: int,
) -> None:
    store = imported_store(tmp_path)
    probe = FakeAuthenticatedProbe(
        {
            CHILD_DIGEST: observation,
            INDEX_DIGEST: ManifestPresence.PRESENT,
        }
    )

    with pytest.raises(
        LiveInventoryVerificationFailed,
        match="live Distribution inventory does not match the verified import",
    ) as refused:
        verify_live_inventory(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
            probe,
        )

    assert refused.value.result.absent_count == absent
    assert refused.value.result.indeterminate_count == indeterminate
    assert refused.value.result.present_count == 1
    assert refused.value.result.status == "refused"
    assert len(probe.calls) == 2
    error = str(refused.value)
    for forbidden in (
        "secret-token-value",
        PROJECT_ID,
        REPOSITORY_ID,
        CHILD_DIGEST,
    ):
        assert forbidden not in error


class MalformedPresenceProbe(FakeAuthenticatedProbe):
    def probe(
        self,
        *,
        repository_id: str,
        repository: str,
        digest: str,
    ) -> ProbeObservation:
        assert self.prepared is not None
        self.calls.append((repository_id, repository, digest))
        return ProbeObservation("present", 200)  # type: ignore[arg-type]


def test_malformed_probe_presence_is_indeterminate(tmp_path: Path) -> None:
    store = imported_store(tmp_path)
    probe = MalformedPresenceProbe({})

    with pytest.raises(LiveInventoryVerificationFailed) as refused:
        verify_live_inventory(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
            probe,
        )

    assert refused.value.result.present_count == 0
    assert refused.value.result.indeterminate_count == 2
    assert len(probe.calls) == 2


def test_missing_authentication_fails_before_any_probe(tmp_path: Path) -> None:
    store = imported_store(tmp_path)
    missing = FakeAuthenticatedProbe(
        {},
        prepare_error=LookupError("missing-token-for-repository"),
    )

    with pytest.raises(
        LiveInventoryAuthenticationRequired,
        match="authenticated live Distribution probe is required",
    ):
        verify_live_inventory(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
            missing,
        )
    assert missing.calls == []

    with pytest.raises(LiveInventoryAuthenticationRequired):
        verify_live_inventory(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
            None,
        )


class ProtectedManifestHandler(BaseHTTPRequestHandler):
    token = "fixture-bearer-token"
    manifests = {CHILD_DIGEST, INDEX_DIGEST}
    requests = 0

    def do_HEAD(self) -> None:  # noqa: N802
        type(self).requests += 1
        if self.headers.get("Authorization") != f"Bearer {type(self).token}":
            self.send_response(401)
            self.end_headers()
            return
        prefix = f"/v2/p/{PROJECT_ID}/inventory/manifests/"
        digest = self.path.removeprefix(prefix)
        if not self.path.startswith(prefix) or digest not in type(self).manifests:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Docker-Content-Digest", digest)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class FixtureHTTPAuthenticatedProbe:
    def __init__(self, origin: str, tokens: dict[str, str]) -> None:
        self.origin = origin
        self.tokens = tokens
        self.prepared = False

    def prepare(self, repositories: tuple[LiveRepositoryTarget, ...]) -> None:
        if any(
            repository.repository_id not in self.tokens
            for repository in repositories
        ):
            raise LookupError("fixture token is missing")
        self.prepared = True

    def probe(
        self,
        *,
        repository_id: str,
        repository: str,
        digest: str,
    ) -> ProbeObservation:
        assert self.prepared
        return HTTPDistributionManifestProbe(
            self.origin,
            timeout_seconds=1,
            headers={"Authorization": f"Bearer {self.tokens[repository_id]}"},
        ).probe(repository=repository, digest=digest)


def test_authenticated_http_fixture_and_wrong_token_refusal(tmp_path: Path) -> None:
    store = imported_store(tmp_path)
    ProtectedManifestHandler.requests = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProtectedManifestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        result = verify_live_inventory(  # type: ignore[arg-type]
            store,
            parsed_artifact(),  # type: ignore[arg-type]
            FixtureHTTPAuthenticatedProbe(
                origin,
                {REPOSITORY_ID: ProtectedManifestHandler.token},
            ),
        )
        assert result.present_count == 2
        with pytest.raises(LiveInventoryVerificationFailed) as refused:
            verify_live_inventory(  # type: ignore[arg-type]
                store,
                parsed_artifact(),  # type: ignore[arg-type]
                FixtureHTTPAuthenticatedProbe(
                    origin,
                    {REPOSITORY_ID: "wrong-token-not-printed"},
                ),
            )
        assert refused.value.result.indeterminate_count == 2
        assert "wrong-token-not-printed" not in str(refused.value)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert ProtectedManifestHandler.requests == 4
