#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {status|bootstrap|prechecks|pull|deploy|reconfigure}" >&2
    exit 64
fi

action="$1"
expected_hostname="coffer-kolla-ha-stage5-controller-1"
commit="cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc"
state_root="/home/ubuntu/coffer-stage5"
source_root="${state_root}/kolla-ansible"
venv="${state_root}/venv"
lifecycle_root="${state_root}/lifecycle"
log_root="${state_root}/logs"
inventory="/etc/kolla/multinode"
config_root="/etc/kolla"
passwords="${config_root}/passwords.yml"
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"
production_profile_marker="${state_root}/production-profile.prepared"
management_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)

case "${action}" in
    status|bootstrap|prechecks|pull|deploy|reconfigure)
        ;;
    *)
        echo "refusing an unknown Kolla lifecycle action" >&2
        exit 64
        ;;
esac

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(cat "${state_root}/OWNER")" = "${commit}"
test "$(cat "${state_root}/INSTALL_COMPLETE")" = "${commit}"
test "$(git -C "${source_root}" rev-parse HEAD)" = "${commit}"
test -x "${venv}/bin/kolla-ansible"
test -x "${venv}/bin/ansible-inventory"
test "$(stat -c '%U:%G:%a' "${deployment_key}")" = ubuntu:ubuntu:600
test -f "${known_hosts}"
test "$(stat -c '%U:%G:%a' "${inventory}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${config_root}/globals.yml")" = root:root:644
test "$(stat -c '%U:%G:%a' "${passwords}")" = root:root:600
env \
    ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
    "${venv}/bin/ansible-inventory" \
    -i "${inventory}" --graph >/dev/null

ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
)

field_value() {
    local snapshot="$1"
    local name="$2"
    local field

    for field in ${snapshot}; do
        if [[ "${field}" == "${name}="* ]]; then
            printf '%s\n' "${field#*=}"
            return 0
        fi
    done
    return 1
}

controller_snapshot() {
    local index="$1"
    local address="${management_addresses[${index}]}"
    local expected="${hostnames[${index}]}"
    local name
    local snapshot
    local value

    if ! snapshot="$(
        sudo -u ubuntu ssh "${ssh_options[@]}" \
            "ubuntu@${address}" \
            sudo env LC_ALL=C LANG=C bash -s -- \
            "${expected}" "$((index + 1))" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
index="$2"
begin_marker="# BEGIN COFFER STAGE5 KOLLA"
end_marker="# END COFFER STAGE5 KOLLA"

test "$(hostname)" = "${expected_hostname}"
test "$(grep -Fxc "${begin_marker}" /home/ubuntu/.ssh/authorized_keys)" -eq 1
test "$(grep -Fxc "${end_marker}" /home/ubuntu/.ssh/authorized_keys)" -eq 1

private_key=0
owner_state=0
config_state=0
docker_binary=0
docker_active=0
containers=0
nonrunning=0
unhealthy=0
images=0
coffer_containers=0
coffer_images=0
coffer_listeners=0
coffer_configs=0
internal_vip=0
external_vip=0

test -e /home/ubuntu/.ssh/coffer-stage5-kolla && private_key=1
test -e /home/ubuntu/coffer-stage5/OWNER && owner_state=1
test -e /etc/kolla/globals.yml && config_state=1
command -v docker >/dev/null 2>&1 && docker_binary=1
systemctl is-active --quiet docker 2>/dev/null && docker_active=1
if test "${docker_active}" -eq 1; then
    containers="$(docker ps -a --format '{{.Names}}' | wc -l | tr -d ' ')"
    nonrunning="$(
        docker ps -a --format '{{.State}}' |
            awk '$1 != "running" {count += 1} END {print count + 0}'
    )"
    unhealthy="$(
        docker ps -a --format '{{.Status}}' |
            awk '/\(unhealthy\)/ {count += 1} END {print count + 0}'
    )"
    images="$(
        docker image ls --quiet |
            sort -u |
            awk 'NF {count += 1} END {print count + 0}'
    )"
    coffer_containers="$(
        docker ps -a --format '{{.Names}}' |
            grep -Ec \
                '^(coffer_api|coffer_edge|coffer_registry|coffer_reconcile|bootstrap_coffer)$' ||
            true
    )"
    for image in \
        localhost/coffer:stage5 \
        localhost/coffer-registry:stage5; do
        if docker image inspect "${image}" >/dev/null 2>&1; then
            coffer_images="$((coffer_images + 1))"
        fi
    done
