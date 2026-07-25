from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit


DIRECTORY = Path(__file__).resolve().parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


native_surfaces = _module(
    "coffer_load_native_target_surfaces",
    DIRECTORY / "native_surfaces.py",
)

TARGET_SCHEMA = "coffer.load-telemetry-native-target/v1"
EVIDENCE_SCHEMA = "coffer.load-telemetry-native-evidence/v1"
ADAPTER = "stage6-native-telemetry-adapter"
TARGET_CLASS = "disposable-stage6-pilot"
PHASES = ("before", "during", "after")
SURFACES = (
    "prometheus",
    "haproxy",
    "galera",
    "rgw",
    "quota",
    "reconciliation",
    "hosts",
)
DIRECT_COMPONENTS = ("api", "edge", "reconcile", "registry")
JSON_CONTENT_TYPES = ("application/json",)
EXPOSITION_CONTENT_TYPES = (
    "application/openmetrics-text",
    "text/plain",
)
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_AUXILIARY_DEPTH = 8
MAX_AUXILIARY_KEYS = 32
MAX_AUXILIARY_ITEMS = 64
MAX_AUXILIARY_STRING = 256

PROMQL = {
    "direct_targets": (
        'label_replace(sum by (component, instance) '
        '(label_replace(up{job=~"coffer-(api|edge|registry|reconcile)"},'
        '"component","$1","job",'
        '"coffer-(api|edge|registry|reconcile)")),'
        '"kind","up","component",".+") '
        "or "
        'label_replace(max by (component, instance) '
        '(coffer_process_start_time_seconds{'
        'job=~"coffer-(api|edge|reconcile)",'
        'component=~"api|edge|reconcile"}),'
        '"kind","process_start_seconds","component",".+") '
        "or "
        'label_replace(label_replace(max by (instance) '
        '(process_start_time_seconds{job="coffer-registry"}),'
        '"component","registry","instance",".+"),'
        '"kind","process_start_seconds","component",".+") '
        "or "
        'label_replace(sum by (component, instance) '
        '(coffer_http_requests_total{job=~"coffer-(api|edge)",'
        'component=~"api|edge"}),'
        '"kind","counter","component",".+") '
        "or "
        'label_replace(label_replace(sum by (instance) '
        '(coffer_reconciliation_cycles_total{job="coffer-reconcile"}),'
        '"component","reconcile","instance",".+"),'
        '"kind","counter","component",".+") '
        "or "
        'label_replace(label_replace(sum by (instance) '
        '(registry_http_requests_total{job="coffer-registry"}),'
        '"component","registry","instance",".+"),'
        '"kind","counter","component",".+")'
    ),
    "schema_mismatches": (
        'scalar(count(ALERTS{alertname="CofferMetricsSchemaMismatch",'
        'alertstate="firing"}) or vector(0))'
    ),
    "scrape_interval_seconds": (
        'scalar(round(max(prometheus_target_interval_length_seconds{'
        'interval="30s",quantile="0.5"})))'
    ),
    "stale_series": (
        "scalar(count("
        '(up{job=~"coffer-(api|edge|registry|reconcile)"} == 0) '
        "or "
        '((time() - timestamp(up{'
        'job=~"coffer-(api|edge|registry|reconcile)"})) > 90)'
        ") or vector(0))"
    ),
    "host_cpu_usage_percent": (
        '100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{'
        'job="node",mode="idle"}[5m])))'
    ),
    "host_oom_kills": (
        'round(sum by (instance) (increase(node_vmstat_oom_kill{'
        'job="node"}[5m])))'
    ),
}
PROMETHEUS_SURFACE_QUERIES = frozenset(
    {
        "direct_targets",
        "schema_mismatches",
        "scrape_interval_seconds",
        "stale_series",
    }
)
HOST_QUERIES = frozenset(
    {"host_cpu_usage_percent", "host_oom_kills"}
)


class NativeTargetError(RuntimeError):
    pass


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def wall_time(self) -> float: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall_time(self) -> float:
        return time.time()


