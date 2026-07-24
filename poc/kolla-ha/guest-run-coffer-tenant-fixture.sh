#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {preflight|prepare|renew-preflight|renew|status|cleanup}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    preflight|prepare|renew-preflight|renew|status|cleanup)
        ;;
    *)
        echo "refusing an unknown Coffer tenant fixture action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
fixture_root="${state_root}/tenant-fixture"
identity_state="${fixture_root}/identities.json"
prepared_marker="${fixture_root}/prepared.complete"
renewed_marker="${fixture_root}/renewed.complete"
marker_value="coffer-stage5-tenant-fixture-v1"
renewed_marker_value="coffer-stage5-tenant-credential-renewal-v1"
passwords="/etc/kolla/passwords.yml"
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"
companion_marker="${state_root}/companion-lifecycle/deploy.complete"
companion_marker_value="coffer-stage5-companion-lifecycle-v1"
toolbox_state="/run/coffer-stage5-tenant-identities.json"
admin_password="/run/coffer-stage5-tenant-admin-password"
client_root="/run/coffer-stage5-tenant-client"
registry_name="registry.coffer.stage5"
hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
)

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(stat -c '%U:%G:%a' "${passwords}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${deployment_key}")" = ubuntu:ubuntu:600
test "$(stat -c '%U:%G:%a' "${known_hosts}")" = ubuntu:ubuntu:644
test "$(stat -c '%U:%G:%a' "${companion_marker}")" = root:root:600
test "$(cat "${companion_marker}")" = "${companion_marker_value}"
test "$(docker inspect -f '{{.State.Running}}' kolla_toolbox)" = true
test "$(docker inspect -f '{{.State.Running}}' coffer_api)" = true
test ! -e "${toolbox_state}"
test ! -e "${admin_password}"

cleanup_transfers() {
    rm -f -- "${toolbox_state}" "${admin_password}"
}
trap cleanup_transfers EXIT

materialize_admin_password() {
    install -o root -g root -m 0600 /dev/null "${admin_password}"
    /home/ubuntu/coffer-stage5/venv/bin/python3 - \
        "${passwords}" "${admin_password}" <<'PY'
from pathlib import Path
import os
import sys

import yaml


passwords_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
document = yaml.safe_load(passwords_path.read_text(encoding="utf-8"))
value = document.get("keystone_admin_password")
if not isinstance(value, str) or len(value) < 8:
    raise SystemExit("Keystone admin password is unavailable")
descriptor = os.open(output_path, os.O_WRONLY | os.O_TRUNC)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    stream.write(value)
    stream.write("\n")
os.chmod(output_path, 0o600)
PY
    test "$(stat -c '%U:%G:%a' "${admin_password}")" = root:root:600
}

run_identity_action() {
    local identity_action="$1"
    local rc

    case "${identity_action}" in
        preflight|prepare|renew-status|renew-stage|renew-finalize|status|cleanup)
            ;;
        *)
            echo "refusing an unknown identity action" >&2
            return 64
            ;;
    esac

    test ! -e "${toolbox_state}"
    materialize_admin_password
    case "${identity_action}" in
        renew-status|renew-stage|renew-finalize|status|cleanup)
            test "$(stat -c '%U:%G:%a' "${identity_state}")" = root:root:600
            install -o root -g root -m 0600 \
                "${identity_state}" "${toolbox_state}"
            ;;
        preflight|prepare)
            test ! -e "${identity_state}"
            ;;
    esac

    set +e
    docker exec --user root -i kolla_toolbox \
        python3 - "${identity_action}" \
        "${toolbox_state}" "${admin_password}" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any

import yaml
from openstack.connection import Connection


