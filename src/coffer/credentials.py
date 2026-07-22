from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import re


MAX_AUTHORIZATION_HEADER_BYTES = 16 * 1024
MAX_APPLICATION_CREDENTIAL_ID_BYTES = 512
MAX_APPLICATION_CREDENTIAL_SECRET_BYTES = 8 * 1024
APPLICATION_CREDENTIAL_ID = re.compile(
    r"(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})"
)


class InvalidBasicCredentials(Exception):
    pass


@dataclass(frozen=True, slots=True)
class BasicApplicationCredential:
    application_credential_id: str
    application_credential_secret: str = field(repr=False)


def parse_basic_application_credential(
    authorization: str | None,
) -> BasicApplicationCredential:
    if not authorization:
        raise InvalidBasicCredentials("Basic application credential is required")
    if len(authorization.encode("utf-8")) > MAX_AUTHORIZATION_HEADER_BYTES:
        raise InvalidBasicCredentials("Authorization header is too large")

    scheme, separator, encoded = authorization.partition(" ")
    if not separator or scheme.lower() != "basic" or not encoded or " " in encoded:
        raise InvalidBasicCredentials("Basic application credential is malformed")

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidBasicCredentials(
            "Basic application credential is malformed"
        ) from exc

    identifier, separator, secret = decoded.partition(b":")
    if not separator or not identifier or not secret:
        raise InvalidBasicCredentials("Basic application credential is malformed")
    if len(identifier) > MAX_APPLICATION_CREDENTIAL_ID_BYTES:
        raise InvalidBasicCredentials("Application credential ID is too large")
    if len(secret) > MAX_APPLICATION_CREDENTIAL_SECRET_BYTES:
        raise InvalidBasicCredentials("Application credential secret is too large")

    try:
        decoded_identifier = identifier.decode("utf-8")
        decoded_secret = secret.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidBasicCredentials(
            "Basic application credential must be UTF-8"
        ) from exc
    if APPLICATION_CREDENTIAL_ID.fullmatch(decoded_identifier) is None:
        raise InvalidBasicCredentials(
            "Basic username must be an application credential ID"
        )

    return BasicApplicationCredential(
        application_credential_id=decoded_identifier,
        application_credential_secret=decoded_secret,
    )
