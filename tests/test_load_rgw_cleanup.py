from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_DIRECTORY = ROOT / "poc" / "load-soak" / "collector"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


CLEANUP = load_module(
    "coffer_load_rgw_cleanup_tests",
    COLLECTOR_DIRECTORY / "rgw_cleanup.py",
)
ADAPTER_TESTS = load_module(
    "coffer_load_rgw_cleanup_adapter_fixtures",
    ROOT / "tests" / "test_load_rgw_live_adapter.py",
)


def page(value: str) -> str:
    return "sha256:" + value * 64


def empty_inventory(
    pages: tuple[str, ...] = (page("a"), page("b"), page("c")),
) -> CLEANUP.CleanupInventory:
    return CLEANUP.CleanupInventory(
        current_keys=(),
        delete_markers=(),
        multipart_uploads=(),
        page_sha256=pages,
        versions=(),
    )


def populated(prefix: str) -> CLEANUP.CleanupInventory:
    return CLEANUP.CleanupInventory(
        current_keys=(f"{prefix}/current", f"{prefix}/versioned"),
        delete_markers=((f"{prefix}/deleted", "marker-1"),),
        multipart_uploads=((f"{prefix}/upload", "upload-1"),),
        page_sha256=(page("1"), page("2"), page("3")),
        versions=((f"{prefix}/versioned", "version-1"),),
    )


class FakeCleanupClient:
    def __init__(
        self,
        inventories: list[CLEANUP.CleanupInventory],
    ) -> None:
        self.inventories = list(inventories)
        self.scans: list[tuple[int, str]] = []
        self.removed: list[CLEANUP.CleanupInventory] = []

    def scan(self, *, max_pages: int, prefix: str):
        self.scans.append((max_pages, prefix))
        return self.inventories.pop(0)

    def remove(self, inventory: CLEANUP.CleanupInventory) -> None:
        self.removed.append(inventory)


def values(
    tmp_path: Path,
    *,
    phase: str = "before",
) -> tuple[Path, dict]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    ADAPTER_TESTS.owner_bytes(ca_path, b"bounded test CA\n")
    return ca_path, ADAPTER_TESTS.config(ca_path, phase=phase)


def clocks(*values: float):
    return iter(values).__next__


def test_cleanup_removes_exact_inventory_and_proves_zero(
    tmp_path: Path,
) -> None:
    _, config = values(tmp_path)
    before = populated(config["probe_prefix"])
    client = FakeCleanupClient([before, empty_inventory()])

    result = CLEANUP.cleanup(
        config,
        client=client,
        clock=clocks(200, 900),
    )

    assert result["schema"] == CLEANUP.RESULT_SCHEMA
    assert result["synthetic"] is False
    assert result["execution_source"] == "pilot"
    assert result["observed_before"] == {
        "current_objects": 2,
        "delete_markers": 1,
        "multipart_uploads": 1,
        "versions": 1,
    }
    assert result["remaining"] == {
        "current_objects": 0,
        "delete_markers": 0,
        "multipart_uploads": 0,
        "versions": 0,
    }
    assert client.removed == [before]
    assert client.scans == [
        (10, "coffer-evidence/before"),
        (10, "coffer-evidence/before"),
    ]
    retained = json.dumps(result, sort_keys=True)
    for forbidden in (
        "/current",
        "/versioned",
        "marker-1",
        "upload-1",
        "coffer-evidence",
        "coffer-registry-stage6",
        "rgw.stage6.test",
    ):
        assert forbidden not in retained


