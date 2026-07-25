from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import ssl
import sys
import threading
from typing import Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "native_surfaces.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


NATIVE = load_module("coffer_load_native_surface_tests", MODULE_PATH)
RECORDING_RULES = (
    "coffer:slo_pull_good:ratio_rate5m",
    "coffer:target_up:sum",
)
ALERTS = ("CofferTargetDown", "CofferDependencyUnavailable")
EXPECTED_INSTANCES = {
    "api": ("api1",),
    "edge": ("edge1",),
    "reconcile": ("reconcile1",),
    "registry": ("registry1",),
}


def api_vector(entries: list[tuple[dict[str, str], float]]) -> dict:
    return {
        "data": {
            "result": [
                {
                    "metric": labels,
                    "value": [1_000, str(value)],
                }
                for labels, value in entries
            ],
            "resultType": "vector",
        },
        "status": "success",
    }


def api_scalar(value: float) -> dict:
    return {
        "data": {
            "result": [1_000, str(value)],
            "resultType": "scalar",
        },
        "status": "success",
    }


def direct_vector() -> dict:
    entries: list[tuple[dict[str, str], float]] = []
    for component, instances in EXPECTED_INSTANCES.items():
        for instance in instances:
            for kind, value in (
                ("counter", 10),
                ("process_start_seconds", 100),
                ("up", 1),
            ):
                entries.append(
                    (
                        {
                            "component": component,
                            "instance": instance,
                            "kind": kind,
                        },
                        value,
                    )
                )
    return api_vector(entries)


def rules_document(*, firing: bool = False) -> dict:
    recording = [
        {
            "evaluationTime": 0.001,
            "health": "ok",
            "labels": {},
            "lastEvaluation": "2026-07-25T00:00:00Z",
            "name": name,
            "query": "vector(1)",
            "type": "recording",
        }
        for name in RECORDING_RULES
    ]
    alerting = [
        {
            "alerts": (
                [
                    {
                        "activeAt": "2026-07-25T00:00:00Z",
                        "annotations": {},
                        "labels": {"alertname": name},
                        "state": "firing",
                        "value": "1",
                    }
                ]
                if firing and name == ALERTS[0]
                else []
            ),
            "annotations": {},
            "duration": 120,
            "evaluationTime": 0.001,
            "health": "ok",
            "keepFiringFor": 0,
            "labels": {"service": "coffer"},
            "lastEvaluation": "2026-07-25T00:00:00Z",
            "name": name,
            "query": "vector(0)",
            "state": (
                "firing"
                if firing and name == ALERTS[0]
                else "inactive"
            ),
            "type": "alerting",
        }
        for name in ALERTS
    ]
    return {
        "data": {
            "groups": [
                {
                    "evaluationTime": 0.002,
                    "file": "/etc/prometheus/coffer.rules",
                    "interval": 30,
                    "lastEvaluation": "2026-07-25T00:00:00Z",
                    "limit": 0,
                    "name": "coffer.recording",
                    "rules": recording,
                },
                {
                    "evaluationTime": 0.002,
                    "file": "/etc/prometheus/coffer.rules",
                    "interval": 30,
                    "lastEvaluation": "2026-07-25T00:00:00Z",
                    "limit": 0,
                    "name": "coffer.alerts",
                    "rules": alerting,
                },
            ]
        },
        "status": "success",
    }


def query_documents() -> dict:
    return {
        "direct_targets": direct_vector(),
        "schema_mismatches": api_scalar(0),
        "scrape_interval_seconds": api_scalar(30),
        "secret_leaks": api_scalar(0),
        "stale_series": api_scalar(0),
    }


def haproxy_payload(
    backends: dict[str, tuple[str, ...]],
    *,
    down: set[tuple[str, str]] | None = None,
) -> bytes:
    down = down or set()
    lines = [
        "# HELP haproxy_server_status Current status.",
        "# TYPE haproxy_server_status gauge",
    ]
    for proxy, servers in backends.items():
        for server in servers:
            active = "DOWN" if (proxy, server) in down else "UP"
            for state in NATIVE.HAPROXY_STATES:
                lines.append(
                    "haproxy_server_status"
                    f'{{proxy="{proxy}",server="{server}",state="{state}"}} '
                    f"{int(state == active)}"
                )
    lines.extend(
        [
            (
                "haproxy_server_status"
                '{proxy="unrelated",server="other",state="UP"} 1'
            ),
            "haproxy_process_uptime_seconds 100",
        ]
    )
    return ("\n".join(lines) + "\n").encode()


