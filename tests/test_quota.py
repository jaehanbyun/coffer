from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import logging
from pathlib import Path
import threading

import pytest
from sqlalchemy.exc import OperationalError

from coffer.quota import (
    Descriptor,
    InvalidManifest,
    MAX_DESCRIPTOR_COUNT,
    MAX_LOGICAL_BYTES,
    OCI_IMAGE_INDEX,
    QuotaExceeded,
    QuotaStore,
    _retryable_transaction_error,
    parse_manifest,
)


PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"
REPOSITORY_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REPOSITORY_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def image_manifest(config: Descriptor, layers: tuple[Descriptor, ...]) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": config.digest,
                "size": config.size,
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar",
                    "digest": layer.digest,
                    "size": layer.size,
                }
                for layer in layers
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def reserve_parsed(
    store: QuotaStore,
    parsed: object,
    *,
    project_id: str = PROJECT_A,
    repository_id: str = REPOSITORY_A,
    request_id: str = "req-one",
):
    return store.reserve(
        project_id=project_id,
        repository_id=repository_id,
        manifest_digest=parsed.digest,
        request_id=request_id,
        descriptors=parsed.descriptors,
    )


def test_manifest_parser_is_bounded_and_rejects_conflicting_descriptors() -> None:
    config = Descriptor(digest(b"config"), 6)
    layer = Descriptor(digest(b"layer"), 5)
    parsed = parse_manifest(image_manifest(config, (layer,)))

    assert parsed.descriptors[0].digest.startswith("sha256:")
    assert {item.digest for item in parsed.descriptors} == {
        parsed.digest,
        config.digest,
        layer.digest,
    }

    document = json.loads(image_manifest(config, (layer, layer)))
    document["layers"][1]["size"] = layer.size + 1
    with pytest.raises(InvalidManifest, match="conflicting"):
        parse_manifest(json.dumps(document).encode())


def test_manifest_parser_binds_media_type_shape_and_descriptor_count() -> None:
    config = Descriptor(digest(b"config"), 6)
    layer = Descriptor(digest(b"layer"), 5)
    body = image_manifest(config, (layer,))
    with pytest.raises(InvalidManifest, match="Content-Type"):
        parse_manifest(body, media_type=OCI_IMAGE_INDEX)

    mixed = json.loads(body)
    mixed["manifests"] = [{"digest": digest(b"child"), "size": 10}]
    with pytest.raises(InvalidManifest, match="index fields"):
        parse_manifest(json.dumps(mixed).encode())

    amplified = json.loads(body)
    amplified["layers"] = [amplified["layers"][0]] * (MAX_DESCRIPTOR_COUNT - 1)
    with pytest.raises(InvalidManifest, match="descriptor count"):
        parse_manifest(json.dumps(amplified).encode())


def test_manifest_parser_accepts_optional_media_type_from_content_type() -> None:
    body = json.loads(
        image_manifest(
            Descriptor(digest(b"config"), 6),
            (Descriptor(digest(b"layer"), 5),),
        )
    )
    del body["mediaType"]
    encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()

    parsed = parse_manifest(
        encoded,
        media_type="application/vnd.oci.image.manifest.v1+json; charset=utf-8",
    )

    assert parsed.media_type == "application/vnd.oci.image.manifest.v1+json"
    with pytest.raises(InvalidManifest, match="media type is required"):
        parse_manifest(encoded)
    body["mediaType"] = None
    with pytest.raises(InvalidManifest, match="must be a string"):
        parse_manifest(json.dumps(body).encode(), media_type=parsed.media_type)


