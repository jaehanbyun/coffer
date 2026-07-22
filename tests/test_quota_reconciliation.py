from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import threading

import pytest

from coffer.quota import Descriptor, QuotaStore
from coffer.quota_reconciliation import (
    HTTPDistributionManifestProbe,
    ManifestPresence,
    ProbeObservation,
    QuotaReconciler,
)


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY_IDS = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
)
CANONICAL_REPOSITORIES = {
    repository_id: f"p/{PROJECT_ID}/repository-{index}"
    for index, repository_id in enumerate(REPOSITORY_IDS)
}


def digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


class FakeResolver:
    def __init__(self, repositories: dict[str, str] | None = None) -> None:
        self.repositories = (
            repositories if repositories is not None else dict(CANONICAL_REPOSITORIES)
        )

    def resolve(self, *, project_id: str, repository_id: str) -> str | None:
        assert project_id == PROJECT_ID
        return self.repositories.get(repository_id)


class FakeProbe:
    def __init__(
        self,
        observations: dict[str, ManifestPresence],
        *,
        before_return: object | None = None,
    ) -> None:
        self.observations = observations
        self.before_return = before_return
        self.calls: list[tuple[str, str]] = []

    def probe(self, *, repository: str, digest: str) -> ProbeObservation:
        self.calls.append((repository, digest))
        if callable(self.before_return):
            self.before_return()
        return ProbeObservation(self.observations[digest], 200)


def make_store(tmp_path: Path) -> QuotaStore:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    store.set_limit(PROJECT_ID, 10_000)
    return store


def reserve(
    store: QuotaStore,
    index: int,
    *,
    shared: Descriptor | None = None,
) -> object:
    manifest = Descriptor(digest(f"manifest-{index}"), 10)
    descriptors = (manifest,) if shared is None else (manifest, shared)
    return store.reserve(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_IDS[index],
        manifest_digest=manifest.digest,
        request_id=f"req-{index}",
        descriptors=descriptors,
    )


def future() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=5)