fi
coffer_listeners="$(
    ss -H -lnt |
        awk '$4 ~ /:(8787|8788|8789)$/ {count += 1}
            END {print count + 0}'
)"
for path in \
    /etc/kolla/coffer-api \
    /etc/kolla/coffer-edge \
    /etc/kolla/coffer-registry \
    /etc/kolla/coffer-reconcile \
    /etc/kolla/coffer-bootstrap; do
    test -e "${path}" && coffer_configs="$((coffer_configs + 1))"
done
internal_vip="$(
    ip -4 -o addr show |
        awk 'index($4, "192.168.252.10/") == 1 {count += 1}
            END {print count + 0}'
)"
external_vip="$(
    ip -4 -o addr show |
        awk 'index($4, "192.168.254.10/") == 1 {count += 1}
            END {print count + 0}'
)"

if test "${index}" -eq 1; then
    test "${private_key}" -eq 1
    test "${owner_state}" -eq 1
    test "${config_state}" -eq 1
else
    test "${private_key}" -eq 0
fi

printf 'host=%s private_key=%s owner=%s config=%s docker=%s active=%s containers=%s nonrunning=%s unhealthy=%s images=%s coffer_containers=%s coffer_images=%s coffer_listeners=%s coffer_configs=%s internal_vip=%s external_vip=%s\n' \
    "${expected_hostname}" "${private_key}" "${owner_state}" "${config_state}" \
    "${docker_binary}" "${docker_active}" "${containers}" "${nonrunning}" \
    "${unhealthy}" "${images}" "${coffer_containers}" "${coffer_images}" \
    "${coffer_listeners}" "${coffer_configs}" "${internal_vip}" "${external_vip}"
REMOTE
    )"; then
        printf 'controller snapshot failed: %s\n' "${expected}" >&2
        return 23
    fi
    if test "$(wc -l <<<"${snapshot}" | tr -d ' ')" -ne 1 ||
        test "$(field_value "${snapshot}" host)" != "${expected}"; then
        printf 'controller snapshot shape mismatch: %s\n' "${expected}" >&2
        return 23
    fi
    for name in \
        private_key owner config docker active containers nonrunning \
        unhealthy images coffer_containers coffer_images coffer_listeners \
        coffer_configs internal_vip external_vip; do
        value="$(field_value "${snapshot}" "${name}")"
        if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
            printf 'controller snapshot field mismatch: %s %s\n' \
                "${expected}" "${name}" >&2
            return 23
        fi
    done
    printf '%s\n' "${snapshot}"
}

