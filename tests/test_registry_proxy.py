from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
from pathlib import Path
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from coffer.registry_proxy import RegistryEdgeProxy, UpstreamOrigin


class ReadSpy(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.sizes.append(size)
        return super().read(size)


@contextmanager
def backend(
    *,
    response_body: bytes = b"backend",
    tls_context: ssl.SSLContext | None = None,
) -> Iterator[tuple[ThreadingHTTPServer, list[tuple[str, str, bytes]]]]:
    records: list[tuple[str, str, bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle_request(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            records.append((self.command, self.path, body))
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response_body)

        do_GET = handle_request
        do_HEAD = handle_request
        do_POST = handle_request
        do_PUT = handle_request
        do_PATCH = handle_request
        do_DELETE = handle_request

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls_context is not None:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def make_server_tls(tmp_path: Path) -> tuple[ssl.SSLContext, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "coffer-edge-test")]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path = tmp_path / "server.key"
    certificate_path = tmp_path / "server.crt"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate_path, key_path)
    return context, certificate_path


def origin(
    server: ThreadingHTTPServer,
    *,
    scheme: str = "http",
    host: str = "127.0.0.1",
    cafile: str | None = None,
) -> UpstreamOrigin:
    return UpstreamOrigin.from_url(
        f"{scheme}://{host}:{server.server_port}",
        label="test upstream",
        timeout_seconds=2.0,
        cafile=cafile,
        allow_insecure_http=scheme == "http",
    )


def invoke(
    application: RegistryEdgeProxy,
    path: str,
    *,
    method: str = "GET",
    query: str = "",
    body: bytes = b"",
    stream: io.BytesIO | None = None,
) -> tuple[str, list[tuple[str, str]], list[bytes]]:
    result: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        result["status"] = status
        result["headers"] = headers

    environ = {
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "REQUEST_METHOD": method,
        "wsgi.input": stream or io.BytesIO(body),
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_HOST": "registry.example",
        "HTTP_AUTHORIZATION": "Bearer example",
    }
    iterable = application(environ, start_response)
    chunks = list(iterable)
    return (
        result["status"],  # type: ignore[return-value]
        result["headers"],  # type: ignore[return-value]
        chunks,
    )


def manifest_application(
    environ: dict[str, object],
    start_response,
):
    start_response("202 Accepted", [("Content-Length", "8")])
    return [b"admitted"]


def test_generic_proxy_preserves_client_host_and_filters_hop_headers() -> None:
    headers = RegistryEdgeProxy._headers(
        {
            "HTTP_HOST": "registry.example:5000",
            "HTTP_AUTHORIZATION": "Bearer example",
            "HTTP_CONNECTION": "keep-alive",
            "CONTENT_TYPE": "application/octet-stream",
            "CONTENT_LENGTH": "17",
        }
    )

    assert headers == {
        "Host": "registry.example:5000",
        "Authorization": "Bearer example",
        "Content-Type": "application/octet-stream",
        "Content-Length": "17",
    }


def test_closed_router_separates_api_registry_and_manifest_admission() -> None:
    with backend(response_body=b"api") as (api_server, api_records), backend(
        response_body=b"registry"
    ) as (registry_server, registry_records):
        application = RegistryEdgeProxy(
            manifest_application,
            origin(registry_server),
            api_origin=origin(api_server),
        )

        assert invoke(application, "/auth/token", query="service=registry")[2] == [
            b"api"
        ]
        assert invoke(application, "/v1/repositories")[2] == [b"api"]
        assert invoke(application, "/v2/")[2] == [b"registry"]
        admitted = invoke(
            application,
            "/v2/p/project/repository/manifests/latest",
            method="PUT",
            body=b"manifest",
        )

    assert admitted[0] == "202 Accepted"
    assert admitted[2] == [b"admitted"]
    assert [record[1] for record in api_records] == [
        "/auth/token?service=registry",
        "/v1/repositories",
    ]
    assert [record[1] for record in registry_records] == ["/v2/"]


@pytest.mark.parametrize(
    "path", ("/", "/healthz", "/readyz", "/metrics", "/v3/", "/auth/token/")
)
def test_unknown_and_operational_public_paths_fail_closed(path: str) -> None:
    unavailable = UpstreamOrigin.from_url(
        "http://127.0.0.1:1",
        label="unavailable",
        timeout_seconds=0.1,
        allow_insecure_http=True,
    )
    application = RegistryEdgeProxy(
        manifest_application,
        unavailable,
        api_origin=unavailable,
    )

    status, _headers, chunks = invoke(application, path)

    assert status == "404 Not Found"
    assert b"NOT_FOUND" in b"".join(chunks)


def test_residual_percent_escape_is_rejected_before_backend_routing() -> None:
    unavailable = UpstreamOrigin.from_url(
        "http://127.0.0.1:1",
        label="unavailable",
        timeout_seconds=0.1,
        allow_insecure_http=True,
    )
    application = RegistryEdgeProxy(manifest_application, unavailable)

    status, _headers, chunks = invoke(
        application,
        "/v2/p%2Fproject%2Frepo%2Fmanifests%2Flatest",
        method="PUT",
    )

    assert status == "400 Bad Request"
    assert b"NAME_INVALID" in b"".join(chunks)


def test_malformed_manifest_put_cannot_fall_through_to_distribution() -> None:
    unavailable = UpstreamOrigin.from_url(
        "http://127.0.0.1:1",
        label="unavailable",
        timeout_seconds=0.1,
        allow_insecure_http=True,
    )
    application = RegistryEdgeProxy(manifest_application, unavailable)

    status, _headers, chunks = invoke(
        application,
        "/v2/p/project/repository/manifests/latest/extra",
        method="PUT",
    )

    assert status == "400 Bad Request"
    assert b"MANIFEST_INVALID" in b"".join(chunks)


def test_streamed_request_and_response_remain_bounded() -> None:
    request_body = b"x" * (512 * 1024)
    response_body = b"y" * (512 * 1024)
    stream = ReadSpy(request_body)
    with backend(response_body=response_body) as (registry_server, records):
        application = RegistryEdgeProxy(
            manifest_application, origin(registry_server)
        )
        status, headers, chunks = invoke(
            application,
            "/v2/p/project/repository/blobs/uploads/id",
            method="PATCH",
            body=request_body,
            stream=stream,
        )

    assert status == "200 OK"
    assert ("Connection", "keep-alive") not in headers
    assert b"".join(chunks) == response_body
    assert records[0][2] == request_body
    assert all(size <= 64 * 1024 for size in map(len, chunks))
    assert -1 not in stream.sizes


def test_transport_failure_is_a_deterministic_secret_safe_503() -> None:
    unavailable = UpstreamOrigin.from_url(
        "http://127.0.0.1:1",
        label="credential-secret",
        timeout_seconds=0.1,
        allow_insecure_http=True,
    )
    application = RegistryEdgeProxy(manifest_application, unavailable)

    status, headers, chunks = invoke(application, "/v2/")
    body = b"".join(chunks)

    assert status == "503 Service Unavailable"
    assert ("Retry-After", "5") in headers
    assert b"UNAVAILABLE" in body
    assert b"credential-secret" not in body


def test_verified_tls_accepts_ca_and_hostname_and_rejects_both_failures(
    tmp_path: Path,
) -> None:
    tls_context, certificate = make_server_tls(tmp_path)
    with backend(response_body=b"tls", tls_context=tls_context) as (
        registry_server,
        _records,
    ):
        trusted = RegistryEdgeProxy(
            manifest_application,
            origin(
                registry_server,
                scheme="https",
                cafile=str(certificate),
            ),
            api_origin=origin(
                registry_server,
                scheme="https",
                cafile=str(certificate),
            ),
        )
        untrusted = RegistryEdgeProxy(
            manifest_application,
            origin(registry_server, scheme="https"),
        )
        wrong_hostname = RegistryEdgeProxy(
            manifest_application,
            origin(
                registry_server,
                scheme="https",
                host="localhost",
                cafile=str(certificate),
            ),
        )

        assert invoke(trusted, "/v2/")[0] == "200 OK"
        assert invoke(trusted, "/auth/token")[0] == "200 OK"
        assert invoke(untrusted, "/v2/")[0] == "503 Service Unavailable"
        assert invoke(wrong_hostname, "/v2/")[0] == "503 Service Unavailable"


def test_plaintext_requires_explicit_loopback_fixture_switch() -> None:
    with pytest.raises(ValueError, match="explicit fixture"):
        UpstreamOrigin.from_url(
            "http://127.0.0.1:5000",
            label="registry",
            timeout_seconds=1.0,
        )
    with pytest.raises(ValueError, match="loopback"):
        UpstreamOrigin.from_url(
            "http://registry.internal:5000",
            label="registry",
            timeout_seconds=1.0,
            allow_insecure_http=True,
        )
    assert UpstreamOrigin.from_url(
        "http://127.0.0.1:5000",
        label="registry",
        timeout_seconds=1.0,
        allow_insecure_http=True,
    ).scheme == "http"