def test_remaining_state_fails_closed(tmp_path: Path) -> None:
    _, config = values(tmp_path)
    before = populated(config["probe_prefix"])
    client = FakeCleanupClient([before, before])

    with pytest.raises(
        CLEANUP.RgwCleanupError,
        match="incomplete",
    ):
        CLEANUP.cleanup(
            config,
            client=client,
            clock=clocks(200, 900),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "cleanup-hash",
        "source-hash",
        "phase",
        "remaining",
        "page-hash",
        "window",
    ],
)
def test_retained_cleanup_result_is_revalidated(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, config = values(tmp_path)
    result = CLEANUP.cleanup(
        config,
        client=FakeCleanupClient(
            [populated(config["probe_prefix"]), empty_inventory()]
        ),
        clock=clocks(200, 900),
    )
    if mutation == "cleanup-hash":
        result["cleanup_sha256"] = page("0")
    elif mutation == "source-hash":
        result["cleanup_source_sha256"] = page("0")
    elif mutation == "phase":
        result["phase"] = "during"
    elif mutation == "remaining":
        result["remaining"]["current_objects"] = 1
    elif mutation == "page-hash":
        result["page_set_sha256"] = "invalid"
    else:
        result["completed_at_seconds"] = 1001
    with pytest.raises(
        (
            CLEANUP.RgwCleanupError,
            CLEANUP.rgw_live_adapter.RgwLiveAdapterError,
        )
    ):
        CLEANUP.validate_result(result, config_value=config)


def test_retained_cleanup_result_round_trips(tmp_path: Path) -> None:
    _, config = values(tmp_path)
    result = CLEANUP.cleanup(
        config,
        client=FakeCleanupClient(
            [populated(config["probe_prefix"]), empty_inventory()]
        ),
        clock=clocks(200, 900),
    )

    assert CLEANUP.validate_result(result, config_value=config) == result


@pytest.mark.parametrize(
    "mutation",
    [
        "current-prefix",
        "version-prefix",
        "marker-prefix",
        "upload-prefix",
        "duplicate-current",
        "duplicate-page",
        "missing-pages",
        "excess-pages",
    ],
)
def test_inventory_scope_and_completeness_are_strict(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, config = values(tmp_path)
    inventory = populated(config["probe_prefix"])
    if mutation == "current-prefix":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "current_keys": ("other/object",),
            }
        )
    elif mutation == "version-prefix":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "versions": (("other/object", "version"),),
            }
        )
    elif mutation == "marker-prefix":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "delete_markers": (("other/object", "marker"),),
            }
        )
    elif mutation == "upload-prefix":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "multipart_uploads": (("other/object", "upload"),),
            }
        )
    elif mutation == "duplicate-current":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "current_keys": (
                    f"{config['probe_prefix']}/same",
                    f"{config['probe_prefix']}/same",
                ),
            }
        )
    elif mutation == "duplicate-page":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "page_sha256": (page("1"), page("1"), page("3")),
            }
        )
    elif mutation == "missing-pages":
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "page_sha256": (page("1"), page("2")),
            }
        )
    else:
        inventory = CLEANUP.CleanupInventory(
            **{
                **inventory.__dict__,
                "page_sha256": tuple(
                    "sha256:" + f"{index:064x}"
                    for index in range(31)
                ),
            }
        )
    client = FakeCleanupClient([inventory, empty_inventory()])

    with pytest.raises(CLEANUP.RgwCleanupError):
        CLEANUP.cleanup(
            config,
            client=client,
            clock=clocks(200, 900),
        )


def test_cleanup_stays_inside_phase_window(tmp_path: Path) -> None:
    _, config = values(tmp_path)
    client = FakeCleanupClient(
        [empty_inventory(), empty_inventory()]
    )

    with pytest.raises(
        CLEANUP.rgw_live_adapter.RgwLiveAdapterError,
        match="escaped",
    ):
        CLEANUP.cleanup(
            config,
            client=client,
            clock=clocks(99, 900),
        )


