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


def write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_fixture.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    write_private(output / "private.pem", private_pem)
    (output / "jwks.json").write_text(
        json.dumps(
            {"keys": [public_jwk(private_key.public_key())]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    values = {
        "COFFER_QUOTA_MEMBER_ID": str(uuid.uuid4()),
        "COFFER_QUOTA_MEMBER_SECRET": secrets.token_urlsafe(32),
        "COFFER_QUOTA_PROJECT_B_MEMBER_ID": str(uuid.uuid4()),
        "COFFER_QUOTA_PROJECT_B_MEMBER_SECRET": secrets.token_urlsafe(32),
        "COFFER_QUOTA_PROJECT_A": str(uuid.uuid4()),
        "COFFER_QUOTA_PROJECT_B": str(uuid.uuid4()),
    }
    write_private(
        output / "fixture.env",
        "".join(f"{name}={value}\n" for name, value in values.items()).encode(),
    )
    client_names = (
        "COFFER_QUOTA_MEMBER_ID",
        "COFFER_QUOTA_MEMBER_SECRET",
        "COFFER_QUOTA_PROJECT_A",
    )
    write_private(
        output / "client.env",
        "".join(f"{name}={values[name]}\n" for name in client_names).encode(),
    )
    print(f"Generated ephemeral quota fixture under {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
