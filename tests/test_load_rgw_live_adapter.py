from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "rgw_live_adapter.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


ADAPTER = load_module("coffer_load_rgw_live_adapter_tests", ADAPTER_PATH)
RGW = ADAPTER.rgw_artifacts
TARGET_SHA256 = f"sha256:{'1' * 64}"
WINDOW_SHA256 = f"sha256:{'2' * 64}"
RGW_CONFIG_SHA256 = f"sha256:{'3' * 64}"
BUCKET_SCOPE_SHA256 = f"sha256:{'4' * 64}"
KMS_POLICY_SHA256 = f"sha256:{'5' * 64}"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def owner_document(path: Path, value: object) -> None:
    owner_bytes(path, canonical(value))


def step_plan(phase: str) -> list[dict[str, str]]:
    steps = [
        {
            "fault_evidence_sha256": ADAPTER.NO_FAULT_SHA256,
            "operation": operation,
            "result": "success",
        }
        for operation in ADAPTER.HEALTHY_OPERATION_ORDER
    ]
    if phase == "during":
        steps.extend(
            [
                {
                    "fault_evidence_sha256": f"sha256:{'a' * 64}",
                    "operation": "put_zero",
                    "result": "expected_wrong_key",
                },
                {
                    "fault_evidence_sha256": ADAPTER.NO_FAULT_SHA256,
                    "operation": "put_zero",
                    "result": "success",
                },
                {
                    "fault_evidence_sha256": f"sha256:{'b' * 64}",
                    "operation": "put_positive",
                    "result": "expected_kms_outage",
                },
                {
                    "fault_evidence_sha256": ADAPTER.NO_FAULT_SHA256,
                    "operation": "put_positive",
                    "result": "success",
                },
            ]
        )
    return steps


def config(ca_path: Path, *, phase: str = "before") -> dict:
    steps = step_plan(phase)
    counts = {
        operation: sum(step["operation"] == operation for step in steps)
        for operation in RGW.OPERATION_CLASSES
    }
    return {
        "adapter_source_sha256": ADAPTER.adapter_source_sha256(),
        "bucket": "coffer-registry-stage6",
        "bucket_scope_sha256": BUCKET_SCOPE_SHA256,
        "ca_file": str(ca_path),
        "ca_file_sha256": payload_hash(ca_path.read_bytes()),
        "endpoint": "https://rgw.stage6.test:8443",
        "expected_operation_counts": counts,
        "kms_policy_sha256": KMS_POLICY_SHA256,
        "max_pages": 10,
        "multipart_source_sha256": ADAPTER.adapter_source_sha256(),
        "phase": phase,
        "probe_prefix": f"coffer-evidence/{phase}",
        "probe_source_sha256": ADAPTER.adapter_source_sha256(),
        "region": "us-east-1",
        "rgw_config_sha256": RGW_CONFIG_SHA256,
        "schema": ADAPTER.CONFIG_SCHEMA,
        "steps": steps,
        "target_sha256": TARGET_SHA256,
        "timeout_seconds": 5,
        "window_completed_at_seconds": 1000,
        "window_sha256": WINDOW_SHA256,
        "window_started_at_seconds": 100,
    }


class FakeClient:
    def __init__(
        self,
        *,
        override: dict[tuple[str, str], str] | None = None,
        page_hashes: list[str] | None = None,
        uploads: int = 0,
    ) -> None:
        self.override = override or {}
        self.page_hashes = (
            [f"sha256:{'6' * 64}"]
            if page_hashes is None
            else page_hashes
        )
        self.uploads = uploads
        self.calls: list[tuple[str, str]] = []
        self.page_bounds: list[int] = []

    def execute(self, operation: str, expected_result: str) -> str:
        self.calls.append((operation, expected_result))
        return self.override.get(
            (operation, expected_result),
            expected_result,
        )

    def list_multipart(self, *, max_pages: int):
        self.page_bounds.append(max_pages)
        return list(self.page_hashes), self.uploads


def times(values: list[float]):
    return iter(values).__next__


def collected(
    config_value: dict,
    *,
    client: FakeClient | None = None,
) -> tuple[list[dict], dict]:
    chosen = client or FakeClient()
    steps = [
        ADAPTER.collect_step(
            config_value,
            index,
            client=chosen,
            clock=times([200 + index * 10, 201 + index * 10]),
        )
        for index in range(len(config_value["steps"]))
    ]
    multipart = ADAPTER.collect_multipart(
        config_value,
        client=chosen,
        clock=times([900, 901]),
    )
    return steps, multipart