def galera_payload(cluster_id: str, *, up: int = 1, state: int = 4) -> bytes:
    return (
        "# TYPE mysql_up gauge\n"
        f"mysql_up {up}\n"
        "mysql_global_status_wsrep_cluster_size 3\n"
        f"mysql_global_status_wsrep_local_state {state}\n"
        "mysql_galera_status_info"
        f'{{wsrep_cluster_state_uuid="{cluster_id}",'
        f'wsrep_local_state_uuid="{cluster_id}",'
        'wsrep_provider_version="4.22"} 1\n'
        "mysql_global_status_threads_connected 10\n"
    ).encode()


def rgw_metadata_payload(
    daemons: dict[str, str],
    *,
    extra_rgw: bool = False,
) -> bytes:
    lines = []
    for index, (daemon, host) in enumerate(daemons.items(), start=1):
        lines.append(
            "ceph_rgw_metadata"
            f'{{ceph_daemon="{daemon}",hostname="{host}",'
            'ceph_version="20.2.3",'
            f'instance_id="{index}"}} 1'
        )
    if extra_rgw:
        lines.append(
            "ceph_rgw_metadata"
            '{ceph_daemon="rgw.extra",hostname="storage4",'
            'ceph_version="20.2.3",instance_id="4"} 1'
        )
    return ("\n".join(lines) + "\n").encode()


def rgw_socket_payload(
    daemons: dict[str, str],
    *,
    down: str | None = None,
) -> bytes:
    return (
        "\n".join(
            "ceph_daemon_socket_up"
            f'{{ceph_daemon="{daemon}",hostname="{host}"}} '
            f"{int(daemon != down)}"
            for daemon, host in daemons.items()
        )
        + "\n"
    ).encode()


def node_payload(*, device: str = "/dev/vda1") -> bytes:
    labels = (
        f'device="{device}",device_error="0",fstype="xfs",mountpoint="/"'
    )
    return (
        "node_memory_MemTotal_bytes 1000\n"
        "node_memory_MemAvailable_bytes 400\n"
        f"node_filesystem_size_bytes{{{labels}}} 1000\n"
        f"node_filesystem_avail_bytes{{{labels}}} 450\n"
        "node_filefd_allocated 40\n"
        "node_filefd_maximum 100\n"
        "node_timex_offset_seconds 0.003\n"
        'node_cpu_seconds_total{cpu="0",mode="idle"} 100\n'
    ).encode()


