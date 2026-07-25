from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import ssl
import stat
import sys
import threading
from types import SimpleNamespace
from typing import Iterator
from contextlib import contextmanager
from urllib.parse import urlencode, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = (
    ROOT / "poc" / "load-soak" / "collector" / "native_target.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


TARGET = load_module("coffer_load_native_target_tests", TARGET_PATH)
COLLECTOR = load_module(
    "coffer_load_native_target_collector_tests",
    ROOT / "poc" / "load-soak" / "collector" / "run.py",
)
LOAD_TOPOLOGY = json.loads(
    (ROOT / "poc" / "load-soak" / "topology.json").read_bytes()
)
OBSERVABILITY_TOPOLOGY = SimpleNamespace(
    raw=json.loads(
        (ROOT / "poc" / "observability" / "topology.json").read_bytes()
    )
)
TOPOLOGY_SHA256 = TARGET._hash(LOAD_TOPOLOGY)
COLLECTOR_OBSERVABILITY_TOPOLOGY = (
    COLLECTOR.telemetry.observability_contract.load_topology(
        ROOT / "poc" / "observability" / "topology.json"
    )
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
COMPONENT_INSTANCES = {
    "api": CONTROLLERS,
    "edge": CONTROLLERS,
    "reconcile": CONTROLLERS[:2],
    "registry": CONTROLLERS,
}
DAEMONS = {
    "rgw.coffer.storage1.a": "storage1",
    "rgw.coffer.storage2.b": "storage2",
    "rgw.coffer.storage3.c": "storage3",
}
CLUSTER_ID = "11111111-2222-3333-4444-555555555555"


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


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def plan_request() -> dict:
    return {
        "bindings": {
            "architectures": ["aarch64", "x86_64"],
            "ceph_revision": "b" * 40,
            "ceph_version": "v20.2.3",
            "client_versions_hash": f"sha256:{'1' * 64}",
            "configuration_hash": f"sha256:{'2' * 64}",
            "distribution_revision": "a" * 40,
            "distribution_version": "v3.1.2",
            "driver_revision": "c" * 40,
            "image_set_hash": f"sha256:{'3' * 64}",
            "readiness_evidence_hash": f"sha256:{'4' * 64}",
            "readiness_status": "qualified",
        },
        "schema": "coffer.load-execution-plan-request/v1",
        "topology_sha256": COLLECTOR.orchestrator.plan_contract._hash(
            LOAD_TOPOLOGY
        ),
    }


def direct_vector(phase: str = "before") -> dict:
    entries = []
    for component, instances in COMPONENT_INSTANCES.items():
        for instance in instances:
            restarted = (
                phase == "after"
                and component == "edge"
                and instance == CONTROLLERS[0]
            )
            for kind, value in (
                (
                    "counter",
                    1
                    if restarted
                    else {"before": 10, "during": 20, "after": 30}[phase],
                ),
                (
                    "process_start_seconds",
                    1_300 if restarted else 100,
                ),
                (
                    "up",
                    int(
                        not (
                            phase == "during"
                            and instance == instances[0]
                        )
                    ),
                ),
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
            "lastEvaluation": "2026-07-26T00:00:00Z",
            "name": name,
            "query": "vector(1)",
            "type": "recording",
        }
        for name in LOAD_TOPOLOGY["required_recording_rules"]
    ]
    alerts = []
    for name in LOAD_TOPOLOGY["required_alerts"]:
        active = firing and name == "CofferTargetDown"
        alerts.append(
            {
            "alerts": (
                [
                    {
                        "activeAt": "2026-07-26T00:00:00Z",
                        "annotations": {},
                        "labels": {"alertname": name},
                        "state": "firing",
                        "value": "1",
                    }
                ]
                if active
                else []
            ),
            "annotations": {},
            "duration": 120,
            "evaluationTime": 0.001,
            "health": "ok",
            "keepFiringFor": 0,
            "labels": {"service": "coffer"},
            "lastEvaluation": "2026-07-26T00:00:00Z",
            "name": name,
            "query": "vector(0)",
            "state": "firing" if active else "inactive",
            "type": "alerting",
            }
        )
    return {
        "data": {
            "groups": [
                {
                    "evaluationTime": 0.002,
                    "file": "/etc/prometheus/coffer.rules",
                    "interval": 30,
                    "lastEvaluation": "2026-07-26T00:00:00Z",
                    "limit": 0,
                    "name": "coffer.recording",
                    "rules": recording,
                },
                {
                    "evaluationTime": 0.002,
                    "file": "/etc/prometheus/coffer.rules",
                    "interval": 30,
                    "lastEvaluation": "2026-07-26T00:00:00Z",
                    "limit": 0,
                    "name": "coffer.alerts",
                    "rules": alerts,
                },
            ]
        },
        "status": "success",
    }


def haproxy_payload(
    backends: dict[str, list[str]],
    *,
    down: set[tuple[str, str]] | None = None,
) -> bytes:
    down = down or set()
    lines = []
    for proxy, servers in backends.items():
        for server in servers:
            active = "DOWN" if (proxy, server) in down else "UP"
            for state in TARGET.native_surfaces.HAPROXY_STATES:
                lines.append(
                    "haproxy_server_status"
                    f'{{proxy="{proxy}",server="{server}",state="{state}"}} '
                    f"{int(state == active)}"
                )
    return ("\n".join(lines) + "\n").encode()


def galera_payload(*, up: int = 1) -> bytes:
    return (
        f"mysql_up {up}\n"
        "mysql_global_status_wsrep_cluster_size 3\n"
        "mysql_global_status_wsrep_local_state 4\n"
        "mysql_galera_status_info"
        f'{{wsrep_cluster_state_uuid="{CLUSTER_ID}",'
        f'wsrep_local_state_uuid="{CLUSTER_ID}",'
        'wsrep_provider_version="4.22"} 1\n'
    ).encode()


def rgw_metadata_payload() -> bytes:
    return (
        "\n".join(
            "ceph_rgw_metadata"
            f'{{ceph_daemon="{daemon}",hostname="{host}",'
            'ceph_version="20.2.3",'
            f'instance_id="{index}"}} 1'
            for index, (daemon, host) in enumerate(
                DAEMONS.items(),
                start=1,
            )
        )
        + "\n"
    ).encode()


def rgw_socket_payload(*, down: str | None = None) -> bytes:
    return (
        "\n".join(
            "ceph_daemon_socket_up"
            f'{{ceph_daemon="{daemon}",hostname="{host}"}} '
            f"{int(daemon != down)}"
            for daemon, host in DAEMONS.items()
        )
        + "\n"
    ).encode()


def node_payload(device: str) -> bytes:
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
    ).encode()


