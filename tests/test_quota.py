from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading

import pytest

from coffer.quota import (
    Descriptor,
    InvalidManifest,
    MAX_DESCRIPTOR_COUNT,
    MAX_LOGICAL_BYTES,
    OCI_IMAGE_INDEX,
    QuotaExceeded,
    QuotaStore,
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


def test_logical_sizes_fit_the_signed_sql_integer_boundary(tmp_path: Path) -> None:
    with pytest.raises(InvalidManifest, match="signed 64-bit"):
        Descriptor(digest(b"too-large"), MAX_LOGICAL_BYTES + 1)

    store = QuotaStore(f"sqlite:///{tmp_path / 'quota.sqlite'}")
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
    store = QuotaStore(f"sqlite:///{tmp_path / 'quota.sqlite'}")
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
    store = QuotaStore(f"sqlite:///{tmp_path / 'quota.sqlite'}")
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
    store = QuotaStore(f"sqlite:///{tmp_path / 'quota.sqlite'}")
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
    store = QuotaStore(f"sqlite:///{tmp_path / 'quota.sqlite'}")
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
    setup = QuotaStore(database)
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
        store = QuotaStore(database)
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