ACTION = sys.argv[1]
STATE_PATH = Path(sys.argv[2])
ADMIN_PASSWORD_PATH = Path(sys.argv[3])
CLOUDS_PATH = Path("/var/lib/kolla/config_files/clouds.yaml")
CA_PATH = "/etc/ssl/certs/ca-certificates.crt"
ADMIN_CLOUD = "kolla-admin-internal"
AUTH_URL = "https://192.168.252.10:5000/v3"
PROJECT_NAMES = {
    "project_a": "coffer-stage5-project-a",
    "project_b": "coffer-stage5-project-b",
}
USER_NAMES = {
    "project_a": "coffer-stage5-user-a",
    "project_b": "coffer-stage5-user-b",
}
APPLICATION_CREDENTIAL_NAMES = {
    "project_a": "coffer-stage5-credential-a",
    "project_b": "coffer-stage5-credential-b",
}
RENEWED_APPLICATION_CREDENTIAL_NAMES = {
    "project_a": "coffer-stage5-credential-a-renewal-1",
    "project_b": "coffer-stage5-credential-b-renewal-1",
}


def cloud_auth() -> dict[str, str]:
    document = yaml.safe_load(CLOUDS_PATH.read_text(encoding="utf-8"))
    cloud = document["clouds"][ADMIN_CLOUD]
    auth = cloud["auth"]
    required = {
        "auth_url",
        "username",
        "project_name",
        "user_domain_name",
        "project_domain_name",
    }
    if set(auth) != required:
        raise RuntimeError("Kolla admin cloud auth contract changed")
    return auth


def admin_connection() -> Connection:
    auth = cloud_auth()
    password = ADMIN_PASSWORD_PATH.read_text(encoding="utf-8").strip()
    if len(password) < 8:
        raise RuntimeError("Keystone admin password is unavailable")
    return Connection(
        auth_type="v3password",
        auth_url=AUTH_URL,
        username=auth["username"],
        password=password,
        project_name=auth["project_name"],
        user_domain_name=auth["user_domain_name"],
        project_domain_name=auth["project_domain_name"],
        interface="internal",
        region_name="RegionOne",
        verify=CA_PATH,
    )


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
        interface="internal",
        region_name="RegionOne",
        verify=CA_PATH,
    )


def application_credential_connection(identifier: str, secret: str) -> Connection:
    return Connection(
        auth_type="v3applicationcredential",
        auth_url=AUTH_URL,
        application_credential_id=identifier,
        application_credential_secret=secret,
        interface="internal",
        region_name="RegionOne",
        verify=CA_PATH,
    )


def write_state(state: dict[str, Any]) -> None:
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".coffer-stage5-tenant-identities.",
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
            raise RuntimeError(f"refusing existing tenant project {name}")
    for name in USER_NAMES.values():
        if list(connection.identity.users(name=name, domain_id=domain_id)):
            raise RuntimeError(f"refusing existing tenant user {name}")


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


def load_state(*, allow_pending_retire: bool = False) -> dict[str, Any]:
    if not STATE_PATH.is_file() or STATE_PATH.stat().st_mode & 0o077:
        raise RuntimeError("tenant identity state is absent or not owner-only")
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    expected = {"expires_at", "project_a", "project_b"}
    if allow_pending_retire:
        expected.add("pending_retire")
    if set(state) != expected:
        raise RuntimeError("tenant identity state shape changed")
    return state