def json_endpoint(url: str) -> dict:
    return {
        "content_types": list(TARGET.JSON_CONTENT_TYPES),
        "url": url,
    }


def exposition_endpoint(url: str) -> dict:
    return {
        "content_types": list(TARGET.EXPOSITION_CONTENT_TYPES),
        "url": url,
    }


def evidence_urls(base_url: str, surface: str) -> dict:
    return {
        phase: json_endpoint(
            f"{base_url}/evidence/{surface}/{phase}"
        )
        for phase in TARGET.PHASES
    }


def target_document(base_url: str) -> dict:
    queries = {}
    for name, promql in TARGET.PROMQL.items():
        queries[name] = {
            "content_types": list(TARGET.JSON_CONTENT_TYPES),
            "promql": promql,
            "promql_sha256": TARGET._text_hash(promql),
            "url": (
                f"{base_url}/api/v1/query?"
                f"{urlencode([('query', promql)])}"
            ),
        }
    required_rules = [
        *LOAD_TOPOLOGY["required_recording_rules"],
        *LOAD_TOPOLOGY["required_alerts"],
    ]
    rules_url = (
        f"{base_url}/api/v1/rules?"
        f"{urlencode([('rule_name[]', name) for name in required_rules])}"
    )
    target = {
        "adapter": TARGET.ADAPTER,
        "adapter_contract_sha256": f"sha256:{'8' * 64}",
        "schema": TARGET.TARGET_SCHEMA,
        "sources": {
            "galera": {
                "evidence_urls": evidence_urls(base_url, "galera"),
                "instances": {
                    host: exposition_endpoint(
                        f"{base_url}/export/galera/{host}"
                    )
                    for host in CONTROLLERS
                },
                "kind": "mysqld-exporter",
            },
            "haproxy": {
                "backend_targets": {
                    component: {
                        "proxy": f"coffer-{component}",
                        "servers": list(COMPONENT_INSTANCES[component]),
                    }
                    for component in ("api", "edge", "registry")
                },
                "evidence_urls": evidence_urls(base_url, "haproxy"),
                "kind": "haproxy-exporter",
                "metrics": exposition_endpoint(
                    f"{base_url}/export/haproxy"
                ),
            },
            "hosts": {
                "instances": {
                    **{
                        host: {
                            **exposition_endpoint(
                                f"{base_url}/export/node/{host}"
                            ),
                            "role": "controller",
                        }
                        for host in CONTROLLERS
                    },
                    **{
                        host: {
                            **exposition_endpoint(
                                f"{base_url}/export/node/{host}"
                            ),
                            "role": "storage",
                        }
                        for host in STORAGE
                    },
                },
                "kind": "node-exporter",
            },
            "prometheus": {
                "evidence_urls": evidence_urls(
                    base_url,
                    "prometheus",
                ),
                "instances": {
                    component: list(instances)
                    for component, instances in COMPONENT_INSTANCES.items()
                },
                "kind": "prometheus-v1",
                "queries": queries,
                "rules": json_endpoint(rules_url),
            },
            "quota": {
                "evidence_urls": evidence_urls(base_url, "quota"),
                "kind": "phase-evidence",
            },
            "reconciliation": {
                "evidence_urls": evidence_urls(
                    base_url,
                    "reconciliation",
                ),
                "kind": "phase-evidence",
            },
            "rgw": {
                "daemon_metadata": exposition_endpoint(
                    f"{base_url}/export/ceph-mgr"
                ),
                "daemon_sockets": exposition_endpoint(
                    f"{base_url}/export/ceph"
                ),
                "daemons": DAEMONS,
                "evidence_urls": evidence_urls(base_url, "rgw"),
                "ingress": exposition_endpoint(
                    f"{base_url}/export/rgw-ingress"
                ),
                "ingress_target": {
                    "proxy": "rgw-ingress",
                    "servers": STORAGE[:2],
                },
                "kind": "ceph-exporters",
            },
        },
        "target_class": TARGET.TARGET_CLASS,
        "topology_sha256": TOPOLOGY_SHA256,
    }
    target["target_sha256"] = TARGET._hash(target)
    return target


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
        .serial_number(26)
        .not_valid_before(datetime(2026, 7, 25, tzinfo=UTC))
        .not_valid_after(datetime(2027, 7, 26, tzinfo=UTC))
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
    cert_path = tmp_path / "native-target.crt"
    key_path = tmp_path / "native-target.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_path.chmod(0o600)
    key_path.chmod(0o600)
    return cert_path, key_path


