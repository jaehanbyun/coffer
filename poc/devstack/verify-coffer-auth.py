from __future__ import annotations

import argparse
import json
from pathlib import Path

from coffer.keystone import (
    ApplicationCredentialAuthenticator,
    InvalidApplicationCredential,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-url", required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--expect", choices=("valid", "invalid"), required=True)
    parser.add_argument("--expect-role", action="append", default=[])
    parser.add_argument("--forbid-registry-roles", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixture = json.loads(args.credential_file.read_text())
    credential_id = fixture["application_credential_id"]
    credential_secret = fixture.pop("application_credential_secret")
    expected_project_id = fixture["project_id"]
    expected_user_id = fixture["user_id"]

    authenticator = ApplicationCredentialAuthenticator(
        auth_url=args.auth_url,
        verify=str(args.ca_file),
        timeout=10.0,
    )
    if args.expect == "invalid":
        try:
            authenticator.authenticate(credential_id, credential_secret)
        except InvalidApplicationCredential:
            print(json.dumps({"deleted_credential": "rejected"}))
            return
        raise AssertionError("deleted application credential unexpectedly authenticated")

    principal = authenticator.authenticate(credential_id, credential_secret)
    assert principal.project_id == expected_project_id
    assert principal.user_id == expected_user_id
    expected_roles = args.expect_role or ["member"]
    assert set(expected_roles).issubset(principal.roles)
    if args.forbid_registry_roles:
        assert {"reader", "member", "admin"}.isdisjoint(principal.roles)
    retained = repr(authenticator) + repr(principal)
    assert credential_secret not in retained
    print(
        json.dumps(
            {
                "coffer_authenticator": "verified",
                "project_id": principal.project_id,
                "user_id": principal.user_id,
                "roles": sorted(principal.roles),
                "token_expires_at": principal.expires_at.isoformat(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
