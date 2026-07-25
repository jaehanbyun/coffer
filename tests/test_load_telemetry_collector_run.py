from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import ssl
import stat
import sys
import threading
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest


ROOT = Path(__file__).resolve().parents[1]
RUN_PATH = (
    ROOT / "poc" / "load-soak" / "collector" / "run.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COLLECTOR = load_module("coffer_load_telemetry_collector_tests", RUN_PATH)
LOAD_TOPOLOGY = COLLECTOR.orchestrator.plan_contract.state_machine.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = (
    COLLECTOR.telemetry.observability_contract.load_topology(
        ROOT / "poc" / "observability" / "topology.json"
    )
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def request() -> dict:
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


def direct_targets(
    phase: str,
    observed_at: int,
) -> dict[str, list[dict]]:
    result = {}
    for component in COLLECTOR.telemetry.DIRECT_COMPONENTS:
        count = LOAD_TOPOLOGY["replicas"][component]
        entries = []
        for index in range(count):
            restarted = (
                phase == "after"
                and component == "edge"
                and index == 0
            )
            entries.append(
                {
                    "counter": (
                        1
                        if restarted
                        else {
                            "before": 10,
                            "during": 20,
                            "after": 30,
                        }[phase]
                    ),
                    "instance": f"{component}{index + 1}",
                    "process_start_seconds": 800 if restarted else 100,
                    "up": (
                        0
                        if phase == "during" and index == 0
                        else 1
                    ),
                }
            )
        result[component] = entries
    return result


def hosts() -> list[dict]:
    return [
        {
            "clock_offset_milliseconds": index - 3,
            "cpu_usage_percent": 50,
            "disk_usage_percent": 55,
            "file_descriptor_usage_percent": 40,
            "instance": (
                f"controller{index + 1}"
                if index < 3
                else f"storage{index - 2}"
            ),
            "memory_usage_percent": 60,
            "oom_kills": 0,
            "role": "controller" if index < 3 else "storage",
        }
        for index in range(6)
    ]


def snapshot(phase: str, observed_at: int) -> dict:
    during = phase == "during"
    return {
        "galera": {
            "max_transaction_attempts": 2,
            "nodes_primary": 2 if during else 3,
            "nodes_ready": 2 if during else 3,
            "nodes_synced": 2 if during else 3,
            "nodes_total": 3,
            "unexpected_errors": 0,
        },
        "haproxy": {
            "backends": {
                component: {
                    "healthy": (
                        LOAD_TOPOLOGY["replicas"][component] - 1
                        if during
                        else LOAD_TOPOLOGY["replicas"][component]
                    ),
                    "total": LOAD_TOPOLOGY["replicas"][component],
                }
                for component in ("api", "edge", "registry")
            },
            "unexpected_errors": 0,
        },
        "hosts": hosts(),
        "observed_at_seconds": observed_at,
        "phase": phase,
        "prometheus": {
            "alerts_loaded": list(LOAD_TOPOLOGY["required_alerts"]),
            "direct_targets": direct_targets(phase, observed_at),
            "firing_alerts": ["CofferTargetDown"] if during else [],
            "recording_rules_loaded": list(
                LOAD_TOPOLOGY["required_recording_rules"]
            ),
            "schema_mismatches": 0,
            "scrape_interval_seconds": 30,
            "secret_leaks": 0,
            "stale_series": 1 if during else 0,
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
            "workers_up": 1 if during else 2,
        },
        "rgw": {
            "daemons_total": 3,
            "daemons_up": 2 if during else 3,
            "ingress_total": 2,
            "ingress_up": 1 if during else 2,
            "kms_errors": 0,
            "multipart_uploads": 2 if during else 0,
            "unexpected_errors": 0,
        },
    }


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
        .serial_number(1)
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
    cert_path = tmp_path / "surface.crt"
    key_path = tmp_path / "surface.key"
    owner_file(
        cert_path,
        cert.public_bytes(serialization.Encoding.PEM),
    )
    owner_file(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    return cert_path, key_path


@contextmanager
def surface_server(
    tmp_path: Path,
    *,
    mutation: str | None = None,
) -> Iterator[tuple[str, Path, list[tuple[str, str]]]]:
    cert_path, key_path = certificate(tmp_path)
    paths = {
        surface: f"/v1/{surface}"
        for surface in COLLECTOR.SURFACES
    }
    reverse = {path: surface for surface, path in paths.items()}
    calls: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            phase = parse_qs(parsed.query).get("phase", [""])[0]
            surface = reverse.get(parsed.path, "")
            calls.append((surface, phase))
            if mutation == "redirect" and surface == "prometheus":
                self.send_response(302)
                self.send_header("Location", "https://example.invalid/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            observed_at = {
                "before": 500,
                "during": 700,
                "after": 1000,
            }[phase]
            payload = snapshot(phase, observed_at)[surface]
            if mutation == "semantic" and surface == "galera":
                payload["nodes_ready"] = 0
            wrapper = {
                "payload": payload,
                "phase": phase,
                "schema": COLLECTOR.SURFACE_SCHEMA,
                "surface": surface,
            }
            body = canonical(wrapper)
            if mutation == "binding" and surface == "prometheus":
                wrapper["surface"] = "haproxy"
                body = canonical(wrapper)
            elif mutation == "noncanonical" and surface == "prometheus":
                body = json.dumps(wrapper).encode("utf-8")
            elif mutation == "oversized" and surface == "prometheus":
                body = b"x" * (COLLECTOR.MAX_SURFACE_BYTES + 1)
            self.send_response(200)
            self.send_header(
                "Content-Type",
                (
                    "text/plain"
                    if mutation == "content-type"
                    and surface == "prometheus"
                    else "application/json"
                ),
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"https://localhost:{server.server_port}",
            cert_path,
            calls,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class FixedClock:
    def __init__(self, observed_at: float):
        self.observed_at = observed_at
        self.elapsed = 0.0

    def monotonic(self) -> float:
        self.elapsed += 0.001
        return self.elapsed

    def wall_time(self) -> float:
        return self.observed_at


def fixture(
    tmp_path: Path,
    *,
    base_url: str,
    ca_path: Path,
) -> tuple[dict, dict[str, Path], dict]:
    session = tmp_path / "session"
    session.mkdir(mode=0o700)
    envelope = COLLECTOR.orchestrator.plan_contract.compile_plan(
        request(),
        topology=LOAD_TOPOLOGY,
    )
    plan_payload = canonical(envelope)
    plan_path = tmp_path / "plan.json"
    owner_file(plan_path, plan_payload)

    surface_urls = {
        surface: f"{base_url}/v1/{surface}"
        for surface in COLLECTOR.SURFACES
    }
    target = {
        "adapter": COLLECTOR.ADAPTER,
        "adapter_contract_sha256": f"sha256:{'8' * 64}",
        "schema": COLLECTOR.TARGET_SCHEMA,
        "surface_urls": surface_urls,
        "target_class": COLLECTOR.TARGET_CLASS,
        "topology_sha256": envelope["plan"]["topology_sha256"],
    }
    target["target_sha256"] = COLLECTOR._hash(
        {
            key: target[key]
            for key in (
                "adapter",
                "adapter_contract_sha256",
                "surface_urls",
                "target_class",
                "topology_sha256",
            )
        }
    )
    target_payload = canonical(target)
    target_path = tmp_path / "target.json"
    owner_file(target_path, target_payload)

    ca_payload = ca_path.read_bytes()
    paths = {
        "bundle": session / "bundle.json",
        "lock": session / "lock",
        "plan": plan_path,
        "state": session / "state.json",
        "target": target_path,
    }
    common = {
        "bundle_file": str(paths["bundle"]),
        "ca_file": str(ca_path),
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
    return common, paths, target


def invocation(
    tmp_path: Path,
    common: dict,
    *,
    phase: str,
) -> tuple[dict, Path, Path]:
    order = {"before": 27, "during": 28, "after": 29}[phase]
    output = Path(common["state_file"]).parent / f"{phase}.json"
    document = {
        **common,
        "output_file": str(output),
        "step": {"kind": "telemetry", "name": phase, "order": order},
    }
    path = tmp_path / f"{phase}-invocation.json"
    owner_file(path, canonical(document))
    return document, path, output


def test_three_tls_windows_emit_one_verified_canonical_bundle(
    tmp_path: Path,
) -> None:
    with surface_server(tmp_path) as (base_url, ca_path, calls):
        common, paths, _ = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        for phase, observed_at, complete in (
            ("before", 500, False),
            ("during", 700, False),
            ("after", 1000, True),
        ):
            _, invocation_path, output = invocation(
                tmp_path,
                common,
                phase=phase,
            )
            assert (
                COLLECTOR.execute_invocation(
                    invocation_path,
                    clock=FixedClock(observed_at),
                )
                is complete
            )
            result = json.loads(output.read_bytes())
            assert result["phase"] == phase
            assert result["snapshot_count"] == (
                COLLECTOR.PHASES.index(phase) + 1
            )
            assert result["complete"] is complete
            assert stat.S_IMODE(output.stat().st_mode) == 0o600
        bundle_payload = paths["bundle"].read_bytes()
        bundle = json.loads(bundle_payload)
        assert bundle_payload == canonical(bundle)
        assert bundle["schema"] == COLLECTOR.telemetry.BUNDLE_SCHEMA
        assert bundle["source"] == "fixture"
        assert bundle["synthetic"] is True
        verified = COLLECTOR.telemetry.verify_document(
            bundle,
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
        )
        assert verified["snapshot_count"] == 3
        assert verified["restart_count"] == 1
        assert stat.S_IMODE(paths["state"].stat().st_mode) == 0o600
        assert stat.S_IMODE(paths["bundle"].stat().st_mode) == 0o600
        assert stat.S_IMODE(paths["lock"].stat().st_mode) == 0o600
        assert calls == [
            (surface, phase)
            for phase in COLLECTOR.PHASES
            for surface in COLLECTOR.SURFACES
        ]

        _, before_path, before_output = invocation(
            tmp_path,
            common,
            phase="before",
        )
        retained = before_output.read_bytes()
        assert COLLECTOR.execute_invocation(
            before_path,
            clock=FixedClock(500),
        )
        assert before_output.read_bytes() == retained
        assert len(calls) == 21


def test_pilot_bundle_requires_independent_result_and_expected_hashes(
    tmp_path: Path,
) -> None:
    with surface_server(tmp_path) as (base_url, ca_path, _):
        common, paths, target = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        common["execution_source"] = "pilot"
        after_output = None
        for phase, observed_at in (
            ("before", 500),
            ("during", 700),
            ("after", 1000),
        ):
            _, invocation_path, output = invocation(
                tmp_path,
                common,
                phase=phase,
            )
            COLLECTOR.execute_invocation(
                invocation_path,
                clock=FixedClock(observed_at),
            )
            if phase == "after":
                after_output = output
        assert after_output is not None
        bundle = json.loads(paths["bundle"].read_bytes())
        result = json.loads(after_output.read_bytes())
        assert bundle["source"] == "prometheus-export"
        assert bundle["synthetic"] is False
        verified = COLLECTOR.telemetry.verify_collected_document(
            bundle,
            result,
            collector_source_sha256=common[
                "collector_source_sha256"
            ],
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
            plan_sha256=result["plan_sha256"],
            target_sha256=target["target_sha256"],
        )
        assert verified["synthetic"] is False
        assert verified["source"] == "prometheus-export"
        with pytest.raises(COLLECTOR.telemetry.TelemetryError):
            COLLECTOR.telemetry.verify_collected_document(
                bundle,
                result,
                collector_source_sha256=f"sha256:{'0' * 64}",
                load_topology=LOAD_TOPOLOGY,
                observability_topology=OBSERVABILITY_TOPOLOGY,
                plan_sha256=result["plan_sha256"],
                target_sha256=target["target_sha256"],
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "redirect",
        "binding",
        "noncanonical",
        "oversized",
        "content-type",
        "semantic",
    ],
)
def test_surface_transport_or_semantic_drift_fails_without_checkpoint(
    tmp_path: Path,
    mutation: str,
) -> None:
    with surface_server(tmp_path, mutation=mutation) as (
        base_url,
        ca_path,
        _,
    ):
        common, paths, _ = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        _, invocation_path, output = invocation(
            tmp_path,
            common,
            phase="before",
        )
        with pytest.raises(
            COLLECTOR.CommandError,
            match="collection-unavailable",
        ):
            COLLECTOR.execute_invocation(
                invocation_path,
                clock=FixedClock(500),
            )
        assert not paths["state"].exists()
        assert not paths["bundle"].exists()
        assert not output.exists()


def test_verified_tls_refuses_hostname_mismatch_before_checkpoint(
    tmp_path: Path,
) -> None:
    with surface_server(tmp_path) as (base_url, ca_path, _):
        common, paths, target = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        target["surface_urls"] = {
            surface: url.replace("localhost", "127.0.0.1")
            for surface, url in target["surface_urls"].items()
        }
        target["target_sha256"] = COLLECTOR._hash(
            {
                key: target[key]
                for key in (
                    "adapter",
                    "adapter_contract_sha256",
                    "surface_urls",
                    "target_class",
                    "topology_sha256",
                )
            }
        )
        payload = canonical(target)
        owner_file(paths["target"], payload)
        common["target_file_sha256"] = digest(payload)
        _, invocation_path, output = invocation(
            tmp_path,
            common,
            phase="before",
        )
        with pytest.raises(
            COLLECTOR.CommandError,
            match="collection-unavailable",
        ):
            COLLECTOR.execute_invocation(
                invocation_path,
                clock=FixedClock(500),
            )
        assert not paths["state"].exists()
        assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "invocation-mode",
        "plan-hash",
        "target-hash",
        "target-schema",
        "source-hash",
        "insecure-url",
        "path-alias",
        "wrong-step",
        "out-of-order",
    ],
)
def test_preflight_drift_is_refused_before_collection(
    tmp_path: Path,
    mutation: str,
) -> None:
    with surface_server(tmp_path) as (base_url, ca_path, calls):
        common, paths, target = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        document, invocation_path, output = invocation(
            tmp_path,
            common,
            phase="before",
        )
        if mutation == "invocation-mode":
            invocation_path.chmod(0o640)
        elif mutation == "plan-hash":
            document["plan_file_sha256"] = f"sha256:{'0' * 64}"
            owner_file(invocation_path, canonical(document))
        elif mutation == "target-hash":
            document["target_file_sha256"] = f"sha256:{'0' * 64}"
            owner_file(invocation_path, canonical(document))
        elif mutation == "source-hash":
            document["collector_source_sha256"] = f"sha256:{'0' * 64}"
            owner_file(invocation_path, canonical(document))
        elif mutation == "target-schema":
            target["schema"] = "coffer.load-telemetry-target/v2"
            payload = canonical(target)
            owner_file(paths["target"], payload)
            document["target_file_sha256"] = digest(payload)
            owner_file(invocation_path, canonical(document))
        elif mutation == "insecure-url":
            target["surface_urls"]["prometheus"] = target[
                "surface_urls"
            ]["prometheus"].replace("https://", "http://")
            target["target_sha256"] = COLLECTOR._hash(
                {
                    key: target[key]
                    for key in (
                        "adapter",
                        "adapter_contract_sha256",
                        "surface_urls",
                        "target_class",
                        "topology_sha256",
                    )
                }
            )
            payload = canonical(target)
            owner_file(paths["target"], payload)
            document["target_file_sha256"] = digest(payload)
            owner_file(invocation_path, canonical(document))
        elif mutation == "path-alias":
            document["output_file"] = document["state_file"]
            owner_file(invocation_path, canonical(document))
        elif mutation == "wrong-step":
            document["step"]["order"] = 28
            owner_file(invocation_path, canonical(document))
        else:
            document["step"] = {
                "kind": "telemetry",
                "name": "during",
                "order": 28,
            }
            owner_file(invocation_path, canonical(document))
        with pytest.raises(
            COLLECTOR.CommandError,
            match="contract-refused",
        ):
            COLLECTOR.execute_invocation(
                invocation_path,
                clock=FixedClock(500),
            )
        assert calls == []
        assert not paths["state"].exists()
        assert not paths["bundle"].exists()
        assert not output.exists()


def test_state_tamper_and_nonblocking_lock_fail_closed(
    tmp_path: Path,
) -> None:
    with surface_server(tmp_path) as (base_url, ca_path, calls):
        common, paths, _ = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        _, before_path, _ = invocation(
            tmp_path,
            common,
            phase="before",
        )
        assert not COLLECTOR.execute_invocation(
            before_path,
            clock=FixedClock(500),
        )
        state = json.loads(paths["state"].read_bytes())
        state["snapshots"][0]["quota"]["headroom_percent"] = 41
        state["snapshots"][0]["quota"]["limit_usage_percent"] = 59
        owner_file(paths["state"], canonical(state))
        _, during_path, during_output = invocation(
            tmp_path,
            common,
            phase="during",
        )
        with pytest.raises(
            COLLECTOR.CommandError,
            match="contract-refused",
        ):
            COLLECTOR.execute_invocation(
                during_path,
                clock=FixedClock(700),
            )
        assert len(calls) == 7
        assert not during_output.exists()

        state["snapshots"][0]["quota"]["headroom_percent"] = 40
        state["snapshots"][0]["quota"]["limit_usage_percent"] = 60
        owner_file(paths["state"], canonical(state))
        descriptor = paths["lock"].open("r+b")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(
                COLLECTOR.CommandError,
                match="lock-unavailable",
            ):
                COLLECTOR.execute_invocation(
                    during_path,
                    clock=FixedClock(700),
                )
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            descriptor.close()


def test_cli_has_fixed_argument_and_fixture_status(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert COLLECTOR.run([], stdout=stdout, stderr=stderr) == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "load telemetry failed: invalid-arguments\n"
    )

    with surface_server(tmp_path) as (base_url, ca_path, _):
        common, _, _ = fixture(
            tmp_path,
            base_url=base_url,
            ca_path=ca_path,
        )
        _, before_path, _ = invocation(
            tmp_path,
            common,
            phase="before",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        assert (
            COLLECTOR.run(
                ["--invocation", str(before_path)],
                stdout=stdout,
                stderr=stderr,
            )
            == 3
        )
        assert stdout.getvalue() == (
            "load telemetry fixture window collected\n"
        )
        assert stderr.getvalue() == ""