def validate_state(
    connection: Connection,
    state: dict[str, Any],
    *,
    allow_pending_retire: bool = False,
    allow_missing_retired: bool = False,
) -> None:
    expires_at = datetime.strptime(
        state["expires_at"], "%Y-%m-%dT%H:%M:%S"
    ).replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise RuntimeError("tenant application credentials expired")
    domain = connection.identity.find_domain("default", ignore_missing=False)
    member = connection.identity.find_role("member", ignore_missing=False)
    credential_ids_by_fixture: dict[str, set[str]] = {}
    for fixture_name in ("project_a", "project_b"):
        fixture = state[fixture_name]
        project = connection.identity.get_project(fixture["project_id"])
        user = connection.identity.get_user(fixture["user_id"])
        if (
            project.name != PROJECT_NAMES[fixture_name]
            or project.domain_id != domain.id
            or user.name != USER_NAMES[fixture_name]
            or user.domain_id != domain.id
        ):
            raise RuntimeError("tenant identity metadata changed")
        assignments = list(
            connection.identity.role_assignments(
                user_id=user.id,
                project_id=project.id,
                role_id=member.id,
            )
        )
        if len(assignments) != 1:
            raise RuntimeError("tenant member assignment changed")
        named_credentials = list(
            connection.identity.application_credentials(
                user=user.id,
                name=fixture["application_credential_name"],
            )
        )
        if (
            len(named_credentials) != 1
            or named_credentials[0].id != fixture["application_credential_id"]
        ):
            raise RuntimeError("tenant application credential changed")
        credentials = list(
            connection.identity.application_credentials(user=user.id)
        )
        expected_credential_counts = (
            {1, 2}
            if allow_pending_retire and allow_missing_retired
            else {2}
            if allow_pending_retire
            else {1}
        )
        if len(credentials) not in expected_credential_counts:
            raise RuntimeError("tenant application credential count changed")
        credential_ids_by_fixture[fixture_name] = {
            credential.id for credential in credentials
        }
        application_credential_connection(
            fixture["application_credential_id"],
            fixture["application_credential_secret"],
        ).authorize()
    if allow_pending_retire:
        pending = state["pending_retire"]
        if set(pending) != {"project_a", "project_b"}:
            raise RuntimeError("tenant pending credential shape changed")
        for fixture_name in ("project_a", "project_b"):
            retired = pending[fixture_name]
            if set(retired) != {"application_credential_id"}:
                raise RuntimeError("tenant retired credential shape changed")
            if retired["application_credential_id"] == state[fixture_name][
                "application_credential_id"
            ]:
                raise RuntimeError("tenant credential renewal did not rotate")
            if (
                not allow_missing_retired
                and retired["application_credential_id"]
                not in credential_ids_by_fixture[fixture_name]
            ):
                raise RuntimeError("tenant retired credential disappeared")


def preflight() -> None:
    if STATE_PATH.exists():
        raise RuntimeError("tenant identity transfer state already exists")
    connection = admin_connection()
    domain = connection.identity.find_domain("default", ignore_missing=False)
    connection.identity.find_role("member", ignore_missing=False)
    assert_names_absent(connection, domain.id)
    print(
        "coffer_tenant_identity state=clean projects=0 users=0 "
        "credentials=0 mutation=none"
    )