@contextmanager
def tls_server(
    tmp_path: Path,
) -> Iterator[
    tuple[
        str,
        Path,
        dict[str, tuple[str, bytes]],
        list[str],
    ]
]:
    cert_path, key_path = certificate(tmp_path)
    responses: dict[str, tuple[str, bytes]] = {}
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            calls.append(self.path)
            response = responses.get(self.path)
            if response is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            content_type, payload = response
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"https://localhost:{server.server_port}",
            cert_path,
            responses,
            calls,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def evidence(surface: str, payload: dict, phase: str = "before") -> bytes:
    return (
        json.dumps(
            {
                "payload": payload,
                "phase": phase,
                "schema": TARGET.EVIDENCE_SCHEMA,
                "surface": surface,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def response_path(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def populate_responses(
    responses: dict[str, tuple[str, bytes]],
    target: dict,
    *,
    phase: str = "before",
) -> None:
    query_values = {
        "direct_targets": direct_vector(phase),
        "host_cpu_usage_percent": api_vector(
            [({"instance": host}, 50) for host in CONTROLLERS + STORAGE]
        ),
        "host_oom_kills": api_vector(
            [({"instance": host}, 0) for host in CONTROLLERS + STORAGE]
        ),
        "schema_mismatches": api_scalar(0),
        "scrape_interval_seconds": api_scalar(30),
        "stale_series": api_scalar(1 if phase == "during" else 0),
    }
    prometheus = target["sources"]["prometheus"]
    for name, endpoint in prometheus["queries"].items():
        responses[response_path(endpoint["url"])] = (
            "application/json",
            json.dumps(query_values[name]).encode(),
        )
    responses[response_path(prometheus["rules"]["url"])] = (
        "application/json",
        json.dumps(rules_document(firing=phase == "during")).encode(),
    )
    payloads = {
        "prometheus": {"secret_leaks": 0},
        "haproxy": {"unexpected_errors": 0},
        "galera": {
            "max_transaction_attempts": 2,
            "unexpected_errors": 0,
        },
        "rgw": {
            "kms_errors": 0,
            "multipart_uploads": 2 if phase == "during" else 0,
            "unexpected_errors": 0,
        },
        "quota": {
            "headroom_percent": 40,
            "invariant": True,
            "limit_usage_percent": 60,
            "max_transaction_attempts": 2,
            "stale_claims": 0,
            "unexpected_errors": 0,
        },
        "reconciliation": {
            "claims_exact": True,
            "fencing_violations": 0,
            "fresh": True,
            "last_success_age_seconds": 30,
            "stale_claims": 0,
            "workers_total": 2,
            "workers_up": 1 if phase == "during" else 2,
        },
    }
    for surface, payload in payloads.items():
        endpoint = target["sources"][surface]["evidence_urls"][phase]
        responses[response_path(endpoint["url"])] = (
            "application/json",
            evidence(surface, payload, phase=phase),
        )
    haproxy = target["sources"]["haproxy"]
    responses[response_path(haproxy["metrics"]["url"])] = (
        "text/plain; version=0.0.4",
        haproxy_payload(
            {
                "coffer-api": CONTROLLERS,
                "coffer-edge": CONTROLLERS,
                "coffer-registry": CONTROLLERS,
            },
            down=(
                {
                    ("coffer-api", CONTROLLERS[0]),
                    ("coffer-edge", CONTROLLERS[0]),
                    ("coffer-registry", CONTROLLERS[0]),
                }
                if phase == "during"
                else set()
            ),
        ),
    )
    for host, endpoint in target["sources"]["galera"]["instances"].items():
        responses[response_path(endpoint["url"])] = (
            "text/plain; version=0.0.4",
            galera_payload(
                up=int(not (phase == "during" and host == CONTROLLERS[-1]))
            ),
        )
    rgw = target["sources"]["rgw"]
    responses[response_path(rgw["daemon_metadata"]["url"])] = (
        "text/plain; version=0.0.4",
        rgw_metadata_payload(),
    )
    responses[response_path(rgw["daemon_sockets"]["url"])] = (
        "text/plain; version=0.0.4",
        rgw_socket_payload(
            down=(
                next(reversed(DAEMONS))
                if phase == "during"
                else None
            )
        ),
    )
    responses[response_path(rgw["ingress"]["url"])] = (
        "text/plain; version=0.0.4",
        haproxy_payload(
            {"rgw-ingress": STORAGE[:2]},
            down=(
                {("rgw-ingress", STORAGE[0])}
                if phase == "during"
                else set()
            ),
        ),
    )
    for host, endpoint in target["sources"]["hosts"]["instances"].items():
        responses[response_path(endpoint["url"])] = (
            "text/plain; version=0.0.4",
            node_payload("/dev/vda1" if host in CONTROLLERS else "/dev/sda1"),
        )


class FixedClock:
    def __init__(self, observed_at: float = 1_000) -> None:
        self.elapsed = 0.0
        self.observed_at = observed_at

    def monotonic(self) -> float:
        self.elapsed += 0.001
        return self.elapsed

    def wall_time(self) -> float:
        return self.observed_at


def test_native_target_composes_one_phase_over_verified_tls(
    tmp_path: Path,
) -> None:
    with tls_server(tmp_path) as (
        base_url,
        ca_file,
        responses,
        calls,
    ):
        target = target_document(base_url)
        populate_responses(responses, target)
        validated = TARGET.validate_target(
            target,
            topology_sha256=TOPOLOGY_SHA256,
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
        )
        assert validated.target_sha256 == target["target_sha256"]
        snapshot = TARGET.compose_phase_snapshot(
            target,
            ca_file=ca_file,
            phase="before",
            timeout_seconds=5,
            topology_sha256=TOPOLOGY_SHA256,
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
            clock=FixedClock(),
        )
        assert snapshot["phase"] == "before"
        assert snapshot["observed_at_seconds"] == 1_000
        assert snapshot["prometheus"]["secret_leaks"] == 0
        assert snapshot["prometheus"]["direct_targets"]["registry"] == [
            {
                "counter": 10.0,
                "instance": host,
                "process_start_seconds": 100.0,
                "up": 1,
            }
            for host in CONTROLLERS
        ]
        assert snapshot["galera"]["nodes_primary"] == 3
        assert snapshot["rgw"]["daemons_up"] == 3
        assert len(snapshot["hosts"]) == 6
        assert len(calls) == 26
        assert all("Authorization" not in call for call in calls)


def test_collector_dispatches_three_native_phases_into_verified_bundle(
    tmp_path: Path,
) -> None:
    with tls_server(tmp_path) as (
        base_url,
        ca_file,
        responses,
        calls,
    ):
        target = target_document(base_url)
        session = tmp_path / "native-session"
        session.mkdir(mode=0o700)
        envelope = COLLECTOR.orchestrator.plan_contract.compile_plan(
            plan_request(),
            topology=LOAD_TOPOLOGY,
        )
        plan_payload = canonical(envelope)
        plan_path = tmp_path / "native-plan.json"
        owner_file(plan_path, plan_payload)
        target_payload = canonical(target)
        target_path = tmp_path / "native-target.json"
        owner_file(target_path, target_payload)
        ca_payload = ca_file.read_bytes()
        paths = {
            "bundle": session / "bundle.json",
            "lock": session / "lock",
            "state": session / "state.json",
        }
        common = {
            "bundle_file": str(paths["bundle"]),
            "ca_file": str(ca_file),
            "ca_sha256": digest(ca_payload),
            "collector_source_sha256": COLLECTOR._source_hash(),
            "execution_source": "fixture",
            "lock_file": str(paths["lock"]),
            "plan_file": str(plan_path),
            "plan_file_sha256": digest(plan_payload),
            "schema": COLLECTOR.INVOCATION_SCHEMA,
            "state_file": str(paths["state"]),
            "target_class": COLLECTOR.TARGET_CLASS,
            "target_file": str(target_path),
            "target_file_sha256": digest(target_payload),
            "timeout_seconds": 5,
        }
        final_result = None
        for phase, observed_at, order in (
            ("before", 1_000, 27),
            ("during", 1_200, 28),
            ("after", 1_400, 29),
        ):
            responses.clear()
            populate_responses(responses, target, phase=phase)
            output_path = session / f"{phase}.json"
            invocation = {
                **common,
                "output_file": str(output_path),
                "step": {
                    "kind": "telemetry",
                    "name": phase,
                    "order": order,
                },
            }
            invocation_path = tmp_path / f"native-{phase}.json"
            owner_file(invocation_path, canonical(invocation))
            assert (
                COLLECTOR.execute_invocation(
                    invocation_path,
                    clock=FixedClock(observed_at),
                )
                is (phase == "after")
            )
            result = json.loads(output_path.read_bytes())
            assert result["phase"] == phase
            assert result["target_sha256"] == target["target_sha256"]
            assert result["collector_source_sha256"] == COLLECTOR._source_hash()
            assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
            if phase == "after":
                final_result = result
        assert final_result is not None
        bundle_payload = paths["bundle"].read_bytes()
        bundle = json.loads(bundle_payload)
        assert bundle_payload == canonical(bundle)
        assert bundle["source"] == "fixture"
        assert bundle["synthetic"] is True
        verified = COLLECTOR.telemetry.verify_document(
            bundle,
            load_topology=LOAD_TOPOLOGY,
            observability_topology=COLLECTOR_OBSERVABILITY_TOPOLOGY,
        )
        assert verified["snapshot_count"] == 3
        assert verified["restart_count"] == 1
        assert final_result["snapshot_count"] == 3
        assert final_result["complete"] is True
        assert len(calls) == 78
        assert stat.S_IMODE(paths["state"].stat().st_mode) == 0o600
        assert stat.S_IMODE(paths["bundle"].stat().st_mode) == 0o600
        assert stat.S_IMODE(paths["lock"].stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "mutation",
    (
        "query-hash",
        "query-url",
        "rules-filter",
        "content-types",
        "repeated-url",
        "controller-drift",
        "target-hash",
    ),
)
def test_native_target_refuses_contract_drift(
    mutation: str,
) -> None:
    target = target_document("https://telemetry.example:9443")
    if mutation == "query-hash":
        target["sources"]["prometheus"]["queries"]["direct_targets"][
            "promql_sha256"
        ] = f"sha256:{'0' * 64}"
    elif mutation == "query-url":
        target["sources"]["prometheus"]["queries"]["direct_targets"][
            "url"
        ] += "&time=1"
    elif mutation == "rules-filter":
        target["sources"]["prometheus"]["rules"]["url"] = target[
            "sources"
        ]["prometheus"]["rules"]["url"].replace(
            "CofferTargetDown",
            "UnknownAlert",
        )
    elif mutation == "content-types":
        target["sources"]["haproxy"]["metrics"]["content_types"] = [
            "application/json"
        ]
    elif mutation == "repeated-url":
        target["sources"]["quota"]["evidence_urls"]["before"]["url"] = target[
            "sources"
        ]["prometheus"]["evidence_urls"]["before"]["url"]
    elif mutation == "controller-drift":
        target["sources"]["prometheus"]["instances"]["api"][0] = "other"
    else:
        target["target_sha256"] = f"sha256:{'0' * 64}"
    if mutation != "target-hash":
        target["target_sha256"] = TARGET._hash(
            {
                key: value
                for key, value in target.items()
                if key != "target_sha256"
            }
        )
    with pytest.raises(TARGET.NativeTargetError):
        TARGET.validate_target(
            target,
            topology_sha256=TOPOLOGY_SHA256,
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
        )


def test_phase_bound_auxiliary_evidence_refuses_mismatch(
    tmp_path: Path,
) -> None:
    with tls_server(tmp_path) as (
        base_url,
        ca_file,
        responses,
        calls,
    ):
        target = target_document(base_url)
        populate_responses(responses, target)
        endpoint = target["sources"]["prometheus"]["evidence_urls"]["before"]
        responses[response_path(endpoint["url"])] = (
            "application/json",
            evidence(
                "prometheus",
                {"secret_leaks": 0},
                phase="during",
            ),
        )
        with pytest.raises(
            TARGET.NativeTargetError,
            match="auxiliary evidence changed",
        ):
            TARGET.compose_phase_snapshot(
                target,
                ca_file=ca_file,
                phase="before",
                timeout_seconds=5,
                topology_sha256=TOPOLOGY_SHA256,
                load_topology=LOAD_TOPOLOGY,
                observability_topology=OBSERVABILITY_TOPOLOGY,
                clock=FixedClock(),
            )
        assert calls