class LowLevelClient:
    def __init__(self) -> None:
        self.current: list[dict[str, Any]] = []
        self.versions: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_errors: list[dict[str, Any]] = []

    @staticmethod
    def _pop(values: list[dict[str, Any]]) -> dict[str, Any]:
        assert values
        return values.pop(0)

    def list_objects_v2(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(("list_objects_v2", arguments))
        return self._pop(self.current)

    def list_object_versions(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(("list_object_versions", arguments))
        return self._pop(self.versions)

    def list_multipart_uploads(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(("list_multipart_uploads", arguments))
        return self._pop(self.uploads)

    def abort_multipart_upload(self, **arguments: Any) -> None:
        self.calls.append(("abort_multipart_upload", arguments))

    def delete_objects(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(("delete_objects", arguments))
        return {"Errors": list(self.delete_errors)}


def low_level() -> LowLevelClient:
    client = LowLevelClient()
    client.current = [
        {
            "Contents": [{"Key": "probe/before/current"}],
            "IsTruncated": True,
            "NextContinuationToken": "current-next",
        },
        {
            "Contents": [],
            "IsTruncated": False,
        },
    ]
    client.versions = [
        {
            "Versions": [
                {
                    "Key": "probe/before/versioned",
                    "VersionId": "version-1",
                }
            ],
            "DeleteMarkers": [
                {
                    "Key": "probe/before/deleted",
                    "VersionId": "marker-1",
                }
            ],
            "IsTruncated": True,
            "NextKeyMarker": "version-next",
            "NextVersionIdMarker": "version-id-next",
        },
        {
            "Versions": [],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]
    client.uploads = [
        {
            "Uploads": [
                {
                    "Key": "probe/before/upload",
                    "UploadId": "upload-1",
                }
            ],
            "IsTruncated": True,
            "NextKeyMarker": "upload-next",
            "NextUploadIdMarker": "upload-id-next",
        },
        {
            "Uploads": [],
            "IsTruncated": False,
        },
    ]
    return client


def test_boto_client_scans_all_three_paginated_surfaces() -> None:
    low = low_level()
    client = CLEANUP.Boto3CleanupClient(
        client=low,
        bucket="bucket",
    )

    inventory = client.scan(max_pages=2, prefix="probe/before")

    assert inventory.current_keys == ("probe/before/current",)
    assert inventory.versions == (
        ("probe/before/versioned", "version-1"),
    )
    assert inventory.delete_markers == (
        ("probe/before/deleted", "marker-1"),
    )
    assert inventory.multipart_uploads == (
        ("probe/before/upload", "upload-1"),
    )
    assert len(inventory.page_sha256) == 6
    assert len(set(inventory.page_sha256)) == 6
    assert low.calls[1][1]["ContinuationToken"] == "current-next"
    assert low.calls[3][1] == {
        "Bucket": "bucket",
        "KeyMarker": "version-next",
        "MaxKeys": 1000,
        "Prefix": "probe/before/",
        "VersionIdMarker": "version-id-next",
    }
    assert low.calls[5][1]["UploadIdMarker"] == "upload-id-next"


@pytest.mark.parametrize(
    ("surface", "response"),
    [
        (
            "current",
            {
                "Contents": [{"Key": "other/object"}],
                "IsTruncated": False,
            },
        ),
        (
            "versions",
            {
                "Versions": [
                    {"Key": "other/object", "VersionId": "version"}
                ],
                "DeleteMarkers": [],
                "IsTruncated": False,
            },
        ),
        (
            "uploads",
            {
                "Uploads": [
                    {"Key": "other/object", "UploadId": "upload"}
                ],
                "IsTruncated": False,
            },
        ),
    ],
)
def test_boto_scan_rejects_server_prefix_escape(
    surface: str,
    response: dict[str, Any],
) -> None:
    low = low_level()
    setattr(low, surface, [response])
    client = CLEANUP.Boto3CleanupClient(
        client=low,
        bucket="bucket",
    )

    with pytest.raises(CLEANUP.RgwCleanupError, match="prefix"):
        client.scan(max_pages=2, prefix="probe/before")


@pytest.mark.parametrize("surface", ["current", "versions", "uploads"])
def test_boto_scan_rejects_incomplete_cursor(surface: str) -> None:
    low = low_level()
    if surface == "current":
        low.current = [{"Contents": [], "IsTruncated": True}]
    elif surface == "versions":
        low.current = [{"Contents": [], "IsTruncated": False}]
        low.versions = [
            {
                "Versions": [],
                "DeleteMarkers": [],
                "IsTruncated": True,
            }
        ]
    else:
        low.current = [{"Contents": [], "IsTruncated": False}]
        low.versions = [
            {
                "Versions": [],
                "DeleteMarkers": [],
                "IsTruncated": False,
            }
        ]
        low.uploads = [{"Uploads": [], "IsTruncated": True}]
    client = CLEANUP.Boto3CleanupClient(
        client=low,
        bucket="bucket",
    )

    with pytest.raises(CLEANUP.RgwCleanupError, match="cursor"):
        client.scan(max_pages=2, prefix="probe/before")


def test_boto_remove_aborts_uploads_and_deletes_exact_identities() -> None:
    low = LowLevelClient()
    client = CLEANUP.Boto3CleanupClient(
        client=low,
        bucket="bucket",
    )
    inventory = CLEANUP.CleanupInventory(
        current_keys=(
            "probe/before/current",
            "probe/before/versioned",
        ),
        delete_markers=(("probe/before/deleted", "marker-1"),),
        multipart_uploads=(("probe/before/upload", "upload-1"),),
        page_sha256=(page("1"), page("2"), page("3")),
        versions=(("probe/before/versioned", "version-1"),),
    )

    client.remove(inventory)

    assert low.calls[0] == (
        "abort_multipart_upload",
        {
            "Bucket": "bucket",
            "Key": "probe/before/upload",
            "UploadId": "upload-1",
        },
    )
    assert low.calls[1] == (
        "delete_objects",
        {
            "Bucket": "bucket",
            "Delete": {
                "Objects": [
                    {
                        "Key": "probe/before/versioned",
                        "VersionId": "version-1",
                    },
                    {
                        "Key": "probe/before/deleted",
                        "VersionId": "marker-1",
                    },
                    {"Key": "probe/before/current"},
                ],
                "Quiet": True,
            },
        },
    )


def test_boto_remove_rejects_partial_delete() -> None:
    low = LowLevelClient()
    low.delete_errors = [{"Code": "AccessDenied"}]
    client = CLEANUP.Boto3CleanupClient(
        client=low,
        bucket="bucket",
    )
    inventory = CLEANUP.CleanupInventory(
        current_keys=("probe/before/current",),
        delete_markers=(),
        multipart_uploads=(),
        page_sha256=(page("1"), page("2"), page("3")),
        versions=(),
    )

    with pytest.raises(CLEANUP.RgwCleanupError, match="deletion"):
        client.remove(inventory)


def test_owner_only_file_composition_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, config = values(tmp_path)
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "cleanup.json"
    ADAPTER_TESTS.owner_document(config_path, config)
    client = FakeCleanupClient(
        [populated(config["probe_prefix"]), empty_inventory()]
    )

    result = CLEANUP.cleanup_file(
        config_path,
        output_path,
        client=client,
        clock=clocks(200, 900),
    )

    assert json.loads(output_path.read_bytes()) == result
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert output_path.stat().st_nlink == 1
    assert CLEANUP.main(["source-hash"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["schema"] == (
        CLEANUP.SOURCE_RESULT_SCHEMA
    )
    assert CLEANUP.main([]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "rgw-cleanup-refused\n"


def test_file_output_refuses_alias_and_unsafe_mode(
    tmp_path: Path,
) -> None:
    _, config = values(tmp_path)
    config_path = tmp_path / "config.json"
    ADAPTER_TESTS.owner_document(config_path, config)
    client = FakeCleanupClient(
        [empty_inventory(), empty_inventory()]
    )

    with pytest.raises(CLEANUP.RgwCleanupError):
        CLEANUP.cleanup_file(
            config_path,
            config_path,
            client=client,
            clock=clocks(200, 900),
        )

    config_path.chmod(0o644)
    with pytest.raises(CLEANUP.RgwCleanupError):
        CLEANUP.cleanup_file(
            config_path,
            tmp_path / "result.json",
            client=client,
            clock=clocks(200, 900),
        )