def certificate(tmp_path: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(10)
        .not_valid_before(datetime(2026, 7, 24, tzinfo=UTC))
        .not_valid_after(datetime(2027, 7, 25, tzinfo=UTC))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "native.crt"
    key_path = tmp_path / "native.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@contextmanager
def tls_server(
    tmp_path: Path,
    responses: dict[str, tuple[str, bytes]],
) -> Iterator[tuple[str, Path, list[str]]]:
    cert_path, key_path = certificate(tmp_path)
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            calls.append(self.path)
            if self.path not in responses:
                self.send_response(404)
                self.end_headers()
                return
            content_type, payload = responses[self.path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"https://localhost:{server.server_address[1]}",
            cert_path,
            calls,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_verified_tls_fetches_prometheus_and_exporter_payloads(
    tmp_path: Path,
) -> None:
    prometheus = json.dumps(api_scalar(1)).encode()
    exporter = b"# TYPE mysql_up gauge\nmysql_up 1\n"
    with tls_server(
        tmp_path,
        {
            "/api/v1/query?query=vector%281%29": (
                "application/json",
                prometheus,
            ),
            "/metrics": (
                "application/openmetrics-text; version=1.0.0",
                exporter,
            ),
        },
    ) as (base_url, ca_file, calls):
        client = NATIVE.VerifiedHTTPSClient()
        assert client.fetch_json(
            f"{base_url}/api/v1/query?query=vector%281%29",
            ca_file=ca_file,
            timeout_seconds=2,
        ) == api_scalar(1)
        assert (
            client.fetch_exposition(
                f"{base_url}/metrics",
                ca_file=ca_file,
                timeout_seconds=2,
            )
            == exporter
        )
        assert calls == [
            "/api/v1/query?query=vector%281%29",
            "/metrics",
        ]

        with pytest.raises(
            NATIVE.NativeSurfaceError,
            match="transport failed",
        ):
            client.fetch_json(
                f"{base_url.replace('localhost', '127.0.0.1')}"
                "/api/v1/query?query=vector%281%29",
                ca_file=ca_file,
                timeout_seconds=2,
            )


def test_all_seven_surfaces_normalize_from_local_verified_tls(
    tmp_path: Path,
) -> None:
    cluster_id = "11111111-2222-3333-4444-555555555555"
    daemons = {
        "rgw.coffer.storage1.a": "storage1",
        "rgw.coffer.storage2.b": "storage2",
        "rgw.coffer.storage3.c": "storage3",
    }
    nodes = {
        **{
            f"controller{index}": node_payload()
            for index in range(1, 4)
        },
        **{
            f"storage{index}": node_payload(device="/dev/sda1")
            for index in range(1, 4)
        },
    }
    quota = {
        "headroom_percent": 40,
        "invariant": True,
        "limit_usage_percent": 60,
        "max_transaction_attempts": 2,
        "stale_claims": 0,
        "unexpected_errors": 0,
    }
    reconciliation = {
        "claims_exact": True,
        "fencing_violations": 0,
        "fresh": True,
        "last_success_age_seconds": 30,
        "stale_claims": 0,
        "workers_total": 2,
        "workers_up": 2,
    }
    responses: dict[str, tuple[str, bytes]] = {
        "/prom/direct": (
            "application/json",
            json.dumps(direct_vector()).encode(),
        ),
        "/prom/rules": (
            "application/json",
            json.dumps(rules_document()).encode(),
        ),
        "/prom/schema": (
            "application/json",
            json.dumps(api_scalar(0)).encode(),
        ),
        "/prom/scrape": (
            "application/json",
            json.dumps(api_scalar(30)).encode(),
        ),
        "/prom/secrets": (
            "application/json",
            json.dumps(api_scalar(0)).encode(),
        ),
        "/prom/stale": (
            "application/json",
            json.dumps(api_scalar(0)).encode(),
        ),
        "/prom/cpu": (
            "application/json",
            json.dumps(
                api_vector(
                    [
                        ({"instance": instance}, 50)
                        for instance in nodes
                    ]
                )
            ).encode(),
        ),
        "/prom/oom": (
            "application/json",
            json.dumps(
                api_vector(
                    [
                        ({"instance": instance}, 0)
                        for instance in nodes
                    ]
                )
            ).encode(),
        ),
        "/export/haproxy": (
            "text/plain; version=0.0.4",
            haproxy_payload(
                {
                    "coffer-api": ("api1", "api2", "api3"),
                    "coffer-edge": ("edge1", "edge2", "edge3"),
                    "coffer-registry": (
                        "registry1",
                        "registry2",
                        "registry3",
                    ),
                }
            ),
        ),
        "/export/ceph-mgr": (
            "text/plain; version=0.0.4",
            rgw_metadata_payload(daemons),
        ),
        "/export/ceph": (
            "text/plain; version=0.0.4",
            rgw_socket_payload(daemons),
        ),
        "/export/rgw-ingress": (
            "text/plain; version=0.0.4",
            haproxy_payload(
                {"rgw-ingress": ("storage1", "storage2")}
            ),
        ),
        "/evidence/quota": (
            "application/json",
            json.dumps(quota).encode(),
        ),
        "/evidence/reconciliation": (
            "application/json",
            json.dumps(reconciliation).encode(),
        ),
    }
    for index in range(1, 4):
        responses[f"/export/galera{index}"] = (
            "text/plain; version=0.0.4",
            galera_payload(cluster_id),
        )
    for instance, payload in nodes.items():
        responses[f"/export/node/{instance}"] = (
            "text/plain; version=0.0.4",
            payload,
        )

    with tls_server(tmp_path, responses) as (
        base_url,
        ca_file,
        calls,
    ):
        client = NATIVE.VerifiedHTTPSClient()

        def json_source(path: str) -> object:
            return client.fetch_json(
                f"{base_url}{path}",
                ca_file=ca_file,
                timeout_seconds=2,
            )

        def exporter(path: str) -> bytes:
            return client.fetch_exposition(
                f"{base_url}{path}",
                ca_file=ca_file,
                timeout_seconds=2,
            )

        surfaces = {
            "prometheus": NATIVE.parse_prometheus_surface(
                {
                    "direct_targets": json_source("/prom/direct"),
                    "schema_mismatches": json_source("/prom/schema"),
                    "scrape_interval_seconds": json_source("/prom/scrape"),
                    "secret_leaks": json_source("/prom/secrets"),
                    "stale_series": json_source("/prom/stale"),
                },
                json_source("/prom/rules"),
                expected_instances=EXPECTED_INSTANCES,
                required_recording_rules=RECORDING_RULES,
                required_alerts=ALERTS,
            ),
            "haproxy": NATIVE.parse_haproxy_surface(
                exporter("/export/haproxy"),
                backend_targets={
                    "api": {
                        "proxy": "coffer-api",
                        "servers": ["api1", "api2", "api3"],
                    },
                    "edge": {
                        "proxy": "coffer-edge",
                        "servers": ["edge1", "edge2", "edge3"],
                    },
                    "registry": {
                        "proxy": "coffer-registry",
                        "servers": [
                            "registry1",
                            "registry2",
                            "registry3",
                        ],
                    },
                },
                unexpected_errors=0,
            ),
            "galera": NATIVE.parse_galera_surface(
                {
                    f"controller{index}": exporter(
                        f"/export/galera{index}"
                    )
                    for index in range(1, 4)
                },
                max_transaction_attempts=2,
                unexpected_errors=0,
            ),
            "rgw": NATIVE.parse_rgw_surface(
                exporter("/export/ceph-mgr"),
                exporter("/export/ceph"),
                exporter("/export/rgw-ingress"),
                expected_daemons=daemons,
                ingress_target={
                    "proxy": "rgw-ingress",
                    "servers": ["storage1", "storage2"],
                },
                kms_errors=0,
                multipart_uploads=0,
                unexpected_errors=0,
            ),
            "quota": NATIVE.parse_quota_surface(
                json_source("/evidence/quota")
            ),
            "reconciliation": NATIVE.parse_reconciliation_surface(
                json_source("/evidence/reconciliation")
            ),
            "hosts": NATIVE.parse_hosts_surface(
                {
                    instance: exporter(f"/export/node/{instance}")
                    for instance in nodes
                },
                roles={
                    instance: (
                        "controller"
                        if instance.startswith("controller")
                        else "storage"
                    )
                    for instance in nodes
                },
                cpu_usage_document=json_source("/prom/cpu"),
                oom_kills_document=json_source("/prom/oom"),
            ),
        }
        assert set(surfaces) == {
            "galera",
            "haproxy",
            "hosts",
            "prometheus",
            "quota",
            "reconciliation",
            "rgw",
        }
        assert surfaces["galera"]["nodes_primary"] == 3
        assert surfaces["rgw"]["daemons_up"] == 3
        assert len(surfaces["hosts"]) == 6
        assert len(calls) == len(responses)


def test_prometheus_api_and_rules_normalize_exact_surface() -> None:
    result = NATIVE.parse_prometheus_surface(
        query_documents(),
        rules_document(firing=True),
        expected_instances=EXPECTED_INSTANCES,
        required_recording_rules=RECORDING_RULES,
        required_alerts=ALERTS,
    )
    assert result["recording_rules_loaded"] == list(RECORDING_RULES)
    assert result["alerts_loaded"] == list(ALERTS)
    assert result["firing_alerts"] == ["CofferTargetDown"]
    assert result["scrape_interval_seconds"] == 30
    assert result["direct_targets"]["registry"] == [
        {
            "counter": 10.0,
            "instance": "registry1",
            "process_start_seconds": 100.0,
            "up": 1,
        }
    ]


@pytest.mark.parametrize(
    "mutation",
    ["warning", "extra-label", "missing-series", "extra-rule", "nan"],
)
def test_prometheus_surface_refuses_ambiguous_or_extra_series(
    mutation: str,
) -> None:
    queries = query_documents()
    rules = rules_document()
    if mutation == "warning":
        queries["stale_series"]["warnings"] = ["partial response"]
    elif mutation == "extra-label":
        queries["direct_targets"]["data"]["result"][0]["metric"][
            "job"
        ] = "coffer"
    elif mutation == "missing-series":
        queries["direct_targets"]["data"]["result"].pop()
    elif mutation == "extra-rule":
        duplicate = dict(rules["data"]["groups"][0]["rules"][0])
        duplicate["name"] = "coffer:unexpected"
        rules["data"]["groups"][0]["rules"].append(duplicate)
    else:
        queries["stale_series"]["data"]["result"][1] = "NaN"
    with pytest.raises(NATIVE.NativeSurfaceError):
        NATIVE.parse_prometheus_surface(
            queries,
            rules,
            expected_instances=EXPECTED_INSTANCES,
            required_recording_rules=RECORDING_RULES,
            required_alerts=ALERTS,
        )


def test_exposition_parser_bounds_selected_series_and_ignores_others() -> None:
    parsed = NATIVE.parse_exposition(
        (
            "# HELP wanted selected\n"
            'wanted{quote="a\\\"b",newline="a\\nb"} 1\n'
            'unrelated_bucket{le="1"} 10 # {trace_id="abc"} 1\n'
        ).encode(),
        selected_metrics=frozenset({"wanted"}),
    )
    assert parsed["wanted"][0].label_map == {
        "newline": "a\nb",
        "quote": 'a"b',
    }
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="selected exporter sample",
    ):
        NATIVE.parse_exposition(
            b"wanted 1 1234\n",
            selected_metrics=frozenset({"wanted"}),
        )
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="duplicated",
    ):
        NATIVE.parse_exposition(
            b'wanted{a="b"} 1\nwanted{a="b"} 2\n',
            selected_metrics=frozenset({"wanted"}),
        )


