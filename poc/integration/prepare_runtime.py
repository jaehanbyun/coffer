from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import os
from pathlib import Path
import stat
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from coffer.db import RepositoryStore
from coffer.tokens import public_jwk


REPOSITORY_NAME = "real-rgw"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def write_file(path: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    os.chmod(path, mode)


def private_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def certificate_pem(certificate: x509.Certificate) -> bytes:
    return certificate.public_bytes(serialization.Encoding.PEM)


def load_project_ids(path: Path) -> tuple[str, str]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("credential file must be owner-only")
    fixture = json.loads(path.read_text(encoding="utf-8"))
    project_a = fixture["project_a"]["project_id"].lower()
    project_b = fixture["project_b"]["project_id"].lower()
    uuid.UUID(project_a)
    uuid.UUID(project_b)
    if project_a == project_b:
        raise ValueError("integration projects must be distinct")
    return project_a, project_b


def main() -> None:
    args = parse_args()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    project_a, project_b = load_project_ids(args.credential_file)

    signing_key_path = output / "signing-key.pem"
    jwks_path = output / "jwks.json"
    broker_ca_key_path = output / "broker-ca-key.pem"
    broker_ca_path = output / "broker-ca.crt"
    broker_key_path = output / "broker-key.pem"
    broker_certificate_path = output / "broker.crt"
    database_path = output / "coffer.sqlite"
    targets = (
        signing_key_path,
        jwks_path,
        broker_ca_key_path,
        broker_ca_path,
        broker_key_path,
        broker_certificate_path,
        database_path,
    )
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError("refusing to replace existing integration runtime")

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    write_file(signing_key_path, private_pem(signing_key), 0o600)
    write_file(
        jwks_path,
        (
            json.dumps(
                {"keys": [public_jwk(signing_key.public_key())]},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode(),
        0o644,
    )

    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Coffer token PoC CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    write_file(broker_ca_key_path, private_pem(ca_key), 0o600)
    write_file(broker_ca_path, certificate_pem(ca_certificate), 0o644)

    broker_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    broker_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Coffer token broker PoC")]
    )
    broker_certificate = (
        x509.CertificateBuilder()
        .subject_name(broker_name)
        .issuer_name(ca_certificate.subject)
        .public_key(broker_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    write_file(broker_key_path, private_pem(broker_key), 0o600)
    write_file(broker_certificate_path, certificate_pem(broker_certificate), 0o644)

    store = RepositoryStore(
        f"sqlite:///{database_path}", bootstrap_schema=True
    )
    store.create(project_a, REPOSITORY_NAME)
    store.create(project_b, REPOSITORY_NAME)
    os.chmod(database_path, 0o600)

    print("Prepared ephemeral real-integration broker runtime.")


if __name__ == "__main__":
    main()
