from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit
import uuid


DIRECTORY = Path(__file__).resolve().parent
ROOT_DIRECTORY = DIRECTORY.parents[2]


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


rgw_artifacts = _module(
    "coffer_load_rgw_live_artifacts",
    DIRECTORY / "rgw_artifacts.py",
)
control_artifacts = rgw_artifacts.control_artifacts
native_target = rgw_artifacts.native_target

CONFIG_SCHEMA = "coffer.load-rgw-live-adapter-config/v1"
STEP_SCHEMA = "coffer.load-rgw-probe-step-result/v1"
RESULT_SCHEMA = "coffer.load-rgw-live-adapter-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-rgw-live-adapter-source-result/v1"
ACCESS_KEY_ENVIRONMENT = "COFFER_RGW_EVIDENCE_ACCESS_KEY"
SECRET_KEY_ENVIRONMENT = "COFFER_RGW_EVIDENCE_SECRET_KEY"
KMS_KEY_ENVIRONMENT = "COFFER_RGW_EVIDENCE_KMS_KEY_ID"
MAX_STEPS = 64
MAX_TIMEOUT_SECONDS = 30
MAX_PREFIX_LENGTH = 128
BUCKET_PATTERN = re.compile(
    r"^(?=.{3,63}$)(?![0-9]+(?:\.[0-9]+){3}$)"
    r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$"
)
REGION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
NO_FAULT_SHA256 = (
    "sha256:"
    + hashlib.sha256(b'{"fault":"none"}').hexdigest()
)
FAULT_RESULTS = frozenset(rgw_artifacts.FAULT_CLASSES)
HEALTHY_OPERATION_ORDER = (
    "put_zero",
    "put_positive",
    "head",
    "get",
    "copy_zero",
    "copy_positive",
    "list_multipart",
)
KMS_ERROR_CODES = frozenset(
    {
        "AccessDenied",
        "InternalError",
        "KMS.ConnectionError",
        "KMS.DisabledException",
        "KMS.InvalidKeyUsageException",
        "KMS.NotFoundException",
        "KMS.UnavailableException",
    }
)
FAULT_HTTP_STATUSES = frozenset({400, 403, 500, 503})
POSITIVE_PAYLOAD = b"coffer-stage6-rgw-evidence-v1\n"
SOURCE_FILES = (
    DIRECTORY / "rgw_artifacts.py",
    DIRECTORY / "rgw_live_adapter.py",
)


class RgwLiveAdapterError(RuntimeError):
    pass


class Clock(Protocol):
    def __call__(self) -> float: ...


