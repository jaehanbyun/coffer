from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import ssl
import stat
import sys
import threading
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent
POC_DIRECTORY = LOAD_DIRECTORY.parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


phase_evidence = _module(
    "coffer_load_evidence_server_phase_evidence",
    DIRECTORY / "phase_evidence.py",
)
native_target = phase_evidence.native_target
load_contract = phase_evidence.load_contract
observability_contract = phase_evidence.observability_contract

CONFIG_SCHEMA = "coffer.load-telemetry-evidence-server-config/v1"
RESULT_SCHEMA = "coffer.load-telemetry-evidence-server-result/v1"
SOURCE_RESULT_SCHEMA = "coffer.load-telemetry-evidence-server-source-result/v1"
SOURCE_FILES = (
    DIRECTORY / "native_surfaces.py",
    DIRECTORY / "native_target.py",
    DIRECTORY / "render_target.py",
    DIRECTORY / "phase_evidence.py",
    DIRECTORY / "evidence_server.py",
)
MAX_TLS_FILE_BYTES = 64 * 1024
MAX_CONCURRENCY = 32
MAX_REQUEST_TIMEOUT_SECONDS = 30


class EvidenceServerError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise EvidenceServerError(f"{category} boundary changed")
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


def server_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": path.name,
                    "sha256": _payload_hash(path.read_bytes()),
                }
            )
    except OSError as error:
        raise EvidenceServerError("server source is unavailable") from error
    return _hash({"files": files})


def _sha256(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or native_target.SHA256.fullmatch(value) is None
    ):
        raise EvidenceServerError(f"{category} is invalid")
    return value


def _integer(
    value: object,
    category: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise EvidenceServerError(f"{category} is invalid")
    return value


def _absolute_path(value: object, category: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1024
        or "\x00" in value
    ):
        raise EvidenceServerError(f"{category} is invalid")
    path = Path(value)
    if not path.is_absolute() or str(path) != value:
        raise EvidenceServerError(f"{category} is not canonical")
    return path


def _private_bind(value: object) -> str:
    if not isinstance(value, str):
        raise EvidenceServerError("server bind address is invalid")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise EvidenceServerError("server bind address is invalid") from error
    if (
        address.version != 4
        or address.compressed != value
        or address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or not (address.is_loopback or address.is_private)
    ):
        raise EvidenceServerError("server bind address is not private")
    return value


def _server_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 253
        or value != value.lower()
        or value.endswith(".")
    ):
        raise EvidenceServerError("server name is invalid")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    if address is not None:
        if address.compressed != value:
            raise EvidenceServerError("server name is not canonical")
        return value
    if native_target.HOST_PATTERN.fullmatch(value) is None:
        raise EvidenceServerError("server name is invalid")
    return value


def _read_owner_document(
    path: Path,
) -> tuple[object, bytes, os.stat_result]:
    try:
        return phase_evidence._read_owner_document(path)
    except phase_evidence.PhaseEvidenceError as error:
        raise EvidenceServerError("server document is unavailable") from error