def prepare() -> None:
    if STATE_PATH.exists():
        raise RuntimeError("tenant identity transfer state already exists")
    connection = admin_connection()
    domain = connection.identity.find_domain("default", ignore_missing=False)
    member = connection.identity.find_role("member", ignore_missing=False)
    assert_names_absent(connection, domain.id)
    expires_at = (datetime.now(UTC) + timedelta(hours=12)).strftime(
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
    validate_state(connection, state)
    print(
        f"coffer_tenant_identity state=prepared projects=2 users=2 "
        f"credentials=2 expires_at={expires_at}"
    )


def status() -> None:
    connection = admin_connection()
    state = load_state()
    validate_state(connection, state)
    print(
        f"coffer_tenant_identity state=prepared projects=2 users=2 "
        f"credentials=2 expires_at={state['expires_at']}"
    )


def renew_stage() -> None:
    connection = admin_connection()
    state = load_state()
    validate_state(connection, state)
    member = connection.identity.find_role("member", ignore_missing=False)
    expires_at = (datetime.now(UTC) + timedelta(hours=12)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    original_state = json.loads(json.dumps(state))
    created: list[tuple[str, str]] = []
    try:
        state["pending_retire"] = {}
        for fixture_name in ("project_a", "project_b"):
            fixture = state[fixture_name]
            user = connection.identity.get_user(fixture["user_id"])
            existing_credentials = list(
                connection.identity.application_credentials(user=user.id)
            )
            if (
                len(existing_credentials) != 1
                or existing_credentials[0].id
                != fixture["application_credential_id"]
            ):
                raise RuntimeError(
                    "refusing credential renewal from non-exact state"
                )
            state["pending_retire"][fixture_name] = {
                "application_credential_id": fixture[
                    "application_credential_id"
                ],
            }
            scoped = user_connection(
                username=fixture["username"],
                password=fixture["user_password"],
                user_domain_id=fixture["user_domain_id"],
                project_id=fixture["project_id"],
            )
            scoped.authorize()
            credential = scoped.identity.create_application_credential(
                user,
                RENEWED_APPLICATION_CREDENTIAL_NAMES[fixture_name],
                expires_at=expires_at,
                roles=[{"id": member.id}],
                unrestricted=False,
            )
            if not credential.id or not credential.secret:
                raise RuntimeError(
                    "Keystone omitted renewed application credential material"
                )
            created.append((user.id, credential.id))
            fixture.update(
                {
                    "application_credential_id": credential.id,
                    "application_credential_name": credential.name,
                    "application_credential_secret": credential.secret,
                }
            )
            application_credential_connection(
                credential.id,
                credential.secret,
            ).authorize()
        state["expires_at"] = expires_at
        validate_state(
            connection,
            state,
            allow_pending_retire=True,
        )
        write_state(state)
    except Exception:
        for user_id, credential_id in reversed(created):
            connection.identity.delete_application_credential(
                user_id,
                credential_id,
                ignore_missing=True,
            )
        write_state(original_state)
        raise
    print(
        f"coffer_tenant_identity state=renewal-staged projects=2 users=2 "
        f"credentials=4 expires_at={expires_at}"
    )


def renew_status() -> None:
    connection = admin_connection()
    state = load_state(allow_pending_retire=True)
    validate_state(
        connection,
        state,
        allow_pending_retire=True,
        allow_missing_retired=True,
    )
    print(
        f"coffer_tenant_identity state=renewal-staged projects=2 users=2 "
        f"expires_at={state['expires_at']} mutation=none"
    )


def renew_finalize() -> None:
    connection = admin_connection()
    state = load_state(allow_pending_retire=True)
    validate_state(
        connection,
        state,
        allow_pending_retire=True,
        allow_missing_retired=True,
    )
    pending = state["pending_retire"]
    for fixture_name in ("project_a", "project_b"):
        fixture = state[fixture_name]
        connection.identity.delete_application_credential(
            fixture["user_id"],
            pending[fixture_name]["application_credential_id"],
            ignore_missing=True,
        )
    del state["pending_retire"]
    validate_state(connection, state)
    write_state(state)
    print(
        f"coffer_tenant_identity state=renewed projects=2 users=2 "
        f"credentials=2 expires_at={state['expires_at']}"
    )


def remove() -> None:
    connection = admin_connection()
    state = load_state()
    cleanup(connection, state)
    domain = connection.identity.find_domain("default", ignore_missing=False)
    assert_names_absent(connection, domain.id)
    STATE_PATH.unlink()
    print(
        "coffer_tenant_identity state=removed projects=0 users=0 "
        "credentials=0"
    )


if ACTION == "preflight":
    preflight()
elif ACTION == "prepare":
    prepare()
elif ACTION == "renew-status":
    renew_status()
elif ACTION == "renew-stage":
    renew_stage()
elif ACTION == "renew-finalize":
    renew_finalize()
elif ACTION == "status":
    status()
elif ACTION == "cleanup":
    remove()
else:
    raise SystemExit("invalid embedded identity action")
PY
    rc="$?"
    set -e

    rm -f -- "${admin_password}"
    if test "${rc}" -ne 0; then
        rm -f -- "${toolbox_state}"
        return "${rc}"
    fi

    case "${identity_action}" in
        prepare)
            test "$(stat -c '%U:%G:%a' "${toolbox_state}")" = root:root:600
            install -o root -g root -m 0600 \
                "${toolbox_state}" "${identity_state}"
            ;;
        renew-status)
            test "$(stat -c '%U:%G:%a' "${toolbox_state}")" = root:root:600
            ;;
        renew-stage|renew-finalize)
            test "$(stat -c '%U:%G:%a' "${toolbox_state}")" = root:root:600
            install -o root -g root -m 0600 \
                "${toolbox_state}" "${identity_state}"
            ;;
        cleanup)
            test ! -e "${toolbox_state}"
            rm -f -- "${identity_state}"
            ;;
    esac
    rm -f -- "${toolbox_state}"
}