class EvidenceClient(Protocol):
    def execute(self, operation: str, expected_result: str) -> str: ...

    def list_multipart(
        self,
        *,
        max_pages: int,
    ) -> tuple[list[str], int]: ...


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise RgwLiveAdapterError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def adapter_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": str(path.relative_to(ROOT_DIRECTORY)),
                    "sha256": _payload_hash(path.read_bytes()),
                }
            )
    except OSError as error:
        raise RgwLiveAdapterError(
            "RGW live adapter source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise RgwLiveAdapterError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int = 0,
    maximum: int = rgw_artifacts.phase_evidence.MAX_COUNT,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise RgwLiveAdapterError(f"{category} is invalid")
    return value


def _number(value: object, category: str) -> float:
    if isinstance(value, bool):
        raise RgwLiveAdapterError(f"{category} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise RgwLiveAdapterError(f"{category} is invalid") from error
    if not 0 <= result <= rgw_artifacts.MAX_SECONDS or result != result:
        raise RgwLiveAdapterError(f"{category} is invalid")
    return result


def _owner_bytes(path: Path, category: str) -> tuple[bytes, os.stat_result]:
    try:
        return control_artifacts._read_owner_bytes(
            path,
            maximum_bytes=64 * 1024,
        )
    except control_artifacts.ControlArtifactError as error:
        raise RgwLiveAdapterError(f"{category} is unavailable") from error


def _endpoint(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise RgwLiveAdapterError("RGW endpoint is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise RgwLiveAdapterError("RGW endpoint is invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RgwLiveAdapterError("RGW endpoint is not verified HTTPS")
    return f"https://{parsed.hostname}:{port}"


def _text(
    value: object,
    pattern: re.Pattern[str],
    category: str,
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RgwLiveAdapterError(f"{category} is invalid")
    return value


def _step(value: object, *, phase: str) -> dict[str, str]:
    raw = _exact(
        value,
        {"fault_evidence_sha256", "operation", "result"},
        "RGW probe step",
    )
    operation = raw["operation"]
    result = raw["result"]
    if (
        operation not in rgw_artifacts.OPERATION_CLASSES
        or result not in rgw_artifacts.RESULT_CLASSES
        or result
        in {"unexpected_kms_error", "unexpected_storage_error"}
    ):
        raise RgwLiveAdapterError("RGW probe step is invalid")
    fault_hash = _sha256(
        raw["fault_evidence_sha256"],
        "RGW fault evidence hash",
    )
    if result == "success":
        if fault_hash != NO_FAULT_SHA256:
            raise RgwLiveAdapterError(
                "healthy RGW probe step has fault evidence"
            )
    elif (
        phase != "during"
        or operation not in {"put_positive", "put_zero"}
        or fault_hash == NO_FAULT_SHA256
    ):
        raise RgwLiveAdapterError("RGW fault probe step is invalid")
    return {
        "fault_evidence_sha256": fault_hash,
        "operation": str(operation),
        "result": str(result),
    }


def _config(value: object) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "adapter_source_sha256",
            "bucket",
            "bucket_scope_sha256",
            "ca_file",
            "ca_file_sha256",
            "endpoint",
            "expected_operation_counts",
            "kms_policy_sha256",
            "max_pages",
            "multipart_source_sha256",
            "phase",
            "probe_prefix",
            "probe_source_sha256",
            "region",
            "rgw_config_sha256",
            "schema",
            "steps",
            "target_sha256",
            "timeout_seconds",
            "window_completed_at_seconds",
            "window_sha256",
            "window_started_at_seconds",
        },
        "RGW live adapter configuration",
    )
    source_hash = adapter_source_sha256()
    if (
        raw["schema"] != CONFIG_SCHEMA
        or raw["adapter_source_sha256"] != source_hash
        or raw["probe_source_sha256"] != source_hash
        or raw["multipart_source_sha256"] != source_hash
        or raw["phase"] not in native_target.PHASES
    ):
        raise RgwLiveAdapterError("RGW live adapter binding changed")
    steps_raw = raw["steps"]
    if (
        not isinstance(steps_raw, list)
        or not 1 <= len(steps_raw) <= MAX_STEPS
    ):
        raise RgwLiveAdapterError("RGW probe step set is invalid")
    steps = [_step(item, phase=raw["phase"]) for item in steps_raw]
    if [
        (item["operation"], item["result"])
        for item in steps[: len(HEALTHY_OPERATION_ORDER)]
    ] != [
        (operation, "success") for operation in HEALTHY_OPERATION_ORDER
    ]:
        raise RgwLiveAdapterError("RGW healthy probe order changed")
    if any(
        item["result"] not in FAULT_RESULTS
        for item in steps[len(HEALTHY_OPERATION_ORDER) :]
    ):
        raise RgwLiveAdapterError("RGW extra probe step changed")
    observed_counts = {
        operation: sum(
            item["operation"] == operation for item in steps
        )
        for operation in rgw_artifacts.OPERATION_CLASSES
    }
    expected_counts = rgw_artifacts._counts(
        raw["expected_operation_counts"],
        rgw_artifacts.OPERATION_CLASSES,
        "expected RGW operation counts",
        minimum=1,
    )
    if observed_counts != expected_counts:
        raise RgwLiveAdapterError("RGW probe operation plan changed")
    fault_counts = {
        result: sum(item["result"] == result for item in steps)
        for result in rgw_artifacts.FAULT_CLASSES
    }
    if (
        raw["phase"] == "during"
        and any(fault_counts[result] < 1 for result in FAULT_RESULTS)
    ):
        raise RgwLiveAdapterError("RGW fault probe coverage changed")
    if raw["phase"] != "during" and any(fault_counts.values()):
        raise RgwLiveAdapterError("RGW fault escaped its phase")
    started = _number(
        raw["window_started_at_seconds"],
        "RGW window start",
    )
    completed = _number(
        raw["window_completed_at_seconds"],
        "RGW window completion",
    )
    if started >= completed:
        raise RgwLiveAdapterError("RGW phase window order changed")
    ca_path = control_artifacts._absolute_path(
        raw["ca_file"],
        "RGW CA file",
    )
    ca_payload, _ = _owner_bytes(ca_path, "RGW CA file")
    if raw["ca_file_sha256"] != _payload_hash(ca_payload):
        raise RgwLiveAdapterError("RGW CA file hash changed")
    prefix = _text(
        raw["probe_prefix"],
        PREFIX_PATTERN,
        "RGW probe prefix",
    ).rstrip("/")
    if (
        not prefix
        or ".." in prefix.split("/")
        or len(prefix) > MAX_PREFIX_LENGTH
    ):
        raise RgwLiveAdapterError("RGW probe prefix is invalid")
    return {
        "adapter_source_sha256": source_hash,
        "bucket": _text(raw["bucket"], BUCKET_PATTERN, "RGW bucket"),
        "bucket_scope_sha256": _sha256(
            raw["bucket_scope_sha256"],
            "RGW bucket scope hash",
        ),
        "ca_file": str(ca_path),
        "ca_file_sha256": _sha256(
            raw["ca_file_sha256"],
            "RGW CA file hash",
        ),
        "endpoint": _endpoint(raw["endpoint"]),
        "expected_operation_counts": expected_counts,
        "kms_policy_sha256": _sha256(
            raw["kms_policy_sha256"],
            "RGW KMS policy hash",
        ),
        "max_pages": _integer(
            raw["max_pages"],
            "RGW multipart page bound",
            minimum=1,
            maximum=rgw_artifacts.MAX_PAGES,
        ),
        "multipart_source_sha256": source_hash,
        "phase": raw["phase"],
        "probe_prefix": prefix,
        "probe_source_sha256": source_hash,
        "region": _text(raw["region"], REGION_PATTERN, "RGW region"),
        "rgw_config_sha256": _sha256(
            raw["rgw_config_sha256"],
            "RGW configuration hash",
        ),
        "schema": CONFIG_SCHEMA,
        "steps": steps,
        "target_sha256": _sha256(
            raw["target_sha256"],
            "RGW target hash",
        ),
        "timeout_seconds": _integer(
            raw["timeout_seconds"],
            "RGW timeout",
            minimum=1,
            maximum=MAX_TIMEOUT_SECONDS,
        ),
        "window_completed_at_seconds": completed,
        "window_sha256": _sha256(
            raw["window_sha256"],
            "RGW window hash",
        ),
        "window_started_at_seconds": started,
    }


def _inside_window(
    config: Mapping[str, Any],
    started: float,
    completed: float,
) -> None:
    if (
        started > completed
        or started < config["window_started_at_seconds"]
        or completed > config["window_completed_at_seconds"]
    ):
        raise RgwLiveAdapterError("RGW observation escaped its phase window")


def collect_step(
    config_value: object,
    index: int,
    *,
    client: EvidenceClient,
    clock: Clock = time.time,
) -> dict[str, Any]:
    config = _config(config_value)
    selected = _integer(
        index,
        "RGW probe step index",
        maximum=len(config["steps"]) - 1,
    )
    step = config["steps"][selected]
    started = _number(clock(), "RGW probe step start")
    try:
        result = client.execute(step["operation"], step["result"])
    except Exception as error:
        raise RgwLiveAdapterError(
            "RGW probe client failed"
        ) from error
    completed = _number(clock(), "RGW probe step completion")
    _inside_window(config, started, completed)
    if result not in rgw_artifacts.RESULT_CLASSES:
        raise RgwLiveAdapterError("RGW probe client result changed")
    unsigned = {
        "adapter_source_sha256": config["adapter_source_sha256"],
        "bucket_scope_sha256": config["bucket_scope_sha256"],
        "completed_at_seconds": completed,
        "execution_source": "pilot",
        "fault_evidence_sha256": step["fault_evidence_sha256"],
        "index": selected,
        "operation": step["operation"],
        "phase": config["phase"],
        "result": result,
        "rgw_config_sha256": config["rgw_config_sha256"],
        "schema": STEP_SCHEMA,
        "started_at_seconds": started,
        "synthetic": False,
        "target_sha256": config["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "step_sha256": _hash(unsigned)}


def _validated_step(
    value: object,
    *,
    config: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    raw = _exact(
        value,
        {
            "adapter_source_sha256",
            "bucket_scope_sha256",
            "completed_at_seconds",
            "execution_source",
            "fault_evidence_sha256",
            "index",
            "operation",
            "phase",
            "result",
            "rgw_config_sha256",
            "schema",
            "started_at_seconds",
            "step_sha256",
            "synthetic",
            "target_sha256",
            "window_sha256",
        },
        "RGW probe step result",
    )
    expected = config["steps"][index]
    unsigned = {key: raw[key] for key in raw if key != "step_sha256"}
    if (
        raw["schema"] != STEP_SCHEMA
        or raw["execution_source"] != "pilot"
        or raw["synthetic"] is not False
        or raw["adapter_source_sha256"]
        != config["adapter_source_sha256"]
        or raw["bucket_scope_sha256"]
        != config["bucket_scope_sha256"]
        or raw["index"] != index
        or raw["operation"] != expected["operation"]
        or raw["phase"] != config["phase"]
        or raw["rgw_config_sha256"] != config["rgw_config_sha256"]
        or raw["target_sha256"] != config["target_sha256"]
        or raw["window_sha256"] != config["window_sha256"]
        or raw["fault_evidence_sha256"]
        != expected["fault_evidence_sha256"]
        or raw["step_sha256"] != _hash(unsigned)
    ):
        raise RgwLiveAdapterError("RGW probe step binding changed")
    result = raw["result"]
    if result not in rgw_artifacts.RESULT_CLASSES:
        raise RgwLiveAdapterError("RGW probe step result is invalid")
    if expected["result"] == "success":
        if result != "success":
            if result not in {
                "unexpected_kms_error",
                "unexpected_storage_error",
            }:
                raise RgwLiveAdapterError(
                    "RGW healthy probe result changed"
                )
    elif result not in {
        expected["result"],
        "unexpected_kms_error",
        "unexpected_storage_error",
    }:
        raise RgwLiveAdapterError("RGW fault probe result changed")
    started = _number(
        raw["started_at_seconds"],
        "RGW probe step start",
    )
    completed = _number(
        raw["completed_at_seconds"],
        "RGW probe step completion",
    )
    _inside_window(config, started, completed)
    return {
        "completed_at_seconds": completed,
        "operation": str(raw["operation"]),
        "result": str(result),
        "started_at_seconds": started,
        "step_sha256": _sha256(
            raw["step_sha256"],
            "RGW probe step hash",
        ),
    }


def compile_probe(
    config_value: object,
    step_values: Sequence[object],
) -> dict[str, Any]:
    config = _config(config_value)
    if len(step_values) != len(config["steps"]):
        raise RgwLiveAdapterError("RGW probe step result set changed")
    steps = [
        _validated_step(value, config=config, index=index)
        for index, value in enumerate(step_values)
    ]
    if any(
        left["completed_at_seconds"] > right["started_at_seconds"]
        for left, right in zip(steps, steps[1:])
    ):
        raise RgwLiveAdapterError("RGW probe step order changed")
    operation_counts = {
        operation: sum(step["operation"] == operation for step in steps)
        for operation in rgw_artifacts.OPERATION_CLASSES
    }
    result_counts = {
        result: sum(step["result"] == result for step in steps)
        for result in rgw_artifacts.RESULT_CLASSES
    }
    unsigned = {
        "bucket_scope_sha256": config["bucket_scope_sha256"],
        "completed_at_seconds": steps[-1]["completed_at_seconds"],
        "events_sha256": _hash(
            {"step_sha256": [step["step_sha256"] for step in steps]}
        ),
        "execution_source": "pilot",
        "kms_policy_sha256": config["kms_policy_sha256"],
        "observed_operation_counts": operation_counts,
        "phase": config["phase"],
        "probe_source_sha256": config["probe_source_sha256"],
        "result_counts": result_counts,
        "rgw_config_sha256": config["rgw_config_sha256"],
        "schema": rgw_artifacts.PROBE_SCHEMA,
        "started_at_seconds": steps[0]["started_at_seconds"],
        "synthetic": False,
        "target_sha256": config["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "probe_sha256": rgw_artifacts._hash(unsigned)}


def collect_multipart(
    config_value: object,
    *,
    client: EvidenceClient,
    clock: Clock = time.time,
) -> dict[str, Any]:
    config = _config(config_value)
    observed_at = _number(clock(), "RGW multipart observation")
    try:
        page_hashes, upload_count = client.list_multipart(
            max_pages=config["max_pages"]
        )
    except Exception as error:
        raise RgwLiveAdapterError(
            "RGW multipart client failed"
        ) from error
    completed_at = _number(clock(), "RGW multipart completion")
    _inside_window(config, observed_at, completed_at)
    if (
        not isinstance(page_hashes, list)
        or not 1 <= len(page_hashes) <= config["max_pages"]
    ):
        raise RgwLiveAdapterError("RGW multipart page set changed")
    normalized_hashes = [
        _sha256(value, "RGW multipart page hash")
        for value in page_hashes
    ]
    if len(set(normalized_hashes)) != len(normalized_hashes):
        raise RgwLiveAdapterError("RGW multipart page repeated")
    unsigned = {
        "bucket_scope_sha256": config["bucket_scope_sha256"],
        "execution_source": "pilot",
        "listing_complete": True,
        "multipart_source_sha256": config[
            "multipart_source_sha256"
        ],
        "observed_at_seconds": completed_at,
        "page_count": len(normalized_hashes),
        "page_sha256": normalized_hashes,
        "phase": config["phase"],
        "rgw_config_sha256": config["rgw_config_sha256"],
        "schema": rgw_artifacts.MULTIPART_SCHEMA,
        "synthetic": False,
        "target_sha256": config["target_sha256"],
        "upload_count": _integer(
            upload_count,
            "RGW multipart upload count",
        ),
        "window_sha256": config["window_sha256"],
    }
    return {**unsigned, "capture_sha256": rgw_artifacts._hash(unsigned)}


@dataclass(frozen=True)
class Boto3EvidenceClient:
    client: Any
    bucket: str
    kms_key_id: str
    prefix: str

    def _key(self, slot: str) -> str:
        return f"{self.prefix}/{slot}"

    def _assert_encryption(self, response: Mapping[str, Any]) -> None:
        if (
            response.get("ServerSideEncryption") != "aws:kms"
            or response.get("SSEKMSKeyId") != self.kms_key_id
        ):
            raise RgwLiveAdapterError(
                "RGW SSE-KMS response changed"
            )

    def _put(self, key: str, payload: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
        )
        self._assert_encryption(
            self.client.head_object(Bucket=self.bucket, Key=key)
        )

    def _copy(self, source: str, destination: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            Key=destination,
            CopySource={"Bucket": self.bucket, "Key": source},
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self.kms_key_id,
        )
        self._assert_encryption(
            self.client.head_object(
                Bucket=self.bucket,
                Key=destination,
            )
        )

    @staticmethod
    def _error(error: Exception, expected_result: str) -> str:
        response = getattr(error, "response", None)
        if not isinstance(response, Mapping):
            return "unexpected_storage_error"
        metadata = response.get("ResponseMetadata")
        details = response.get("Error")
        if not isinstance(metadata, Mapping) or not isinstance(details, Mapping):
            return "unexpected_storage_error"
        status = metadata.get("HTTPStatusCode")
        code = details.get("Code")
        kms_error = (
            isinstance(code, str)
            and (
                code in KMS_ERROR_CODES
                or code.startswith("KMS.")
                or code.startswith("Barbican")
            )
        )
        if (
            expected_result in FAULT_RESULTS
            and status in FAULT_HTTP_STATUSES
            and (kms_error or code == "InternalError")
        ):
            return expected_result
        return (
            "unexpected_kms_error"
            if kms_error
            else "unexpected_storage_error"
        )

    def execute(self, operation: str, expected_result: str) -> str:
        zero = self._key("zero-source")
        positive = self._key("positive-source")
        try:
            if operation == "put_zero":
                self._put(zero, b"")
            elif operation == "put_positive":
                self._put(positive, POSITIVE_PAYLOAD)
            elif operation == "head":
                self._assert_encryption(
                    self.client.head_object(
                        Bucket=self.bucket,
                        Key=positive,
                    )
                )
            elif operation == "get":
                response = self.client.get_object(
                    Bucket=self.bucket,
                    Key=positive,
                )
                self._assert_encryption(response)
                body = response["Body"]
                try:
                    payload = body.read()
                finally:
                    close = getattr(body, "close", None)
                    if callable(close):
                        close()
                if payload != POSITIVE_PAYLOAD:
                    raise RgwLiveAdapterError(
                        "RGW decrypted probe payload changed"
                    )
            elif operation == "copy_zero":
                self._copy(zero, self._key("zero-copy"))
            elif operation == "copy_positive":
                self._copy(positive, self._key("positive-copy"))
            elif operation == "list_multipart":
                self.list_multipart(max_pages=1)
            else:
                raise RgwLiveAdapterError("RGW probe operation changed")
        except Exception as error:
            if isinstance(error, RgwLiveAdapterError):
                return "unexpected_storage_error"
            return self._error(error, expected_result)
        return (
            "success"
            if expected_result == "success"
            else "unexpected_storage_error"
        )

    def list_multipart(
        self,
        *,
        max_pages: int,
    ) -> tuple[list[str], int]:
        page_hashes: list[str] = []
        upload_count = 0
        key_marker: str | None = None
        upload_marker: str | None = None
        seen_markers: set[tuple[str, str]] = set()
        while True:
            if len(page_hashes) >= max_pages:
                raise RgwLiveAdapterError(
                    "RGW multipart pagination exceeded"
                )
            arguments: dict[str, Any] = {
                "Bucket": self.bucket,
                "MaxUploads": 1000,
            }
            if key_marker is not None:
                arguments["KeyMarker"] = key_marker
                arguments["UploadIdMarker"] = upload_marker
            response = self.client.list_multipart_uploads(**arguments)
            uploads = response.get("Uploads", [])
            if (
                not isinstance(uploads, list)
                or any(
                    not isinstance(item, Mapping)
                    or not isinstance(item.get("Key"), str)
                    or not item["Key"]
                    or not isinstance(item.get("UploadId"), str)
                    or not item["UploadId"]
                    for item in uploads
                )
            ):
                raise RgwLiveAdapterError(
                    "RGW multipart page changed"
                )
            upload_count += len(uploads)
            if upload_count > rgw_artifacts.phase_evidence.MAX_COUNT:
                raise RgwLiveAdapterError(
                    "RGW multipart upload count exceeded"
                )
            page_hashes.append(
                _hash(
                    {
                        "is_truncated": response.get("IsTruncated") is True,
                        "next_key_marker_sha256": (
                            _payload_hash(
                                str(response.get("NextKeyMarker", "")).encode()
                            )
                        ),
                        "next_upload_marker_sha256": (
                            _payload_hash(
                                str(
                                    response.get(
                                        "NextUploadIdMarker",
                                        "",
                                    )
                                ).encode()
                            )
                        ),
                        "upload_identity_sha256": sorted(
                            _hash(
                                {
                                    "key": item.get("Key"),
                                    "upload_id": item.get("UploadId"),
                                }
                            )
                            for item in uploads
                        ),
                    }
                )
            )
            if response.get("IsTruncated") is not True:
                break
            next_key = response.get("NextKeyMarker")
            next_upload = response.get("NextUploadIdMarker")
            if (
                not isinstance(next_key, str)
                or not next_key
                or not isinstance(next_upload, str)
                or not next_upload
                or (next_key, next_upload) in seen_markers
            ):
                raise RgwLiveAdapterError(
                    "RGW multipart cursor changed"
                )
            seen_markers.add((next_key, next_upload))
            key_marker = next_key
            upload_marker = next_upload
        return page_hashes, upload_count


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value or "\x00" in value:
        raise RgwLiveAdapterError(
            "RGW live credential input is unavailable"
        )
    return value


def boto3_client(config: Mapping[str, Any]) -> Boto3EvidenceClient:
    try:
        boto3 = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
    except ImportError as error:
        raise RgwLiveAdapterError(
            "RGW live client dependency is unavailable"
        ) from error
    key_id = _required_environment(KMS_KEY_ENVIRONMENT)
    try:
        uuid.UUID(key_id)
    except ValueError as error:
        raise RgwLiveAdapterError(
            "RGW live KMS identity is invalid"
        ) from error
    client = boto3.client(
        "s3",
        aws_access_key_id=_required_environment(ACCESS_KEY_ENVIRONMENT),
        aws_secret_access_key=_required_environment(
            SECRET_KEY_ENVIRONMENT
        ),
        endpoint_url=config["endpoint"],
        region_name=config["region"],
        verify=config["ca_file"],
        config=botocore_config.Config(
            signature_version="s3v4",
            retries={"max_attempts": 1, "mode": "standard"},
            connect_timeout=config["timeout_seconds"],
            read_timeout=config["timeout_seconds"],
            s3={"addressing_style": "path"},
        ),
    )
    return Boto3EvidenceClient(
        client=client,
        bucket=config["bucket"],
        kms_key_id=key_id,
        prefix=config["probe_prefix"],
    )


def _read_config(
    path: Path,
) -> tuple[dict[str, Any], bytes, os.stat_result]:
    try:
        value, payload, metadata = (
            control_artifacts._read_owner_document(path)
        )
    except control_artifacts.ControlArtifactError as error:
        raise RgwLiveAdapterError(
            "RGW live adapter configuration is unavailable"
        ) from error
    return _config(value), payload, metadata


def _write(
    output: Path,
    value: object,
    *,
    inputs: Sequence[tuple[Path, os.stat_result]],
) -> None:
    try:
        control_artifacts._write_output(
            output,
            value,
            inputs=inputs,
        )
    except control_artifacts.ControlArtifactError as error:
        raise RgwLiveAdapterError(
            "RGW live adapter output is unavailable"
        ) from error


def collect_step_file(
    config_path: Path,
    index: int,
    output_path: Path,
    *,
    client: EvidenceClient | None = None,
    clock: Clock = time.time,
) -> dict[str, Any]:
    config_path = control_artifacts._absolute_path(
        str(config_path),
        "RGW live configuration",
    )
    config, _, metadata = _read_config(config_path)
    selected_client = client or boto3_client(config)
    result = collect_step(
        config,
        index,
        client=selected_client,
        clock=clock,
    )
    _write(output_path, result, inputs=[(config_path, metadata)])
    return result


def collect_multipart_file(
    config_path: Path,
    output_path: Path,
    *,
    client: EvidenceClient | None = None,
    clock: Clock = time.time,
) -> dict[str, Any]:
    config_path = control_artifacts._absolute_path(
        str(config_path),
        "RGW live configuration",
    )
    config, _, metadata = _read_config(config_path)
    selected_client = client or boto3_client(config)
    result = collect_multipart(
        config,
        client=selected_client,
        clock=clock,
    )
    _write(output_path, result, inputs=[(config_path, metadata)])
    return result


def compile_probe_files(
    config_path: Path,
    step_paths: Sequence[Path],
    output_path: Path,
) -> dict[str, Any]:
    config_path = control_artifacts._absolute_path(
        str(config_path),
        "RGW live configuration",
    )
    config, _, config_metadata = _read_config(config_path)
    if len(step_paths) != len(config["steps"]):
        raise RgwLiveAdapterError("RGW probe step file set changed")
    values: list[object] = []
    inputs = [(config_path, config_metadata)]
    for path in step_paths:
        canonical_path = control_artifacts._absolute_path(
            str(path),
            "RGW probe step file",
        )
        try:
            value, _, metadata = (
                control_artifacts._read_owner_document(canonical_path)
            )
        except control_artifacts.ControlArtifactError as error:
            raise RgwLiveAdapterError(
                "RGW probe step file is unavailable"
            ) from error
        values.append(value)
        inputs.append((canonical_path, metadata))
    try:
        control_artifacts._distinct_inputs(inputs)
    except control_artifacts.ControlArtifactError as error:
        raise RgwLiveAdapterError(
            "RGW probe step files alias"
        ) from error
    result = compile_probe(config, values)
    _write(output_path, result, inputs=inputs)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = adapter_source_sha256()
        except RgwLiveAdapterError:
            print("rgw-live-adapter-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "adapter_source_sha256": source_sha256,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    try:
        if len(arguments) == 4 and arguments[0] == "collect-step":
            result = collect_step_file(
                Path(arguments[1]),
                int(arguments[2]),
                Path(arguments[3]),
            )
            response = {
                "index": result["index"],
                "schema": RESULT_SCHEMA,
                "step_sha256": result["step_sha256"],
            }
        elif len(arguments) == 3 and arguments[0] == "collect-multipart":
            result = collect_multipart_file(
                Path(arguments[1]),
                Path(arguments[2]),
            )
            response = {
                "capture_sha256": result["capture_sha256"],
                "schema": RESULT_SCHEMA,
            }
        elif len(arguments) >= 4 and arguments[0] == "compile-probe":
            result = compile_probe_files(
                Path(arguments[1]),
                [Path(value) for value in arguments[2:-1]],
                Path(arguments[-1]),
            )
            response = {
                "probe_sha256": result["probe_sha256"],
                "schema": RESULT_SCHEMA,
            }
        else:
            raise RgwLiveAdapterError("RGW live adapter command changed")
    except (
        RgwLiveAdapterError,
        control_artifacts.ControlArtifactError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("rgw-live-adapter-refused", file=sys.stderr)
        return 2
    print(_canonical(response).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