def _read_owner_bytes(
    path: Path,
    *,
    category: str,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise EvidenceServerError(f"{category} is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= MAX_TLS_FILE_BYTES
        ):
            raise EvidenceServerError(f"{category} is unsafe")
        payload = os.read(descriptor, MAX_TLS_FILE_BYTES + 1)
        if len(payload) != metadata.st_size:
            raise EvidenceServerError(f"{category} changed")
    except OSError as error:
        raise EvidenceServerError(f"{category} is unavailable") from error
    finally:
        os.close(descriptor)
    return payload, metadata


def _distinct_files(
    files: Sequence[tuple[Path, os.stat_result]],
) -> None:
    paths = [path for path, _ in files]
    inodes = [
        (metadata.st_dev, metadata.st_ino)
        for _, metadata in files
    ]
    if len(set(paths)) != len(paths) or len(set(inodes)) != len(inodes):
        raise EvidenceServerError("server input files alias")


def _certificate_pair(
    certificate_payload: bytes,
    private_key_payload: bytes,
    *,
    server_name: str,
) -> None:
    try:
        certificate = x509.load_pem_x509_certificate(certificate_payload)
        private_key = serialization.load_pem_private_key(
            private_key_payload,
            password=None,
        )
        basic_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
        extended_key_usage = certificate.extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        ).value
        key_usage = certificate.extensions.get_extension_for_class(
            x509.KeyUsage
        ).value
        subject_alternative_name = (
            certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
        )
    except (TypeError, ValueError, x509.ExtensionNotFound) as error:
        raise EvidenceServerError("server TLS material is invalid") from error
    if (
        basic_constraints.ca
        or ExtendedKeyUsageOID.SERVER_AUTH not in extended_key_usage
        or not key_usage.digital_signature
        or key_usage.key_cert_sign
        or certificate.not_valid_before_utc > datetime.now(UTC)
        or certificate.not_valid_after_utc <= datetime.now(UTC)
        or certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        != private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ):
        raise EvidenceServerError("server TLS material is invalid")
    try:
        expected_address = ipaddress.ip_address(server_name)
    except ValueError:
        expected_address = None
    if expected_address is None:
        names = subject_alternative_name.get_values_for_type(x509.DNSName)
        if server_name not in names:
            raise EvidenceServerError("server certificate name changed")
    else:
        addresses = subject_alternative_name.get_values_for_type(
            x509.IPAddress
        )
        if expected_address not in addresses:
            raise EvidenceServerError("server certificate name changed")


@dataclass(frozen=True)
class ServerConfiguration:
    bind_address: str
    bundle_sha256: str
    certificate_file: Path
    documents: Mapping[str, bytes]
    max_concurrency: int
    phase: str
    port: int
    private_key_file: Path
    request_timeout_seconds: int
    server_name: str
    target_sha256: str