discover_external_owner() {
    local index
    local owner_count=0

    external_owner_address=""
    external_owner_hostname=""
    for index in "${!addresses[@]}"; do
        if sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${addresses[${index}]}" \
            "ip -4 -o address show dev ens5 |
                grep -Fq '192.168.254.10/32'"; then
            external_owner_address="${addresses[${index}]}"
            external_owner_hostname="${hostnames[${index}]}"
            owner_count="$((owner_count + 1))"
        fi
    done
    test "${owner_count}" -eq 1
}

verify_client_boundary() {
    local index
    local address
    local expected
    local owner_client_state

    discover_external_owner
    for index in "${!addresses[@]}"; do
        address="${addresses[${index}]}"
        expected="${hostnames[${index}]}"
        sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${address}" \
            sudo env LC_ALL=C LANG=C bash -s -- \
            "${expected}" "${client_root}" "${registry_name}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
client_root="$2"
registry_name="$3"

test "$(hostname)" = "${expected_hostname}"
test "$(systemctl is-active docker)" = active
test ! -e "${client_root}"
test ! -e "/etc/docker/certs.d/${registry_name}"
test -z "$(
    docker image ls \
        --filter "reference=${registry_name}/*" \
        --format '{{.Repository}}:{{.Tag}}'
)"
REMOTE
    done

    owner_client_state="$(
        sudo -u ubuntu ssh \
        "${ssh_options[@]}" "ubuntu@${external_owner_address}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${external_owner_hostname}" "${registry_name}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
registry_name="$2"

test "$(hostname)" = "${expected_hostname}"
for command_name in curl docker jq openssl getent sha256sum; do
    command -v "${command_name}" >/dev/null
done
docker info >/dev/null 2>&1
dns_state=override-required
if resolved="$(getent ahostsv4 "${registry_name}" 2>/dev/null)"; then
    awk '$1 != "192.168.254.10" {exit 1}' <<<"${resolved}"
    test -n "${resolved}"
    dns_state=valid
else
    test -z "$(
        grep -F -- "${registry_name}" /etc/hosts 2>/dev/null || true
    )"
fi
printf 'dns=%s\n' "${dns_state}"
REMOTE
    )"
    case "${owner_client_state}" in
        dns=valid|dns=override-required)
            ;;
        *)
            echo "external owner DNS boundary changed" >&2
            return 1
            ;;
    esac

    printf 'coffer_tenant_client state=clean external_owner=%s tools=ready %s residue=none\n' \
        "${external_owner_hostname}" "${owner_client_state}"
}

write_marker() {
    local temporary="${prepared_marker}.tmp.$$"

    printf '%s\n' "${marker_value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${prepared_marker}"
}

write_renewed_marker() {
    local temporary="${renewed_marker}.tmp.$$"

    printf '%s\n' "${renewed_marker_value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${renewed_marker}"
}

require_marker() {
    test "$(stat -c '%U:%G:%a' "${prepared_marker}")" = root:root:600
    test "$(cat "${prepared_marker}")" = "${marker_value}"
}

