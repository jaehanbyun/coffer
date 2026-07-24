from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import stat
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from coffer.keystone import ApplicationCredentialPrincipal
from coffer.tokens import AccessGrant, TokenIssuer


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
REPOSITORY = f"p/{PROJECT_ID}/stage2"


def write_bytes(path: Path, value: bytes, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        mode,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
    os.chmod(path, mode)


def write_text(path: Path, value: str, mode: int = 0o600) -> None:
    write_bytes(path, value.encode(), mode)


def certificate_authority() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Coffer Stage 2 CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def issue_server_certificate(
    ca_key: rsa.RSAPrivateKey,
    ca_certificate: x509.Certificate,
    *,
    common_name: str,
    dns_names: tuple[str, ...],
    include_loopback: bool,
) -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    names: list[x509.GeneralName] = [x509.DNSName(name) for name in dns_names]
    if include_loopback:
        names.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        )
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def config_entry(source: str, destination: str, owner: str, mode: str) -> dict:
    return {
        "source": f"/var/lib/kolla/config_files/{source}",
        "dest": destination,
        "owner": owner,
        "perm": mode,
    }


def kolla_config(
    command: str,
    entries: list[dict],
    permissions: list[dict],
) -> str:
    return (
        json.dumps(
            {
                "command": command,
                "config_files": entries
                + [
                    config_entry(
                        "ca-certificates",
                        "/var/lib/kolla/share/ca-certificates",
                        "root",
                        "0644",
                    )
                ],
                "permissions": permissions,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def prepare_role(
    root: Path,
    role: str,
    *,
    command: str,
    config: str,
    entries: list[tuple[str, bytes, int, str, str]],
    permissions: list[dict],
    ca_pem: bytes,
) -> None:
    directory = root / role
    directory.mkdir(mode=0o700)
    write_text(directory / "coffer.conf", config)
    kolla_entries = [
        config_entry("coffer.conf", "/etc/coffer/coffer.conf", "coffer", "0600")
    ]
    for name, value, mode, destination, destination_mode in entries:
        write_bytes(directory / name, value, mode)
        kolla_entries.append(
            config_entry(name, destination, "coffer", destination_mode)
        )
    ca_directory = directory / "ca-certificates"
    ca_directory.mkdir(mode=0o755)
    write_bytes(ca_directory / "stage2-ca.crt", ca_pem, 0o644)
    write_text(
        directory / "config.json",
        kolla_config(command, kolla_entries, permissions),
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_fixture.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)

    ca_key, ca_certificate = certificate_authority()
    ca_pem = ca_certificate.public_bytes(serialization.Encoding.PEM)
    write_bytes(output / "ca.crt", ca_pem, 0o644)

    certificates = {}
    for role, dns_names, include_loopback in (
        ("api", ("coffer-stage2-api",), True),
        ("edge", ("coffer-stage2-edge",), True),
        ("registry", ("coffer-stage2-registry",), False),
    ):
        certificates[role] = issue_server_certificate(
            ca_key,
            ca_certificate,
            common_name=f"coffer-stage2-{role}",
            dns_names=dns_names,
            include_loopback=include_loopback,
        )

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = TokenIssuer(
        private_key=signing_key,
        issuer="coffer-stage2",
        service="coffer-stage2-registry",
    )
    signing_pem = signing_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    jwks = (json.dumps(issuer.jwks(), indent=2, sort_keys=True) + "\n").encode()

    database = "sqlite:////var/lib/coffer/coffer.sqlite"
    common_database = f"[database]\nconnection = {database}\n"
    api_config = f"""\
{common_database}
[api]
bind_host = 0.0.0.0
bind_port = 8787
workers = 1
threads = 2
tls_certfile = /etc/coffer/api.crt
tls_keyfile = /etc/coffer/api.key

[keystone]
auth_url = https://keystone.invalid/v3

[keystone_authtoken]
www_authenticate_uri = https://keystone.invalid/v3

[token]
enabled = true
issuer = {issuer.issuer}
service = {issuer.service}
private_key_file = /etc/coffer/signing-key.pem
key_id = {issuer.key_id}
"""
    standard_permission = [
        {
            "path": "/var/lib/coffer",
            "owner": "coffer:coffer",
            "recurse": True,
        },
        {
            "path": "/var/log/kolla/coffer",
            "owner": "coffer:coffer",
            "recurse": True,
        },
    ]
    prepare_role(
        output,
        "api",
        command="coffer-api --config-file /etc/coffer/coffer.conf",
        config=api_config,
        entries=[
            (
                "signing-key.pem",
                signing_pem,
                0o600,
                "/etc/coffer/signing-key.pem",
                "0600",
            ),
            ("api.crt", certificates["api"][0], 0o644, "/etc/coffer/api.crt", "0644"),
            ("api.key", certificates["api"][1], 0o600, "/etc/coffer/api.key", "0600"),
        ],
        permissions=standard_permission,
        ca_pem=ca_pem,
    )

    edge_config = f"""\
{common_database}
[edge]
bind_host = 0.0.0.0
bind_port = 8788
workers = 1
threads = 4
tls_certfile = /etc/coffer/edge.crt
tls_keyfile = /etc/coffer/edge.key
api_upstream_url = https://coffer-stage2-api:8787
registry_upstream_url = https://coffer-stage2-registry:8789
api_cafile = /etc/coffer/backend-ca.crt
registry_cafile = /etc/coffer/backend-ca.crt
allow_insecure_http = false
api_upstream_timeout_seconds = 5
registry_upstream_timeout_seconds = 30
jwks_file = /etc/coffer/jwks.json
token_realm = https://127.0.0.1:18788/auth/token

[token]
issuer = {issuer.issuer}
service = {issuer.service}
"""
    prepare_role(
        output,
        "edge",
        command="coffer-edge --config-file /etc/coffer/coffer.conf",
        config=edge_config,
        entries=[
            ("jwks.json", jwks, 0o644, "/etc/coffer/jwks.json", "0644"),
            (
                "backend-ca.crt",
                ca_pem,
                0o644,
                "/etc/coffer/backend-ca.crt",
                "0644",
            ),
            (
                "edge.crt",
                certificates["edge"][0],
                0o644,
                "/etc/coffer/edge.crt",
                "0644",
            ),
            (
                "edge.key",
                certificates["edge"][1],
                0o600,
                "/etc/coffer/edge.key",
                "0600",
            ),
        ],
        permissions=standard_permission,
        ca_pem=ca_pem,
    )

    prepare_role(
        output,
        "bootstrap",
        command="coffer-bootstrap --config-file /etc/coffer/coffer.conf",
        config=common_database,
        entries=[],
        permissions=standard_permission,
        ca_pem=ca_pem,
    )
    reconcile_config = f"""\
{common_database}
[reconciliation]
mode = once
upstream_url = https://coffer-stage2-registry:8789
cafile = /etc/coffer/registry-ca.crt
allow_insecure_http = false
timeout_seconds = 5
batch_limit = 1
lease_seconds = 120
"""
    prepare_role(
        output,
        "reconcile",
        command="coffer-reconcile --config-file /etc/coffer/coffer.conf",
        config=reconcile_config,
        entries=[
            (
                "registry-ca.crt",
                ca_pem,
                0o644,
                "/etc/coffer/registry-ca.crt",
                "0644",
            )
        ],
        permissions=standard_permission,
        ca_pem=ca_pem,
    )

    registry_directory = output / "registry"
    registry_directory.mkdir(mode=0o700)
    registry_secret = secrets.token_urlsafe(48)
    registry_config = f"""\
version: 0.1
log:
  level: info
  formatter: json
  fields:
    service: coffer-stage2-registry
auth:
  token:
    realm: https://127.0.0.1:18788/auth/token
    service: {issuer.service}
    issuer: {issuer.issuer}
    jwks: /etc/coffer-registry/jwks.json
    signingalgorithms: [RS256]
storage:
  delete:
    enabled: true
  filesystem:
    rootdirectory: /var/lib/registry
http:
  addr: 0.0.0.0:8789
  secret: {registry_secret}
  relativeurls: true
  tls:
    certificate: /etc/coffer-registry/registry.crt
    key: /etc/coffer-registry/registry.key
  headers:
    X-Content-Type-Options: [nosniff]
health:
  storagedriver:
    enabled: true
    interval: 10s
    threshold: 3
"""
    registry_entries = [
        config_entry(
            "config.yml", "/etc/coffer-registry/config.yml", "registry", "0600"
        ),
        config_entry(
            "jwks.json", "/etc/coffer-registry/jwks.json", "registry", "0644"
        ),
        config_entry(
            "registry.crt",
            "/etc/coffer-registry/registry.crt",
            "registry",
            "0644",
        ),
        config_entry(
            "registry.key",
            "/etc/coffer-registry/registry.key",
            "registry",
            "0600",
        ),
    ]
    for name, value, mode in (
        ("config.yml", registry_config.encode(), 0o600),
        ("jwks.json", jwks, 0o644),
        ("registry.crt", certificates["registry"][0], 0o644),
        ("registry.key", certificates["registry"][1], 0o600),
    ):
        write_bytes(registry_directory / name, value, mode)
    registry_ca_directory = registry_directory / "ca-certificates"
    registry_ca_directory.mkdir(mode=0o755)
    write_bytes(registry_ca_directory / "stage2-ca.crt", ca_pem, 0o644)
    write_text(
        registry_directory / "config.json",
        kolla_config(
            "registry serve /etc/coffer-registry/config.yml",
            registry_entries,
            [
                {
                    "path": "/var/lib/registry",
                    "owner": "registry:registry",
                    "recurse": True,
                },
                {
                    "path": "/var/log/kolla/coffer-registry",
                    "owner": "registry:registry",
                    "recurse": True,
                },
            ],
        ),
    )

    blob = b'{"architecture":"arm64","os":"linux"}'
    blob_digest = f"sha256:{hashlib.sha256(blob).hexdigest()}"
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": blob_digest,
                "size": len(blob),
            },
            "layers": [],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    manifest_digest = f"sha256:{hashlib.sha256(manifest).hexdigest()}"
    write_bytes(output / "blob.json", blob, 0o644)
    write_bytes(output / "manifest.json", manifest, 0o644)

    principal = ApplicationCredentialPrincipal(
        application_credential_id="stage2-fixture",
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        project_id=PROJECT_ID,
        roles=("member",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        audit_ids=("stage2-fixture",),
    )
    token = issuer.issue(
        principal,
        (AccessGrant("repository", REPOSITORY, ("pull", "push")),),
    ).token
    write_text(
        output / "curl-auth.conf",
        f'header = "Authorization: Bearer {token}"\n',
    )
    write_text(
        output / "forbidden-values.txt",
        f"{token}\n{registry_secret}\n",
    )
    write_text(
        output / "artifact.json",
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "repository": REPOSITORY,
                "blob_digest": blob_digest,
                "manifest_digest": manifest_digest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        0o644,
    )

    for directory in output.iterdir():
        if directory.is_dir():
            os.chmod(directory, 0o700)
    assert stat.S_IMODE((output / "curl-auth.conf").stat().st_mode) == 0o600
    print("Generated owner-only disposable Kolla runtime fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