collect_status() {
    local index
    local images
    local snapshot

    status_docker=0
    status_active=0
    status_containers=0
    status_nonrunning=0
    status_unhealthy=0
    status_images_min=-1
    status_coffer_containers=0
    status_coffer_images=0
    status_coffer_listeners=0
    status_coffer_configs=0
    status_internal_vips=0
    status_external_vips=0
    status_internal_owner_index=-1
    status_external_owner_index=-1

    for index in "${!management_addresses[@]}"; do
        snapshot="$(controller_snapshot "${index}")"
        printf 'kolla_controller %s\n' "${snapshot}"
        status_docker="$((status_docker + $(field_value "${snapshot}" docker)))"
        status_active="$((status_active + $(field_value "${snapshot}" active)))"
        status_containers="$((status_containers +
            $(field_value "${snapshot}" containers)))"
        status_nonrunning="$((status_nonrunning +
            $(field_value "${snapshot}" nonrunning)))"
        status_unhealthy="$((status_unhealthy +
            $(field_value "${snapshot}" unhealthy)))"
        images="$(field_value "${snapshot}" images)"
        if test "${status_images_min}" -lt 0 ||
            test "${images}" -lt "${status_images_min}"; then
            status_images_min="${images}"
        fi
        status_coffer_containers="$((status_coffer_containers +
            $(field_value "${snapshot}" coffer_containers)))"
        status_coffer_images="$((status_coffer_images +
            $(field_value "${snapshot}" coffer_images)))"
        status_coffer_listeners="$((status_coffer_listeners +
            $(field_value "${snapshot}" coffer_listeners)))"
        status_coffer_configs="$((status_coffer_configs +
            $(field_value "${snapshot}" coffer_configs)))"
        status_internal_vips="$((status_internal_vips +
            $(field_value "${snapshot}" internal_vip)))"
        status_external_vips="$((status_external_vips +
            $(field_value "${snapshot}" external_vip)))"
        if test "$(field_value "${snapshot}" internal_vip)" -eq 1; then
            status_internal_owner_index="${index}"
        fi
        if test "$(field_value "${snapshot}" external_vip)" -eq 1; then
            status_external_owner_index="${index}"
        fi
    done
}

marker_path() {
    case "$1" in
        bootstrap|prechecks|pull|deploy|reconfigure)
            ;;
        *)
            echo "refusing a non-lifecycle marker" >&2
            return 64
            ;;
    esac
    printf '%s/%s.complete\n' "${lifecycle_root}" "$1"
}

require_marker() {
    local phase="$1"
    local marker

    marker="$(marker_path "${phase}")"
    test -f "${marker}"
    test "$(cat "${marker}")" = "${commit}"
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
}

write_marker() {
    local phase="$1"
    local marker
    local temporary

    marker="$(marker_path "${phase}")"
    temporary="${marker}.tmp.$$"
    cleanup_marker() {
        rm -f -- "${temporary}"
    }
    trap cleanup_marker EXIT
    printf '%s\n' "${commit}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${marker}"
    trap - EXIT
}

verify_log_secret_free() {
    local log="$1"

    "${venv}/bin/python3" - "${passwords}" "${log}" <<'PY'
from pathlib import Path
import base64
import re
import sys
import urllib.parse

import yaml

passwords_path = Path(sys.argv[1])
log_path = Path(sys.argv[2])
document = yaml.safe_load(passwords_path.read_text(encoding="utf-8"))
data = log_path.read_bytes()
for value in document.values():
    if not isinstance(value, str) or len(value) < 8:
        continue
    encoded = value.encode()
    candidates = {
        encoded,
        urllib.parse.quote(value, safe="").encode(),
        base64.b64encode(encoded),
    }
    if any(candidate in data for candidate in candidates):
        raise SystemExit("generated credential found in lifecycle log")
if re.search(
    rb"Authorization ['\"](?:Basic|Bearer) [A-Za-z0-9+/=._-]+",
    data,
):
    raise SystemExit("authorization credential found in lifecycle log")
PY
}

probe_external_keystone() {
    local ca_base64
    local owner_address
    local owner_hostname

    test "${status_external_vips}" -eq 1
    test "${status_external_owner_index}" -ge 0
    owner_address="${management_addresses[${status_external_owner_index}]}"
    owner_hostname="${hostnames[${status_external_owner_index}]}"
    ca_base64="$(
        base64 --wrap=0 "${config_root}/certificates-stage5/ca/root.crt"
    )"
    sudo -u ubuntu ssh "${ssh_options[@]}" \
        "ubuntu@${owner_address}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
        CA_CERT_BASE64="${ca_base64}" \
        python3 - <<'PY'
