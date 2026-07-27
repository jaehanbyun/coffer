#!/usr/bin/env python3
"""Manage retained, owner-only identities for the live UI preview."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import shlex
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


STATE_PATH = Path("/root/coffer-ui-preview-identities.json")
OPENRC_PATH = Path("/etc/kolla/admin-openrc.sh")
PROJECT_NAMES = {
    "project_a": "coffer-ui-preview-a",
    "project_b": "coffer-ui-preview-b",
}
USER_NAMES = {
    "project_a": "coffer-preview-a",
    "project_b": "coffer-preview-b",
}
CREDENTIAL_NAMES = {
    "project_a": "coffer-ui-preview-a",
    "project_b": "coffer-ui-preview-b",
}


class Keystone:
    def __init__(self, auth_url: str, token: str | None = None) -> None:
        self.base = auth_url.rstrip("/")
        if not self.base.endswith("/v3"):
            self.base += "/v3"
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        document: dict[str, Any] | None = None,
        expected: set[int],
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        data = None
        headers = {"Accept": "application/json"}
        if document is not None:
            data = json.dumps(document).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token is not None:
            headers["X-Auth-Token"] = self.token
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status = response.status
                response_headers = dict(response.headers.items())
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = dict(error.headers.items())
            raw = error.read()
        if status not in expected:
            raise RuntimeError(
                f"Keystone {method} {path} returned unexpected HTTP {status}"
            )
        return (
            json.loads(raw) if raw else None,
            response_headers,
        )


def openrc() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in OPENRC_PATH.read_text(encoding="utf-8").splitlines():
        if not line.startswith("export OS_") or "=" not in line:
            continue
        name, raw = line.removeprefix("export ").split("=", maxsplit=1)
        parsed = shlex.split(raw, comments=False, posix=True)
        if len(parsed) != 1:
            raise RuntimeError(f"invalid {name} assignment in admin openrc")
        values[name] = parsed[0]
    required = {
        "OS_AUTH_URL",
        "OS_PROJECT_DOMAIN_NAME",
        "OS_PROJECT_NAME",
        "OS_PASSWORD",
        "OS_USER_DOMAIN_NAME",
        "OS_USERNAME",
    }
    if not required.issubset(values):
        raise RuntimeError("admin openrc is incomplete")
    return values


def password_document(
    values: dict[str, str],
    *,
    username: str,
    password: str,
    project_name: str | None = None,
    project_id: str | None = None,
    domain_id: str | None = None,
) -> dict[str, Any]:
    user_domain: dict[str, str] = (
        {"id": domain_id}
        if domain_id is not None
        else {"name": values["OS_USER_DOMAIN_NAME"]}
    )
    project: dict[str, Any]
    if project_id is not None:
        project = {"id": project_id}
    elif project_name is not None:
        project = {
            "name": project_name,
            "domain": {"name": values["OS_PROJECT_DOMAIN_NAME"]},
        }
    else:
        raise RuntimeError("password authentication requires a project scope")
    return {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": username,
                        "domain": user_domain,
                        "password": password,
                    }
                },
            },
            "scope": {"project": project},
        }
    }


def token_for(keystone: Keystone, document: dict[str, Any]) -> str:
    _body, headers = keystone.request(
        "POST",
        "/auth/tokens",
        document=document,
        expected={201},
    )
    token = next(
        (
            value
            for name, value in headers.items()
            if name.lower() == "x-subject-token"
        ),
        None,
    )
    if not token:
        raise RuntimeError("Keystone omitted X-Subject-Token")
    return token


def application_credential_token(
    keystone: Keystone,
    identifier: str,
    secret: str,
) -> str:
    return token_for(
        keystone,
        {
            "auth": {
                "identity": {
                    "methods": ["application_credential"],
                    "application_credential": {
                        "id": identifier,
                        "secret": secret,
                    },
                }
            }
        },
    )


def write_state(state: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".coffer-ui-preview-identities.",
        dir=STATE_PATH.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def one(
    keystone: Keystone,
    path: str,
    collection: str,
    *,
    query: dict[str, str],
) -> dict[str, Any] | None:
    suffix = urllib.parse.urlencode(query)
    document, _headers = keystone.request(
        "GET",
        f"{path}?{suffix}",
        expected={200},
    )
    assert document is not None
    matches = document[collection]
    if len(matches) > 1:
        raise RuntimeError(f"Keystone returned duplicate {collection}")
    return matches[0] if matches else None


def delete_owned(keystone: Keystone, state: dict[str, Any]) -> None:
    for fixture_name in ("project_a", "project_b"):
        fixture = state.get(fixture_name, {})
        user_id = fixture.get("user_id")
        credential_id = fixture.get("application_credential_id")
        if user_id and credential_id:
            keystone.request(
                "DELETE",
                f"/users/{user_id}/application_credentials/{credential_id}",
                expected={204, 404},
            )
    for fixture_name in ("project_a", "project_b"):
        user_id = state.get(fixture_name, {}).get("user_id")
        if user_id:
            keystone.request("DELETE", f"/users/{user_id}", expected={204, 404})
    for fixture_name in ("project_a", "project_b"):
        project_id = state.get(fixture_name, {}).get("project_id")
        if project_id:
            keystone.request(
                "DELETE",
                f"/projects/{project_id}",
                expected={204, 404},
            )


def admin() -> tuple[Keystone, dict[str, str]]:
    values = openrc()
    unauthenticated = Keystone(values["OS_AUTH_URL"])
    token = token_for(
        unauthenticated,
        password_document(
            values,
            username=values["OS_USERNAME"],
            password=values["OS_PASSWORD"],
            project_name=values["OS_PROJECT_NAME"],
        ),
    )
    return Keystone(values["OS_AUTH_URL"], token), values


def prepare() -> None:
    if STATE_PATH.exists():
        raise RuntimeError("preview identity state already exists")
    keystone, values = admin()
    domain = one(
        keystone,
        "/domains",
        "domains",
        query={"name": values["OS_USER_DOMAIN_NAME"]},
    )
    member = one(
        keystone,
        "/roles",
        "roles",
        query={"name": "member"},
    )
    if domain is None or member is None:
        raise RuntimeError("Default domain or member role is absent")
    for name in PROJECT_NAMES.values():
        if one(
            keystone,
            "/projects",
            "projects",
            query={"name": name, "domain_id": domain["id"]},
        ):
            raise RuntimeError(f"refusing to replace existing project {name}")
    for name in USER_NAMES.values():
        if one(
            keystone,
            "/users",
            "users",
            query={"name": name, "domain_id": domain["id"]},
        ):
            raise RuntimeError(f"refusing to replace existing user {name}")

    expires_at = (datetime.now(UTC) + timedelta(days=7)).strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z"
    )
    state: dict[str, Any] = {
        "expires_at": expires_at,
        "project_a": {},
        "project_b": {},
    }
    write_state(state)
    try:
        for fixture_name in ("project_a", "project_b"):
            project_document, _headers = keystone.request(
                "POST",
                "/projects",
                document={
                    "project": {
                        "name": PROJECT_NAMES[fixture_name],
                        "domain_id": domain["id"],
                        "enabled": True,
                    }
                },
                expected={201},
            )
            assert project_document is not None
            project = project_document["project"]
            password = secrets.token_urlsafe(36)
            user_document, _headers = keystone.request(
                "POST",
                "/users",
                document={
                    "user": {
                        "name": USER_NAMES[fixture_name],
                        "domain_id": domain["id"],
                        "default_project_id": project["id"],
                        "enabled": True,
                        "password": password,
                    }
                },
                expected={201},
            )
            assert user_document is not None
            user = user_document["user"]
            keystone.request(
                "PUT",
                (
                    f"/projects/{project['id']}/users/{user['id']}"
                    f"/roles/{member['id']}"
                ),
                expected={204},
            )
            state[fixture_name].update(
                {
                    "project_id": project["id"],
                    "project_name": project["name"],
                    "user_domain_id": domain["id"],
                    "user_domain_name": values["OS_USER_DOMAIN_NAME"],
                    "user_id": user["id"],
                    "username": user["name"],
                    "user_password": password,
                }
            )
            write_state(state)
            user_token = token_for(
                Keystone(values["OS_AUTH_URL"]),
                password_document(
                    values,
                    username=user["name"],
                    password=password,
                    project_id=project["id"],
                    domain_id=domain["id"],
                ),
            )
            user_keystone = Keystone(values["OS_AUTH_URL"], user_token)
            credential_document, _headers = user_keystone.request(
                "POST",
                f"/users/{user['id']}/application_credentials",
                document={
                    "application_credential": {
                        "name": CREDENTIAL_NAMES[fixture_name],
                        "expires_at": expires_at,
                        "roles": [{"id": member["id"]}],
                        "unrestricted": False,
                    }
                },
                expected={201},
            )
            assert credential_document is not None
            credential = credential_document["application_credential"]
            if not credential.get("id") or not credential.get("secret"):
                raise RuntimeError(
                    "Keystone omitted application credential material"
                )
            state[fixture_name].update(
                {
                    "application_credential_id": credential["id"],
                    "application_credential_name": credential["name"],
                    "application_credential_secret": credential["secret"],
                }
            )
            write_state(state)
            application_credential_token(
                Keystone(values["OS_AUTH_URL"]),
                credential["id"],
                credential["secret"],
            )
    except Exception:
        delete_owned(keystone, state)
        STATE_PATH.unlink(missing_ok=True)
        raise
    print(f"preview identities prepared expires_at={expires_at}")


def status() -> None:
    if not STATE_PATH.is_file() or STATE_PATH.stat().st_mode & 0o077:
        raise RuntimeError("preview identity state is absent or not owner-only")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    keystone, values = admin()
    for fixture_name in ("project_a", "project_b"):
        fixture = state[fixture_name]
        project, _headers = keystone.request(
            "GET",
            f"/projects/{fixture['project_id']}",
            expected={200},
        )
        user, _headers = keystone.request(
            "GET",
            f"/users/{fixture['user_id']}",
            expected={200},
        )
        assert project is not None and user is not None
        token = application_credential_token(
            Keystone(values["OS_AUTH_URL"]),
            fixture["application_credential_id"],
            fixture["application_credential_secret"],
        )
        if not token:
            raise RuntimeError("application credential validation failed")
        print(
            f"{fixture_name} project={project['project']['name']} "
            f"user={user['user']['name']} status=active"
        )
    print(f"expires_at={state['expires_at']}")


def cleanup() -> None:
    if not STATE_PATH.is_file() or STATE_PATH.stat().st_mode & 0o077:
        raise RuntimeError("preview identity state is absent or not owner-only")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    keystone, values = admin()
    delete_owned(keystone, state)
    domain = one(
        keystone,
        "/domains",
        "domains",
        query={"name": values["OS_USER_DOMAIN_NAME"]},
    )
    assert domain is not None
    for name in PROJECT_NAMES.values():
        if one(
            keystone,
            "/projects",
            "projects",
            query={"name": name, "domain_id": domain["id"]},
        ):
            raise RuntimeError(f"project cleanup failed for {name}")
    for name in USER_NAMES.values():
        if one(
            keystone,
            "/users",
            "users",
            query={"name": name, "domain_id": domain["id"]},
        ):
            raise RuntimeError(f"user cleanup failed for {name}")
    STATE_PATH.unlink()
    print("preview identities removed")


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("preview identity helper requires root")
    import sys

    if len(sys.argv) != 2 or sys.argv[1] not in {
        "prepare",
        "status",
        "cleanup",
    }:
        raise SystemExit("usage: guest-identities.py prepare|status|cleanup")
    globals()[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