def test_haproxy_native_status_normalizes_only_pinned_backends() -> None:
    payload = haproxy_payload(
        {
            "coffer-api": ("api1", "api2", "api3"),
            "coffer-edge": ("edge1", "edge2", "edge3"),
            "coffer-registry": ("registry1", "registry2", "registry3"),
        },
        down={("coffer-edge", "edge1")},
    )
    result = NATIVE.parse_haproxy_surface(
        payload,
        backend_targets={
            "api": {
                "proxy": "coffer-api",
                "servers": ["api1", "api2", "api3"],
            },
            "edge": {
                "proxy": "coffer-edge",
                "servers": ["edge1", "edge2", "edge3"],
            },
            "registry": {
                "proxy": "coffer-registry",
                "servers": ["registry1", "registry2", "registry3"],
            },
        },
        unexpected_errors=0,
    )
    assert result == {
        "backends": {
            "api": {"healthy": 3, "total": 3},
            "edge": {"healthy": 2, "total": 3},
            "registry": {"healthy": 3, "total": 3},
        },
        "unexpected_errors": 0,
    }

    changed = payload + (
        "haproxy_server_status"
        '{proxy="coffer-api",server="api4",state="UP"} 1\n'
    ).encode()
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="selected backend",
    ):
        NATIVE.parse_haproxy_surface(
            changed,
            backend_targets={
                "api": {
                    "proxy": "coffer-api",
                    "servers": ["api1", "api2", "api3"],
                }
            },
            unexpected_errors=0,
        )