require_renewed_marker() {
    test "$(stat -c '%U:%G:%a' "${renewed_marker}")" = root:root:600
    test "$(cat "${renewed_marker}")" = "${renewed_marker_value}"
}

require_clean_boundary() {
    test ! -e "${fixture_root}"
    run_identity_action preflight
    verify_client_boundary
}

require_fixture_boundary() {
    test "$(stat -c '%U:%G:%a' "${fixture_root}")" = root:root:700
    require_marker
    verify_client_boundary
}

require_prepared_boundary() {
    require_fixture_boundary
    run_identity_action status
}

has_pending_renewal() {
    /home/ubuntu/coffer-stage5/venv/bin/python3 - \
        "${identity_state}" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
if not path.is_file() or path.stat().st_mode & 0o077:
    raise SystemExit(2)
state = json.loads(path.read_text(encoding="utf-8"))
base = {"expires_at", "project_a", "project_b"}
if set(state) == base | {"pending_retire"}:
    raise SystemExit(0)
if set(state) == base:
    raise SystemExit(1)
raise SystemExit(2)
PY
}

if test "${action}" = preflight; then
    require_clean_boundary
    printf 'coffer_tenant_fixture state=clean mutation=none\n'
    exit 0
fi

if test "${action}" = status; then
    require_prepared_boundary
    printf 'coffer_tenant_fixture state=prepared identities=2 credentials=2\n'
    exit 0
fi

if test "${action}" = renew-preflight; then
    require_fixture_boundary
    test ! -e "${renewed_marker}"
    if has_pending_renewal; then
        run_identity_action renew-status
    else
        test "$?" -eq 1
        run_identity_action status
    fi
    printf 'coffer_tenant_fixture state=prepared renewal=ready mutation=none\n'
    exit 0
fi

exec 9>/run/lock/coffer-stage5-tenant-fixture.lock
if ! flock -n 9; then
    echo "refusing concurrent Coffer tenant fixture execution" >&2
    exit 75
fi

case "${action}" in
    prepare)
        if test -e "${prepared_marker}"; then
            require_prepared_boundary
            printf 'coffer_tenant_fixture phase=prepare result=passed idempotent=yes\n'
            exit 0
        fi
        require_clean_boundary
        install -d -o root -g root -m 0700 "${fixture_root}"
        rollback_prepare() {
            local rc="$?"

            trap - EXIT
            if test "${rc}" -ne 0; then
                if test -e "${identity_state}"; then
                    run_identity_action cleanup >/dev/null 2>&1 || true
                fi
                rm -f -- "${prepared_marker}"
                rmdir -- "${fixture_root}" 2>/dev/null || true
            fi
            cleanup_transfers
            exit "${rc}"
        }
        trap rollback_prepare EXIT
        run_identity_action prepare
        write_marker
        require_prepared_boundary
        trap cleanup_transfers EXIT
        ;;
    renew)
        if test -e "${renewed_marker}"; then
            require_prepared_boundary
            require_renewed_marker
            printf 'coffer_tenant_fixture phase=renew result=passed idempotent=yes\n'
            exit 0
        fi
        require_fixture_boundary
        if has_pending_renewal; then
            printf 'coffer_tenant_fixture phase=renew state=resuming-finalize\n'
        else
            test "$?" -eq 1
            run_identity_action status
            run_identity_action renew-stage
        fi
        run_identity_action renew-finalize
        write_renewed_marker
        require_prepared_boundary
        require_renewed_marker
        ;;
    cleanup)
        require_prepared_boundary
        run_identity_action cleanup
        rm -f -- "${renewed_marker}"
        rm -f -- "${prepared_marker}"
        rmdir -- "${fixture_root}"
        require_clean_boundary
        ;;
esac

printf 'coffer_tenant_fixture phase=%s result=passed marker=%s\n' \
    "${action}" "$(
        if test "${action}" = prepare; then
            printf complete
        else
            printf absent
        fi
    )"