import base64
import os
import ssl
import urllib.error
import urllib.request

url = "https://192.168.254.10:5000/v3/"
context = ssl.create_default_context(
    cadata=base64.b64decode(os.environ["CA_CERT_BASE64"]).decode()
)
with urllib.request.urlopen(url, context=context, timeout=10) as response:
    if response.status != 200:
        raise SystemExit("trusted external Keystone probe failed")
try:
    urllib.request.urlopen(url, timeout=10)
except urllib.error.URLError:
    pass
else:
    raise SystemExit("untrusted external Keystone unexpectedly succeeded")
try:
    urllib.request.urlopen(
        "http://192.168.254.10:5000/v3/",
        timeout=10,
    )
except (ConnectionError, OSError, urllib.error.URLError):
    pass
else:
    raise SystemExit("plaintext external Keystone unexpectedly succeeded")
PY
    printf 'external_vip_probe owner=%s tls=200 untrusted=denied plaintext=denied\n' \
        "${owner_hostname}"
}

probe_production_profile() {
    local ca_base64
    local external_owner_address
    local external_owner_hostname
    local internal_owner_address
    local internal_owner_hostname

    test "${status_internal_vips}" -eq 1
    test "${status_external_vips}" -eq 1
    test "${status_internal_owner_index}" -ge 0
    test "${status_external_owner_index}" -ge 0
    internal_owner_address="${management_addresses[status_internal_owner_index]}"
    internal_owner_hostname="${hostnames[${status_internal_owner_index}]}"
    external_owner_address="${management_addresses[status_external_owner_index]}"
    external_owner_hostname="${hostnames[${status_external_owner_index}]}"
    ca_base64="$(
        base64 --wrap=0 "${config_root}/certificates-stage5/ca/root.crt"
    )"

    sudo -u ubuntu ssh "${ssh_options[@]}" \
        "ubuntu@${internal_owner_address}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
        CA_CERT_BASE64="${ca_base64}" \
        python3 - <<'PY'
import base64
import http.client
import os
import ssl
import urllib.error
import urllib.request


context = ssl.create_default_context(
    cadata=base64.b64decode(os.environ["CA_CERT_BASE64"]).decode()
)
url = "https://192.168.252.10:5000/v3/"
with urllib.request.urlopen(url, context=context, timeout=10) as response:
    if response.status != 200:
        raise SystemExit("trusted internal Keystone probe failed")


def require_failure(
    target: str,
    tls_context: ssl.SSLContext | None = None,
) -> None:
    try:
        urllib.request.urlopen(
            target,
            context=tls_context,
            timeout=10,
        )
    except (
        ConnectionError,
        OSError,
        http.client.HTTPException,
        ssl.SSLError,
        urllib.error.URLError,
    ):
        return
    raise SystemExit(f"unexpectedly reachable endpoint: {target}")


require_failure(url)
require_failure("http://192.168.252.10:5000/v3/")
PY

    sudo -u ubuntu ssh "${ssh_options[@]}" \
        "ubuntu@${external_owner_address}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
        CA_CERT_BASE64="${ca_base64}" \
        python3 - <<'PY'
import base64
import http.client
import os
import socket
import ssl
import urllib.error
import urllib.request


context = ssl.create_default_context(
    cadata=base64.b64decode(os.environ["CA_CERT_BASE64"]).decode()
)
url = "https://192.168.254.10:443/v3/"
with urllib.request.urlopen(url, context=context, timeout=10) as response:
    if response.status != 200:
        raise SystemExit("trusted external Keystone probe failed")


def require_failure(
    target: str,
    tls_context: ssl.SSLContext | None = None,
) -> None:
    try:
        urllib.request.urlopen(
            target,
            context=tls_context,
            timeout=10,
        )
    except (
        ConnectionError,
        OSError,
        http.client.HTTPException,
        ssl.SSLError,
        urllib.error.URLError,
    ):
        return
    raise SystemExit(f"unexpectedly reachable endpoint: {target}")