def test_mysqld_exporter_galera_surface_requires_one_synced_cluster() -> None:
    cluster_id = "11111111-2222-3333-4444-555555555555"
    payloads = {
        f"controller{index}": galera_payload(cluster_id)
        for index in range(1, 4)
    }
    assert NATIVE.parse_galera_surface(
        payloads,
        max_transaction_attempts=2,
        unexpected_errors=0,
    ) == {
        "max_transaction_attempts": 2,
        "nodes_primary": 3,
        "nodes_ready": 3,
        "nodes_synced": 3,
        "nodes_total": 3,
        "unexpected_errors": 0,
    }
    payloads["controller3"] = galera_payload(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="split",
    ):
        NATIVE.parse_galera_surface(
            payloads,
            max_transaction_attempts=2,
            unexpected_errors=0,
        )


def test_ceph_rgw_and_haproxy_ingress_normalize_exact_daemons() -> None:
    daemons = {
        "rgw.coffer.storage1.a": "storage1",
        "rgw.coffer.storage2.b": "storage2",
        "rgw.coffer.storage3.c": "storage3",
    }
    result = NATIVE.parse_rgw_surface(
        rgw_metadata_payload(daemons),
        rgw_socket_payload(
            daemons,
            down="rgw.coffer.storage1.a",
        ),
        haproxy_payload(
            {"rgw-ingress": ("storage1", "storage2")},
            down={("rgw-ingress", "storage1")},
        ),
        expected_daemons=daemons,
        ingress_target={
            "proxy": "rgw-ingress",
            "servers": ["storage1", "storage2"],
        },
        kms_errors=0,
        multipart_uploads=2,
        unexpected_errors=0,
    )
    assert result == {
        "daemons_total": 3,
        "daemons_up": 2,
        "ingress_total": 2,
        "ingress_up": 1,
        "kms_errors": 0,
        "multipart_uploads": 2,
        "unexpected_errors": 0,
    }
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="metadata target",
    ):
        NATIVE.parse_rgw_surface(
            rgw_metadata_payload(daemons, extra_rgw=True),
            rgw_socket_payload(daemons),
            haproxy_payload(
                {"rgw-ingress": ("storage1", "storage2")}
            ),
            expected_daemons=daemons,
            ingress_target={
                "proxy": "rgw-ingress",
                "servers": ["storage1", "storage2"],
            },
            kms_errors=0,
            multipart_uploads=0,
            unexpected_errors=0,
        )


