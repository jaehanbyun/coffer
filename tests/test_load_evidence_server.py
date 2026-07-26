from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import stat
import sys
import threading
from typing import Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "evidence_server.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


SERVER = load_module("coffer_load_evidence_server_tests", SERVER_PATH)
COMPILER = SERVER.phase_evidence
RENDERER = COMPILER.render_target
LOAD_TOPOLOGY = SERVER.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = SERVER.observability_contract.load_topology(
    ROOT / "poc" / "observability" / "topology.json"
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
WINDOW_SHA256 = f"sha256:{'7' * 64}"
COLLECTOR_SOURCE_SHA256 = f"sha256:{'8' * 64}"
SOURCE_ARTIFACT_SHA256 = f"sha256:{'9' * 64}"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def target_request(port: int) -> dict:
    all_hosts = CONTROLLERS + STORAGE
    return {
        "adapter_source_sha256": RENDERER.adapter_source_sha256(),
        "inventory": {
            "controllers": list(CONTROLLERS),
            "reconcile_hosts": CONTROLLERS[:2],
            "rgw_daemons": {
                "rgw.coffer.storage1.a": "storage1",
                "rgw.coffer.storage2.b": "storage2",
                "rgw.coffer.storage3.c": "storage3",
            },
            "rgw_ingress_hosts": STORAGE[:2],
            "storage_hosts": list(STORAGE),
        },
        "load_topology_sha256": SERVER.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "observability_topology_sha256": SERVER.native_target._hash(
            OBSERVABILITY_TOPOLOGY.raw
        ),
        "origins": {
            "ceph_exporter": "https://ceph-exporter.stage6.test:9926",
            "ceph_mgr": "https://ceph-mgr.stage6.test:9283",
            "evidence": f"https://localhost:{port}",
            "galera": {
                host: f"https://{host}.stage6.test:9104"
                for host in CONTROLLERS
            },
            "haproxy": "https://haproxy.stage6.test:8405",
            "hosts": {
                host: f"https://{host}.stage6.test:9100"
                for host in all_hosts
            },
            "prometheus": "https://prometheus.stage6.test:9091",
            "rgw_ingress": "https://rgw-ingress.stage6.test:8406",
        },
        "schema": RENDERER.REQUEST_SCHEMA,
        "target_class": SERVER.native_target.TARGET_CLASS,
    }


def evidence_payloads() -> dict[str, dict]:
    return {
        "prometheus": {"secret_leaks": 0},
        "haproxy": {"unexpected_errors": 0},
        "galera": {
            "max_transaction_attempts": 2,
            "unexpected_errors": 0,
        },
        "rgw": {
            "kms_errors": 0,
            "multipart_uploads": 0,
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
            "workers_up": 2,
        },
    }


def summary(surface: str, payload: dict, phase: str) -> dict:
    value = {
        "collector_source_sha256": COLLECTOR_SOURCE_SHA256,
        "payload": payload,
        "phase": phase,
        "schema": COMPILER.SUMMARY_SCHEMA,
        "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
        "source_class": COMPILER.SOURCE_CLASSES[surface],
        "surface": surface,
        "window_sha256": WINDOW_SHA256,
    }
    value["summary_sha256"] = COMPILER._hash(value)
    return value


def evidence_request(target: dict, target_payload: bytes, phase: str) -> dict:
    payloads = evidence_payloads()
    return {
        "compiler_source_sha256": COMPILER.compiler_source_sha256(),
        "load_topology_sha256": SERVER.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "phase": phase,
        "schema": COMPILER.REQUEST_SCHEMA,
        "summaries": {
            surface: summary(surface, payloads[surface], phase)
            for surface in COMPILER.SURFACES
        },
        "target_file_sha256": payload_hash(target_payload),
        "target_sha256": target["target_sha256"],
        "window_sha256": WINDOW_SHA256,
    }


def certificate_material(
    *,
    server_name: str = "localhost",
    mismatch_key: bool = False,
) -> tuple[bytes, bytes, bytes]:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Coffer test CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [x509.NameAttribute(NameOID.COMMON_NAME, server_name)]
            )
        )
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(
                server_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(server_name)]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    private_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if mismatch_key
        else server_key
    )
    return (
        ca_certificate.public_bytes(serialization.Encoding.PEM),
        server_certificate.public_bytes(serialization.Encoding.PEM),
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def server_files(
    tmp_path: Path,
    *,
    phase: str = "before",
    port: int | None = None,
    mismatch_key: bool = False,
) -> tuple[Path, Path, dict, dict, Path]:
    tmp_path.chmod(0o700)
    selected_port = port or free_port()
    target = RENDERER.render_request(target_request(selected_port))
    target_payload = canonical(target)
    request = evidence_request(target, target_payload, phase)
    bundle = COMPILER.compile_bundle(
        request,
        target,
        target_file_sha256=payload_hash(target_payload),
    )
    bundle_payload = canonical(bundle)
    ca_payload, certificate_payload, key_payload = certificate_material(
        mismatch_key=mismatch_key
    )
    target_path = tmp_path / "target.json"
    bundle_path = tmp_path / "bundle.json"
    ca_path = tmp_path / "ca.crt"
    certificate_path = tmp_path / "server.crt"
    private_key_path = tmp_path / "server.key"
    config_path = tmp_path / "server.json"
    owner_file(target_path, target_payload)
    owner_file(bundle_path, bundle_payload)
    owner_file(ca_path, ca_payload)
    owner_file(certificate_path, certificate_payload)
    owner_file(private_key_path, key_payload)
    config = {
        "bind_address": "127.0.0.1",
        "bundle_file": str(bundle_path),
        "bundle_file_sha256": payload_hash(bundle_payload),
        "certificate_file": str(certificate_path),
        "certificate_sha256": payload_hash(certificate_payload),
        "max_concurrency": 4,
        "phase": phase,
        "port": selected_port,
        "private_key_file": str(private_key_path),
        "private_key_sha256": payload_hash(key_payload),
        "request_timeout_seconds": 5,
        "schema": SERVER.CONFIG_SCHEMA,
        "server_name": "localhost",
        "server_source_sha256": SERVER.server_source_sha256(),
        "target_file": str(target_path),
        "target_file_sha256": payload_hash(target_payload),
    }
    owner_file(config_path, canonical(config))
    return config_path, ca_path, target, bundle, private_key_path


@contextmanager
def running_server(
    tmp_path: Path,
    *,
    phase: str = "before",
) -> Iterator[tuple[object, Path, dict, dict]]:
    config_path, ca_path, target, bundle, _ = server_files(
        tmp_path,
        phase=phase,
    )
    server = SERVER.build_server(config_path)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.01},
        daemon=True,
    )
    thread.start()
    try:
        yield server, ca_path, target, bundle
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        assert not thread.is_alive()


