from __future__ import annotations

from datetime import UTC, datetime, timedelta
import grp
import ipaddress
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import yaml

from coffer.tokens import public_jwk


ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
WORK = HARNESS / "work"


def write_bytes(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def write_text(path: Path, content: str, mode: int) -> None:
    write_bytes(path, content.encode(), mode)


def private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def certificate_pair() -> tuple[bytes, bytes, bytes]:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Coffer Stage 3 Contract CA")]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "registry.internal.example.test")]
    )
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("registry.internal.example.test"),
                    x509.DNSName("registry.example.test"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.2")),
                ]
            ),
            False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()
            ),
            False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return (
        ca_certificate.public_bytes(serialization.Encoding.PEM),
        server_certificate.public_bytes(serialization.Encoding.PEM),
        private_pem(server_key),
    )


def prepare() -> None:
    if WORK.exists():
        shutil.rmtree(WORK)
    source_config = WORK / "source-config"
    target_config = WORK / "target-config"
    secret_directory = source_config / "coffer" / "secrets"
    public_directory = source_config / "coffer" / "public"
    certificate_directory = source_config / "certificates"

    for directory in (
        WORK / "bin",
        target_config / "haproxy" / "services.d",
        target_config / "proxysql" / "users",
        target_config / "proxysql" / "rules",
        secret_directory,
        public_directory,
        certificate_directory / "ca",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    write_text(
        WORK / "bin" / "ip",
        "#!/bin/sh\n"
        "printf '%s\\n' "
        "'1: en0    inet 127.0.0.2/8 scope host en0'\n",
        0o755,
    )
    write_text(
        WORK / "bin" / "docker",
        "#!/bin/sh\n"
        "# Contract-only stand-in for config-validator exec calls.\n"
        "[ \"${1:-}\" = exec ] || exit 64\n"
        "exit 0\n",
        0o755,
    )

    fixture_secrets = {
        "database-password": secrets.token_urlsafe(32),
        "keystone-service-password": secrets.token_urlsafe(32),
        "distribution-http-secret": secrets.token_urlsafe(48),
        "rgw-access-key": secrets.token_hex(10).upper(),
        "rgw-secret-key": secrets.token_urlsafe(40),
    }
    for name, value in fixture_secrets.items():
        write_text(secret_directory / name, value + "\n", 0o600)

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_id = "coffer-stage3-contract"
    write_bytes(secret_directory / "signing-key.pem", private_pem(signing_key), 0o600)
    write_text(
        public_directory / "jwks.json",
        json.dumps(
            {"keys": [public_jwk(signing_key.public_key(), key_id=key_id)]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        0o644,
    )

    ca_pem, certificate_pem, private_key_pem = certificate_pair()
    write_bytes(certificate_directory / "ca" / "contract-ca.crt", ca_pem, 0o644)
    write_bytes(certificate_directory / "backend-cert.pem", certificate_pem, 0o644)
    write_bytes(certificate_directory / "backend-key.pem", private_key_pem, 0o600)
    write_bytes(source_config / "coffer" / "certs" / "rgw-ca.crt", ca_pem, 0o644)

    user = pwd.getpwuid(os.getuid())
    runtime_vars = {
        "CONFIG_DIR": str(WORK / "kolla-config"),
        "api_interface": "en0",
        "ansible_become_exe": str(HARNESS / "fake-sudo"),
        "ansible_python_interpreter": str(
            ROOT / "work/kolla-ansible-stage3/.venv/bin/python"
        ),
        "coffer_backend_cacert": str(certificate_directory / "ca/contract-ca.crt"),
        "coffer_backend_tls_cert": str(
            certificate_directory / "backend-cert.pem"
        ),
        "coffer_backend_tls_key": str(
            certificate_directory / "backend-key.pem"
        ),
        "coffer_config_controller_become": False,
        "coffer_rgw_cacert": str(source_config / "coffer/certs/rgw-ca.crt"),
        "coffer_secret_owner_uid": os.getuid(),
        "coffer_token_key_id": key_id,
        "config_owner_group": grp.getgrgid(user.pw_gid).gr_name,
        "config_owner_user": user.pw_name,
        "kolla_certificates_dir": str(certificate_directory),
        "kolla_action_stop_ignore_missing": False,
        "node_config": str(WORK / "kolla-config"),
        "node_config_directory": str(target_config),
        "node_custom_config": str(source_config),
    }
    write_text(
        WORK / "runtime-vars.yml",
        yaml.safe_dump(runtime_vars, sort_keys=True),
        0o600,
    )
    write_text(
        WORK / "fixture-secrets.json",
        json.dumps(sorted(fixture_secrets.values()), indent=2) + "\n",
        0o600,
    )
    write_text(
        WORK / "state.json",
        json.dumps({"containers": {}, "operations": []}, indent=2) + "\n",
        0o600,
    )
    write_text(WORK / "events.jsonl", "", 0o600)


if __name__ == "__main__":
    prepare()
