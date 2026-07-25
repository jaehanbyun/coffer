from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import json
import math
from pathlib import Path
import re
import ssl
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_EXPOSITION_LINES = 20_000
MAX_SELECTED_SERIES = 512
MAX_LABELS = 16
MAX_LABEL_LENGTH = 256
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
METRIC_PATTERN = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]*$")
LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHA_UUID_PATTERN = re.compile(r"^[A-Fa-f0-9-]{8,64}$")
SAMPLE_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)"
    r"(?:\{(?P<labels>.*)\})?[ \t]+(?P<value>[^ \t]+)$"
)
PROMETHEUS_QUERY_KEYS = frozenset(
    {
        "direct_targets",
        "schema_mismatches",
        "scrape_interval_seconds",
        "secret_leaks",
        "stale_series",
    }
)
DIRECT_KINDS = frozenset({"counter", "process_start_seconds", "up"})
HAPROXY_STATES = ("DOWN", "UP", "MAINT", "DRAIN", "NOLB")
GALERA_METRICS = frozenset(
    {
        "mysql_galera_status_info",
        "mysql_global_status_wsrep_cluster_size",
        "mysql_global_status_wsrep_local_state",
        "mysql_up",
    }
)
CEPH_METADATA_METRIC = "ceph_rgw_metadata"
CEPH_SOCKET_METRIC = "ceph_daemon_socket_up"
NODE_METRICS = frozenset(
    {
        "node_filefd_allocated",
        "node_filefd_maximum",
        "node_filesystem_avail_bytes",
        "node_filesystem_size_bytes",
        "node_memory_MemAvailable_bytes",
        "node_memory_MemTotal_bytes",
        "node_timex_offset_seconds",
    }
)


class NativeSurfaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetricSample:
    name: str
    labels: tuple[tuple[str, str], ...]
    value: float

    @property
    def label_map(self) -> dict[str, str]:
        return dict(self.labels)


@dataclass(frozen=True)
class VectorSample:
    labels: tuple[tuple[str, str], ...]
    timestamp: float
    value: float

    @property
    def label_map(self) -> dict[str, str]:
        return dict(self.labels)


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise NativeSurfaceError(f"{category} boundary changed")
    return value


