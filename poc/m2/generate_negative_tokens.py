from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from coffer.tokens import public_jwk


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_negative_tokens.py OUTPUT_FILE")
    output = Path(sys.argv[1]).resolve()
    with open(os.environ["COFFER_M2_PRIVATE_KEY_FILE"], "rb") as stream:
        private_key = serialization.load_pem_private_key(stream.read(), password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise SystemExit("fixture signing key is not RSA")
    with open(os.environ["COFFER_M2_NEXT_PRIVATE_KEY_FILE"], "rb") as stream:
        next_private_key = serialization.load_pem_private_key(
            stream.read(), password=None
        )
    if not isinstance(next_private_key, rsa.RSAPrivateKey):
        raise SystemExit("fixture next signing key is not RSA")

    now = datetime.now(UTC).replace(microsecond=0)
    repository = f"p/{os.environ['COFFER_M2_PROJECT_ID']}/demo"
    base = {
        "iss": "coffer-m2",
        "sub": "00000000-0000-4000-8000-000000000001",
        "aud": "coffer-m2-registry",
        "exp": now + timedelta(minutes=5),
        "nbf": now,
        "iat": now,
        "jti": str(uuid.uuid4()),
        "access": [
            {"type": "repository", "name": repository, "actions": ["pull"]}
        ],
    }
    key_id = public_jwk(private_key.public_key())["kid"]
    next_key_id = public_jwk(next_private_key.public_key())["kid"]

    def sign(claims: dict[str, object]) -> str:
        return jwt.encode(
            claims,
            private_key,
            algorithm="RS256",
            headers={"alg": "RS256", "kid": key_id, "typ": "JWT"},
        )

    expired = {**base, "exp": now - timedelta(minutes=2), "nbf": now - timedelta(minutes=5)}
    future = {**base, "nbf": now + timedelta(minutes=10), "iat": now + timedelta(minutes=10)}
    wrong_issuer = {**base, "iss": "not-coffer"}
    wrong_audience = {**base, "aud": "not-the-registry"}
    valid = sign(base)
    token_parts = valid.split(".")
    token_parts[2] = ("A" if token_parts[2][0] != "A" else "B") + token_parts[2][1:]
    tampered = ".".join(token_parts)
    wrong_algorithm = jwt.encode(
        base,
        "fixture-hmac-key-with-at-least-32-bytes",
        algorithm="HS256",
        headers={"alg": "HS256", "kid": key_id, "typ": "JWT"},
    )
    rotated = jwt.encode(
        base,
        next_private_key,
        algorithm="RS256",
        headers={"alg": "RS256", "kid": next_key_id, "typ": "JWT"},
    )
    tokens = {
        "expired": sign(expired),
        "future": sign(future),
        "tampered": tampered,
        "wrong_algorithm": wrong_algorithm,
        "wrong_audience": sign(wrong_audience),
        "wrong_issuer": sign(wrong_issuer),
        "rotated": rotated,
    }
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(tokens, stream)
    print(f"Generated {len(tokens)} bearer verification cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