@pytest.mark.parametrize("phase", ADAPTER.native_target.PHASES)
def test_produces_exact_rgw_collector_inputs(
    tmp_path: Path,
    phase: str,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path, phase=phase)
    steps, multipart = collected(config_value)

    probe = ADAPTER.compile_probe(config_value, steps)

    expected_faults = {
        result: sum(
            step["result"] == result for step in config_value["steps"]
        )
        for result in RGW.FAULT_CLASSES
    }
    rgw_config = {
        "bucket_scope_sha256": BUCKET_SCOPE_SHA256,
        "collector_source_sha256": RGW.collector_source_sha256(),
        "expected_fault_counts": expected_faults,
        "expected_operation_counts": config_value[
            "expected_operation_counts"
        ],
        "kms_policy_sha256": KMS_POLICY_SHA256,
        "multipart_source_sha256": ADAPTER.adapter_source_sha256(),
        "phase": phase,
        "probe_source_sha256": ADAPTER.adapter_source_sha256(),
        "rgw_config_sha256": RGW_CONFIG_SHA256,
        "schema": RGW.CONFIG_SCHEMA,
        "target_file": "/owner/target.json",
        "target_file_sha256": f"sha256:{'7' * 64}",
        "window_completed_at_seconds": 1000,
        "window_sha256": WINDOW_SHA256,
        "window_started_at_seconds": 100,
    }
    probe_config = {
        **rgw_config,
        "collector_source_sha256": RGW.collector_source_sha256(),
    }
    normalized = RGW._probe(
        probe,
        config={
            **probe_config,
            "expected_fault_counts": expected_faults,
            "expected_operation_counts": config_value[
                "expected_operation_counts"
            ],
            "window_started_at_seconds": 100.0,
            "window_completed_at_seconds": 1000.0,
        },
        target_sha256=TARGET_SHA256,
    )
    multipart_normalized = RGW._multipart(
        multipart,
        config={
            **probe_config,
            "window_started_at_seconds": 100.0,
            "window_completed_at_seconds": 1000.0,
        },
        target_sha256=TARGET_SHA256,
    )

    assert normalized[1] == len(config_value["steps"])
    assert multipart_normalized[0]["upload_count"] == 0
    assert probe["schema"] == RGW.PROBE_SCHEMA
    assert probe["result_counts"]["unexpected_kms_error"] == 0
    assert probe["result_counts"]["unexpected_storage_error"] == 0
    assert multipart["schema"] == RGW.MULTIPART_SCHEMA


def test_expected_faults_are_observed_not_hidden(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path, phase="during")
    steps, _ = collected(config_value)

    probe = ADAPTER.compile_probe(config_value, steps)

    assert probe["result_counts"]["expected_wrong_key"] == 1
    assert probe["result_counts"]["expected_kms_outage"] == 1
    assert probe["result_counts"]["unexpected_kms_error"] == 0
    assert probe["result_counts"]["success"] == 9


def test_unexpected_results_remain_nonzero(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path)
    client = FakeClient(
        override={
            ("get", "success"): "unexpected_kms_error",
            ("head", "success"): "unexpected_storage_error",
        }
    )
    steps, _ = collected(config_value, client=client)

    probe = ADAPTER.compile_probe(config_value, steps)

    assert probe["result_counts"]["unexpected_kms_error"] == 1
    assert probe["result_counts"]["unexpected_storage_error"] == 1
    assert probe["result_counts"]["success"] == len(steps) - 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong"),
        ("adapter_source_sha256", f"sha256:{'0' * 64}"),
        ("probe_source_sha256", f"sha256:{'0' * 64}"),
        ("multipart_source_sha256", f"sha256:{'0' * 64}"),
        ("phase", "unknown"),
        ("endpoint", "http://rgw.stage6.test:8443"),
        ("endpoint", "https://user@rgw.stage6.test:8443"),
        ("endpoint", "https://rgw.stage6.test"),
        ("probe_prefix", "../escape"),
        ("region", "INVALID"),
        ("timeout_seconds", 0),
        ("max_pages", 0),
    ],
)
def test_configuration_drift_is_refused(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    changed = config(ca_path)
    changed[field] = value

    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)


