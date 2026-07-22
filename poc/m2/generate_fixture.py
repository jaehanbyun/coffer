from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from coffer.tokens import public_jwk


def _write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_fixture.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    next_private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    next_private_pem = next_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    _write_private(output / "private.pem", private_pem)
    _write_private(output / "next-private.pem", next_private_pem)

    jwks = {
        "keys": [
            public_jwk(private_key.public_key()),
            public_jwk(next_private_key.public_key()),
        ]
    }
    (output / "jwks.json").write_text(
        json.dumps(jwks, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    fixture_values = {
        "COFFER_M2_MEMBER_CREDENTIAL_ID": str(uuid.uuid4()),
        "COFFER_M2_MEMBER_CREDENTIAL_SECRET": secrets.token_urlsafe(32),
        "COFFER_M2_READER_CREDENTIAL_ID": str(uuid.uuid4()),
        "COFFER_M2_READER_CREDENTIAL_SECRET": secrets.token_urlsafe(32),
        "COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_ID": str(uuid.uuid4()),
        "COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_SECRET": secrets.token_urlsafe(32),
        "COFFER_M2_PRIVATE_KEY_FILE": str(output / "private.pem"),
        "COFFER_M2_NEXT_PRIVATE_KEY_FILE": str(output / "next-private.pem"),
        "COFFER_M2_DATABASE_FILE": str(output / "coffer.sqlite"),
        "COFFER_M2_PROJECT_ID": str(uuid.uuid4()),
        "COFFER_M2_PROJECT_B_ID": str(uuid.uuid4()),
    }
    environment = "".join(f"{key}={value}\n" for key, value in fixture_values.items())
    _write_private(output / "fixture.env", environment.encode())
    print(f"Generated ephemeral M2 fixture under {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