def test_node_exporter_and_prometheus_rates_normalize_host_resources() -> None:
    payloads = {
        f"controller{index}": node_payload()
        for index in range(1, 4)
    }
    payloads.update(
        {
            f"storage{index}": node_payload(device="/dev/sda1")
            for index in range(1, 4)
        }
    )
    roles = {
        instance: (
            "controller"
            if instance.startswith("controller")
            else "storage"
        )
        for instance in payloads
    }
    cpu = api_vector(
        [({"instance": instance}, 50) for instance in payloads]
    )
    oom = api_vector(
        [({"instance": instance}, 0) for instance in payloads]
    )
    result = NATIVE.parse_hosts_surface(
        payloads,
        roles=roles,
        cpu_usage_document=cpu,
        oom_kills_document=oom,
    )
    assert len(result) == 6
    assert result[0] == {
        "clock_offset_milliseconds": 3.0,
        "cpu_usage_percent": 50.0,
        "disk_usage_percent": 55.00000000000001,
        "file_descriptor_usage_percent": 40.0,
        "instance": "controller1",
        "memory_usage_percent": 60.0,
        "oom_kills": 0,
        "role": "controller",
    }
    cpu["data"]["result"].pop()
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="targets incomplete",
    ):
        NATIVE.parse_hosts_surface(
            payloads,
            roles=roles,
            cpu_usage_document=cpu,
            oom_kills_document=oom,
        )


def test_quota_and_reconciliation_auxiliary_evidence_is_strict() -> None:
    quota = {
        "headroom_percent": 40,
        "invariant": True,
        "limit_usage_percent": 60,
        "max_transaction_attempts": 2,
        "stale_claims": 0,
        "unexpected_errors": 0,
    }
    reconciliation = {
        "claims_exact": True,
        "fencing_violations": 0,
        "fresh": True,
        "last_success_age_seconds": 30,
        "stale_claims": 0,
        "workers_total": 2,
        "workers_up": 2,
    }
    assert NATIVE.parse_quota_surface(quota) == {
        **quota,
        "headroom_percent": 40.0,
        "limit_usage_percent": 60.0,
    }
    assert NATIVE.parse_reconciliation_surface(reconciliation) == {
        **reconciliation,
        "last_success_age_seconds": 30.0,
    }
    quota["invariant"] = 1
    with pytest.raises(
        NATIVE.NativeSurfaceError,
        match="invariant",
    ):
        NATIVE.parse_quota_surface(quota)