require_failure(url)
require_failure("http://192.168.254.10:443/v3/")
require_failure("https://192.168.254.10:5000/v3/", context)
with socket.create_connection(("192.168.254.10", 443), timeout=10) as raw:
    with context.wrap_socket(
        raw,
        server_hostname="registry.coffer.stage5",
    ) as secured:
        if secured.version() is None:
            raise SystemExit("Coffer DNS TLS handshake failed")
PY

    printf 'production_profile_probe internal_owner=%s internal_tls=200 external_owner=%s external_tls=200 external_port=443 old_external_port=denied dns_identity=valid plaintext=denied untrusted=denied\n' \
        "${internal_owner_hostname}" "${external_owner_hostname}"
}

probe_control_plane() {
    "${venv}/bin/python3" - "${passwords}" \
        "${config_root}/certificates-stage5/ca/root.crt" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request

import yaml


passwords = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
ca_path = sys.argv[2]
database_password = passwords["database_password"]
query = (
    "SHOW GLOBAL STATUS WHERE Variable_name IN "
    "('wsrep_cluster_size','wsrep_cluster_status',"
    "'wsrep_local_state_comment','wsrep_ready','wsrep_connected');"
)
database = subprocess.run(
    [
        "docker",
        "exec",
        "-e",
        f"MYSQL_PWD={database_password}",
        "mariadb",
        "mariadb",
        "-uroot",
        "-Nse",
        query,
    ],
    check=True,
    capture_output=True,
    text=True,
)
galera = {
    line.split("\t", 1)[0]: line.split("\t", 1)[1]
    for line in database.stdout.splitlines()
}
expected_galera = {
    "wsrep_cluster_size": "3",
    "wsrep_cluster_status": "Primary",
    "wsrep_connected": "ON",
    "wsrep_local_state_comment": "Synced",
    "wsrep_ready": "ON",
}
if galera != expected_galera:
    raise SystemExit("Galera quorum acceptance failed")

coffer_counts = subprocess.run(
    [
        "docker",
        "exec",
        "-e",
        f"MYSQL_PWD={database_password}",
        "mariadb",
        "mariadb",
        "-uroot",
        "-Nse",
        (
            "SELECT "
            "(SELECT COUNT(*) FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME='coffer'),"
            "(SELECT COUNT(*) FROM mysql.user WHERE User='coffer');"
        ),
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
if coffer_counts != "0\t0":
    raise SystemExit("Coffer database state exists before deployment")

rabbitmq = json.loads(
    subprocess.run(
        [
            "docker",
            "exec",
            "rabbitmq",
            "rabbitmq-diagnostics",
            "cluster_status",
            "--formatter",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)
expected_rabbitmq = {
    "rabbit@coffer-kolla-ha-stage5-controller-1",
    "rabbit@coffer-kolla-ha-stage5-controller-2",
    "rabbit@coffer-kolla-ha-stage5-controller-3",
}
if set(rabbitmq.get("running_nodes", [])) != expected_rabbitmq:
    raise SystemExit("RabbitMQ running-node acceptance failed")
if rabbitmq.get("partitions") != {}:
    raise SystemExit("RabbitMQ partition acceptance failed")

context = ssl.create_default_context(cafile=ca_path)
payload = json.dumps(
    {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": "admin",
                        "domain": {"name": "Default"},
                        "password": passwords["keystone_admin_password"],
                    }
                },
            },
            "scope": {
                "project": {
                    "name": "admin",
                    "domain": {"name": "Default"},
                }
            },
        }
    }
).encode()
request = urllib.request.Request(
    "https://192.168.252.10:5000/v3/auth/tokens",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(
    request,
    context=context,
    timeout=10,
) as response:
    token = response.headers.get("X-Subject-Token")
    token_document = json.load(response)
if not token:
    raise SystemExit("Keystone admin token is missing")

identity_services = [
    service
    for service in token_document["token"]["catalog"]
    if service.get("type") == "identity"
]
if len(identity_services) != 1:
    raise SystemExit("identity catalog service count changed")
endpoints: dict[str, set[str]] = {}
for endpoint in identity_services[0].get("endpoints", []):
    endpoints.setdefault(endpoint["interface"], set()).add(endpoint["url"])
if endpoints.get("internal") != {"https://192.168.252.10:5000/v3"}:
    raise SystemExit("internal identity catalog URL mismatch")
if endpoints.get("public") != {"https://192.168.254.10:443/v3"}:
    raise SystemExit("public identity catalog URL mismatch")


def keystone_count(path: str, collection: str) -> int:
    query_request = urllib.request.Request(
        f"https://192.168.252.10:5000/v3/{path}",
        headers={"X-Auth-Token": token},
    )
    with urllib.request.urlopen(
        query_request,
        context=context,
        timeout=10,
    ) as response:
        return len(json.load(response).get(collection, []))


if keystone_count("services?type=oci-registry", "services") != 0:
    raise SystemExit("Coffer Keystone service exists before deployment")
if keystone_count("users?name=coffer", "users") != 0:
    raise SystemExit("Coffer Keystone user exists before deployment")

print(
    "control_plane_probe "
    "galera=3/Primary/Synced rabbitmq=3 partitions=0 "
    "catalog_internal=https catalog_public=443 "
    "coffer_database=absent coffer_catalog=absent"
)
PY
}

run_kolla() {
    local phase="$1"
    local timeout_seconds="$2"
    shift 2
    local log="${log_root}/${phase}.log"
    local rc

    install -o root -g root -m 0600 /dev/null "${log}"
    set +e
    env \
        PATH="${venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        LC_ALL=C.UTF-8 \
        LANG=C.UTF-8 \
        ANSIBLE_NOCOLOR=1 \
        ANSIBLE_NO_LOG=True \
        ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
        timeout --signal=INT --kill-after=120 "${timeout_seconds}" \
        "${venv}/bin/kolla-ansible" \
        "$@" \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        >"${log}" 2>&1
    rc="$?"
    set -e
    if test "${rc}" -ne 0; then
        printf 'kolla_lifecycle phase=%s result=failed rc=%s log=%s\n' \
            "${phase}" "${rc}" "${log}" >&2
        return "${rc}"
    fi
    verify_log_secret_free "${log}"
    awk '
        /^PLAY RECAP/ {capture = 1; next}
        capture && NF {print "kolla_recap " $0}
        capture && !NF {exit}
    ' "${log}"
}

run_kolla_check() {
    local phase="$1"
    local log="${log_root}/${phase}-check.log"
    local rc

    install -o root -g root -m 0600 /dev/null "${log}"
    set +e
    env \
        PATH="${venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        LC_ALL=C.UTF-8 \
        LANG=C.UTF-8 \
        ANSIBLE_NOCOLOR=1 \
        ANSIBLE_NO_LOG=True \
        ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
        timeout --signal=INT --kill-after=120 1800 \
        "${venv}/bin/kolla-ansible" check \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        >"${log}" 2>&1
    rc="$?"
    set -e
    if test "${rc}" -ne 0; then
        printf 'kolla_lifecycle phase=%s-check result=failed rc=%s log=%s\n' \
            "${phase}" "${rc}" "${log}" >&2
        return "${rc}"
    fi
    verify_log_secret_free "${log}"
}

if test "${action}" = status; then
    collect_status
    completed=()
    for phase in bootstrap prechecks pull deploy reconfigure; do
        if test -f "$(marker_path "${phase}")"; then
            require_marker "${phase}"
            completed+=("${phase}")
        fi
    done
    printf 'kolla_lifecycle status completed=%s docker=%s/3 active=%s/3 containers=%s nonrunning=%s unhealthy=%s images_min=%s coffer_containers=%s coffer_images=%s coffer_listeners=%s coffer_configs=%s internal_vips=%s external_vips=%s\n' \
        "$(
            if test "${#completed[@]}" -eq 0; then
                printf none
            else
                IFS=,
                printf '%s' "${completed[*]}"
            fi
        )" \
        "${status_docker}" "${status_active}" "${status_containers}" \
        "${status_nonrunning}" "${status_unhealthy}" "${status_images_min}" \
        "${status_coffer_containers}" "${status_coffer_images}" \
        "${status_coffer_listeners}" "${status_coffer_configs}" \
        "${status_internal_vips}" "${status_external_vips}"
    exit 0
