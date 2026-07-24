#!/usr/bin/env python3

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any

from openstack.config import OpenStackConfig
from openstack.connection import Connection


STATE_PATH = Path("/root/coffer-kolla-aio-stage4-identities.json")
CLOUDS_PATH = "/etc/kolla/clouds.yaml"
ADMIN_CLOUD = "kolla-admin-internal"
AUTH_URL = "https://192.168.122.220:5000/v3"
CA_PATH = "/etc/kolla/certificates-stage4/ca/root.crt"
PROJECT_NAMES = {
    "project_a": "coffer-stage4-project-a",
    "project_b": "coffer-stage4-project-b",
}
USER_NAMES = {
    "project_a": "coffer-stage4-user-a",
    "project_b": "coffer-stage4-user-b",
}
APPLICATION_CREDENTIAL_NAMES = {
    "project_a": "coffer-stage4-credential-a",
    "project_b": "coffer-stage4-credential-b",
}


def admin_connection() -> Connection:
    config = OpenStackConfig(config_files=[CLOUDS_PATH]).get_one_cloud(ADMIN_CLOUD)
    return Connection(config=config)


def write_state(state: dict[str, Any]) -> None:
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".coffer-kolla-aio-stage4-identities.",
        dir=STATE_PATH.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, STATE_PATH)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def assert_names_absent(connection: Connection, domain_id: str) -> None:
    for name in PROJECT_NAMES.values():
        if list(connection.identity.projects(name=name, domain_id=domain_id)):
            raise RuntimeError(f"refusing to replace existing project {name}")
    for name in USER_NAMES.values():
        if list(connection.identity.users(name=name, domain_id=domain_id)):
            raise RuntimeError(f"refusing to replace existing user {name}")


def user_connection(
    *,
    username: str,
    password: str,
    user_domain_id: str,
    project_id: str,
) -> Connection:
    return Connection(
        auth_type="v3password",
        auth_url=AUTH_URL,
        username=username,
        password=password,
        user_domain_id=user_domain_id,
        project_id=project_id,
        project_domain_id=user_domain_id,
        verify=CA_PATH,
    )


def application_credential_connection(identifier: str, secret: str) -> Connection:
    return Connection(
        auth_type="v3applicationcredential",
        auth_url=AUTH_URL,
        application_credential_id=identifier,
        application_credential_secret=secret,
        verify=CA_PATH,
    )


def cleanup(connection: Connection, state: dict[str, Any]) -> None:
    for fixture_name in ("project_a", "project_b"):
        fixture = state.get(fixture_name, {})
        user_id = fixture.get("user_id")
        credential_id = fixture.get("application_credential_id")
        if user_id and credential_id:
            connection.identity.delete_application_credential(
                user_id,
                credential_id,
                ignore_missing=True,
            )
    for fixture_name in ("project_a", "project_b"):
        fixture = state.get(fixture_name, {})
        user_id = fixture.get("user_id")
        if user_id:
            connection.identity.delete_user(user_id, ignore_missing=True)
    for fixture_name in ("project_a", "project_b"):
        fixture = state.get(fixture_name, {})
        project_id = fixture.get("project_id")
        if project_id:
            connection.identity.delete_project(project_id, ignore_missing=True)


def prepare() -> None:
    if STATE_PATH.exists():
        raise RuntimeError("Stage 4 identity state already exists")
    connection = admin_connection()
    domain = connection.identity.find_domain("default", ignore_missing=False)
    member = connection.identity.find_role("member", ignore_missing=False)
    assert_names_absent(connection, domain.id)

    expires_at = (datetime.now(UTC) + timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    state: dict[str, Any] = {
        "expires_at": expires_at,
        "project_a": {},
        "project_b": {},
    }
    write_state(state)
    try:
        for fixture_name in ("project_a", "project_b"):
            project = connection.identity.create_project(
                name=PROJECT_NAMES[fixture_name],
                domain_id=domain.id,
                enabled=True,
            )
            password = secrets.token_urlsafe(36)
            user = connection.identity.create_user(
                name=USER_NAMES[fixture_name],
                domain_id=domain.id,
                default_project_id=project.id,
                enabled=True,
                password=password,
            )
            connection.identity.assign_project_role_to_user(
                project,
                user,
                member,
            )
            state[fixture_name].update(
                {
                    "project_id": project.id,
                    "project_name": project.name,
                    "user_domain_id": domain.id,
                    "user_id": user.id,
                    "username": user.name,
                    "user_password": password,
                }
            )
            write_state(state)

            scoped = user_connection(
                username=user.name,
                password=password,
                user_domain_id=domain.id,
                project_id=project.id,
            )
            scoped.authorize()
            credential = scoped.identity.create_application_credential(
                user,
                APPLICATION_CREDENTIAL_NAMES[fixture_name],
                expires_at=expires_at,
                roles=[{"id": member.id}],
                unrestricted=False,
            )
            if not credential.id or not credential.secret:
                raise RuntimeError("Keystone omitted application credential material")
            state[fixture_name].update(
                {
                    "application_credential_id": credential.id,
                    "application_credential_name": credential.name,
                    "application_credential_secret": credential.secret,
                }
            )
            write_state(state)
            application_credential_connection(
                credential.id,
                credential.secret,
            ).authorize()
    except Exception:
        cleanup(connection, state)
        STATE_PATH.unlink(missing_ok=True)
        raise

    os.chmod(STATE_PATH, 0o600)
    print(f"Stage 4 finite identities prepared expires_at={expires_at}")


def remove() -> None:
    if not STATE_PATH.is_file():
        raise RuntimeError("Stage 4 identity state is absent")
    if STATE_PATH.stat().st_mode & 0o077:
        raise RuntimeError("Stage 4 identity state is not owner-only")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    connection = admin_connection()
    cleanup(connection, state)
    domain = connection.identity.find_domain("default", ignore_missing=False)
    assert_names_absent(connection, domain.id)
    STATE_PATH.unlink()
    print("Stage 4 finite identities removed")


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("Stage 4 identity helper requires root")
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "cleanup"}:
        raise SystemExit("usage: guest-stage4-identities.py prepare|cleanup")
    if sys.argv[1] == "prepare":
        prepare()
    else:
        remove()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