def load_configuration(path: Path) -> ServerConfiguration:
    value, _, config_metadata = _read_owner_document(path)
    config = _exact(
        value,
        {
            "bind_address",
            "bundle_file",
            "bundle_file_sha256",
            "certificate_file",
            "certificate_sha256",
            "max_concurrency",
            "phase",
            "port",
            "private_key_file",
            "private_key_sha256",
            "request_timeout_seconds",
            "schema",
            "server_name",
            "server_source_sha256",
            "target_file",
            "target_file_sha256",
        },
        "evidence server configuration",
    )
    if (
        config["schema"] != CONFIG_SCHEMA
        or config["server_source_sha256"] != server_source_sha256()
        or config["phase"] not in native_target.PHASES
    ):
        raise EvidenceServerError("evidence server binding changed")
    bind_address = _private_bind(config["bind_address"])
    server_name = _server_name(config["server_name"])
    port = _integer(
        config["port"],
        "server port",
        minimum=1,
        maximum=65535,
    )
    max_concurrency = _integer(
        config["max_concurrency"],
        "server concurrency",
        minimum=1,
        maximum=MAX_CONCURRENCY,
    )
    request_timeout_seconds = _integer(
        config["request_timeout_seconds"],
        "server request timeout",
        minimum=1,
        maximum=MAX_REQUEST_TIMEOUT_SECONDS,
    )
    bundle_file = _absolute_path(config["bundle_file"], "bundle file")
    target_file = _absolute_path(config["target_file"], "target file")
    certificate_file = _absolute_path(
        config["certificate_file"],
        "certificate file",
    )
    private_key_file = _absolute_path(
        config["private_key_file"],
        "private key file",
    )
    bundle_value, bundle_payload, bundle_metadata = _read_owner_document(
        bundle_file
    )
    target_value, target_payload, target_metadata = _read_owner_document(
        target_file
    )
    certificate_payload, certificate_metadata = _read_owner_bytes(
        certificate_file,
        category="server certificate",
    )
    private_key_payload, private_key_metadata = _read_owner_bytes(
        private_key_file,
        category="server private key",
    )
    _distinct_files(
        (
            (path, config_metadata),
            (bundle_file, bundle_metadata),
            (target_file, target_metadata),
            (certificate_file, certificate_metadata),
            (private_key_file, private_key_metadata),
        )
    )
    if (
        config["bundle_file_sha256"] != _payload_hash(bundle_payload)
        or config["target_file_sha256"] != _payload_hash(target_payload)
        or config["certificate_sha256"]
        != _payload_hash(certificate_payload)
        or config["private_key_sha256"]
        != _payload_hash(private_key_payload)
    ):
        raise EvidenceServerError("evidence server file hash changed")
    _sha256(config["bundle_file_sha256"], "bundle file hash")
    _sha256(config["target_file_sha256"], "target file hash")
    _sha256(config["certificate_sha256"], "certificate hash")
    _sha256(config["private_key_sha256"], "private key hash")
    try:
        bundle = phase_evidence.validate_bundle(bundle_value)
    except phase_evidence.PhaseEvidenceError as error:
        raise EvidenceServerError("phase evidence bundle is invalid") from error
    load_topology = load_contract.load_topology(
        LOAD_DIRECTORY / "topology.json"
    )
    observability_topology = observability_contract.load_topology(
        POC_DIRECTORY / "observability" / "topology.json"
    )
    topology_sha256 = native_target._hash(load_topology)
    try:
        target = native_target.validate_target(
            target_value,
            topology_sha256=topology_sha256,
            load_topology=load_topology,
            observability_topology=observability_topology,
        ).raw
    except native_target.NativeTargetError as error:
        raise EvidenceServerError("native target is invalid") from error
    if (
        bundle["phase"] != config["phase"]
        or bundle["target_file_sha256"] != config["target_file_sha256"]
        or bundle["target_sha256"] != target["target_sha256"]
    ):
        raise EvidenceServerError("evidence bundle target binding changed")
    documents: dict[str, bytes] = {}
    for surface in phase_evidence.SURFACES:
        source = target["sources"][surface]
        for phase in native_target.PHASES:
            endpoint = source["evidence_urls"][phase]
            parsed = urlsplit(endpoint["url"])
            expected_path = f"/v1/evidence/{surface}/{phase}"
            if (
                parsed.scheme != "https"
                or parsed.hostname != server_name
                or parsed.port != port
                or parsed.path != expected_path
                or parsed.query
                or parsed.fragment
                or endpoint["content_types"]
                != list(native_target.JSON_CONTENT_TYPES)
            ):
                raise EvidenceServerError(
                    "native evidence server route changed"
                )
        current_path = f"/v1/evidence/{surface}/{bundle['phase']}"
        documents[current_path] = _canonical(
            bundle["documents"][surface]["document"]
        )
    _certificate_pair(
        certificate_payload,
        private_key_payload,
        server_name=server_name,
    )
    return ServerConfiguration(
        bind_address=bind_address,
        bundle_sha256=bundle["bundle_sha256"],
        certificate_file=certificate_file,
        documents=documents,
        max_concurrency=max_concurrency,
        phase=bundle["phase"],
        port=port,
        private_key_file=private_key_file,
        request_timeout_seconds=request_timeout_seconds,
        server_name=server_name,
        target_sha256=target["target_sha256"],
    )


class EvidenceRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def version_string(self) -> str:
        return ""

    def _empty(self, status: int, *, allow: bool = False) -> None:
        self.send_response_only(status)
        if allow:
            self.send_header("Allow", "GET")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.close_connection = True

    def send_error(
        self,
        code: int,
        _message: str | None = None,
        _explain: str | None = None,
    ) -> None:
        self._empty(code)

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(
            self.server.configuration.request_timeout_seconds  # type: ignore[attr-defined]
        )

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        content_lengths = self.headers.get_all("Content-Length", failobj=[])
        transfer_encodings = self.headers.get_all(
            "Transfer-Encoding",
            failobj=[],
        )
        accepts = self.headers.get_all("Accept", failobj=[])
        accept_encodings = self.headers.get_all(
            "Accept-Encoding",
            failobj=[],
        )
        hosts = self.headers.get_all("Host", failobj=[])
        expected_host = (
            f"{self.server.configuration.server_name}:"  # type: ignore[attr-defined]
            f"{self.server.configuration.port}"  # type: ignore[attr-defined]
        )
        if (
            parsed.query
            or parsed.fragment
            or content_lengths not in ([], ["0"])
            or transfer_encodings
            or accepts != ["application/json"]
            or accept_encodings not in ([], ["identity"])
            or hosts != [expected_host]
        ):
            self._empty(400)
            return
        document = self.server.configuration.documents.get(  # type: ignore[attr-defined]
            parsed.path
        )
        if document is None:
            self._empty(404)
            return
        self.send_response_only(200)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(document)))
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(document)
        self.wfile.flush()
        self.close_connection = True

    def __getattr__(self, name: str) -> Any:
        if name.startswith("do_"):
            return lambda: self._empty(405, allow=True)
        raise AttributeError(name)


class BoundedEvidenceServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = MAX_CONCURRENCY

    def __init__(
        self,
        configuration: ServerConfiguration,
        context: ssl.SSLContext,
    ):
        self.configuration = configuration
        self.ssl_context = context
        self._slots = threading.BoundedSemaphore(
            configuration.max_concurrency
        )
        super().__init__(
            (configuration.bind_address, configuration.port),
            EvidenceRequestHandler,
            bind_and_activate=True,
        )

    def get_request(self) -> tuple[Any, Any]:
        raw_request, client_address = super().get_request()
        raw_request.settimeout(
            self.configuration.request_timeout_seconds
        )
        try:
            request = self.ssl_context.wrap_socket(
                raw_request,
                server_side=True,
            )
        except (OSError, ssl.SSLError):
            raw_request.close()
            raise
        return request, client_address

    def process_request(
        self,
        request: Any,
        client_address: Any,
    ) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(
        self,
        request: Any,
        client_address: Any,
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def build_server(path: Path) -> BoundedEvidenceServer:
    configuration = load_configuration(path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
    try:
        context.load_cert_chain(
            certfile=str(configuration.certificate_file),
            keyfile=str(configuration.private_key_file),
        )
    except (OSError, ssl.SSLError) as error:
        raise EvidenceServerError("server TLS material is unavailable") from error
    try:
        return BoundedEvidenceServer(configuration, context)
    except OSError as error:
        raise EvidenceServerError("evidence server bind failed") from error


def _result(configuration: ServerConfiguration, *, ready: bool) -> bytes:
    return _canonical(
        {
            "bundle_sha256": configuration.bundle_sha256,
            "phase": configuration.phase,
            "ready": ready,
            "schema": RESULT_SCHEMA,
            "target_sha256": configuration.target_sha256,
        }
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = server_source_sha256()
        except EvidenceServerError:
            print("evidence-server-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "schema": SOURCE_RESULT_SCHEMA,
                    "server_source_sha256": source_sha256,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 2 or arguments[0] not in {"check", "serve"}:
        print("evidence-server-refused", file=sys.stderr)
        return 2
    try:
        if arguments[0] == "check":
            configuration = load_configuration(Path(arguments[1]))
            print(_result(configuration, ready=False).decode("utf-8"), end="")
            return 0
        server = build_server(Path(arguments[1]))
    except (
        EvidenceServerError,
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ):
        print("evidence-server-refused", file=sys.stderr)
        return 2
    try:
        print(
            _result(server.configuration, ready=True).decode("utf-8"),
            end="",
            flush=True,
        )
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