fi

exec 9>/run/lock/coffer-stage5-kolla-lifecycle.lock
if ! flock -n 9; then
    echo "refusing concurrent Kolla lifecycle execution" >&2
    exit 75
fi
install -d -o root -g root -m 0700 "${lifecycle_root}"
install -d -o ubuntu -g ubuntu -m 0700 "${log_root}"

case "${action}" in
    bootstrap)
        run_kolla bootstrap 3600 bootstrap-servers
        collect_status
        test "${status_docker}" -eq 3
        test "${status_active}" -eq 3
        test "${status_containers}" -eq 0
        test "${status_internal_vips}" -eq 0
        test "${status_external_vips}" -eq 0
        ;;
    prechecks)
        require_marker bootstrap
        run_kolla prechecks 1800 prechecks --use-test-images
        collect_status
        test "${status_docker}" -eq 3
        test "${status_active}" -eq 3
        ;;
    pull)
        require_marker bootstrap
        require_marker prechecks
        run_kolla pull 5400 pull
        collect_status
        test "${status_docker}" -eq 3
        test "${status_active}" -eq 3
        test "${status_images_min}" -gt 0
        ;;
    deploy)
        if test -e "${production_profile_marker}"; then
            echo "prepared production profile requires reconfigure, not deploy" >&2
            exit 64
        fi
        require_marker bootstrap
        require_marker prechecks
        require_marker pull
        run_kolla deploy 7200 deploy
        collect_status
        test "${status_docker}" -eq 3
        test "${status_active}" -eq 3
        test "${status_containers}" -gt 0
        test "${status_nonrunning}" -eq 0
        test "${status_unhealthy}" -eq 0
        test "${status_internal_vips}" -eq 1
        test "${status_external_vips}" -eq 1
        run_kolla_check deploy
        test "$(
            curl --silent --show-error --output /dev/null \
                --write-out '%{http_code}' \
                --connect-timeout 3 --max-time 10 \
                http://192.168.252.10:5000/v3/
        )" = 200
        probe_external_keystone
        ;;
    reconfigure)
        require_marker deploy
        test "$(stat -c '%U:%G:%a' "${production_profile_marker}")" = \
            root:root:600
        test "$(cat "${production_profile_marker}")" = \
            coffer-stage5-production-profile-v1
        run_kolla reconfigure 7200 reconfigure
        collect_status
        test "${status_docker}" -eq 3
        test "${status_active}" -eq 3
        test "${status_containers}" -eq 36
        test "${status_nonrunning}" -eq 0
        test "${status_unhealthy}" -eq 0
        test "${status_coffer_containers}" -eq 0
        test "${status_coffer_images}" -eq 0
        test "${status_coffer_listeners}" -eq 0
        test "${status_coffer_configs}" -eq 0
        test "${status_internal_vips}" -eq 1
        test "${status_external_vips}" -eq 1
        run_kolla_check reconfigure
        probe_production_profile
        probe_control_plane
        ;;
esac

write_marker "${action}"
printf 'kolla_lifecycle phase=%s result=passed marker=complete\n' "${action}"