def test_logical_sizes_fit_the_signed_sql_integer_boundary(tmp_path: Path) -> None:
    with pytest.raises(InvalidManifest, match="signed 64-bit"):
        Descriptor(digest(b"too-large"), MAX_LOGICAL_BYTES + 1)

    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    with pytest.raises(ValueError, match="signed 64-bit"):
        store.set_limit(PROJECT_A, MAX_LOGICAL_BYTES + 1)
    store.set_limit(PROJECT_A, MAX_LOGICAL_BYTES)

    parsed = parse_manifest(
        image_manifest(
            Descriptor(digest(b"large-config"), MAX_LOGICAL_BYTES // 2 + 1),
            (Descriptor(digest(b"large-layer"), MAX_LOGICAL_BYTES // 2 + 1),),
        )
    )
    with pytest.raises(QuotaExceeded, match="integer bound"):
        reserve_parsed(store, parsed)
    assert store.usage(PROJECT_A).used_bytes == 0
    assert store.usage(PROJECT_A).reserved_bytes == 0


def test_shared_descriptors_charge_once_per_project_and_once_in_another_project(
    tmp_path: Path,
) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    store.set_limit(PROJECT_A, 10_000)
    store.set_limit(PROJECT_B, 10_000)
    shared_config = Descriptor(digest(b"shared-config"), 100)
    shared_layer = Descriptor(digest(b"shared-layer"), 900)
    first = parse_manifest(image_manifest(shared_config, (shared_layer,)))
    second = parse_manifest(image_manifest(shared_config, (shared_layer,)))
    expected = sum(item.size for item in first.descriptors)

    first_reservation = reserve_parsed(store, first)
    store.commit(first_reservation.id)
    assert store.usage(PROJECT_A).used_bytes == expected

    second_reservation = reserve_parsed(
        store,
        second,
        repository_id=REPOSITORY_B,
        request_id="req-two",
    )
    store.commit(second_reservation.id)
    assert store.usage(PROJECT_A).used_bytes == expected

    project_b = reserve_parsed(
        store,
        first,
        project_id=PROJECT_B,
        repository_id=REPOSITORY_B,
        request_id="req-project-b",
    )
    store.commit(project_b.id)
    assert store.usage(PROJECT_B).used_bytes == expected


def test_pending_is_conservative_and_release_reassigns_shared_reservation(
    tmp_path: Path,
) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    store.set_limit(PROJECT_A, 10_000)
    shared = Descriptor(digest(b"shared"), 500)
    first = parse_manifest(
        image_manifest(Descriptor(digest(b"config-a"), 20), (shared,))
    )
    second = parse_manifest(
        image_manifest(Descriptor(digest(b"config-b"), 30), (shared,))
    )
    reservation_a = reserve_parsed(store, first, request_id="req-a")
    reservation_b = reserve_parsed(
        store,
        second,
        repository_id=REPOSITORY_B,
        request_id="req-b",
    )
    before = store.usage(PROJECT_A)
    assert before.used_bytes == 0
    assert before.reserved_bytes == (
        sum(item.size for item in first.descriptors)
        + sum(item.size for item in second.descriptors if item.digest != shared.digest)
    )

    store.mark_release_pending(reservation_a.id)
    assert store.usage(PROJECT_A).reserved_bytes == before.reserved_bytes
    store.reconcile_absent(reservation_a.id)
    expected_second = sum(item.size for item in second.descriptors)
    assert store.usage(PROJECT_A).reserved_bytes == expected_second
    store.commit(reservation_b.id)
    assert store.usage(PROJECT_A).used_bytes == expected_second
    assert store.usage(PROJECT_A).reserved_bytes == 0


def test_retry_is_idempotent_and_committed_release_refunds_only_after_proof(
    tmp_path: Path,
) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    store.set_limit(PROJECT_A, 10_000)
    parsed = parse_manifest(
        image_manifest(Descriptor(digest(b"config"), 20), ())
    )
    first = reserve_parsed(store, parsed, request_id="req-original")
    retry = reserve_parsed(store, parsed, request_id="req-retry")
    assert retry.id == first.id
    assert store.usage(PROJECT_A).reserved_bytes == first.delta_bytes

    store.commit(first.id)
    charged = store.usage(PROJECT_A).used_bytes
    store.mark_release_pending(first.id)
    assert store.usage(PROJECT_A).used_bytes == charged
    store.reconcile_absent(first.id)
    assert store.usage(PROJECT_A).used_bytes == 0


def test_quota_exceeded_rolls_back_reservation(tmp_path: Path) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    parsed = parse_manifest(
        image_manifest(Descriptor(digest(b"config"), 100), ())
    )
    store.set_limit(PROJECT_A, sum(item.size for item in parsed.descriptors) - 1)

    with pytest.raises(QuotaExceeded):
        reserve_parsed(store, parsed)

    usage = store.usage(PROJECT_A)
    assert usage.used_bytes == 0
    assert usage.reserved_bytes == 0


def test_concurrent_admission_never_exceeds_limit(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'quota.sqlite'}"
    setup = QuotaStore(database, bootstrap_schema=True)
    first = parse_manifest(
        image_manifest(Descriptor(digest(b"config-a"), 400), ())
    )
    second = parse_manifest(
        image_manifest(Descriptor(digest(b"config-b"), 400), ())
    )
    limit = max(
        sum(item.size for item in first.descriptors),
        sum(item.size for item in second.descriptors),
    )
    setup.set_limit(PROJECT_A, limit)
    barrier = threading.Barrier(2)

    def admit(parsed: object, repository: str, request_id: str) -> str:
        store = QuotaStore(database, bootstrap_schema=True)
        barrier.wait()
        try:
            reservation = reserve_parsed(
                store,
                parsed,
                repository_id=repository,
                request_id=request_id,
            )
        except QuotaExceeded:
            return "denied"
        store.commit(reservation.id)
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: admit(*args),
                (
                    (first, REPOSITORY_A, "req-a"),
                    (second, REPOSITORY_B, "req-b"),
                ),
            )
        )

    assert sorted(results) == ["committed", "denied"]
    usage = setup.usage(PROJECT_A)
    assert usage.used_bytes <= usage.limit_bytes
    assert usage.reserved_bytes == 0


def test_quota_writes_retry_only_known_transaction_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    original_writer = store._writer
    attempts = 0

    @contextmanager
    def conflicting_writer():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError(
                "quota write",
                {},
                RuntimeError(1213, "deadlock"),
            )
        with original_writer() as connection:
            yield connection

    monkeypatch.setattr(store, "_writer", conflicting_writer)
    with caplog.at_level(logging.WARNING, logger="coffer.quota"):
        usage = store.set_limit(PROJECT_A, 1024)

    assert attempts == 3
    assert usage.limit_bytes == 1024
    records = [
        record
        for record in caplog.records
        if record.message
        == "retrying quota write after database transaction conflict"
    ]
    assert len(records) == 2
    assert [record.quota_retry_attempt for record in records] == [2, 3]
    assert all(record.quota_operation == "limit" for record in records)


def test_quota_writes_do_not_retry_unclassified_database_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    attempts = 0

    @contextmanager
    def unavailable_writer():
        nonlocal attempts
        attempts += 1
        raise OperationalError(
            "quota write",
            {},
            RuntimeError(2006, "server unavailable"),
        )
        yield

    monkeypatch.setattr(store, "_writer", unavailable_writer)
    with pytest.raises(OperationalError):
        store.set_limit(PROJECT_A, 1024)
    assert attempts == 1


def test_quota_write_transaction_retry_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = QuotaStore(
        f"sqlite:///{tmp_path / 'quota.sqlite'}", bootstrap_schema=True
    )
    attempts = 0

    @contextmanager
    def conflicting_writer():
        nonlocal attempts
        attempts += 1
        raise OperationalError(
            "quota write",
            {},
            RuntimeError(1213, "deadlock"),
        )
        yield

    monkeypatch.setattr(store, "_writer", conflicting_writer)
    with pytest.raises(OperationalError):
        store.set_limit(PROJECT_A, 1024)
    assert attempts == 3


def test_retryable_transaction_classifier_covers_supported_sqlstates() -> None:
    class SerializationFailure(RuntimeError):
        sqlstate = "40001"

    assert _retryable_transaction_error(
        OperationalError("quota write", {}, SerializationFailure())
    )