def test_candidate_query_is_stale_bounded_and_cursor_deterministic(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    reservations = tuple(reserve(store, index) for index in range(3))

    assert not store.list_reconciliation_candidates(
        stale_before=datetime(2000, 1, 1, tzinfo=UTC), limit=2
    ).candidates
    first = store.list_reconciliation_candidates(stale_before=future(), limit=2)
    second = store.list_reconciliation_candidates(
        stale_before=future(), limit=2, after=first.next_cursor
    )

    assert len(first.candidates) == 2
    assert first.next_cursor is not None
    assert len(second.candidates) == 1
    assert second.next_cursor is None
    assert {candidate.reservation_id for candidate in first.candidates + second.candidates} == {
        reservation.id for reservation in reservations
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        store.list_reconciliation_candidates(
            stale_before=datetime(2026, 1, 1), limit=1
        )
    with pytest.raises(ValueError, match="between 1"):
        store.list_reconciliation_candidates(stale_before=future(), limit=0)


@pytest.mark.parametrize(
    ("presence", "expected_state", "used_bytes", "reserved_bytes"),
    (
        (ManifestPresence.PRESENT, "committed", 10, 0),
        (ManifestPresence.ABSENT, "released", 0, 0),
        (ManifestPresence.INDETERMINATE, "pending", 0, 10),
    ),
)
def test_reconciler_applies_only_exact_present_or_absent(
    tmp_path: Path,
    presence: ManifestPresence,
    expected_state: str,
    used_bytes: int,
    reserved_bytes: int,
) -> None:
    store = make_store(tmp_path)
    reservation = reserve(store, 0)
    original_version = reservation.version
    reconciler = QuotaReconciler(
        store,
        FakeResolver(),
        FakeProbe({reservation.manifest_digest: presence}),
        stale_after=timedelta(0),
    )

    result = reconciler.run_once(now=future())

    current = store.get_reservation(reservation.id)
    assert current.state == expected_state
    assert (current.version == original_version) is (
        presence == ManifestPresence.INDETERMINATE
    )
    assert store.usage(PROJECT_ID).used_bytes == used_bytes
    assert store.usage(PROJECT_ID).reserved_bytes == reserved_bytes
    assert result.scanned == 1
    assert result.present == int(presence == ManifestPresence.PRESENT)
    assert result.absent == int(presence == ManifestPresence.ABSENT)
    assert result.indeterminate == int(presence == ManifestPresence.INDETERMINATE)


def test_missing_repository_is_indeterminate_without_state_change(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    reservation = reserve(store, 0)
    probe = FakeProbe({reservation.manifest_digest: ManifestPresence.PRESENT})
    reconciler = QuotaReconciler(
        store,
        FakeResolver({}),
        probe,
        stale_after=timedelta(0),
    )

    result = reconciler.run_once(now=future())

    assert result.indeterminate == 1
    assert not probe.calls
    assert store.get_reservation(reservation.id) == reservation


def test_duplicate_present_is_idempotent_and_reordered_probe_is_stale(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    reservation = reserve(store, 0)
    present = FakeProbe({reservation.manifest_digest: ManifestPresence.PRESENT})
    reconciler = QuotaReconciler(
        store, FakeResolver(), present, stale_after=timedelta(0)
    )

    assert reconciler.run_once(now=future()).present == 1
    first_usage = store.usage(PROJECT_ID)
    assert reconciler.run_once(now=future() + timedelta(minutes=1)).present == 1
    assert store.usage(PROJECT_ID) == first_usage

    reordered = reserve(store, 1)
    changed = False

    def mutate_candidate() -> None:
        nonlocal changed
        if not changed:
            store.mark_release_pending(reordered.id)
            changed = True

    stale_probe = FakeProbe(
        {
            reservation.manifest_digest: ManifestPresence.INDETERMINATE,
            reordered.manifest_digest: ManifestPresence.PRESENT,
        },
        before_return=mutate_candidate,
    )
    stale_run = QuotaReconciler(
        store, FakeResolver(), stale_probe, stale_after=timedelta(0)
    ).run_once(now=future() + timedelta(minutes=2))
    assert stale_run.stale == 1
    assert store.get_reservation(reordered.id).state == "release_pending"

    recovered = QuotaReconciler(
        store,
        FakeResolver(),
        FakeProbe(
            {
                reservation.manifest_digest: ManifestPresence.INDETERMINATE,
                reordered.manifest_digest: ManifestPresence.PRESENT,
            }
        ),
        stale_after=timedelta(0),
    ).run_once(now=future() + timedelta(minutes=3))
    assert recovered.present == 1
    assert store.get_reservation(reordered.id).state == "committed"


def test_periodic_committed_scan_refunds_deleted_shared_descriptors_once(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    shared = Descriptor(digest("shared"), 100)
    first = reserve(store, 0, shared=shared)
    second = reserve(store, 1, shared=shared)
    store.commit(first.id)
    store.commit(second.id)
    assert store.usage(PROJECT_ID).used_bytes == 120

    probe = FakeProbe(
        {
            first.manifest_digest: ManifestPresence.ABSENT,
            second.manifest_digest: ManifestPresence.PRESENT,
        }
    )
    result = QuotaReconciler(
        store, FakeResolver(), probe, stale_after=timedelta(0)
    ).run_once(now=future())

    assert result.absent == 1
    assert result.present == 1
    assert store.usage(PROJECT_ID).used_bytes == 110
    assert store.reconcile_absent(first.id).state == "released"
    assert store.usage(PROJECT_ID).used_bytes == 110

    second_delete = QuotaReconciler(
        store,
        FakeResolver(),
        FakeProbe({second.manifest_digest: ManifestPresence.ABSENT}),
        stale_after=timedelta(0),
    ).run_once(now=future() + timedelta(minutes=1))
    assert second_delete.absent == 1
    assert store.usage(PROJECT_ID).used_bytes == 0


class ProbeHandler(BaseHTTPRequestHandler):
    response_status = 200
    digest_headers: tuple[str, ...] = ()
    expected_path = ""
    seen_accept = ""

    def do_HEAD(self) -> None:  # noqa: N802
        type(self).seen_accept = self.headers.get("Accept", "")
        if self.path != type(self).expected_path:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(type(self).response_status)
        for value in type(self).digest_headers:
            self.send_header("Docker-Content-Digest", value)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def http_observation(status: int, headers: tuple[str, ...]) -> ProbeObservation:
    manifest_digest = digest("http-manifest")
    ProbeHandler.response_status = status
    ProbeHandler.digest_headers = headers
    ProbeHandler.expected_path = (
        f"/v2/p/{PROJECT_ID}/repository-0/manifests/{manifest_digest}"
    )
    ProbeHandler.seen_accept = ""
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = HTTPDistributionManifestProbe(
            f"http://127.0.0.1:{server.server_port}", timeout_seconds=1
        ).probe(
            repository=CANONICAL_REPOSITORIES[REPOSITORY_IDS[0]],
            digest=manifest_digest,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert "application/vnd.oci.image.manifest.v1+json" in ProbeHandler.seen_accept
    return result


def test_http_probe_requires_one_matching_content_digest() -> None:
    manifest_digest = digest("http-manifest")

    assert http_observation(200, (manifest_digest,)).presence == (
        ManifestPresence.PRESENT
    )
    assert http_observation(200, ()).presence == ManifestPresence.INDETERMINATE
    assert http_observation(200, (digest("wrong"),)).presence == (
        ManifestPresence.INDETERMINATE
    )
    assert http_observation(200, (manifest_digest, manifest_digest)).presence == (
        ManifestPresence.INDETERMINATE
    )


@pytest.mark.parametrize("status", (401, 403, 500, 503))
def test_http_probe_treats_authorization_and_dependency_failures_as_indeterminate(
    status: int,
) -> None:
    observation = http_observation(status, ())

    assert observation.presence == ManifestPresence.INDETERMINATE
    assert observation.status_code == status


def test_http_probe_treats_exact_404_as_absent_and_transport_as_indeterminate() -> None:
    assert http_observation(404, ()).presence == ManifestPresence.ABSENT

    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        unused_port = temporary.getsockname()[1]
    transport = HTTPDistributionManifestProbe(
        f"http://127.0.0.1:{unused_port}", timeout_seconds=0.2
    ).probe(
        repository=CANONICAL_REPOSITORIES[REPOSITORY_IDS[0]],
        digest=digest("transport"),
    )
    assert transport == ProbeObservation(ManifestPresence.INDETERMINATE, None)