def test_configuration_requires_owner_only_pinned_ca(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    changed = config(ca_path)
    changed["ca_file_sha256"] = f"sha256:{'0' * 64}"
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)

    changed = config(ca_path)
    ca_path.chmod(0o644)
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)


def test_fault_plan_is_during_only_and_evidence_bound(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    changed = config(ca_path)
    changed["steps"].append(
        {
            "fault_evidence_sha256": f"sha256:{'a' * 64}",
            "operation": "put_zero",
            "result": "expected_wrong_key",
        }
    )
    changed["expected_operation_counts"]["put_zero"] += 1
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)

    changed = config(ca_path, phase="during")
    changed["steps"][-2]["fault_evidence_sha256"] = (
        ADAPTER.NO_FAULT_SHA256
    )
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)

    changed = config(ca_path, phase="during")
    changed["steps"][-1], changed["steps"][-2] = (
        changed["steps"][-2],
        changed["steps"][-1],
    )
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)


def test_healthy_probe_order_is_dependency_safe(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path)
    assert [
        step["operation"] for step in config_value["steps"]
    ] == list(ADAPTER.HEALTHY_OPERATION_ORDER)

    changed = deepcopy(config_value)
    changed["steps"][0], changed["steps"][1] = (
        changed["steps"][1],
        changed["steps"][0],
    )
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER._config(changed)


def test_step_binding_order_and_window_are_fail_closed(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path)
    steps, _ = collected(config_value)
    changed = deepcopy(steps)
    changed[0]["index"] = 1
    changed[0]["step_sha256"] = ADAPTER._hash(
        {
            key: value
            for key, value in changed[0].items()
            if key != "step_sha256"
        }
    )
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER.compile_probe(config_value, changed)

    changed = deepcopy(steps)
    changed[1]["started_at_seconds"] = 199
    changed[1]["step_sha256"] = ADAPTER._hash(
        {
            key: value
            for key, value in changed[1].items()
            if key != "step_sha256"
        }
    )
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER.compile_probe(config_value, changed)


def test_multipart_completion_and_pages_are_fail_closed(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path)
    duplicate = f"sha256:{'6' * 64}"
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER.collect_multipart(
            config_value,
            client=FakeClient(page_hashes=[duplicate, duplicate]),
            clock=times([900, 901]),
        )

    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER.collect_multipart(
            config_value,
            client=FakeClient(page_hashes=[]),
            clock=times([900, 901]),
        )


class ClientError(Exception):
    def __init__(self, code: str, status: int):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakeBody(io.BytesIO):
    closed_by_adapter = False

    def close(self) -> None:
        self.closed_by_adapter = True
        super().close()


class FakeBotoClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.pages: list[dict] = [
            {
                "IsTruncated": True,
                "NextKeyMarker": "key-1",
                "NextUploadIdMarker": "upload-1",
                "Uploads": [{"Key": "a", "UploadId": "one"}],
            },
            {
                "IsTruncated": False,
                "Uploads": [{"Key": "b", "UploadId": "two"}],
            },
        ]
        self.list_calls: list[dict] = []

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.objects[Key] = Body
        return {}

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError("NoSuchKey", 404)
        return {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "00000000-0000-0000-0000-000000000001",
        }

    def get_object(self, *, Bucket, Key):
        response = self.head_object(Bucket=Bucket, Key=Key)
        return {**response, "Body": FakeBody(self.objects[Key])}

    def copy_object(self, *, Bucket, Key, CopySource, **_kwargs):
        self.objects[Key] = self.objects[CopySource["Key"]]
        return {}

    def list_multipart_uploads(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.pages[len(self.list_calls) - 1]


def test_boto_client_executes_fixed_sse_kms_operations() -> None:
    raw = FakeBotoClient()
    client = ADAPTER.Boto3EvidenceClient(
        client=raw,
        bucket="coffer-registry-stage6",
        kms_key_id="00000000-0000-0000-0000-000000000001",
        prefix="coffer-evidence/before",
    )
    for operation in (
        "put_zero",
        "put_positive",
        "head",
        "get",
        "copy_zero",
        "copy_positive",
    ):
        assert client.execute(operation, "success") == "success"

    pages, uploads = client.list_multipart(max_pages=2)
    assert len(pages) == 2
    assert len(set(pages)) == 2
    assert uploads == 2
    assert raw.list_calls[0] == {
        "Bucket": "coffer-registry-stage6",
        "MaxUploads": 1000,
    }
    assert raw.list_calls[1]["KeyMarker"] == "key-1"
    assert raw.list_calls[1]["UploadIdMarker"] == "upload-1"


@pytest.mark.parametrize(
    ("code", "status", "expected", "result"),
    [
        ("InternalError", 500, "expected_wrong_key", "expected_wrong_key"),
        (
            "KMS.ConnectionError",
            503,
            "expected_kms_outage",
            "expected_kms_outage",
        ),
        ("KMS.NotFoundException", 500, "success", "unexpected_kms_error"),
        ("SlowDown", 503, "success", "unexpected_storage_error"),
    ],
)
def test_boto_client_uses_fixed_error_classification(
    code: str,
    status: int,
    expected: str,
    result: str,
) -> None:
    class Failing:
        def put_object(self, **_kwargs):
            raise ClientError(code, status)

    client = ADAPTER.Boto3EvidenceClient(
        client=Failing(),
        bucket="coffer-registry-stage6",
        kms_key_id="00000000-0000-0000-0000-000000000001",
        prefix="coffer-evidence/during",
    )
    assert client.execute("put_zero", expected) == result


def test_boto_multipart_repeated_cursor_is_refused() -> None:
    raw = FakeBotoClient()
    raw.pages = [raw.pages[0], raw.pages[0]]
    client = ADAPTER.Boto3EvidenceClient(
        client=raw,
        bucket="coffer-registry-stage6",
        kms_key_id="00000000-0000-0000-0000-000000000001",
        prefix="coffer-evidence/during",
    )
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        client.list_multipart(max_pages=3)


def test_file_pipeline_is_owner_only_and_compatible(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    config_path = tmp_path / "config.json"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = config(ca_path)
    owner_document(config_path, config_value)
    client = FakeClient()
    step_paths = []
    for index in range(len(config_value["steps"])):
        path = tmp_path / f"step-{index}.json"
        ADAPTER.collect_step_file(
            config_path,
            index,
            path,
            client=client,
            clock=times([200 + index * 10, 201 + index * 10]),
        )
        step_paths.append(path)
    probe_path = tmp_path / "probe.json"
    multipart_path = tmp_path / "multipart.json"
    probe = ADAPTER.compile_probe_files(
        config_path,
        step_paths,
        probe_path,
    )
    multipart = ADAPTER.collect_multipart_file(
        config_path,
        multipart_path,
        client=client,
        clock=times([900, 901]),
    )

    assert json.loads(probe_path.read_bytes()) == probe
    assert json.loads(multipart_path.read_bytes()) == multipart
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in (*step_paths, probe_path, multipart_path)
    )
    retained = (probe_path.read_text() + multipart_path.read_text()).lower()
    for forbidden in (
        "coffer-registry-stage6",
        "rgw.stage6.test",
        "access_key",
        "secret_key",
        "kms_key_id",
        "probe_prefix",
    ):
        assert forbidden not in retained


def test_live_credentials_are_not_configuration_or_static_imports(
    tmp_path: Path,
) -> None:
    tree = ast.parse(ADAPTER_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "boto3" not in imports
    assert "botocore" not in imports

    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    serialized = json.dumps(config(ca_path), sort_keys=True).lower()
    assert "access_key" not in serialized
    assert "secret_key" not in serialized
    assert "kms_key_id" not in serialized


def test_boto_factory_requires_all_fixed_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    ca_path = tmp_path / "ca.crt"
    owner_bytes(ca_path, b"bounded test CA\n")
    config_value = ADAPTER._config(config(ca_path))
    for name in (
        ADAPTER.ACCESS_KEY_ENVIRONMENT,
        ADAPTER.SECRET_KEY_ENVIRONMENT,
        ADAPTER.KMS_KEY_ENVIRONMENT,
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ADAPTER.RgwLiveAdapterError):
        ADAPTER.boto3_client(config_value)


def test_cli_has_fixed_secret_safe_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ADAPTER.main(["source-hash"]) == 0
    source = json.loads(capsys.readouterr().out)
    assert source == {
        "adapter_source_sha256": ADAPTER.adapter_source_sha256(),
        "schema": ADAPTER.SOURCE_RESULT_SCHEMA,
    }
    assert ADAPTER.main(["collect-step", "/missing", "0", "/output"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "rgw-live-adapter-refused\n"
