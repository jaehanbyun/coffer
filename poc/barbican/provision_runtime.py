#!/usr/bin/env python3
"""Create the disposable RGW Barbican principal and symmetric key."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from barbicanclient import client as barbican_client
from keystoneauth1 import session
from keystoneauth1.identity import v3
from openstack import connection


PROJECT_NAME = "coffer-rgw-kms-poc"
USER_NAME = "coffer-rgw-kms-poc"
SECRET_NAME = "coffer-rgw-sse-kms-poc"
DOMAIN_NAME = "Default"


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def password_auth(*, username: str, password: str, project_name: str) -> v3.Password:
    return v3.Password(
        auth_url=required("OS_AUTH_URL"),
        username=username,
        password=password,
        project_name=project_name,
        user_domain_name=DOMAIN_NAME,
        project_domain_name=DOMAIN_NAME,
    )


def main() -> int:
    verify_path = Path(required("OS_CACERT"))
    if not verify_path.is_file():
        raise RuntimeError("OS_CACERT is not a readable file")

    password = required("COFFER_KMS_USER_PASSWORD")
    if len(password) < 32 or not password.isalnum():
        raise RuntimeError("generated KMS user password does not meet the lab bound")
    resume_key_id = os.environ.get("COFFER_KMS_KEY_ID", "")
    resume_project_id = os.environ.get("COFFER_KMS_PROJECT_ID", "")
    resume_user_id = os.environ.get("COFFER_KMS_USER_ID", "")
    resume = bool(resume_key_id)
    if resume != bool(resume_project_id and resume_user_id):
        raise RuntimeError("retained KMS identity state is incomplete")

    admin_auth = password_auth(
        username=required("OS_USERNAME"),
        password=required("OS_PASSWORD"),
        project_name=required("OS_PROJECT_NAME"),
    )
    admin_session = session.Session(auth=admin_auth, verify=str(verify_path))
    cloud = connection.Connection(session=admin_session)

    domain = cloud.identity.find_domain(DOMAIN_NAME, ignore_missing=False)
    project = cloud.identity.find_project(
        PROJECT_NAME, domain_id=domain.id, ignore_missing=True
    )
    user = cloud.identity.find_user(
        USER_NAME, domain_id=domain.id, ignore_missing=True
    )
    if not resume and (project is not None or user is not None):
        raise RuntimeError(
            "refusing to adopt partial KMS identity state without the owner-only runtime file"
        )
    if resume:
        if project is None or project.id != resume_project_id:
            raise RuntimeError("retained KMS project identity does not match Keystone")
        if user is None or user.id != resume_user_id:
            raise RuntimeError("retained KMS user identity does not match Keystone")
    if project is None:
        project = cloud.identity.create_project(
            name=PROJECT_NAME, domain_id=domain.id, enabled=True
        )
    if user is None:
        user = cloud.identity.create_user(
            name=USER_NAME,
            domain_id=domain.id,
            default_project_id=project.id,
            password=password,
            enabled=True,
        )

    creator = cloud.identity.find_role("creator", ignore_missing=False)
    if not cloud.identity.validate_user_has_project_role(project, user, creator):
        cloud.identity.assign_project_role_to_user(project, user, creator)
    if not cloud.identity.validate_user_has_project_role(project, user, creator):
        raise RuntimeError("creator role assignment did not become visible")

    identity_root = required("OS_AUTH_URL").rstrip("/")
    if not identity_root.endswith("/v3"):
        identity_root = f"{identity_root}/v3"
    assignment_url = f"{identity_root}/role_assignments"
    assignment_response = admin_session.get(
        assignment_url,
        params={"user.id": user.id, "effective": ""},
    )
    assignment_response.raise_for_status()
    assignments = assignment_response.json().get("role_assignments", [])
    exact_creator_assignment = (
        len(assignments) == 1
        and assignments[0].get("role", {}).get("id") == creator.id
        and assignments[0].get("scope", {}).get("project", {}).get("id")
        == project.id
    )
    if not exact_creator_assignment:
        raise RuntimeError("KMS caller effective role assignments exceed creator scope")

    caller_auth = password_auth(
        username=USER_NAME,
        password=password,
        project_name=PROJECT_NAME,
    )
    caller_session = session.Session(auth=caller_auth, verify=str(verify_path))
    barbican = barbican_client.Client(session=caller_session)

    if resume:
        secret = barbican.secrets.get(resume_key_id)
        key_id = resume_key_id
    else:
        secret = barbican.secrets.create(
            name=SECRET_NAME,
            payload=os.urandom(32),
            algorithm="aes",
            bit_length=256,
            mode="cbc",
        )
        secret_ref = secret.store()
        key_id = secret_ref.rstrip("/").rsplit("/", 1)[-1]

    stored = barbican.secrets.get(key_id)
    payload = stored.payload
    if not isinstance(payload, bytes) or len(payload) != 32:
        raise RuntimeError("Barbican did not return the expected 256-bit payload")
    if stored.algorithm != "aes" or stored.bit_length != 256:
        raise RuntimeError("Barbican secret metadata does not match the requested key")

    json.dump(
        {
            "project_id": project.id,
            "project_name": PROJECT_NAME,
            "user_id": user.id,
            "user_name": USER_NAME,
            "role": "creator",
            "effective_role_assignments": 1,
            "key_id": key_id,
            "key_bytes": len(payload),
            "algorithm": stored.algorithm,
            "bit_length": stored.bit_length,
            "mode": stored.mode,
        },
        sys.stdout,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