def _bounded_string(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_LABEL_LENGTH
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise NativeSurfaceError(f"{category} is invalid")
    return value


def _bounded_text(
    value: object,
    category: str,
    *,
    maximum: int = 8192,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
        or any(
            ord(character) < 32 and character not in "\n\r\t"
            for character in value
        )
    ):
        raise NativeSurfaceError(f"{category} is invalid")
    return value


def _number(
    value: object,
    category: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise NativeSurfaceError(f"{category} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise NativeSurfaceError(f"{category} is invalid") from error
    if (
        not math.isfinite(result)
        or (minimum is not None and result < minimum)
        or (maximum is not None and result > maximum)
    ):
        raise NativeSurfaceError(f"{category} is invalid")
    return result


def _integer(
    value: object,
    category: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    result = _number(
        value,
        category,
        minimum=float(minimum),
        maximum=None if maximum is None else float(maximum),
    )
    if not result.is_integer():
        raise NativeSurfaceError(f"{category} is invalid")
    return int(result)


def _validate_url(url: str) -> tuple[str, int, str]:
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise NativeSurfaceError("native telemetry URL is invalid")
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise NativeSurfaceError("native telemetry URL is invalid") from error
    host = parsed.hostname
    try:
        valid_ip = host is not None and bool(ipaddress.ip_address(host))
    except ValueError:
        valid_ip = False
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or host is None
        or port is None
        or not parsed.path.startswith("/")
        or parsed.fragment
        or (
            not valid_ip
            and HOST_PATTERN.fullmatch(host) is None
        )
    ):
        raise NativeSurfaceError("native telemetry URL is invalid")
    target = parsed.path
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return host, port, target


class VerifiedHTTPSClient:
    def _fetch(
        self,
        url: str,
        *,
        ca_file: Path,
        accept: str,
        allowed_content_types: frozenset[str],
        timeout_seconds: float,
    ) -> bytes:
        host, port, target = _validate_url(url)
        if timeout_seconds <= 0:
            raise NativeSurfaceError("native telemetry deadline expired")
        connection: http.client.HTTPSConnection | None = None
        try:
            context = ssl.create_default_context(cafile=str(ca_file))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            connection = http.client.HTTPSConnection(
                host,
                port,
                context=context,
                timeout=timeout_seconds,
            )
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": accept,
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "coffer-native-telemetry/1",
                },
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            content_encoding = response.getheader("Content-Encoding")
            length_value = response.getheader("Content-Length")
            if (
                response.status != 200
                or media_type not in allowed_content_types
                or content_encoding not in (None, "identity")
            ):
                raise NativeSurfaceError("native telemetry response failed")
            if length_value is not None:
                try:
                    content_length = int(length_value)
                except ValueError as error:
                    raise NativeSurfaceError(
                        "native telemetry response length is invalid"
                    ) from error
                if not 1 <= content_length <= MAX_RESPONSE_BYTES:
                    raise NativeSurfaceError(
                        "native telemetry response exceeded"
                    )
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if not payload or len(payload) > MAX_RESPONSE_BYTES:
                raise NativeSurfaceError("native telemetry response exceeded")
            return payload
        except NativeSurfaceError:
            raise
        except (
            OSError,
            ssl.SSLError,
            http.client.HTTPException,
        ) as error:
            raise NativeSurfaceError(
                "native telemetry transport failed"
            ) from error
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    def fetch_json(
        self,
        url: str,
        *,
        ca_file: Path,
        timeout_seconds: float,
    ) -> object:
        payload = self._fetch(
            url,
            ca_file=ca_file,
            accept="application/json",
            allowed_content_types=frozenset({"application/json"}),
            timeout_seconds=timeout_seconds,
        )
        try:
            return json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise NativeSurfaceError(
                "native telemetry JSON is invalid"
            ) from error

    def fetch_exposition(
        self,
        url: str,
        *,
        ca_file: Path,
        timeout_seconds: float,
    ) -> bytes:
        return self._fetch(
            url,
            ca_file=ca_file,
            accept=(
                "application/openmetrics-text; version=1.0.0, "
                "text/plain; version=0.0.4"
            ),
            allowed_content_types=frozenset(
                {"application/openmetrics-text", "text/plain"}
            ),
            timeout_seconds=timeout_seconds,
        )


def _api_data(value: object, category: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeSurfaceError(f"{category} response changed")
    allowed = {"data", "infos", "status", "warnings"}
    if not {"data", "status"} <= set(value) or not set(value) <= allowed:
        raise NativeSurfaceError(f"{category} response changed")
    if value["status"] != "success":
        raise NativeSurfaceError(f"{category} request failed")
    for optional in ("infos", "warnings"):
        if optional in value and value[optional] != []:
            raise NativeSurfaceError(f"{category} response is incomplete")
    if not isinstance(value["data"], Mapping):
        raise NativeSurfaceError(f"{category} data changed")
    return value["data"]


def _sample_pair(value: object, category: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise NativeSurfaceError(f"{category} sample changed")
    timestamp = _number(value[0], f"{category} timestamp", minimum=0)
    sample_value = _number(value[1], f"{category} value")
    return timestamp, sample_value


def parse_prometheus_vector(
    value: object,
    *,
    expected_labels: frozenset[str],
    maximum_series: int = MAX_SELECTED_SERIES,
) -> tuple[VectorSample, ...]:
    data = _exact(
        _api_data(value, "Prometheus query"),
        {"result", "resultType"},
        "Prometheus query data",
    )
    if data["resultType"] != "vector" or not isinstance(
        data["result"], list
    ):
        raise NativeSurfaceError("Prometheus query result changed")
    if not 0 <= len(data["result"]) <= maximum_series:
        raise NativeSurfaceError("Prometheus query series exceeded")
    samples: list[VectorSample] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for raw in data["result"]:
        sample = _exact(
            raw,
            {"metric", "value"},
            "Prometheus vector sample",
        )
        if (
            not isinstance(sample["metric"], Mapping)
            or set(sample["metric"]) != set(expected_labels)
        ):
            raise NativeSurfaceError("Prometheus vector labels changed")
        labels = tuple(
            sorted(
                (
                    _bounded_string(key, "Prometheus label name"),
                    _bounded_string(label, "Prometheus label value"),
                )
                for key, label in sample["metric"].items()
            )
        )
        if labels in seen:
            raise NativeSurfaceError("Prometheus vector series duplicated")
        seen.add(labels)
        timestamp, sample_value = _sample_pair(
            sample["value"],
            "Prometheus vector",
        )
        samples.append(VectorSample(labels, timestamp, sample_value))
    return tuple(sorted(samples, key=lambda item: item.labels))


def parse_prometheus_scalar(value: object) -> float:
    data = _exact(
        _api_data(value, "Prometheus query"),
        {"result", "resultType"},
        "Prometheus query data",
    )
    if data["resultType"] != "scalar":
        raise NativeSurfaceError("Prometheus scalar result changed")
    _, sample_value = _sample_pair(data["result"], "Prometheus scalar")
    return sample_value


def _bounded_mapping(value: object, category: str) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or len(value) > MAX_LABELS
        or any(
            not isinstance(key, str)
            or LABEL_PATTERN.fullmatch(key) is None
            or not isinstance(item, str)
            or len(item) > MAX_LABEL_LENGTH
            or "\x00" in item
            or any(ord(character) < 32 for character in item)
            for key, item in value.items()
        )
    ):
        raise NativeSurfaceError(f"{category} changed")
    return value


def parse_prometheus_rules(
    value: object,
    *,
    required_recording_rules: Sequence[str],
    required_alerts: Sequence[str],
) -> tuple[list[str], list[str], list[str]]:
    data = _api_data(value, "Prometheus rules")
    if not {"groups"} <= set(data) or not set(data) <= {
        "groups",
        "groupNextToken",
    }:
        raise NativeSurfaceError("Prometheus rules data changed")
    if data.get("groupNextToken") not in (None, ""):
        raise NativeSurfaceError("Prometheus rules response is paginated")
    groups = data["groups"]
    if not isinstance(groups, list) or not 1 <= len(groups) <= 16:
        raise NativeSurfaceError("Prometheus rule groups changed")
    expected_recording = set(required_recording_rules)
    expected_alerting = set(required_alerts)
    if (
        len(expected_recording) != len(required_recording_rules)
        or len(expected_alerting) != len(required_alerts)
    ):
        raise NativeSurfaceError("Prometheus expected rules duplicated")
    recording: set[str] = set()
    alerting: set[str] = set()
    firing: set[str] = set()
    for raw_group in groups:
        group = _exact(
            raw_group,
            {
                "evaluationTime",
                "file",
                "interval",
                "lastEvaluation",
                "limit",
                "name",
                "rules",
            },
            "Prometheus rule group",
        )
        _bounded_string(group["name"], "Prometheus rule group name")
        _bounded_string(group["file"], "Prometheus rule group file")
        _number(group["interval"], "Prometheus rule interval", minimum=1)
        _number(
            group["evaluationTime"],
            "Prometheus rule evaluation time",
            minimum=0,
        )
        _integer(group["limit"], "Prometheus rule limit")
        _bounded_string(
            group["lastEvaluation"],
            "Prometheus rule last evaluation",
        )
        rules = group["rules"]
        if not isinstance(rules, list) or not 1 <= len(rules) <= 64:
            raise NativeSurfaceError("Prometheus rules changed")
        for raw_rule in rules:
            if not isinstance(raw_rule, Mapping):
                raise NativeSurfaceError("Prometheus rule changed")
            rule_type = raw_rule.get("type")
            common = {
                "evaluationTime",
                "health",
                "labels",
                "lastEvaluation",
                "name",
                "query",
                "type",
            }
            optional = {"lastError"}
            if rule_type == "recording":
                allowed = common | optional
                if set(raw_rule) not in (common, allowed):
                    raise NativeSurfaceError("Prometheus recording rule changed")
                name = _bounded_string(
                    raw_rule["name"],
                    "Prometheus recording rule name",
                )
                if name not in expected_recording or name in recording:
                    raise NativeSurfaceError(
                        "Prometheus recording rule set changed"
                    )
                recording.add(name)
            elif rule_type == "alerting":
                alert_fields = {
                    "alerts",
                    "annotations",
                    "duration",
                    "keepFiringFor",
                    "state",
                }
                required = common | alert_fields
                if set(raw_rule) not in (required, required | optional):
                    raise NativeSurfaceError("Prometheus alerting rule changed")
                name = _bounded_string(
                    raw_rule["name"],
                    "Prometheus alert name",
                )
                if name not in expected_alerting or name in alerting:
                    raise NativeSurfaceError("Prometheus alert rule set changed")
                state = raw_rule["state"]
                if state not in {"firing", "inactive", "pending"}:
                    raise NativeSurfaceError("Prometheus alert state changed")
                alerts = raw_rule["alerts"]
                if not isinstance(alerts, list) or len(alerts) > 64:
                    raise NativeSurfaceError("Prometheus active alerts changed")
                if state == "inactive" and alerts:
                    raise NativeSurfaceError("Prometheus alert state conflicts")
                for raw_alert in alerts:
                    if not isinstance(raw_alert, Mapping):
                        raise NativeSurfaceError(
                            "Prometheus active alert changed"
                        )
                    required_alert_fields = {
                        "annotations",
                        "labels",
                        "state",
                        "value",
                    }
                    optional_alert_fields = {
                        "activeAt",
                        "keepFiringSince",
                    }
                    if (
                        not required_alert_fields <= set(raw_alert)
                        or not set(raw_alert)
                        <= required_alert_fields | optional_alert_fields
                    ):
                        raise NativeSurfaceError(
                            "Prometheus active alert changed"
                        )
                    _bounded_mapping(
                        raw_alert["annotations"],
                        "Prometheus active alert annotations",
                    )
                    _bounded_mapping(
                        raw_alert["labels"],
                        "Prometheus active alert labels",
                    )
                    if raw_alert["state"] not in {"firing", "pending"}:
                        raise NativeSurfaceError(
                            "Prometheus active alert state changed"
                        )
                    _number(
                        raw_alert["value"],
                        "Prometheus active alert value",
                    )
                    for optional_field in optional_alert_fields:
                        if optional_field in raw_alert:
                            _bounded_string(
                                raw_alert[optional_field],
                                "Prometheus active alert time",
                            )
                _bounded_mapping(
                    raw_rule["annotations"],
                    "Prometheus annotations",
                )
                _number(
                    raw_rule["duration"],
                    "Prometheus alert duration",
                    minimum=0,
                )
                _number(
                    raw_rule["keepFiringFor"],
                    "Prometheus keep-firing duration",
                    minimum=0,
                )
                alerting.add(name)
                if state == "firing":
                    firing.add(name)
            else:
                raise NativeSurfaceError("Prometheus rule type changed")
            _bounded_text(raw_rule["query"], "Prometheus rule query")
            _bounded_mapping(raw_rule["labels"], "Prometheus rule labels")
            if raw_rule["health"] != "ok":
                raise NativeSurfaceError("Prometheus rule is unhealthy")
            _number(
                raw_rule["evaluationTime"],
                "Prometheus rule evaluation time",
                minimum=0,
            )
            _bounded_string(
                raw_rule["lastEvaluation"],
                "Prometheus rule last evaluation",
            )
            if raw_rule.get("lastError") not in (None, ""):
                raise NativeSurfaceError("Prometheus rule has an error")
    if recording != expected_recording or alerting != expected_alerting:
        raise NativeSurfaceError("Prometheus required rules are incomplete")
    return (
        list(required_recording_rules),
        list(required_alerts),
        sorted(firing),
    )


def parse_prometheus_surface(
    query_documents: Mapping[str, object],
    rules_document: object,
    *,
    expected_instances: Mapping[str, Sequence[str]],
    required_recording_rules: Sequence[str],
    required_alerts: Sequence[str],
) -> dict[str, Any]:
    if set(query_documents) != PROMETHEUS_QUERY_KEYS:
        raise NativeSurfaceError("Prometheus query set changed")
    vector = parse_prometheus_vector(
        query_documents["direct_targets"],
        expected_labels=frozenset({"component", "instance", "kind"}),
    )
    values: dict[tuple[str, str, str], float] = {}
    timestamps: set[float] = set()
    for sample in vector:
        labels = sample.label_map
        component = labels["component"]
        instance = labels["instance"]
        kind = labels["kind"]
        if (
            component not in expected_instances
            or instance not in expected_instances[component]
            or kind not in DIRECT_KINDS
        ):
            raise NativeSurfaceError("Prometheus direct target changed")
        key = (component, instance, kind)
        if key in values:
            raise NativeSurfaceError("Prometheus direct target duplicated")
        values[key] = sample.value
        timestamps.add(sample.timestamp)
    if len(timestamps) != 1:
        raise NativeSurfaceError("Prometheus direct query time changed")
    targets: dict[str, list[dict[str, Any]]] = {}
    for component, instances_value in expected_instances.items():
        instances = tuple(instances_value)
        if (
            not instances
            or len(set(instances)) != len(instances)
            or any(
                HOST_PATTERN.fullmatch(instance) is None
                for instance in instances
            )
        ):
            raise NativeSurfaceError("Prometheus target identity is invalid")
        entries: list[dict[str, Any]] = []
        for instance in instances:
            keys = {
                kind: values.get((component, instance, kind))
                for kind in DIRECT_KINDS
            }
            if any(value is None for value in keys.values()):
                raise NativeSurfaceError("Prometheus direct target incomplete")
            entries.append(
                {
                    "counter": _number(
                        keys["counter"],
                        "Prometheus target counter",
                        minimum=0,
                    ),
                    "instance": instance,
                    "process_start_seconds": _number(
                        keys["process_start_seconds"],
                        "Prometheus process start",
                        minimum=0,
                    ),
                    "up": _integer(
                        keys["up"],
                        "Prometheus target availability",
                        maximum=1,
                    ),
                }
            )
        targets[component] = entries
    expected_count = sum(len(value) for value in expected_instances.values())
    if len(values) != expected_count * len(DIRECT_KINDS):
        raise NativeSurfaceError("Prometheus direct target series changed")
    recording, alerts, firing = parse_prometheus_rules(
        rules_document,
        required_recording_rules=required_recording_rules,
        required_alerts=required_alerts,
    )
    return {
        "alerts_loaded": alerts,
        "direct_targets": targets,
        "firing_alerts": firing,
        "recording_rules_loaded": recording,
        "schema_mismatches": _integer(
            parse_prometheus_scalar(query_documents["schema_mismatches"]),
            "Prometheus schema mismatches",
        ),
        "scrape_interval_seconds": _integer(
            parse_prometheus_scalar(
                query_documents["scrape_interval_seconds"]
            ),
            "Prometheus scrape interval",
            minimum=1,
        ),
        "secret_leaks": _integer(
            parse_prometheus_scalar(query_documents["secret_leaks"]),
            "Prometheus secret leak evidence",
        ),
        "stale_series": _integer(
            parse_prometheus_scalar(query_documents["stale_series"]),
            "Prometheus stale series",
        ),
    }


def _parse_labels(value: str) -> tuple[tuple[str, str], ...]:
    labels: list[tuple[str, str]] = []
    index = 0
    while index < len(value):
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[index:])
        if match is None:
            raise NativeSurfaceError("exporter label syntax changed")
        name = match.group(0)
        index += len(name)
        if index >= len(value) or value[index] != "=":
            raise NativeSurfaceError("exporter label syntax changed")
        index += 1
        if index >= len(value) or value[index] != '"':
            raise NativeSurfaceError("exporter label syntax changed")
        index += 1
        characters: list[str] = []
        while index < len(value):
            character = value[index]
            index += 1
            if character == '"':
                break
            if character == "\\":
                if index >= len(value):
                    raise NativeSurfaceError("exporter label escape changed")
                escaped = value[index]
                index += 1
                if escaped == "n":
                    characters.append("\n")
                elif escaped in {'"', "\\"}:
                    characters.append(escaped)
                else:
                    raise NativeSurfaceError("exporter label escape changed")
            else:
                if ord(character) < 32:
                    raise NativeSurfaceError("exporter label value is invalid")
                characters.append(character)
        else:
            raise NativeSurfaceError("exporter label syntax changed")
        label = "".join(characters)
        if len(label) > MAX_LABEL_LENGTH:
            raise NativeSurfaceError("exporter label value exceeded")
        labels.append((name, label))
        if len(labels) > MAX_LABELS:
            raise NativeSurfaceError("exporter labels exceeded")
        if index == len(value):
            break
        if value[index] != ",":
            raise NativeSurfaceError("exporter label syntax changed")
        index += 1
    if len(dict(labels)) != len(labels):
        raise NativeSurfaceError("exporter label duplicated")
    return tuple(sorted(labels))


def parse_exposition(
    payload: bytes,
    *,
    selected_metrics: frozenset[str],
) -> dict[str, tuple[MetricSample, ...]]:
    if not payload or len(payload) > MAX_RESPONSE_BYTES:
        raise NativeSurfaceError("exporter response exceeded")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as error:
        raise NativeSurfaceError("exporter response is invalid") from error
    lines = text.splitlines()
    if not lines or len(lines) > MAX_EXPOSITION_LINES:
        raise NativeSurfaceError("exporter response lines exceeded")
    if (
        not selected_metrics
        or any(METRIC_PATTERN.fullmatch(name) is None for name in selected_metrics)
    ):
        raise NativeSurfaceError("exporter metric allowlist is invalid")
    samples: dict[str, list[MetricSample]] = {
        name: [] for name in selected_metrics
    }
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    selected_count = 0
    for line in lines:
        if len(line) > 16_384 or "\x00" in line:
            raise NativeSurfaceError("exporter line is invalid")
        if not line or line.startswith("#"):
            continue
        name_match = re.match(r"^([A-Za-z_:][A-Za-z0-9_:]*)", line)
        if name_match is None:
            raise NativeSurfaceError("exporter sample syntax changed")
        name = name_match.group(1)
        if name not in selected_metrics:
            continue
        match = SAMPLE_PATTERN.fullmatch(line)
        if match is None:
            raise NativeSurfaceError("selected exporter sample changed")
        labels = _parse_labels(match.group("labels") or "")
        value = _number(match.group("value"), "exporter sample")
        identity = (name, labels)
        if identity in seen:
            raise NativeSurfaceError("selected exporter series duplicated")
        seen.add(identity)
        samples[name].append(MetricSample(name, labels, value))
        selected_count += 1
        if selected_count > MAX_SELECTED_SERIES:
            raise NativeSurfaceError("selected exporter series exceeded")
    return {
        name: tuple(sorted(entries, key=lambda sample: sample.labels))
        for name, entries in samples.items()
    }


def _haproxy_backends(
    payload: bytes,
    *,
    backend_targets: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, int]]:
    selected = parse_exposition(
        payload,
        selected_metrics=frozenset({"haproxy_server_status"}),
    )["haproxy_server_status"]
    proxies: dict[str, tuple[str, tuple[str, ...]]] = {}
    for component, raw_target in backend_targets.items():
        target = _exact(
            raw_target,
            {"proxy", "servers"},
            "HAProxy backend target",
        )
        proxy = _bounded_string(target["proxy"], "HAProxy proxy")
        servers_value = target["servers"]
        if (
            not isinstance(servers_value, Sequence)
            or isinstance(servers_value, (str, bytes))
        ):
            raise NativeSurfaceError("HAProxy server allowlist changed")
        servers = tuple(
            _bounded_string(server, "HAProxy server")
            for server in servers_value
        )
        if not servers or len(set(servers)) != len(servers):
            raise NativeSurfaceError("HAProxy server allowlist changed")
        proxies[component] = (proxy, servers)
    if len({proxy for proxy, _ in proxies.values()}) != len(proxies):
        raise NativeSurfaceError("HAProxy proxies are not unique")
    by_proxy = {
        proxy: (component, servers)
        for component, (proxy, servers) in proxies.items()
    }
    states: dict[tuple[str, str], dict[str, int]] = {}
    for sample in selected:
        labels = sample.label_map
        if set(labels) != {"proxy", "server", "state"}:
            raise NativeSurfaceError("HAProxy server labels changed")
        proxy = labels["proxy"]
        if proxy not in by_proxy:
            continue
        component, expected_servers = by_proxy[proxy]
        server = labels["server"]
        state = labels["state"]
        if server not in expected_servers or state not in HAPROXY_STATES:
            raise NativeSurfaceError("HAProxy selected backend changed")
        value = _integer(
            sample.value,
            "HAProxy server status",
            maximum=1,
        )
        state_values = states.setdefault((component, server), {})
        if state in state_values:
            raise NativeSurfaceError("HAProxy server state duplicated")
        state_values[state] = value
    result: dict[str, dict[str, int]] = {}
    for component, (_, servers) in proxies.items():
        healthy = 0
        for server in servers:
            state_values = states.get((component, server))
            if (
                state_values is None
                or set(state_values) != set(HAPROXY_STATES)
                or sum(state_values.values()) != 1
            ):
                raise NativeSurfaceError("HAProxy server state incomplete")
            healthy += state_values["UP"]
        result[component] = {"healthy": healthy, "total": len(servers)}
    if len(states) != sum(len(servers) for _, servers in proxies.values()):
        raise NativeSurfaceError("HAProxy selected series changed")
    return result


def parse_haproxy_surface(
    payload: bytes,
    *,
    backend_targets: Mapping[str, Mapping[str, object]],
    unexpected_errors: int,
) -> dict[str, Any]:
    return {
        "backends": _haproxy_backends(
            payload,
            backend_targets=backend_targets,
        ),
        "unexpected_errors": _integer(
            unexpected_errors,
            "HAProxy unexpected errors",
        ),
    }


def _single_metric(
    parsed: Mapping[str, tuple[MetricSample, ...]],
    name: str,
    labels: frozenset[str],
) -> MetricSample:
    samples = parsed[name]
    if len(samples) != 1 or set(samples[0].label_map) != set(labels):
        raise NativeSurfaceError(f"{name} series changed")
    return samples[0]


def parse_galera_surface(
    payloads: Mapping[str, bytes],
    *,
    max_transaction_attempts: int,
    unexpected_errors: int,
) -> dict[str, Any]:
    if not payloads or len(payloads) > 16:
        raise NativeSurfaceError("Galera target set changed")
    cluster_ids: set[str] = set()
    nodes_primary = 0
    nodes_ready = 0
    nodes_synced = 0
    total = len(payloads)
    for instance, payload in payloads.items():
        if HOST_PATTERN.fullmatch(instance) is None:
            raise NativeSurfaceError("Galera instance is invalid")
        parsed = parse_exposition(payload, selected_metrics=GALERA_METRICS)
        up = _integer(
            _single_metric(parsed, "mysql_up", frozenset()).value,
            "mysql_up",
            maximum=1,
        )
        cluster_size = _integer(
            _single_metric(
                parsed,
                "mysql_global_status_wsrep_cluster_size",
                frozenset(),
            ).value,
            "wsrep cluster size",
            minimum=1,
        )
        local_state = _integer(
            _single_metric(
                parsed,
                "mysql_global_status_wsrep_local_state",
                frozenset(),
            ).value,
            "wsrep local state",
            maximum=4,
        )
        info = _single_metric(
            parsed,
            "mysql_galera_status_info",
            frozenset(
                {
                    "wsrep_cluster_state_uuid",
                    "wsrep_local_state_uuid",
                    "wsrep_provider_version",
                }
            ),
        )
        if info.value != 1:
            raise NativeSurfaceError("Galera status info changed")
        info_labels = info.label_map
        cluster_id = info_labels["wsrep_cluster_state_uuid"]
        local_id = info_labels["wsrep_local_state_uuid"]
        if (
            SHA_UUID_PATTERN.fullmatch(cluster_id) is None
            or local_id != cluster_id
            or not info_labels["wsrep_provider_version"]
        ):
            raise NativeSurfaceError("Galera cluster identity changed")
        cluster_ids.add(cluster_id)
        synced = up == 1 and local_state == 4
        nodes_ready += int(synced)
        nodes_synced += int(synced)
        nodes_primary += int(synced and cluster_size == total)
    if len(cluster_ids) != 1:
        raise NativeSurfaceError("Galera cluster split detected")
    return {
        "max_transaction_attempts": _integer(
            max_transaction_attempts,
            "Galera transaction attempts",
            minimum=1,
        ),
        "nodes_primary": nodes_primary,
        "nodes_ready": nodes_ready,
        "nodes_synced": nodes_synced,
        "nodes_total": total,
        "unexpected_errors": _integer(
            unexpected_errors,
            "Galera unexpected errors",
        ),
    }


def parse_rgw_surface(
    metadata_payload: bytes,
    socket_payload: bytes,
    ingress_payload: bytes,
    *,
    expected_daemons: Mapping[str, str],
    ingress_target: Mapping[str, object],
    kms_errors: int,
    multipart_uploads: int,
    unexpected_errors: int,
) -> dict[str, Any]:
    if not expected_daemons or len(expected_daemons) > 32:
        raise NativeSurfaceError("RGW daemon target set changed")
    expected = {
        _bounded_string(daemon, "RGW daemon"): _bounded_string(
            host,
            "RGW host",
        )
        for daemon, host in expected_daemons.items()
    }
    if any(not daemon.startswith("rgw.") for daemon in expected):
        raise NativeSurfaceError("RGW daemon identity changed")
    metadata = parse_exposition(
        metadata_payload,
        selected_metrics=frozenset({CEPH_METADATA_METRIC}),
    )[CEPH_METADATA_METRIC]
    seen_metadata: set[str] = set()
    for sample in metadata:
        labels = sample.label_map
        daemon = labels.get("ceph_daemon")
        if daemon not in expected:
            if isinstance(daemon, str) and daemon.startswith("rgw."):
                raise NativeSurfaceError("RGW metadata target changed")
            continue
        if (
            set(labels)
            != {"ceph_daemon", "ceph_version", "hostname", "instance_id"}
            or labels["hostname"] != expected[daemon]
            or not labels["ceph_version"]
            or not labels["instance_id"]
            or sample.value != 1
            or daemon in seen_metadata
        ):
            raise NativeSurfaceError("RGW metadata changed")
        seen_metadata.add(daemon)
    if seen_metadata != set(expected):
        raise NativeSurfaceError("RGW metadata incomplete")
    sockets = parse_exposition(
        socket_payload,
        selected_metrics=frozenset({CEPH_SOCKET_METRIC}),
    )[CEPH_SOCKET_METRIC]
    socket_values: dict[str, int] = {}
    for sample in sockets:
        labels = sample.label_map
        daemon = labels.get("ceph_daemon")
        if daemon not in expected:
            if isinstance(daemon, str) and daemon.startswith("rgw."):
                raise NativeSurfaceError("RGW socket target changed")
            continue
        if (
            set(labels) != {"ceph_daemon", "hostname"}
            or labels["hostname"] != expected[daemon]
            or daemon in socket_values
        ):
            raise NativeSurfaceError("RGW socket series changed")
        socket_values[daemon] = _integer(
            sample.value,
            "RGW socket availability",
            maximum=1,
        )
    if set(socket_values) != set(expected):
        raise NativeSurfaceError("RGW socket evidence incomplete")
    ingress = _haproxy_backends(
        ingress_payload,
        backend_targets={"rgw-ingress": ingress_target},
    )["rgw-ingress"]
    return {
        "daemons_total": len(expected),
        "daemons_up": sum(socket_values.values()),
        "ingress_total": ingress["total"],
        "ingress_up": ingress["healthy"],
        "kms_errors": _integer(kms_errors, "RGW KMS errors"),
        "multipart_uploads": _integer(
            multipart_uploads,
            "RGW multipart uploads",
        ),
        "unexpected_errors": _integer(
            unexpected_errors,
            "RGW unexpected errors",
        ),
    }


def _vector_by_instance(
    value: object,
    category: str,
    expected_instances: set[str],
) -> dict[str, float]:
    samples = parse_prometheus_vector(
        value,
        expected_labels=frozenset({"instance"}),
        maximum_series=len(expected_instances),
    )
    result: dict[str, float] = {}
    for sample in samples:
        instance = sample.label_map["instance"]
        if instance not in expected_instances or instance in result:
            raise NativeSurfaceError(f"{category} targets changed")
        result[instance] = sample.value
    if set(result) != expected_instances:
        raise NativeSurfaceError(f"{category} targets incomplete")
    return result


def parse_hosts_surface(
    payloads: Mapping[str, bytes],
    *,
    roles: Mapping[str, str],
    cpu_usage_document: object,
    oom_kills_document: object,
    mountpoint: str = "/",
) -> list[dict[str, Any]]:
    if (
        not payloads
        or set(payloads) != set(roles)
        or len(payloads) > 64
        or mountpoint != "/"
    ):
        raise NativeSurfaceError("node-exporter target set changed")
    expected_instances = set(payloads)
    cpu_usage = _vector_by_instance(
        cpu_usage_document,
        "node CPU query",
        expected_instances,
    )
    oom_kills = _vector_by_instance(
        oom_kills_document,
        "node OOM query",
        expected_instances,
    )
    result: list[dict[str, Any]] = []
    for instance in sorted(payloads):
        role = roles[instance]
        if (
            HOST_PATTERN.fullmatch(instance) is None
            or role not in {"controller", "storage"}
        ):
            raise NativeSurfaceError("node-exporter identity changed")
        parsed = parse_exposition(
            payloads[instance],
            selected_metrics=NODE_METRICS,
        )
        total_memory = _number(
            _single_metric(
                parsed,
                "node_memory_MemTotal_bytes",
                frozenset(),
            ).value,
            "node total memory",
            minimum=1,
        )
        available_memory = _number(
            _single_metric(
                parsed,
                "node_memory_MemAvailable_bytes",
                frozenset(),
            ).value,
            "node available memory",
            minimum=0,
            maximum=total_memory,
        )
        allocated_fds = _number(
            _single_metric(
                parsed,
                "node_filefd_allocated",
                frozenset(),
            ).value,
            "node allocated file descriptors",
            minimum=0,
        )
        maximum_fds = _number(
            _single_metric(
                parsed,
                "node_filefd_maximum",
                frozenset(),
            ).value,
            "node maximum file descriptors",
            minimum=1,
        )
        if allocated_fds > maximum_fds:
            raise NativeSurfaceError("node file descriptor values changed")
        clock_offset = _number(
            _single_metric(
                parsed,
                "node_timex_offset_seconds",
                frozenset(),
            ).value,
            "node clock offset",
        )
        filesystem: dict[str, tuple[float, Mapping[str, str]]] = {}
        for metric_name in (
            "node_filesystem_avail_bytes",
            "node_filesystem_size_bytes",
        ):
            selected = []
            for sample in parsed[metric_name]:
                labels = sample.label_map
                if set(labels) != {
                    "device",
                    "device_error",
                    "fstype",
                    "mountpoint",
                }:
                    raise NativeSurfaceError(
                        "node filesystem labels changed"
                    )
                if labels["mountpoint"] == mountpoint:
                    selected.append(sample)
            if len(selected) != 1:
                raise NativeSurfaceError("node root filesystem changed")
            filesystem[metric_name] = (
                _number(
                    selected[0].value,
                    metric_name,
                    minimum=0,
                ),
                selected[0].label_map,
            )
        size, size_labels = filesystem["node_filesystem_size_bytes"]
        available, available_labels = filesystem[
            "node_filesystem_avail_bytes"
        ]
        if (
            size <= 0
            or available > size
            or size_labels != available_labels
            or size_labels["device_error"] != "0"
        ):
            raise NativeSurfaceError("node filesystem values changed")
        result.append(
            {
                "clock_offset_milliseconds": clock_offset * 1000,
                "cpu_usage_percent": _number(
                    cpu_usage[instance],
                    "node CPU usage",
                    minimum=0,
                    maximum=100,
                ),
                "disk_usage_percent": (1 - available / size) * 100,
                "file_descriptor_usage_percent": (
                    allocated_fds / maximum_fds
                )
                * 100,
                "instance": instance,
                "memory_usage_percent": (
                    1 - available_memory / total_memory
                )
                * 100,
                "oom_kills": _integer(
                    oom_kills[instance],
                    "node OOM kills",
                ),
                "role": role,
            }
        )
    return result


def parse_quota_surface(value: object) -> dict[str, Any]:
    quota = _exact(
        value,
        {
            "headroom_percent",
            "invariant",
            "limit_usage_percent",
            "max_transaction_attempts",
            "stale_claims",
            "unexpected_errors",
        },
        "quota evidence",
    )
    invariant = quota["invariant"]
    if not isinstance(invariant, bool):
        raise NativeSurfaceError("quota invariant is invalid")
    return {
        "headroom_percent": _number(
            quota["headroom_percent"],
            "quota headroom",
            minimum=0,
            maximum=100,
        ),
        "invariant": invariant,
        "limit_usage_percent": _number(
            quota["limit_usage_percent"],
            "quota usage",
            minimum=0,
            maximum=100,
        ),
        "max_transaction_attempts": _integer(
            quota["max_transaction_attempts"],
            "quota transaction attempts",
            minimum=1,
        ),
        "stale_claims": _integer(
            quota["stale_claims"],
            "quota stale claims",
        ),
        "unexpected_errors": _integer(
            quota["unexpected_errors"],
            "quota unexpected errors",
        ),
    }


def parse_reconciliation_surface(value: object) -> dict[str, Any]:
    reconciliation = _exact(
        value,
        {
            "claims_exact",
            "fencing_violations",
            "fresh",
            "last_success_age_seconds",
            "stale_claims",
            "workers_total",
            "workers_up",
        },
        "reconciliation evidence",
    )
    claims_exact = reconciliation["claims_exact"]
    fresh = reconciliation["fresh"]
    if not isinstance(claims_exact, bool) or not isinstance(fresh, bool):
        raise NativeSurfaceError("reconciliation boolean evidence changed")
    workers_total = _integer(
        reconciliation["workers_total"],
        "reconciliation worker total",
        minimum=1,
    )
    return {
        "claims_exact": claims_exact,
        "fencing_violations": _integer(
            reconciliation["fencing_violations"],
            "reconciliation fencing violations",
        ),
        "fresh": fresh,
        "last_success_age_seconds": _number(
            reconciliation["last_success_age_seconds"],
            "reconciliation freshness",
            minimum=0,
        ),
        "stale_claims": _integer(
            reconciliation["stale_claims"],
            "reconciliation stale claims",
        ),
        "workers_total": workers_total,
        "workers_up": _integer(
            reconciliation["workers_up"],
            "reconciliation workers up",
            maximum=workers_total,
        ),
    }
