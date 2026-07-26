from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlencode, urlsplit, urlunsplit

from coffer.quota import QuotaControlEvidenceSnapshot, QuotaStore


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent
POC_DIRECTORY = LOAD_DIRECTORY.parent
ROOT_DIRECTORY = POC_DIRECTORY.parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


source_summaries = _module(
    "coffer_load_control_artifacts_source_summaries",
    DIRECTORY / "source_summaries.py",
)
phase_evidence = source_summaries.phase_evidence
native_target = source_summaries.native_target
native_surfaces = phase_evidence.native_surfaces
render_target = source_summaries.render_target
load_contract = source_summaries.load_contract
observability_contract = source_summaries.observability_contract

CONFIG_SCHEMA = "coffer.load-telemetry-control-artifact-config/v1"
CAPTURE_SCHEMA = "coffer.load-telemetry-control-capture/v1"
RESULT_SCHEMA = "coffer.load-telemetry-control-artifact-result/v1"
CAPTURE_RESULT_SCHEMA = "coffer.load-telemetry-control-capture-result/v1"
CAPTURE_KINDS = ("baseline", "current")
SURFACES = ("quota", "reconciliation")
DATABASE_URL_ENV = "COFFER_DATABASE_URL"
PROJECT_ID_ENV = "COFFER_LOAD_PROJECT_ID"
MAX_CAPTURE_SECONDS = 300
MAX_SERIES = 512
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_CA_BYTES = 1024 * 1024
ATTEMPT_BUCKETS = ("1.0", "2.0", "3.0", "+Inf")
ATTEMPT_OPERATIONS = frozenset(
    {"claim", "commit", "limit", "reconcile", "release", "reserve"}
)
ATTEMPT_RESULTS = frozenset(
    {"conflict_exhausted", "database_error", "rejected", "success"}
)
PROMQL = {
    "attempts": (
        "sum by (instance,job,le,operation,result) "
        "(coffer_quota_transaction_attempts_bucket{"
        'job=~"coffer-(edge|reconcile)",'
        'operation=~"claim|commit|limit|reconcile|release|reserve",'
        'result=~"conflict_exhausted|database_error|rejected|success",'
        'le=~"1.0|2.0|3.0|\\\\+Inf"})'
    ),
    "edge_internal_errors": (
        'sum by (instance) (coffer_quota_admission_total{'
        'job="coffer-edge",result="internal_error"}) '
        "or on (instance) "
        '(0 * max by (instance) (up{job="coffer-edge"}))'
    ),
    "process_start": (
        "max by (component,instance) "
        "(coffer_process_start_time_seconds{"
        'job=~"coffer-(edge|reconcile)",'
        'component=~"edge|reconcile"})'
    ),
    "reconcile_database_up": (
        "max by (instance) (coffer_dependency_up{"
        'job="coffer-reconcile",component="reconcile",'
        'dependency="database"})'
    ),
    "reconcile_last_success": (
        "max by (instance) "
        "(coffer_reconciliation_last_success_timestamp_seconds{"
        'job="coffer-reconcile"})'
    ),
    "reconcile_up": (
        'max by (instance) (up{job="coffer-reconcile"})'
    ),
}
QUERY_LABELS = {
    "attempts": frozenset(
        {"instance", "job", "le", "operation", "result"}
    ),
    "edge_internal_errors": frozenset({"instance"}),
    "process_start": frozenset({"component", "instance"}),
    "reconcile_database_up": frozenset({"instance"}),
    "reconcile_last_success": frozenset({"instance"}),
    "reconcile_up": frozenset({"instance"}),
}
SOURCE_FILES = (
    ROOT_DIRECTORY / "src" / "coffer" / "observability.py",
    ROOT_DIRECTORY / "src" / "coffer" / "quota.py",
    DIRECTORY / "native_surfaces.py",
    DIRECTORY / "native_target.py",
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "source_summaries.py",
    DIRECTORY / "control_artifacts.py",
)
SQL_KEYS = frozenset(
    {
        "active_claims",
        "claim_invariant_violations",
        "claims_exact",
        "descriptor_invariant_violations",
        "eligible_active_claims",
        "expected_reserved_bytes",
        "expected_used_bytes",
        "limit_bytes",
        "mismatched_pending_deltas",
        "pending_reservations",
        "quota_invariant",
        "reserved_bytes",
        "stale_claims",
        "used_bytes",
    }
)


class ControlArtifactError(RuntimeError):
    pass


class CaptureStore(Protocol):
    def control_evidence_snapshot(
        self,
        project_id: str,
        *,
        observed_at: datetime,
    ) -> QuotaControlEvidenceSnapshot: ...


