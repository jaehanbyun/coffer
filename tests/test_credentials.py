from __future__ import annotations

import base64

import pytest

from coffer.credentials import (
    MAX_APPLICATION_CREDENTIAL_SECRET_BYTES,
    BasicApplicationCredential,
    InvalidBasicCredentials,
    parse_basic_application_credential,
)


def _basic(identifier: bytes, secret: bytes) -> str:
    encoded = base64.b64encode(identifier + b":" + secret).decode("ascii")
    return f"Basic {encoded}"


def test_basic_credentials_split_only_the_first_colon_and_redact_repr() -> None:
    identifier = b"33333333-3333-4333-8333-333333333333"
    credential = parse_basic_application_credential(
        _basic(identifier, b"secret:with:colons")
    )

    assert credential == BasicApplicationCredential(
        application_credential_id=identifier.decode(),
        application_credential_secret="secret:with:colons",
    )
    assert "secret:with:colons" not in repr(credential)


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer token",
        "Basic",
        "Basic !!!not-base64!!!",
        _basic(b"", b"secret"),
        _basic(b"identifier", b""),
        "Basic " + base64.b64encode(b"no-colon").decode("ascii"),
        "Basic " + base64.b64encode(b"identifier:\xff").decode("ascii"),
        _basic(b"identifier-with-newline\n", b"secret"),
    ],
)
def test_malformed_credentials_are_rejected_without_echoing_input(
    authorization: str | None,
) -> None:
    with pytest.raises(InvalidBasicCredentials) as raised:
        parse_basic_application_credential(authorization)

    if authorization and len(authorization) > 16:
        assert authorization not in str(raised.value)


def test_oversized_secret_is_rejected() -> None:
    authorization = _basic(
        b"identifier", b"x" * (MAX_APPLICATION_CREDENTIAL_SECRET_BYTES + 1)
    )

    with pytest.raises(InvalidBasicCredentials):
        parse_basic_application_credential(authorization)