@dataclass(frozen=True)
class ValidatedTarget:
    raw: Mapping[str, Any]
    target_sha256: str


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise NativeTargetError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _text_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _name(value: object, category: str) -> str:
    if not isinstance(value, str) or NAME_PATTERN.fullmatch(value) is None:
        raise NativeTargetError(f"{category} is invalid")
    return value


def _host(value: object, category: str) -> str:
    if not isinstance(value, str) or HOST_PATTERN.fullmatch(value) is None:
        raise NativeTargetError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise NativeTargetError(f"{category} is invalid")
    return value


def _bounded_auxiliary(value: object, *, depth: int = 0) -> None:
    if depth > MAX_AUXILIARY_DEPTH:
        raise NativeTargetError("native auxiliary evidence nesting exceeded")
    if isinstance(value, Mapping):
        if len(value) > MAX_AUXILIARY_KEYS:
            raise NativeTargetError("native auxiliary evidence object exceeded")
        for key, nested in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > MAX_AUXILIARY_STRING
                or "\x00" in key
            ):
                raise NativeTargetError(
                    "native auxiliary evidence key is invalid"
                )
            _bounded_auxiliary(nested, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_AUXILIARY_ITEMS:
            raise NativeTargetError("native auxiliary evidence array exceeded")
        for nested in value:
            _bounded_auxiliary(nested, depth=depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_AUXILIARY_STRING or "\x00" in value:
            raise NativeTargetError(
                "native auxiliary evidence string exceeded"
            )
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise NativeTargetError("native auxiliary evidence value is invalid")


def _url(value: object, category: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise NativeTargetError(f"{category} URL is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise NativeTargetError(f"{category} URL is invalid") from error
    hostname = parsed.hostname
    try:
        valid_ip = hostname is not None and bool(ipaddress.ip_address(hostname))
    except ValueError:
        valid_ip = False
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or hostname is None
        or port is None
        or not 1 <= port <= 65535
        or not parsed.path.startswith("/")
        or parsed.fragment
        or (not valid_ip and HOST_PATTERN.fullmatch(hostname) is None)
    ):
        raise NativeTargetError(f"{category} URL is invalid")
    return value, parsed.path


def _endpoint(
    value: object,
    *,
    category: str,
    content_types: Sequence[str],
    path_suffix: str | None = None,
    allow_query: bool = False,
) -> str:
    endpoint = _exact(value, {"content_types", "url"}, category)
    if endpoint["content_types"] != list(content_types):
        raise NativeTargetError(f"{category} content types changed")
    url, path = _url(endpoint["url"], category)
    parsed = urlsplit(url)
    if (
        (path_suffix is not None and not path.endswith(path_suffix))
        or (not allow_query and parsed.query)
    ):
        raise NativeTargetError(f"{category} URL changed")
    return url


def _query(value: object, name: str) -> str:
    query = _exact(
        value,
        {"content_types", "promql", "promql_sha256", "url"},
        f"{name} query",
    )
    promql = query["promql"]
    if (
        not isinstance(promql, str)
        or promql != PROMQL[name]
        or query["promql_sha256"] != _text_hash(promql)
        or query["content_types"] != list(JSON_CONTENT_TYPES)
    ):
        raise NativeTargetError(f"{name} PromQL changed")
    url, path = _url(query["url"], f"{name} query")
    parsed = urlsplit(url)
    canonical_query = urlencode([("query", promql)])
    if (
        not path.endswith("/api/v1/query")
        or parsed.query != canonical_query
        or parse_qsl(parsed.query, keep_blank_values=True)
        != [("query", promql)]
    ):
        raise NativeTargetError(f"{name} query URL changed")
    return url


def _evidence_urls(
    value: object,
    surface: str,
) -> dict[str, dict[str, Any]]:
    evidence = _exact(value, set(PHASES), f"{surface} evidence URLs")
    result: dict[str, dict[str, Any]] = {}
    for phase in PHASES:
        endpoint = _exact(
            evidence[phase],
            {"content_types", "url"},
            f"{surface} {phase} evidence",
        )
        _endpoint(
            endpoint,
            category=f"{surface} {phase} evidence",
            content_types=JSON_CONTENT_TYPES,
        )
        result[phase] = dict(endpoint)
    return result


def _host_array(
    value: object,
    *,
    category: str,
    length: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) != length
        or len(set(value)) != length
    ):
        raise NativeTargetError(f"{category} changed")
    return [_host(item, category) for item in value]


def _validate_rules_url(
    value: object,
    *,
    required_rules: Sequence[str],
) -> str:
    url = _endpoint(
        value,
        category="Prometheus rules",
        content_types=JSON_CONTENT_TYPES,
        path_suffix="/api/v1/rules",
        allow_query=True,
    )
    parsed = urlsplit(url)
    pairs = [("rule_name[]", rule) for rule in required_rules]
    if (
        len(set(required_rules)) != len(required_rules)
        or parsed.query != urlencode(pairs)
        or parse_qsl(parsed.query, keep_blank_values=True) != pairs
    ):
        raise NativeTargetError("Prometheus rules URL changed")
    return url


def _validate_prometheus(
    value: object,
    *,
    load_topology: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    source = _exact(
        value,
        {
            "evidence_urls",
            "instances",
            "kind",
            "queries",
            "rules",
        },
        "Prometheus source",
    )
    if source["kind"] != "prometheus-v1":
        raise NativeTargetError("Prometheus source kind changed")
    instances_raw = _exact(
        source["instances"],
        set(DIRECT_COMPONENTS),
        "Prometheus instances",
    )
    instances = {
        component: _host_array(
            instances_raw[component],
            category=f"{component} Prometheus instances",
            length=_integer(
                load_topology["replicas"][component],
                f"{component} replica count",
                minimum=1,
                maximum=32,
            ),
        )
        for component in DIRECT_COMPONENTS
    }
    queries_raw = _exact(
        source["queries"],
        set(PROMQL),
        "Prometheus query set",
    )
    query_urls = {
        name: _query(queries_raw[name], name)
        for name in PROMQL
    }
    required_rules = [
        *load_topology["required_recording_rules"],
        *load_topology["required_alerts"],
    ]
    rules_url = _validate_rules_url(
        source["rules"],
        required_rules=required_rules,
    )
    evidence_urls = _evidence_urls(
        source["evidence_urls"],
        "prometheus",
    )
    normalized = {
        "evidence_urls": evidence_urls,
        "instances": instances,
        "kind": source["kind"],
        "queries": dict(queries_raw),
        "rules": dict(source["rules"]),
    }
    return (
        normalized,
        [
            *query_urls.values(),
            rules_url,
            *[endpoint["url"] for endpoint in evidence_urls.values()],
        ],
    )


def _validate_haproxy(
    value: object,
    *,
    component_instances: Mapping[str, Sequence[str]],
) -> tuple[dict[str, Any], list[str]]:
    source = _exact(
        value,
        {"backend_targets", "evidence_urls", "kind", "metrics"},
        "HAProxy source",
    )
    if source["kind"] != "haproxy-exporter":
        raise NativeTargetError("HAProxy source kind changed")
    targets_raw = _exact(
        source["backend_targets"],
        {"api", "edge", "registry"},
        "HAProxy backend targets",
    )
    targets: dict[str, dict[str, Any]] = {}
    for component in ("api", "edge", "registry"):
        target = _exact(
            targets_raw[component],
            {"proxy", "servers"},
            f"{component} HAProxy target",
        )
        servers = _host_array(
            target["servers"],
            category=f"{component} HAProxy servers",
            length=len(component_instances[component]),
        )
        if (
            target["proxy"] != f"coffer-{component}"
            or servers != list(component_instances[component])
        ):
            raise NativeTargetError(f"{component} HAProxy target changed")
        targets[component] = {
            "proxy": target["proxy"],
            "servers": servers,
        }
    metrics_url = _endpoint(
        source["metrics"],
        category="HAProxy metrics",
        content_types=EXPOSITION_CONTENT_TYPES,
    )
    evidence_urls = _evidence_urls(source["evidence_urls"], "haproxy")
    return (
        {
            "backend_targets": targets,
            "evidence_urls": evidence_urls,
            "kind": source["kind"],
            "metrics": dict(source["metrics"]),
        },
        [
            metrics_url,
            *[endpoint["url"] for endpoint in evidence_urls.values()],
        ],
    )


def _validate_galera(
    value: object,
    *,
    controller_hosts: set[str],
) -> tuple[dict[str, Any], list[str]]:
    source = _exact(
        value,
        {"evidence_urls", "instances", "kind"},
        "Galera source",
    )
    if source["kind"] != "mysqld-exporter":
        raise NativeTargetError("Galera source kind changed")
    instances_raw = _exact(
        source["instances"],
        controller_hosts,
        "Galera instances",
    )
    instances = {
        host: dict(
            _exact(
                instances_raw[host],
                {"content_types", "url"},
                f"{host} Galera metrics",
            )
        )
        for host in sorted(controller_hosts)
    }
    urls = [
        _endpoint(
            instances[host],
            category=f"{host} Galera metrics",
            content_types=EXPOSITION_CONTENT_TYPES,
        )
        for host in sorted(instances)
    ]
    evidence_urls = _evidence_urls(source["evidence_urls"], "galera")
    return (
        {
            "evidence_urls": evidence_urls,
            "instances": instances,
            "kind": source["kind"],
        },
        [
            *urls,
            *[endpoint["url"] for endpoint in evidence_urls.values()],
        ],
    )


def _validate_rgw(
    value: object,
    *,
    load_topology: Mapping[str, Any],
    storage_hosts: set[str],
) -> tuple[dict[str, Any], list[str]]:
    source = _exact(
        value,
        {
            "daemon_metadata",
            "daemon_sockets",
            "daemons",
            "evidence_urls",
            "ingress",
            "ingress_target",
            "kind",
        },
        "RGW source",
    )
    if source["kind"] != "ceph-exporters":
        raise NativeTargetError("RGW source kind changed")
    daemon_count = _integer(
        load_topology["replicas"]["rgw"],
        "RGW replica count",
        minimum=1,
        maximum=32,
    )
    daemons_raw = source["daemons"]
    if (
        not isinstance(daemons_raw, Mapping)
        or len(daemons_raw) != daemon_count
    ):
        raise NativeTargetError("RGW daemon targets changed")
    daemons = {
        _name(daemon, "RGW daemon"): _host(host, "RGW daemon host")
        for daemon, host in daemons_raw.items()
    }
    if (
        any(not daemon.startswith("rgw.") for daemon in daemons)
        or set(daemons.values()) != storage_hosts
    ):
        raise NativeTargetError("RGW daemon targets changed")
    ingress = _exact(
        source["ingress_target"],
        {"proxy", "servers"},
        "RGW ingress target",
    )
    ingress_servers = _host_array(
        ingress["servers"],
        category="RGW ingress servers",
        length=_integer(
            load_topology["replicas"]["rgw-ingress"],
            "RGW ingress replica count",
            minimum=1,
            maximum=16,
        ),
    )
    if (
        ingress["proxy"] != "rgw-ingress"
        or not set(ingress_servers) <= storage_hosts
    ):
        raise NativeTargetError("RGW ingress target changed")
    endpoint_values = (
        ("daemon_metadata", "RGW daemon metadata"),
        ("daemon_sockets", "RGW daemon sockets"),
        ("ingress", "RGW ingress metrics"),
    )
    urls = [
        _endpoint(
            source[key],
            category=category,
            content_types=EXPOSITION_CONTENT_TYPES,
        )
        for key, category in endpoint_values
    ]
    evidence_urls = _evidence_urls(source["evidence_urls"], "rgw")
    return (
        {
            "daemon_metadata": dict(source["daemon_metadata"]),
            "daemon_sockets": dict(source["daemon_sockets"]),
            "daemons": dict(daemons),
            "evidence_urls": evidence_urls,
            "ingress": dict(source["ingress"]),
            "ingress_target": {
                "proxy": ingress["proxy"],
                "servers": ingress_servers,
            },
            "kind": source["kind"],
        },
        [
            *urls,
            *[endpoint["url"] for endpoint in evidence_urls.values()],
        ],
    )


def _validate_hosts(
    value: object,
    *,
    load_topology: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], set[str], set[str]]:
    source = _exact(value, {"instances", "kind"}, "host source")
    if source["kind"] != "node-exporter":
        raise NativeTargetError("host source kind changed")
    instances_raw = source["instances"]
    if not isinstance(instances_raw, Mapping):
        raise NativeTargetError("host instances changed")
    expected_controllers = _integer(
        load_topology["replicas"]["galera"],
        "controller host count",
        minimum=1,
        maximum=16,
    )
    expected_storage = _integer(
        load_topology["replicas"]["rgw"],
        "storage host count",
        minimum=1,
        maximum=32,
    )
    if len(instances_raw) != expected_controllers + expected_storage:
        raise NativeTargetError("host instances changed")
    normalized: dict[str, dict[str, Any]] = {}
    urls: list[str] = []
    controller_hosts: set[str] = set()
    storage_hosts: set[str] = set()
    for raw_host, raw_target in instances_raw.items():
        host = _host(raw_host, "node-exporter host")
        target = _exact(
            raw_target,
            {"content_types", "role", "url"},
            f"{host} node-exporter target",
        )
        role = target["role"]
        if role not in {"controller", "storage"}:
            raise NativeTargetError("node-exporter role changed")
        endpoint = {
            "content_types": target["content_types"],
            "url": target["url"],
        }
        urls.append(
            _endpoint(
                endpoint,
                category=f"{host} node-exporter metrics",
                content_types=EXPOSITION_CONTENT_TYPES,
            )
        )
        normalized[host] = {
            "content_types": target["content_types"],
            "role": role,
            "url": target["url"],
        }
        (controller_hosts if role == "controller" else storage_hosts).add(
            host
        )
    if (
        len(controller_hosts) != expected_controllers
        or len(storage_hosts) != expected_storage
    ):
        raise NativeTargetError("host role topology changed")
    return (
        {"instances": normalized, "kind": source["kind"]},
        urls,
        controller_hosts,
        storage_hosts,
    )


def _validate_auxiliary_source(
    value: object,
    surface: str,
) -> tuple[dict[str, Any], list[str]]:
    source = _exact(value, {"evidence_urls", "kind"}, f"{surface} source")
    if source["kind"] != "phase-evidence":
        raise NativeTargetError(f"{surface} source kind changed")
    evidence_urls = _evidence_urls(source["evidence_urls"], surface)
    return (
        {"evidence_urls": evidence_urls, "kind": source["kind"]},
        [endpoint["url"] for endpoint in evidence_urls.values()],
    )


def validate_target(
    value: object,
    *,
    topology_sha256: str,
    load_topology: Mapping[str, Any],
    observability_topology: Any,
) -> ValidatedTarget:
    target = _exact(
        value,
        {
            "adapter",
            "adapter_contract_sha256",
            "schema",
            "sources",
            "target_class",
            "target_sha256",
            "topology_sha256",
        },
        "native telemetry target",
    )
    if (
        target["schema"] != TARGET_SCHEMA
        or target["adapter"] != ADAPTER
        or target["target_class"] != TARGET_CLASS
        or target["topology_sha256"] != topology_sha256
        or target["topology_sha256"]
        != _hash(load_topology)
        or not isinstance(target["adapter_contract_sha256"], str)
        or SHA256.fullmatch(target["adapter_contract_sha256"]) is None
        or getattr(observability_topology, "raw", {}).get(
            "scrape_interval_seconds"
        )
        != 30
    ):
        raise NativeTargetError("native telemetry target binding changed")
    sources = _exact(target["sources"], set(SURFACES), "native sources")
    hosts, host_urls, controller_hosts, storage_hosts = _validate_hosts(
        sources["hosts"],
        load_topology=load_topology,
    )
    prometheus, prometheus_urls = _validate_prometheus(
        sources["prometheus"],
        load_topology=load_topology,
    )
    if (
        set(prometheus["instances"]["api"]) != controller_hosts
        or set(prometheus["instances"]["edge"]) != controller_hosts
        or set(prometheus["instances"]["registry"]) != controller_hosts
        or not set(prometheus["instances"]["reconcile"])
        <= controller_hosts
    ):
        raise NativeTargetError("Prometheus host topology changed")
    haproxy, haproxy_urls = _validate_haproxy(
        sources["haproxy"],
        component_instances=prometheus["instances"],
    )
    galera, galera_urls = _validate_galera(
        sources["galera"],
        controller_hosts=controller_hosts,
    )
    rgw, rgw_urls = _validate_rgw(
        sources["rgw"],
        load_topology=load_topology,
        storage_hosts=storage_hosts,
    )
    quota, quota_urls = _validate_auxiliary_source(
        sources["quota"],
        "quota",
    )
    reconciliation, reconciliation_urls = _validate_auxiliary_source(
        sources["reconciliation"],
        "reconciliation",
    )
    urls = [
        *prometheus_urls,
        *haproxy_urls,
        *galera_urls,
        *rgw_urls,
        *quota_urls,
        *reconciliation_urls,
        *host_urls,
    ]
    if len(urls) != len(set(urls)):
        raise NativeTargetError("native telemetry URL is repeated")
    unsigned = {
        key: target[key] for key in target if key != "target_sha256"
    }
    if target["target_sha256"] != _hash(unsigned):
        raise NativeTargetError("native telemetry target hash changed")
    normalized = {
        "adapter": target["adapter"],
        "adapter_contract_sha256": target["adapter_contract_sha256"],
        "schema": target["schema"],
        "sources": {
            "galera": galera,
            "haproxy": haproxy,
            "hosts": hosts,
            "prometheus": prometheus,
            "quota": quota,
            "reconciliation": reconciliation,
            "rgw": rgw,
        },
        "target_class": target["target_class"],
        "target_sha256": target["target_sha256"],
        "topology_sha256": target["topology_sha256"],
    }
    return ValidatedTarget(
        raw=json.loads(_canonical(normalized)),
        target_sha256=str(target["target_sha256"]),
    )


def _evidence(
    client: Any,
    endpoint: Mapping[str, Any],
    *,
    ca_file: Path,
    phase: str,
    surface: str,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    value = client.fetch_json(
        endpoint["url"],
        ca_file=ca_file,
        timeout_seconds=timeout_seconds,
    )
    wrapper = _exact(
        value,
        {"payload", "phase", "schema", "surface"},
        f"{surface} auxiliary evidence",
    )
    if (
        wrapper["schema"] != EVIDENCE_SCHEMA
        or wrapper["phase"] != phase
        or wrapper["surface"] != surface
        or not isinstance(wrapper["payload"], Mapping)
    ):
        raise NativeTargetError(f"{surface} auxiliary evidence changed")
    _bounded_auxiliary(wrapper["payload"])
    return wrapper["payload"]


def compose_phase_snapshot(
    target_value: object,
    *,
    ca_file: Path,
    phase: str,
    timeout_seconds: int,
    topology_sha256: str,
    load_topology: Mapping[str, Any],
    observability_topology: Any,
    client: Any | None = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    if phase not in PHASES:
        raise NativeTargetError("native telemetry phase changed")
    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= 300
    ):
        raise NativeTargetError("native telemetry timeout is invalid")
    target = validate_target(
        target_value,
        topology_sha256=topology_sha256,
        load_topology=load_topology,
        observability_topology=observability_topology,
    ).raw
    chosen_client = client or native_surfaces.VerifiedHTTPSClient()
    chosen_clock = clock or RealClock()
    started = chosen_clock.monotonic()

    def remaining() -> float:
        value = timeout_seconds - (chosen_clock.monotonic() - started)
        if value <= 0:
            raise NativeTargetError("native telemetry deadline expired")
        return value

    def fetch_json(endpoint: Mapping[str, Any]) -> object:
        return chosen_client.fetch_json(
            endpoint["url"],
            ca_file=ca_file,
            timeout_seconds=remaining(),
        )

    def fetch_exposition(endpoint: Mapping[str, Any]) -> bytes:
        return chosen_client.fetch_exposition(
            endpoint["url"],
            ca_file=ca_file,
            timeout_seconds=remaining(),
        )

    def evidence(surface: str) -> Mapping[str, Any]:
        source = target["sources"][surface]
        return _evidence(
            chosen_client,
            source["evidence_urls"][phase],
            ca_file=ca_file,
            phase=phase,
            surface=surface,
            timeout_seconds=remaining(),
        )

    sources = target["sources"]
    try:
        prometheus_source = sources["prometheus"]
        query_documents = {
            name: fetch_json(prometheus_source["queries"][name])
            for name in sorted(PROMETHEUS_SURFACE_QUERIES)
        }
        prometheus_evidence = evidence("prometheus")
        prometheus_evidence = _exact(
            prometheus_evidence,
            {"secret_leaks"},
            "Prometheus auxiliary payload",
        )
        prometheus = native_surfaces.parse_prometheus_surface(
            query_documents,
            fetch_json(prometheus_source["rules"]),
            expected_instances=prometheus_source["instances"],
            required_recording_rules=load_topology[
                "required_recording_rules"
            ],
            required_alerts=load_topology["required_alerts"],
            secret_leaks=_integer(
                prometheus_evidence["secret_leaks"],
                "Prometheus secret leak evidence",
            ),
        )

        haproxy_source = sources["haproxy"]
        haproxy_evidence = _exact(
            evidence("haproxy"),
            {"unexpected_errors"},
            "HAProxy auxiliary payload",
        )
        haproxy = native_surfaces.parse_haproxy_surface(
            fetch_exposition(haproxy_source["metrics"]),
            backend_targets=haproxy_source["backend_targets"],
            unexpected_errors=haproxy_evidence["unexpected_errors"],
        )

        galera_source = sources["galera"]
        galera_evidence = _exact(
            evidence("galera"),
            {"max_transaction_attempts", "unexpected_errors"},
            "Galera auxiliary payload",
        )
        galera = native_surfaces.parse_galera_surface(
            {
                host: fetch_exposition(endpoint)
                for host, endpoint in sorted(
                    galera_source["instances"].items()
                )
            },
            max_transaction_attempts=galera_evidence[
                "max_transaction_attempts"
            ],
            unexpected_errors=galera_evidence["unexpected_errors"],
        )

        rgw_source = sources["rgw"]
        rgw_evidence = _exact(
            evidence("rgw"),
            {"kms_errors", "multipart_uploads", "unexpected_errors"},
            "RGW auxiliary payload",
        )
        rgw = native_surfaces.parse_rgw_surface(
            fetch_exposition(rgw_source["daemon_metadata"]),
            fetch_exposition(rgw_source["daemon_sockets"]),
            fetch_exposition(rgw_source["ingress"]),
            expected_daemons=rgw_source["daemons"],
            ingress_target=rgw_source["ingress_target"],
            kms_errors=rgw_evidence["kms_errors"],
            multipart_uploads=rgw_evidence["multipart_uploads"],
            unexpected_errors=rgw_evidence["unexpected_errors"],
        )

        quota = native_surfaces.parse_quota_surface(evidence("quota"))
        reconciliation = native_surfaces.parse_reconciliation_surface(
            evidence("reconciliation")
        )

        hosts_source = sources["hosts"]
        host_queries = prometheus_source["queries"]
        hosts = native_surfaces.parse_hosts_surface(
            {
                host: fetch_exposition(endpoint)
                for host, endpoint in sorted(
                    hosts_source["instances"].items()
                )
            },
            roles={
                host: endpoint["role"]
                for host, endpoint in hosts_source["instances"].items()
            },
            cpu_usage_document=fetch_json(
                host_queries["host_cpu_usage_percent"]
            ),
            oom_kills_document=fetch_json(
                host_queries["host_oom_kills"]
            ),
        )
    except (KeyError, TypeError, native_surfaces.NativeSurfaceError) as error:
        raise NativeTargetError("native telemetry surface failed") from error
    snapshot = {
        "galera": galera,
        "haproxy": haproxy,
        "hosts": hosts,
        "observed_at_seconds": chosen_clock.wall_time(),
        "phase": phase,
        "prometheus": prometheus,
        "quota": quota,
        "reconciliation": reconciliation,
        "rgw": rgw,
    }
    _bounded_auxiliary(snapshot)
    return snapshot