class PrometheusClient(Protocol):
    def fetch_json(
        self,
        url: str,
        *,
        ca_file: Path,
        timeout_seconds: float,
    ) -> object: ...


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ControlArtifactError(f"{category} boundary changed")
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


def collector_source_sha256() -> str:
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
        raise ControlArtifactError(
            "control collector source is unavailable"
        ) from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise ControlArtifactError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int = 0,
    maximum: int = phase_evidence.MAX_COUNT,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise ControlArtifactError(f"{category} is invalid")
    return value


def _number(
    value: object,
    category: str,
    *,
    minimum: float = 0,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise ControlArtifactError(f"{category} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ControlArtifactError(f"{category} is invalid") from error
    if (
        not math.isfinite(result)
        or not minimum <= result <= maximum
    ):
        raise ControlArtifactError(f"{category} is invalid")
    return result


def _absolute_path(value: object, category: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\x00" in value
    ):
        raise ControlArtifactError(f"{category} is invalid")
    path = Path(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or os.path.normpath(value) != value
    ):
        raise ControlArtifactError(f"{category} is not canonical")
    return path


def _load_topologies() -> tuple[Mapping[str, Any], Any]:
    return (
        load_contract.load_topology(LOAD_DIRECTORY / "topology.json"),
        observability_contract.load_topology(
            POC_DIRECTORY / "observability" / "topology.json"
        ),
    )


def _validated_target(
    value: object,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    load_topology, observability_topology = _load_topologies()
    topology_sha256 = native_target._hash(load_topology)
    try:
        target = native_target.validate_target(
            value,
            topology_sha256=topology_sha256,
            load_topology=load_topology,
            observability_topology=observability_topology,
        ).raw
    except native_target.NativeTargetError as error:
        raise ControlArtifactError("native target is invalid") from error
    return target, load_topology


def _config(
    value: object,
    target_value: object,
    *,
    target_file_sha256: str,
) -> tuple[dict[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    raw = _exact(
        value,
        {
            "ca_file",
            "ca_file_sha256",
            "collector_source_sha256",
            "phase",
            "reconciliation_freshness_seconds",
            "schema",
            "target_file",
            "target_file_sha256",
            "timeout_seconds",
            "window_sha256",
        },
        "control artifact configuration",
    )
    if (
        raw["schema"] != CONFIG_SCHEMA
        or raw["collector_source_sha256"] != collector_source_sha256()
        or raw["phase"] not in native_target.PHASES
        or raw["target_file_sha256"] != target_file_sha256
    ):
        raise ControlArtifactError("control artifact binding changed")
    target, load_topology = _validated_target(target_value)
    if target["target_sha256"] != (
        target_value.get("target_sha256")
        if isinstance(target_value, Mapping)
        else None
    ):
        raise ControlArtifactError("native target hash changed")
    normalized = {
        "ca_file": str(
            _absolute_path(raw["ca_file"], "control collector CA file")
        ),
        "ca_file_sha256": _sha256(
            raw["ca_file_sha256"],
            "control collector CA hash",
        ),
        "collector_source_sha256": collector_source_sha256(),
        "phase": raw["phase"],
        "reconciliation_freshness_seconds": _integer(
            raw["reconciliation_freshness_seconds"],
            "reconciliation freshness",
            minimum=1,
            maximum=3600,
        ),
        "schema": CONFIG_SCHEMA,
        "target_file": str(
            _absolute_path(raw["target_file"], "native target file")
        ),
        "target_file_sha256": _sha256(
            raw["target_file_sha256"],
            "native target file hash",
        ),
        "timeout_seconds": _number(
            raw["timeout_seconds"],
            "control collector timeout",
            minimum=1,
            maximum=30,
        ),
        "window_sha256": _sha256(
            raw["window_sha256"],
            "control collector window hash",
        ),
    }
    return normalized, target, load_topology


def _query_urls(target: Mapping[str, Any]) -> dict[str, str]:
    direct_url = target["sources"]["prometheus"]["queries"][
        "direct_targets"
    ]["url"]
    parsed = urlsplit(direct_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not parsed.path.endswith("/api/v1/query")
    ):
        raise ControlArtifactError("Prometheus query origin changed")
    origin_path = parsed.path
    return {
        name: urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                origin_path,
                urlencode([("query", promql)]),
                "",
            )
        )
        for name, promql in PROMQL.items()
    }


def _sample_document(
    value: object,
    name: str,
) -> list[dict[str, Any]]:
    try:
        samples = native_surfaces.parse_prometheus_vector(
            value,
            expected_labels=QUERY_LABELS[name],
            maximum_series=MAX_SERIES,
        )
    except native_surfaces.NativeSurfaceError as error:
        raise ControlArtifactError(
            f"{name} Prometheus response is invalid"
        ) from error
    return [
        {
            "labels": dict(sample.labels),
            "timestamp": sample.timestamp,
            "value": sample.value,
        }
        for sample in samples
    ]


def _sql_document(
    snapshot: QuotaControlEvidenceSnapshot,
) -> dict[str, Any]:
    document = {
        **asdict(snapshot),
        "claims_exact": snapshot.claims_exact,
        "quota_invariant": snapshot.quota_invariant,
    }
    if set(document) != set(SQL_KEYS):
        raise ControlArtifactError("control SQL snapshot changed")
    return document


def capture_snapshot(
    config_value: object,
    target_value: object,
    *,
    target_file_sha256: str,
    capture_kind: str,
    client: PrometheusClient,
    store: CaptureStore,
    project_id: str,
    ca_file: Path,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    config, target, _ = _config(
        config_value,
        target_value,
        target_file_sha256=target_file_sha256,
    )
    if capture_kind not in CAPTURE_KINDS:
        raise ControlArtifactError("control capture kind is invalid")
    if (
        not project_id
        or project_id.strip() != project_id
        or len(project_id) > 64
        or "\x00" in project_id
    ):
        raise ControlArtifactError("control capture project is invalid")
    if ca_file != Path(config["ca_file"]):
        raise ControlArtifactError("control collector CA path changed")
    started_at = _number(
        clock(),
        "control capture start",
        maximum=2**53,
    )
    queries: dict[str, Any] = {}
    for name, url in _query_urls(target).items():
        response = client.fetch_json(
            url,
            ca_file=ca_file,
            timeout_seconds=float(config["timeout_seconds"]),
        )
        queries[name] = {
            "promql_sha256": _payload_hash(PROMQL[name].encode("utf-8")),
            "samples": _sample_document(response, name),
        }
    observed_at = _number(
        clock(),
        "control SQL observation time",
        minimum=started_at,
        maximum=2**53,
    )
    snapshot = store.control_evidence_snapshot(
        project_id,
        observed_at=datetime.fromtimestamp(observed_at, UTC),
    )
    completed_at = _number(
        clock(),
        "control capture completion",
        minimum=observed_at,
        maximum=2**53,
    )
    if completed_at - started_at > MAX_CAPTURE_SECONDS:
        raise ControlArtifactError("control capture deadline exceeded")
    unsigned = {
        "capture_kind": capture_kind,
        "collector_source_sha256": config["collector_source_sha256"],
        "completed_at_seconds": completed_at,
        "phase": config["phase"],
        "prometheus": queries,
        "schema": CAPTURE_SCHEMA,
        "sql": _sql_document(snapshot),
        "sql_observed_at_seconds": observed_at,
        "started_at_seconds": started_at,
        "target_sha256": target["target_sha256"],
        "window_sha256": config["window_sha256"],
    }
    capture = {**unsigned, "capture_sha256": _hash(unsigned)}
    return json.loads(json.dumps(capture, separators=(",", ":"), sort_keys=True))


def _samples(
    value: object,
    name: str,
    *,
    started_at: float,
    completed_at: float,
) -> tuple[dict[tuple[tuple[str, str], ...], float], int]:
    if not isinstance(value, list) or len(value) > MAX_SERIES:
        raise ControlArtifactError(f"{name} sample set changed")
    samples: dict[tuple[tuple[str, str], ...], float] = {}
    for raw in value:
        sample = _exact(
            raw,
            {"labels", "timestamp", "value"},
            f"{name} sample",
        )
        labels = sample["labels"]
        if (
            not isinstance(labels, Mapping)
            or set(labels) != set(QUERY_LABELS[name])
            or any(
                not isinstance(key, str)
                or not isinstance(label, str)
                or not label
                or len(label) > native_surfaces.MAX_LABEL_LENGTH
                or "\x00" in label
                for key, label in labels.items()
            )
        ):
            raise ControlArtifactError(f"{name} sample labels changed")
        identity = tuple(sorted(labels.items()))
        if identity in samples:
            raise ControlArtifactError(f"{name} sample is duplicated")
        timestamp = _number(
            sample["timestamp"],
            f"{name} sample timestamp",
            minimum=max(0, started_at - 90),
            maximum=completed_at + 90,
        )
        if not started_at - 90 <= timestamp <= completed_at + 90:
            raise ControlArtifactError(f"{name} sample is stale")
        samples[identity] = _number(
            sample["value"],
            f"{name} sample value",
            maximum=(
                float(2**53)
                if name in {"process_start", "reconcile_last_success"}
                else float(phase_evidence.MAX_COUNT)
            ),
        )
    return samples, len(value)


def _sql(value: object) -> dict[str, Any]:
    raw = _exact(value, SQL_KEYS, "control SQL snapshot")
    counts = {
        key: _integer(raw[key], f"control SQL {key}", maximum=2**63 - 1)
        for key in SQL_KEYS - {"claims_exact", "quota_invariant"}
    }
    if not isinstance(raw["claims_exact"], bool) or not isinstance(
        raw["quota_invariant"], bool
    ):
        raise ControlArtifactError("control SQL invariant changed")
    expected_quota = (
        counts["used_bytes"] == counts["expected_used_bytes"]
        and counts["reserved_bytes"] == counts["expected_reserved_bytes"]
        and counts["mismatched_pending_deltas"] == 0
        and counts["descriptor_invariant_violations"] == 0
        and counts["used_bytes"] + counts["reserved_bytes"]
        <= counts["limit_bytes"]
    )
    expected_claims = (
        counts["active_claims"] == counts["eligible_active_claims"]
        and counts["claim_invariant_violations"] == 0
    )
    if (
        raw["quota_invariant"] is not expected_quota
        or raw["claims_exact"] is not expected_claims
    ):
        raise ControlArtifactError("control SQL invariant conflicts")
    return {
        **counts,
        "claims_exact": raw["claims_exact"],
        "quota_invariant": raw["quota_invariant"],
    }


def _capture(
    value: object,
    *,
    config: Mapping[str, Any],
    target: Mapping[str, Any],
    capture_kind: str,
) -> tuple[dict[str, Any], int]:
    raw = _exact(
        value,
        {
            "capture_kind",
            "capture_sha256",
            "collector_source_sha256",
            "completed_at_seconds",
            "phase",
            "prometheus",
            "schema",
            "sql",
            "sql_observed_at_seconds",
            "started_at_seconds",
            "target_sha256",
            "window_sha256",
        },
        "control capture",
    )
    if (
        raw["schema"] != CAPTURE_SCHEMA
        or raw["capture_kind"] != capture_kind
        or raw["collector_source_sha256"]
        != config["collector_source_sha256"]
        or raw["phase"] != config["phase"]
        or raw["target_sha256"] != target["target_sha256"]
        or raw["window_sha256"] != config["window_sha256"]
    ):
        raise ControlArtifactError("control capture binding changed")
    started_at = _number(
        raw["started_at_seconds"],
        "control capture start",
        maximum=2**53,
    )
    observed_at = _number(
        raw["sql_observed_at_seconds"],
        "control SQL observation time",
        minimum=started_at,
        maximum=2**53,
    )
    completed_at = _number(
        raw["completed_at_seconds"],
        "control capture completion",
        minimum=observed_at,
        maximum=2**53,
    )
    if completed_at - started_at > MAX_CAPTURE_SECONDS:
        raise ControlArtifactError("control capture deadline exceeded")
    query_values = _exact(
        raw["prometheus"],
        set(PROMQL),
        "control Prometheus capture",
    )
    queries: dict[str, Any] = {}
    observations = 1
    for name in PROMQL:
        query = _exact(
            query_values[name],
            {"promql_sha256", "samples"},
            f"{name} query capture",
        )
        if query["promql_sha256"] != _payload_hash(
            PROMQL[name].encode("utf-8")
        ):
            raise ControlArtifactError(f"{name} query changed")
        samples, count = _samples(
            query["samples"],
            name,
            started_at=started_at,
            completed_at=completed_at,
        )
        queries[name] = samples
        observations += count
    unsigned = {
        key: raw[key] for key in raw if key != "capture_sha256"
    }
    if raw["capture_sha256"] != _hash(unsigned):
        raise ControlArtifactError("control capture hash changed")
    return (
        {
            "capture_sha256": raw["capture_sha256"],
            "completed_at_seconds": completed_at,
            "prometheus": queries,
            "sql": _sql(raw["sql"]),
            "sql_observed_at_seconds": observed_at,
            "started_at_seconds": started_at,
        },
        observations,
    )


def _label_map(identity: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(identity)


def _expected_instances(
    target: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    instances = target["sources"]["prometheus"]["instances"]
    return set(instances["edge"]), set(instances["reconcile"])


def _process_starts(
    samples: Mapping[tuple[tuple[str, str], ...], float],
    *,
    edge_instances: set[str],
    reconcile_instances: set[str],
) -> dict[tuple[str, str], float]:
    expected = {
        *(("edge", instance) for instance in edge_instances),
        *(("reconcile", instance) for instance in reconcile_instances),
    }
    starts: dict[tuple[str, str], float] = {}
    for identity, value in samples.items():
        labels = _label_map(identity)
        key = (labels["component"], labels["instance"])
        if key not in expected or key in starts or value <= 0:
            raise ControlArtifactError("control process-start series changed")
        starts[key] = value
    if set(starts) != expected:
        raise ControlArtifactError("control process-start series is incomplete")
    return starts


def _bounded_instance_values(
    samples: Mapping[tuple[tuple[str, str], ...], float],
    *,
    expected_instances: set[str],
    category: str,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for identity, value in samples.items():
        labels = _label_map(identity)
        instance = labels["instance"]
        if instance not in expected_instances or instance in values:
            raise ControlArtifactError(f"{category} series changed")
        values[instance] = value
    if set(values) != expected_instances:
        raise ControlArtifactError(f"{category} series is incomplete")
    return values


def _attempt_values(
    samples: Mapping[tuple[tuple[str, str], ...], float],
    *,
    edge_instances: set[str],
    reconcile_instances: set[str],
) -> dict[tuple[str, str, str, str, str], int]:
    values: dict[tuple[str, str, str, str, str], int] = {}
    for identity, raw_value in samples.items():
        labels = _label_map(identity)
        job = labels["job"]
        instance = labels["instance"]
        operation = labels["operation"]
        result = labels["result"]
        bucket = labels["le"]
        if (
            (job == "coffer-edge" and instance not in edge_instances)
            or (
                job == "coffer-reconcile"
                and instance not in reconcile_instances
            )
            or job not in {"coffer-edge", "coffer-reconcile"}
            or operation not in ATTEMPT_OPERATIONS
            or result not in ATTEMPT_RESULTS
            or bucket not in ATTEMPT_BUCKETS
            or not raw_value.is_integer()
        ):
            raise ControlArtifactError(
                "quota transaction-attempt series changed"
            )
        key = (job, instance, operation, result, bucket)
        if key in values:
            raise ControlArtifactError(
                "quota transaction-attempt series duplicated"
            )
        values[key] = int(raw_value)
    groups: dict[tuple[str, str, str, str], set[str]] = {}
    for job, instance, operation, result, bucket in values:
        groups.setdefault(
            (job, instance, operation, result),
            set(),
        ).add(bucket)
    if any(buckets != set(ATTEMPT_BUCKETS) for buckets in groups.values()):
        raise ControlArtifactError(
            "quota transaction-attempt buckets are incomplete"
        )
    for group in groups:
        buckets = [values[(*group, bucket)] for bucket in ATTEMPT_BUCKETS]
        if not buckets[0] <= buckets[1] <= buckets[2] == buckets[3]:
            raise ControlArtifactError(
                "quota transaction-attempt buckets conflict"
            )
    return values


def _counter_delta(
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    category: str,
) -> int:
    total = 0
    for instance in baseline:
        before = baseline[instance]
        after = current[instance]
        if (
            not before.is_integer()
            or not after.is_integer()
            or after < before
        ):
            raise ControlArtifactError(f"{category} counter reset")
        total += int(after - before)
        if total > phase_evidence.MAX_COUNT:
            raise ControlArtifactError(f"{category} count exceeded")
    return total


def _maximum_attempts(
    baseline_samples: Mapping[tuple[tuple[str, str], ...], float],
    current_samples: Mapping[tuple[tuple[str, str], ...], float],
    *,
    edge_instances: set[str],
    reconcile_instances: set[str],
) -> int:
    baseline = _attempt_values(
        baseline_samples,
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    current = _attempt_values(
        current_samples,
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    if not set(baseline) <= set(current):
        raise ControlArtifactError(
            "quota transaction-attempt series disappeared"
        )
    delta = {bucket: 0 for bucket in ATTEMPT_BUCKETS}
    for key, current_value in current.items():
        baseline_value = baseline.get(key, 0)
        if current_value < baseline_value:
            raise ControlArtifactError(
                "quota transaction-attempt counter reset"
            )
        bucket = key[-1]
        delta[bucket] += current_value - baseline_value
        if delta[bucket] > phase_evidence.MAX_COUNT:
            raise ControlArtifactError(
                "quota transaction-attempt count exceeded"
            )
    total = delta["+Inf"]
    if total <= 0 or delta["3.0"] != total:
        raise ControlArtifactError(
            "quota transaction-attempt observation is absent"
        )
    if not delta["1.0"] <= delta["2.0"] <= delta["3.0"]:
        raise ControlArtifactError(
            "quota transaction-attempt delta conflicts"
        )
    if delta["2.0"] < total:
        return 3
    if delta["1.0"] < total:
        return 2
    return 1


def compile_artifacts(
    config_value: object,
    target_value: object,
    baseline_value: object,
    current_value: object,
    *,
    target_file_sha256: str,
) -> dict[str, dict[str, Any]]:
    config, target, load_topology = _config(
        config_value,
        target_value,
        target_file_sha256=target_file_sha256,
    )
    baseline, baseline_observations = _capture(
        baseline_value,
        config=config,
        target=target,
        capture_kind="baseline",
    )
    current, current_observations = _capture(
        current_value,
        config=config,
        target=target,
        capture_kind="current",
    )
    if (
        baseline["completed_at_seconds"]
        > current["started_at_seconds"]
    ):
        raise ControlArtifactError("control capture order changed")
    edge_instances, reconcile_instances = _expected_instances(target)
    baseline_starts = _process_starts(
        baseline["prometheus"]["process_start"],
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    current_starts = _process_starts(
        current["prometheus"]["process_start"],
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    if any(
        value > baseline["completed_at_seconds"]
        for value in baseline_starts.values()
    ) or any(
        value > current["completed_at_seconds"]
        for value in current_starts.values()
    ):
        raise ControlArtifactError("control process-start time changed")
    if baseline_starts != current_starts:
        raise ControlArtifactError(
            "control metric process restarted during phase"
        )
    maximum_attempts = _maximum_attempts(
        baseline["prometheus"]["attempts"],
        current["prometheus"]["attempts"],
        edge_instances=edge_instances,
        reconcile_instances=reconcile_instances,
    )
    baseline_errors = _bounded_instance_values(
        baseline["prometheus"]["edge_internal_errors"],
        expected_instances=edge_instances,
        category="edge internal error",
    )
    current_errors = _bounded_instance_values(
        current["prometheus"]["edge_internal_errors"],
        expected_instances=edge_instances,
        category="edge internal error",
    )
    unexpected_errors = _counter_delta(
        baseline_errors,
        current_errors,
        "edge internal error",
    )
    reconcile_up = _bounded_instance_values(
        current["prometheus"]["reconcile_up"],
        expected_instances=reconcile_instances,
        category="reconciler up",
    )
    database_up = _bounded_instance_values(
        current["prometheus"]["reconcile_database_up"],
        expected_instances=reconcile_instances,
        category="reconciler database",
    )
    last_success = _bounded_instance_values(
        current["prometheus"]["reconcile_last_success"],
        expected_instances=reconcile_instances,
        category="reconciler success",
    )
    if any(value not in {0.0, 1.0} for value in reconcile_up.values()):
        raise ControlArtifactError("reconciler up state changed")
    if any(value not in {0.0, 1.0} for value in database_up.values()):
        raise ControlArtifactError("reconciler database state changed")
    observed_at = float(current["completed_at_seconds"])
    if any(
        value <= 0 or value > observed_at
        for value in last_success.values()
    ):
        raise ControlArtifactError("reconciler success time changed")
    last_success_age = max(
        observed_at - value for value in last_success.values()
    )
    if last_success_age > phase_evidence.MAX_FRESHNESS_SECONDS:
        raise ControlArtifactError("reconciler success is excessively stale")
    workers_total = len(reconcile_instances)
    if workers_total != int(load_topology["replicas"]["reconcile"]):
        raise ControlArtifactError("reconciler topology changed")
    workers_up = sum(int(value) for value in reconcile_up.values())
    fresh = (
        workers_up == workers_total
        and all(value == 1 for value in database_up.values())
        and last_success_age
        <= int(config["reconciliation_freshness_seconds"])
    )
    sql = current["sql"]
    charged = sql["used_bytes"] + sql["reserved_bytes"]
    limit = sql["limit_bytes"]
    if limit == 0:
        if charged:
            raise ControlArtifactError("zero quota has positive charge")
        usage_percent = 0.0
    else:
        usage_percent = charged / limit * 100.0
    if usage_percent > 100:
        raise ControlArtifactError("quota usage exceeds the limit")
    quota_payload = {
        "headroom_percent": 100.0 - usage_percent,
        "invariant": sql["quota_invariant"],
        "limit_usage_percent": usage_percent,
        "max_transaction_attempts": maximum_attempts,
        "stale_claims": sql["stale_claims"],
        "unexpected_errors": unexpected_errors,
    }
    reconciliation_payload = {
        "claims_exact": sql["claims_exact"],
        "fencing_violations": sql["claim_invariant_violations"],
        "fresh": fresh,
        "last_success_age_seconds": last_success_age,
        "stale_claims": sql["stale_claims"],
        "workers_total": workers_total,
        "workers_up": workers_up,
    }
    observations = baseline_observations + current_observations
    if not 1 <= observations <= source_summaries.MAX_OBSERVATIONS:
        raise ControlArtifactError("control observation count exceeded")
    input_set_sha256 = _hash(
        {
            "baseline_capture_sha256": baseline["capture_sha256"],
            "current_capture_sha256": current["capture_sha256"],
        }
    )
    artifacts: dict[str, dict[str, Any]] = {}
    for surface, aggregate in (
        ("quota", quota_payload),
        ("reconciliation", reconciliation_payload),
    ):
        normalized = phase_evidence._normalize_payload(
            surface,
            aggregate,
            load_topology=load_topology,
        )
        artifact = {
            "aggregate": normalized,
            "collector_source_sha256": config["collector_source_sha256"],
            "input_set_sha256": input_set_sha256,
            "observations": observations,
            "phase": config["phase"],
            "schema": source_summaries.ARTIFACT_SCHEMA,
            "source_class": phase_evidence.SOURCE_CLASSES[surface],
            "surface": surface,
            "target_sha256": target["target_sha256"],
            "window_sha256": config["window_sha256"],
        }
        artifact["artifact_sha256"] = _hash(artifact)
        try:
            load_contract.validate_retained_evidence(artifact)
            observability_contract.validate_retained_payload(artifact)
        except (
            load_contract.LoadSoakError,
            observability_contract.ContractError,
        ) as error:
            raise ControlArtifactError(
                f"{surface} control artifact is not retainable"
            ) from error
        artifacts[surface] = json.loads(
            json.dumps(artifact, separators=(",", ":"), sort_keys=True)
        )
    return artifacts


def _read_owner_bytes(
    path: Path,
    *,
    maximum_bytes: int,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ControlArtifactError("control collector input is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= maximum_bytes
        ):
            raise ControlArtifactError("control collector input is unsafe")
        payload = os.read(descriptor, maximum_bytes + 1)
        if len(payload) != metadata.st_size:
            raise ControlArtifactError("control collector input changed")
    except OSError as error:
        raise ControlArtifactError("control collector input is unavailable") from error
    finally:
        os.close(descriptor)
    return payload, metadata


def _read_owner_document(
    path: Path,
) -> tuple[object, bytes, os.stat_result]:
    payload, metadata = _read_owner_bytes(
        path,
        maximum_bytes=MAX_INPUT_BYTES,
    )
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ControlArtifactError("control collector input is invalid") from error
    if payload != _canonical(value):
        raise ControlArtifactError("control collector input is not canonical")
    return value, payload, metadata


def _distinct_inputs(
    files: Sequence[tuple[Path, os.stat_result]],
) -> None:
    paths = [path for path, _ in files]
    identities = [
        (metadata.st_dev, metadata.st_ino)
        for _, metadata in files
    ]
    if len(set(paths)) != len(paths) or len(set(identities)) != len(identities):
        raise ControlArtifactError("control collector inputs alias")


def _validated_output(
    path: Path,
    *,
    inputs: Sequence[tuple[Path, os.stat_result]],
) -> tuple[Path, os.stat_result | None]:
    path = _absolute_path(str(path), "control collector output")
    try:
        render_target._safe_output(path, request_path=inputs[0][0])
    except render_target.RenderError as error:
        raise ControlArtifactError("control collector output is unsafe") from error
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        metadata = None
    except OSError as error:
        raise ControlArtifactError("control collector output is unavailable") from error
    if metadata is not None and (metadata.st_dev, metadata.st_ino) in {
        (item.st_dev, item.st_ino) for _, item in inputs
    }:
        raise ControlArtifactError("control collector output aliases an input")
    return path, metadata


def _write_output(
    path: Path,
    value: object,
    *,
    inputs: Sequence[tuple[Path, os.stat_result]],
) -> None:
    path, _ = _validated_output(path, inputs=inputs)
    payload = _canonical(value)
    try:
        if path.exists() and path.read_bytes() == payload:
            return
        render_target._atomic_write(path, payload)
    except (OSError, render_target.RenderError) as error:
        raise ControlArtifactError(
            "control collector output is unavailable"
        ) from error


def capture_file(
    config_path: Path,
    capture_kind: str,
    output_path: Path,
    *,
    client: PrometheusClient | None = None,
    store_factory: Callable[[str], CaptureStore] = QuotaStore,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    config_path = _absolute_path(str(config_path), "control configuration")
    config_value, _, config_metadata = _read_owner_document(config_path)
    config_raw = _exact(
        config_value,
        {
            "ca_file",
            "ca_file_sha256",
            "collector_source_sha256",
            "phase",
            "reconciliation_freshness_seconds",
            "schema",
            "target_file",
            "target_file_sha256",
            "timeout_seconds",
            "window_sha256",
        },
        "control artifact configuration",
    )
    target_path = _absolute_path(config_raw["target_file"], "native target file")
    ca_path = _absolute_path(config_raw["ca_file"], "control collector CA file")
    target_value, target_payload, target_metadata = _read_owner_document(
        target_path
    )
    ca_payload, ca_metadata = _read_owner_bytes(
        ca_path,
        maximum_bytes=MAX_CA_BYTES,
    )
    inputs = [
        (config_path, config_metadata),
        (target_path, target_metadata),
        (ca_path, ca_metadata),
    ]
    _distinct_inputs(inputs)
    if _payload_hash(ca_payload) != config_raw["ca_file_sha256"]:
        raise ControlArtifactError("control collector CA hash changed")
    _config(
        config_value,
        target_value,
        target_file_sha256=_payload_hash(target_payload),
    )
    _validated_output(output_path, inputs=inputs)
    connection = os.environ.get(DATABASE_URL_ENV)
    project_id = os.environ.get(PROJECT_ID_ENV)
    if not connection or not project_id:
        raise ControlArtifactError(
            "control collector runtime input is unavailable"
        )
    capture = capture_snapshot(
        config_value,
        target_value,
        target_file_sha256=_payload_hash(target_payload),
        capture_kind=capture_kind,
        client=client or native_surfaces.VerifiedHTTPSClient(),
        store=store_factory(connection),
        project_id=project_id,
        ca_file=ca_path,
        clock=clock,
    )
    _write_output(output_path, capture, inputs=inputs)
    return capture


def compile_files(
    config_path: Path,
    baseline_path: Path,
    current_path: Path,
    quota_output_path: Path,
    reconciliation_output_path: Path,
) -> dict[str, dict[str, Any]]:
    config_path = _absolute_path(str(config_path), "control configuration")
    baseline_path = _absolute_path(str(baseline_path), "baseline capture")
    current_path = _absolute_path(str(current_path), "current capture")
    config_value, _, config_metadata = _read_owner_document(config_path)
    config_raw = _exact(
        config_value,
        {
            "ca_file",
            "ca_file_sha256",
            "collector_source_sha256",
            "phase",
            "reconciliation_freshness_seconds",
            "schema",
            "target_file",
            "target_file_sha256",
            "timeout_seconds",
            "window_sha256",
        },
        "control artifact configuration",
    )
    target_path = _absolute_path(config_raw["target_file"], "native target file")
    target_value, target_payload, target_metadata = _read_owner_document(
        target_path
    )
    baseline_value, _, baseline_metadata = _read_owner_document(baseline_path)
    current_value, _, current_metadata = _read_owner_document(current_path)
    inputs = [
        (config_path, config_metadata),
        (target_path, target_metadata),
        (baseline_path, baseline_metadata),
        (current_path, current_metadata),
    ]
    _distinct_inputs(inputs)
    artifacts = compile_artifacts(
        config_value,
        target_value,
        baseline_value,
        current_value,
        target_file_sha256=_payload_hash(target_payload),
    )
    outputs = (
        _absolute_path(str(quota_output_path), "quota artifact output"),
        _absolute_path(
            str(reconciliation_output_path),
            "reconciliation artifact output",
        ),
    )
    if outputs[0] == outputs[1]:
        raise ControlArtifactError("control artifact outputs alias")
    validated_outputs = [
        _validated_output(path, inputs=inputs) for path in outputs
    ]
    existing_output_identities = [
        (metadata.st_dev, metadata.st_ino)
        for _, metadata in validated_outputs
        if metadata is not None
    ]
    if len(existing_output_identities) != len(
        set(existing_output_identities)
    ):
        raise ControlArtifactError("control artifact outputs alias")
    _write_output(outputs[0], artifacts["quota"], inputs=inputs)
    _write_output(outputs[1], artifacts["reconciliation"], inputs=inputs)
    return artifacts


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        print(
            json.dumps(
                {
                    "collector_source_sha256": collector_source_sha256(),
                    "schema": RESULT_SCHEMA,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    try:
        if len(arguments) == 4 and arguments[0] == "capture":
            capture = capture_file(
                Path(arguments[1]),
                arguments[2],
                Path(arguments[3]),
            )
            print(
                json.dumps(
                    {
                        "capture_kind": capture["capture_kind"],
                        "capture_sha256": capture["capture_sha256"],
                        "schema": CAPTURE_RESULT_SCHEMA,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        if len(arguments) == 6 and arguments[0] == "compile":
            artifacts = compile_files(
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
                Path(arguments[4]),
                Path(arguments[5]),
            )
            print(
                json.dumps(
                    {
                        "artifacts": {
                            surface: artifacts[surface]["artifact_sha256"]
                            for surface in SURFACES
                        },
                        "schema": RESULT_SCHEMA,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
    except (
        ControlArtifactError,
        OSError,
        RuntimeError,
        ValueError,
    ):
        print("control-artifact-refused", file=sys.stderr)
        return 2
    print(
        "usage: control_artifacts.py source-hash | "
        "capture CONFIG baseline|current OUTPUT | "
        "compile CONFIG BASELINE CURRENT QUOTA_OUTPUT RECONCILIATION_OUTPUT",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