def tls_connection(port: int, ca_path: Path) -> http.client.HTTPSConnection:
    context = ssl.create_default_context(cafile=str(ca_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return http.client.HTTPSConnection(
        "localhost",
        port,
        context=context,
        timeout=3,
    )


def test_configuration_binds_target_bundle_routes_and_tls(
    tmp_path: Path,
) -> None:
    config_path, _, target, bundle, private_key_path = server_files(tmp_path)
    configuration = SERVER.load_configuration(config_path)

    assert configuration.phase == "before"
    assert configuration.target_sha256 == target["target_sha256"]
    assert configuration.bundle_sha256 == bundle["bundle_sha256"]
    assert configuration.bind_address == "127.0.0.1"
    assert configuration.server_name == "localhost"
    assert len(configuration.documents) == len(COMPILER.SURFACES)
    assert stat.S_IMODE(private_key_path.stat().st_mode) == 0o600
    for surface in COMPILER.SURFACES:
        path = f"/v1/evidence/{surface}/before"
        assert json.loads(configuration.documents[path]) == bundle[
            "documents"
        ][surface]["document"]


def test_verified_tls_serves_every_exact_native_document(
    tmp_path: Path,
) -> None:
    with running_server(tmp_path, phase="during") as (
        server,
        ca_path,
        target,
        bundle,
    ):
        assert server.ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2
        client = SERVER.native_target.native_surfaces.VerifiedHTTPSClient()
        for surface in COMPILER.SURFACES:
            endpoint = target["sources"][surface]["evidence_urls"]["during"]
            document = client.fetch_json(
                endpoint["url"],
                ca_file=ca_path,
                timeout_seconds=3,
            )
            assert document == bundle["documents"][surface]["document"]


@pytest.mark.parametrize(
    ("method", "path", "headers", "body", "status"),
    (
        (
            "GET",
            "/v1/evidence/prometheus/before?raw=1",
            {"Accept": "application/json"},
            None,
            400,
        ),
        (
            "GET",
            "/v1/evidence/prometheus/during",
            {"Accept": "application/json"},
            None,
            404,
        ),
        ("GET", "/", {"Accept": "application/json"}, None, 404),
        ("GET", "/v1/evidence/prometheus/before", {}, None, 400),
        (
            "GET",
            "/v1/evidence/prometheus/before",
            {"Accept": "application/json", "Content-Length": "1"},
            b"x",
            400,
        ),
        (
            "HEAD",
            "/v1/evidence/prometheus/before",
            {"Accept": "application/json"},
            None,
            405,
        ),
        (
            "POST",
            "/v1/evidence/prometheus/before",
            {"Accept": "application/json", "Content-Length": "0"},
            None,
            405,
        ),
    ),
)
def test_server_refuses_nonexact_http_shapes_without_listing(
    tmp_path: Path,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes | None,
    status: int,
) -> None:
    with running_server(tmp_path) as (server, ca_path, _, _):
        connection = tls_connection(server.server_port, ca_path)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        response_headers = {
            key.lower(): value
            for key, value in response.getheaders()
        }
        connection.close()

        assert response.status == status
        assert payload == b""
        assert response_headers["cache-control"] == "no-store"
        assert response_headers["content-length"] == "0"
        assert response_headers["connection"] == "close"
        assert response_headers["x-content-type-options"] == "nosniff"
        assert "location" not in response_headers
        assert "server" not in response_headers
        assert "date" not in response_headers
        if status == 405:
            assert response_headers["allow"] == "GET"


def test_success_response_has_only_fixed_headers_and_canonical_json(
    tmp_path: Path,
) -> None:
    with running_server(tmp_path) as (server, ca_path, _, bundle):
        connection = tls_connection(server.server_port, ca_path)
        connection.request(
            "GET",
            "/v1/evidence/quota/before",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        payload = response.read()
        headers = {
            key.lower(): value
            for key, value in response.getheaders()
        }
        connection.close()

        document = bundle["documents"]["quota"]["document"]
        assert response.status == 200
        assert payload == canonical(document)
        assert headers == {
            "cache-control": "no-store",
            "connection": "close",
            "content-length": str(len(payload)),
            "content-type": "application/json",
            "x-content-type-options": "nosniff",
        }


def test_hostname_and_ca_verification_fail_closed(tmp_path: Path) -> None:
    with running_server(tmp_path) as (server, ca_path, target, _):
        client = SERVER.native_target.native_surfaces.VerifiedHTTPSClient()
        endpoint = target["sources"]["quota"]["evidence_urls"]["before"]["url"]
        wrong_hostname = endpoint.replace("localhost", "127.0.0.1")
        with pytest.raises(
            SERVER.native_target.native_surfaces.NativeSurfaceError
        ):
            client.fetch_json(
                wrong_hostname,
                ca_file=ca_path,
                timeout_seconds=3,
            )
        wrong_ca, _, _ = certificate_material(server_name="other.test")
        wrong_ca_path = tmp_path / "wrong-ca.crt"
        owner_file(wrong_ca_path, wrong_ca)
        with pytest.raises(
            SERVER.native_target.native_surfaces.NativeSurfaceError
        ):
            client.fetch_json(
                endpoint,
                ca_file=wrong_ca_path,
                timeout_seconds=3,
            )
        assert server._slots.acquire(blocking=False)
        server._slots.release()


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "source-hash",
        "public-bind",
        "wildcard-bind",
        "port",
        "server-name",
        "concurrency",
        "timeout",
        "bundle-hash",
        "target-hash",
        "certificate-hash",
        "key-hash",
        "phase",
        "relative-path",
        "mismatched-key",
    ),
)
def test_configuration_refuses_binding_tls_and_file_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    config_path, _, _, _, _ = server_files(
        tmp_path,
        mismatch_key=mutation == "mismatched-key",
    )
    config = json.loads(config_path.read_bytes())
    if mutation == "schema":
        config["schema"] = "unknown"
    elif mutation == "source-hash":
        config["server_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "public-bind":
        config["bind_address"] = "8.8.8.8"
    elif mutation == "wildcard-bind":
        config["bind_address"] = "0.0.0.0"
    elif mutation == "port":
        config["port"] = 0
    elif mutation == "server-name":
        config["server_name"] = "other.test"
    elif mutation == "concurrency":
        config["max_concurrency"] = 33
    elif mutation == "timeout":
        config["request_timeout_seconds"] = 31
    elif mutation == "bundle-hash":
        config["bundle_file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "target-hash":
        config["target_file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "certificate-hash":
        config["certificate_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "key-hash":
        config["private_key_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "phase":
        config["phase"] = "during"
    elif mutation == "relative-path":
        config["bundle_file"] = "bundle.json"
    if mutation != "mismatched-key":
        owner_file(config_path, canonical(config))

    with pytest.raises(SERVER.EvidenceServerError):
        SERVER.load_configuration(config_path)


@pytest.mark.parametrize(
    "unsafe",
    (
        "config-mode",
        "bundle-mode",
        "target-symlink",
        "certificate-mode",
        "key-symlink",
        "input-alias",
    ),
)
def test_configuration_refuses_unsafe_or_aliased_files(
    tmp_path: Path,
    unsafe: str,
) -> None:
    config_path, _, _, _, _ = server_files(tmp_path)
    config = json.loads(config_path.read_bytes())
    if unsafe == "config-mode":
        config_path.chmod(0o640)
    elif unsafe == "bundle-mode":
        Path(config["bundle_file"]).chmod(0o640)
    elif unsafe == "target-symlink":
        target = Path(config["target_file"])
        real_target = target.with_name("real-target.json")
        target.rename(real_target)
        target.symlink_to(real_target)
    elif unsafe == "certificate-mode":
        Path(config["certificate_file"]).chmod(0o644)
    elif unsafe == "key-symlink":
        key = Path(config["private_key_file"])
        real_key = key.with_name("real-server.key")
        key.rename(real_key)
        key.symlink_to(real_key)
    else:
        certificate = Path(config["certificate_file"])
        certificate.unlink()
        certificate.hardlink_to(Path(config["private_key_file"]))

    with pytest.raises(SERVER.EvidenceServerError):
        SERVER.load_configuration(config_path)


def test_check_and_source_hash_cli_are_secret_safe(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _, target, bundle, _ = server_files(tmp_path)
    assert SERVER.main(["check", str(config_path)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked == {
        "bundle_sha256": bundle["bundle_sha256"],
        "phase": "before",
        "ready": False,
        "schema": SERVER.RESULT_SCHEMA,
        "target_sha256": target["target_sha256"],
    }
    assert SERVER.main(["source-hash"]) == 0
    source_result = json.loads(capsys.readouterr().out)
    assert source_result == {
        "schema": SERVER.SOURCE_RESULT_SCHEMA,
        "server_source_sha256": SERVER.server_source_sha256(),
    }
    assert "https://" not in canonical(checked).decode()
    assert "private" not in canonical(checked).decode()


def test_shutdown_closes_listener_and_source_has_no_ambient_adapter(
    tmp_path: Path,
) -> None:
    config_path, _, _, _, _ = server_files(tmp_path)
    server = SERVER.build_server(config_path)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
    assert not thread.is_alive()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", port))

    source = SERVER_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "urllib.request" not in source
    assert "requests." not in source
    assert "HTTP_PROXY" not in source
    assert "HTTPS_PROXY" not in source
