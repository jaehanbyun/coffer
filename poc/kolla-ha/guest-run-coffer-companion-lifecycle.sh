#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {status|prechecks|deploy|stop}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    status|prechecks|deploy|stop)
        ;;
    *)
        echo "refusing an unknown Coffer companion lifecycle action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
source_root="${state_root}/coffer-operator-source"
source_commit="4f1ff7ddfd89d21f17ab7cbb531c335e85d94542"
source_marker="${state_root}/coffer-operator-source.prepared"
source_marker_value="coffer-stage5-operator-source-v2"
source_config_relative="ansible/roles/coffer/tasks/config.yml"
source_template_relative="docker/config/coffer-bootstrap.json.j2"
source_config_sha256="11645fe8a16919f0970b719d8a46c9e84c3a1e43b4522cc364f700204db9b4a5"
source_template_sha256="96758f497c0b821e02091668cc3b2b215ac9addb7a5c2541f93c27af92ee2d04"
venv="${state_root}/venv"
entrypoint="${source_root}/ansible/kolla-ansible-coffer"
inventory="/etc/kolla/multinode"
config_root="/etc/kolla"
passwords="${config_root}/passwords.yml"
coffer_globals="${config_root}/coffer-globals.yml"
input_root="${config_root}/config/coffer"
prepared_marker="${state_root}/companion.prepared"
lifecycle_root="${state_root}/companion-lifecycle"
log_root="${state_root}/companion-logs"
marker_value="coffer-stage5-companion-lifecycle-v1"
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"
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
groups=(
    coffer-api
    coffer-edge
    coffer-registry
    coffer-reconcile
)

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(git -C "${source_root}" rev-parse HEAD)" = "${source_commit}"
test "$(stat -c '%U:%G:%a' "${source_marker}")" = root:root:600
test "$(cat "${source_marker}")" = "${source_marker_value}"
test "$(
    sha256sum "${source_root}/${source_config_relative}" | awk '{print $1}'
)" = "${source_config_sha256}"
test "$(
    sha256sum "${source_root}/${source_template_relative}" | awk '{print $1}'
)" = "${source_template_sha256}"
test "$(
    git -C "${source_root}" diff --name-only | LC_ALL=C sort
)" = "$(
    printf '%s\n' "${source_config_relative}" "${source_template_relative}" |
        LC_ALL=C sort
)"
test -z "$(
    git -C "${source_root}" status --porcelain --untracked-files=all |
        awk '$1 != "M" {print}'
)"
git -C "${source_root}" diff --check
test -x "${entrypoint}"
test -x "${venv}/bin/kolla-ansible"
test -x "${venv}/bin/ansible-inventory"
test "$(stat -c '%U:%G:%a' "${deployment_key}")" = ubuntu:ubuntu:600
test "$(stat -c '%U:%G:%a' "${known_hosts}")" = ubuntu:ubuntu:644
test "$(stat -c '%U:%G:%a' "${inventory}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${config_root}/globals.yml")" = root:root:644
test "$(stat -c '%U:%G:%a' "${passwords}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${coffer_globals}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${prepared_marker}")" = root:root:600
test "$(cat "${prepared_marker}")" = coffer-stage5-companion-v1

ANSIBLE_COLLECTIONS_PATH=\
/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
    "${venv}/bin/ansible-inventory" -i "${inventory}" --list |
    "${venv}/bin/python3" -c '
import json
import sys

document = json.load(sys.stdin)
separator = sys.argv.index("--")
hosts = set(sys.argv[1:separator])
for group in sys.argv[separator + 1:]:
    if set(document.get(group, {}).get("hosts", [])) != hosts:
        raise SystemExit(f"companion inventory mismatch: {group}")
' "${hostnames[@]}" -- "${groups[@]}"

ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
)

marker_path() {
    case "$1" in
        prechecks|deploy|stop)
            ;;
        *)
            echo "refusing a non-companion marker" >&2
            return 64
            ;;
    esac
    printf '%s/%s.complete\n' "${lifecycle_root}" "$1"
}

require_marker() {
    local marker

    marker="$(marker_path "$1")"
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${marker_value}"
}

write_marker() {
    local marker
    local temporary

    marker="$(marker_path "$1")"
    temporary="${marker}.tmp.$$"
    cleanup_marker() {
        rm -f -- "${temporary}"
    }
    trap cleanup_marker EXIT
    printf '%s\n' "${marker_value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${marker}"
    trap - EXIT
}

verify_log_secret_free() {
    local log="$1"

    "${venv}/bin/python3" - \
        "${passwords}" "${input_root}/secrets" "${log}" <<'PY'
from pathlib import Path
import base64
import re
import sys
import urllib.parse

import yaml


passwords_path = Path(sys.argv[1])
secret_root = Path(sys.argv[2])
log_path = Path(sys.argv[3])
document = yaml.safe_load(passwords_path.read_text(encoding="utf-8"))
values = [
    value.encode()
    for value in document.values()
    if isinstance(value, str) and len(value) >= 8
]
for path in sorted(secret_root.iterdir()):
    if path.is_file():
        value = path.read_bytes().strip()
        if len(value) >= 8:
            values.append(value)

data = log_path.read_bytes()
for value in values:
    candidates = {value}
    if len(value) <= 512:
        text = value.decode(errors="ignore")
        candidates.add(urllib.parse.quote(text, safe="").encode())
        candidates.add(base64.b64encode(value))
    if any(candidate and candidate in data for candidate in candidates):
        raise SystemExit("credential found in retained Coffer log")
if b"-----BEGIN PRIVATE KEY-----" in data:
    raise SystemExit("private key found in retained Coffer log")
if re.search(
    rb"Authorization ['\"](?:Basic|Bearer) [A-Za-z0-9+/=._-]+",
    data,
):
    raise SystemExit("authorization credential found in retained Coffer log")
if re.search(
    rb"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    data,
):
    raise SystemExit("bearer token found in retained Coffer log")
PY
}

verify_runtime_logs_secret_free() (
    set -Eeuo pipefail

    local temporary_root
    local index
    local address
    local expected
    local log
    local -a runtime_logs=()

    temporary_root="$(
        mktemp -d "${state_root}/.coffer-runtime-log-audit.XXXXXX"
    )"
    chmod 0700 "${temporary_root}"
    # shellcheck disable=SC2329  # Invoked by the EXIT trap.
    cleanup_runtime_logs() {
        local runtime_log

        for runtime_log in "${runtime_logs[@]}"; do
            rm -f -- "${runtime_log}"
        done
        rmdir -- "${temporary_root}"
    }
    collect_runtime_log() {
        local target_address="$1"

        sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${target_address}" \
            sudo env LC_ALL=C LANG=C bash -s
    }
    trap cleanup_runtime_logs EXIT

    for index in "${!addresses[@]}"; do
        address="${addresses[${index}]}"
        expected="${hostnames[${index}]}"
        log="${temporary_root}/${expected}.log"
        runtime_logs+=("${log}")
        if ! collect_runtime_log "${address}" \
            >"${log}" 2>&1 <<'REMOTE'
set -Eeuo pipefail

docker logs coffer_api
docker logs coffer_edge
docker logs coffer_registry
REMOTE
        then
            printf 'runtime log collection failed for %s\n' \
                "${expected}" >&2
            return 1
        fi
        chmod 0600 "${log}"
        verify_log_secret_free "${log}"
    done

    printf 'coffer_runtime_log_audit hosts=3 containers=9 secrets=redacted result=passed\n'
)

node_snapshot() {
    local index="$1"
    local address="${addresses[${index}]}"
    local expected="${hostnames[${index}]}"

    sudo -u ubuntu ssh "${ssh_options[@]}" "ubuntu@${address}" \
        sudo env LC_ALL=C LANG=C bash -s -- "${expected}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
test "$(hostname)" = "${expected_hostname}"
test "$(systemctl is-active docker)" = active

containers=0
running=0
unhealthy=0
healthy=0
bootstrap=0
for name in coffer_api coffer_edge coffer_registry; do
    if docker inspect "${name}" >/dev/null 2>&1; then
        containers="$((containers + 1))"
        test "$(docker inspect --format '{{.State.Running}}' "${name}")" = true &&
            running="$((running + 1))"
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}")"
        if test "${health}" = healthy; then
            healthy="$((healthy + 1))"
        else
            unhealthy="$((unhealthy + 1))"
        fi
    fi
done
if docker inspect bootstrap_coffer >/dev/null 2>&1; then
    bootstrap=1
    test "$(docker inspect --format '{{.State.Running}}' bootstrap_coffer)" = false
fi
if docker inspect coffer_reconcile >/dev/null 2>&1; then
    echo "disabled reconciler container exists" >&2
    exit 20
fi

listeners="$(
    ss -H -lnt |
        awk '$4 ~ /:(8787|8788|8789)$/ {count += 1}
             END {print count + 0}'
)"
configs=0
for path in \
    /etc/kolla/coffer-api \
    /etc/kolla/coffer-edge \
    /etc/kolla/coffer-registry \
    /etc/kolla/coffer-bootstrap; do
    test -d "${path}" && configs="$((configs + 1))"
done
test ! -e /etc/kolla/coffer-reconcile

printf 'host=%s containers=%s running=%s healthy=%s unhealthy=%s bootstrap=%s listeners=%s configs=%s\n' \
    "${expected_hostname}" "${containers}" "${running}" "${healthy}" \
    "${unhealthy}" "${bootstrap}" "${listeners}" "${configs}"
REMOTE
}

collect_nodes() {
    local index
    local snapshot

    total_containers=0
    total_running=0
    total_healthy=0
    total_unhealthy=0
    total_bootstrap=0
    total_listeners=0
    total_configs=0
    for index in "${!addresses[@]}"; do
        snapshot="$(node_snapshot "${index}")"
        test "$(wc -l <<<"${snapshot}" | tr -d ' ')" -eq 1
        test "$(sed -n 's/^host=\([^ ]*\).*/\1/p' <<<"${snapshot}")" = \
            "${hostnames[${index}]}"
        printf 'coffer_companion_node %s\n' "${snapshot}"
        for field in \
            containers running healthy unhealthy bootstrap listeners configs; do
            value="$(
                sed -n "s/.* ${field}=\\([^ ]*\\).*/\\1/p" <<<" ${snapshot}"
            )"
            [[ "${value}" =~ ^[0-9]+$ ]]
            case "${field}" in
                containers) total_containers="$((total_containers + value))" ;;
                running) total_running="$((total_running + value))" ;;
                healthy) total_healthy="$((total_healthy + value))" ;;
                unhealthy) total_unhealthy="$((total_unhealthy + value))" ;;
                bootstrap) total_bootstrap="$((total_bootstrap + value))" ;;
                listeners) total_listeners="$((total_listeners + value))" ;;
                configs) total_configs="$((total_configs + value))" ;;
            esac
        done
    done
}

require_predeploy_boundary() {
    collect_nodes
    test "${total_containers}" -eq 0
    test "${total_running}" -eq 0
    test "${total_healthy}" -eq 0
    test "${total_unhealthy}" -eq 0
    test "${total_bootstrap}" -eq 0
    test "${total_listeners}" -eq 0
    test "${total_configs}" -eq 0
}

probe_service_endpoints() {
    local backend_ca="${input_root}/public/backend-ca.crt"
    local kolla_ca="${config_root}/certificates-stage5/ca/root.crt"
    local ca_base64
    local index
    local owner_address=
    local owner_count=0
    local owner_hostname=
    local owner_snapshot
    local status

    status="$(
        curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
            --cacert "${kolla_ca}" --connect-timeout 3 --max-time 10 \
            https://192.168.252.10:8787/healthz
    )"
    test "${status}" = 200
    for port in 8788 8789; do
        status="$(
            curl --silent --show-error --output /dev/null \
                --write-out '%{http_code}' --cacert "${kolla_ca}" \
                --connect-timeout 3 --max-time 10 \
                "https://192.168.252.10:${port}/v2/"
        )"
        test "${status}" = 401
    done
    for index in "${!addresses[@]}"; do
        for port in 8787 8788 8789; do
            status="$(
                curl --silent --show-error --output /dev/null \
                    --write-out '%{http_code}' --cacert "${backend_ca}" \
                    --connect-timeout 3 --max-time 10 \
                    "https://${addresses[${index}]}:${port}/$(
                        if test "${port}" -eq 8787; then
                            printf healthz
                        else
                            printf v2/
                        fi
                    )"
            )"
            if test "${port}" -eq 8787; then
                test "${status}" = 200
            else
                test "${status}" = 401
            fi
        done
    done
    for index in "${!addresses[@]}"; do
        owner_snapshot="$(
            sudo -u ubuntu ssh "${ssh_options[@]}" \
                "ubuntu@${addresses[${index}]}" \
                sudo ip -4 -o addr show
        )"
        if grep -q '192[.]168[.]254[.]10/' <<<"${owner_snapshot}"; then
            owner_count="$((owner_count + 1))"
            owner_address="${addresses[${index}]}"
            owner_hostname="${hostnames[${index}]}"
        fi
    done
    test "${owner_count}" -eq 1
    ca_base64="$(base64 --wrap=0 "${kolla_ca}")"
    sudo -u ubuntu ssh "${ssh_options[@]}" "ubuntu@${owner_address}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
        CA_CERT_BASE64="${ca_base64}" python3 - <<'PY'
import base64
import http.client
import os
import socket
import ssl


context = ssl.create_default_context(
    cadata=base64.b64decode(os.environ["CA_CERT_BASE64"]).decode()
)
with socket.create_connection(("192.168.254.10", 443), timeout=10) as raw:
    with context.wrap_socket(
        raw,
        server_hostname="registry.coffer.stage5",
    ) as secured:
        secured.sendall(
            b"GET /v2/ HTTP/1.1\r\n"
            b"Host: registry.coffer.stage5\r\n"
            b"Connection: close\r\n\r\n"
        )
        response = http.client.HTTPResponse(secured)
        response.begin()
        response.read()
if response.status != 401:
    raise SystemExit("public Coffer challenge status failed")
challenge = response.getheader("WWW-Authenticate", "")
if (
    'realm="https://registry.coffer.stage5/auth/token"' not in challenge
    or 'service="coffer-registry"' not in challenge
):
    raise SystemExit("public Coffer challenge contract failed")
try:
    private = socket.create_connection(("192.168.254.10", 8789), timeout=3)
except OSError:
    pass
else:
    private.close()
    raise SystemExit("private registry port is reachable on the external VIP")
PY
    printf 'coffer_endpoint_probe api=200 edge=401 registry=401 backends=9/9 public=401 external_owner=%s bypass=denied tls=verified\n' \
        "${owner_hostname}"
}

probe_database_and_catalog() {
    "${venv}/bin/python3" - \
        "${passwords}" "${config_root}/certificates-stage5/ca/root.crt" \
        "$1" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request

import yaml


passwords = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_mode = sys.argv[3]
database_state = subprocess.run(
    [
        "docker",
        "exec",
        "-e",
        f"MYSQL_PWD={passwords['database_password']}",
        "mariadb",
        "mariadb",
        "-uroot",
        "-Nse",
        (
            "SELECT COUNT(*) FROM information_schema.SCHEMATA "
            "WHERE SCHEMA_NAME='coffer';"
            "SELECT COUNT(*) FROM mysql.user WHERE User='coffer';"
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA='coffer' AND TABLE_NAME='alembic_version';"
        ),
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
if database_state not in (["1", "1", "0"], ["1", "1", "1"]):
    raise SystemExit("Coffer database state acceptance failed")
migration = "absent"
if database_state[2] == "1":
    migration = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"MYSQL_PWD={passwords['database_password']}",
            "mariadb",
            "mariadb",
            "-uroot",
            "-Nse",
            "SELECT version_num FROM coffer.alembic_version;",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
if expected_mode == "partial":
    if database_state != ["1", "1", "0"] or migration != "absent":
        raise SystemExit("Coffer partial database acceptance failed")
elif expected_mode == "deployed":
    if database_state != ["1", "1", "1"] or migration != "0004_inventory_import":
        raise SystemExit("Coffer deployed database acceptance failed")
else:
    raise SystemExit("unknown Coffer control-state mode")

context = ssl.create_default_context(cafile=sys.argv[2])
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
    token = response.headers["X-Subject-Token"]


def query(path: str, collection: str) -> list[dict[str, object]]:
    request = urllib.request.Request(
        f"https://192.168.252.10:5000/v3/{path}",
        headers={"X-Auth-Token": token},
    )
    with urllib.request.urlopen(
        request,
        context=context,
        timeout=10,
    ) as response:
        return json.load(response)[collection]


services = query(
    "services?" + urllib.parse.urlencode({"type": "oci-registry"}),
    "services",
)
users = query(
    "users?" + urllib.parse.urlencode({"name": "coffer"}),
    "users",
)
if len(services) != 1 or len(users) != 1:
    raise SystemExit("Coffer catalog identity count failed")
endpoints = query(
    "endpoints?" + urllib.parse.urlencode({"service_id": services[0]["id"]}),
    "endpoints",
)
actual = {(endpoint["interface"], endpoint["url"]) for endpoint in endpoints}
expected = {
    ("internal", "https://192.168.252.10:8788/v1"),
    ("admin", "https://192.168.252.10:8788/v1"),
    ("public", "https://registry.coffer.stage5/v1"),
}
if actual != expected:
    raise SystemExit("Coffer endpoint catalog acceptance failed")
print(
    f"coffer_control_probe state={expected_mode} database=present "
    f"migration={migration} database_user=1 service=1 service_user=1 "
    "endpoints=3"
)
PY
}

classify_predeploy_or_partial_boundary() {
    collect_nodes
    if test "${total_containers}" -eq 0 &&
        test "${total_running}" -eq 0 &&
        test "${total_healthy}" -eq 0 &&
        test "${total_unhealthy}" -eq 0 &&
        test "${total_bootstrap}" -eq 0 &&
        test "${total_listeners}" -eq 0 &&
        test "${total_configs}" -eq 0; then
        boundary_state=prechecked
        return 0
    fi
    if test "${total_containers}" -eq 0 &&
        test "${total_running}" -eq 0 &&
        test "${total_healthy}" -eq 0 &&
        test "${total_unhealthy}" -eq 0 &&
        test "${total_bootstrap}" -eq 0 &&
        test "${total_listeners}" -eq 9 &&
        test "${total_configs}" -eq 12; then
        probe_database_and_catalog partial
        boundary_state=deploy-partial
        return 0
    fi
    if test "${total_containers}" -eq 9 &&
        test "${total_running}" -eq 9 &&
        test "${total_healthy}" -eq 9 &&
        test "${total_unhealthy}" -eq 0 &&
        test "${total_bootstrap}" -le 1 &&
        test "${total_listeners}" -eq 18 &&
        test "${total_configs}" -eq 12; then
        probe_database_and_catalog deployed
        boundary_state=deploy-candidate
        return 0
    fi
    return 1
}

require_deployed_boundary() {
    collect_nodes
    test "${total_containers}" -eq 9
    test "${total_running}" -eq 9
    test "${total_healthy}" -eq 9
    test "${total_unhealthy}" -eq 0
    test "${total_bootstrap}" -le 1
    test "${total_listeners}" -eq 18
    test "${total_configs}" -eq 12
    probe_database_and_catalog deployed
    probe_service_endpoints
    verify_runtime_logs_secret_free
}

require_stopped_boundary() {
    collect_nodes
    test "${total_containers}" -eq 9
    test "${total_running}" -eq 0
    test "${total_healthy}" -eq 0
    test "${total_unhealthy}" -eq 9
    test "${total_bootstrap}" -le 1
    test "${total_listeners}" -eq 9
    test "${total_configs}" -eq 12
    probe_database_and_catalog deployed
}

run_companion() {
    local phase="$1"
    local timeout_seconds="$2"
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
        KOLLA_ANSIBLE_PYTHON="${venv}/bin/python3" \
        timeout --signal=INT --kill-after=120 "${timeout_seconds}" \
        "${entrypoint}" "${phase}" \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        -e "@${coffer_globals}" \
        >"${log}" 2>&1
    rc="$?"
    set -e
    verify_log_secret_free "${log}"
    if test "${rc}" -ne 0; then
        printf 'coffer_companion_lifecycle phase=%s result=failed rc=%s log=%s\n' \
            "${phase}" "${rc}" "${log}" >&2
        return "${rc}"
    fi
    awk '
        /^PLAY RECAP/ {capture = 1; next}
        capture && NF {print "coffer_recap " $0}
        capture && !NF {exit}
    ' "${log}"
}

run_companion_check() {
    local log="${log_root}/deploy-check.log"
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
        KOLLA_ANSIBLE_PYTHON="${venv}/bin/python3" \
        timeout --signal=INT --kill-after=120 1800 \
        "${entrypoint}" check \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        -e "@${coffer_globals}" \
        >"${log}" 2>&1
    rc="$?"
    set -e
    verify_log_secret_free "${log}"
    if test "${rc}" -ne 0; then
        printf 'coffer_companion_lifecycle phase=deploy-check result=failed rc=%s log=%s\n' \
            "${rc}" "${log}" >&2
        return "${rc}"
    fi
}

if test "${action}" = status; then
    if test -e "$(marker_path stop)"; then
        require_marker prechecks
        require_marker deploy
        require_marker stop
        require_stopped_boundary
        state=stopped
    elif test -e "$(marker_path deploy)"; then
        require_marker prechecks
        require_marker deploy
        require_deployed_boundary
        state=deployed
    elif test -e "$(marker_path prechecks)"; then
        require_marker prechecks
        classify_predeploy_or_partial_boundary
        state="${boundary_state}"
    else
        test ! -e "$(marker_path deploy)"
        require_predeploy_boundary
        state=prepared
    fi
    printf 'coffer_companion_lifecycle state=%s runtime_containers=%s listeners=%s configs=%s\n' \
        "${state}" "${total_containers}" "${total_listeners}" "${total_configs}"
    exit 0
fi

exec 9>/run/lock/coffer-stage5-companion-lifecycle.lock
if ! flock -n 9; then
    echo "refusing concurrent Coffer companion lifecycle execution" >&2
    exit 75
fi
install -d -o root -g root -m 0700 "${lifecycle_root}"
install -d -o root -g root -m 0700 "${log_root}"

case "${action}" in
    prechecks)
        test ! -e "$(marker_path deploy)"
        if test -e "$(marker_path prechecks)"; then
            require_marker prechecks
            require_predeploy_boundary
            printf 'coffer_companion_lifecycle phase=prechecks result=passed idempotent=yes\n'
            exit 0
        fi
        require_predeploy_boundary
        run_companion prechecks 1800
        require_predeploy_boundary
        write_marker prechecks
        ;;
    deploy)
        require_marker prechecks
        if test -e "$(marker_path deploy)"; then
            require_marker deploy
            require_deployed_boundary
            printf 'coffer_companion_lifecycle phase=deploy result=passed idempotent=yes\n'
            exit 0
        fi
        classify_predeploy_or_partial_boundary
        run_companion deploy 7200
        run_companion_check
        require_deployed_boundary
        write_marker deploy
        ;;
    stop)
        require_marker prechecks
        require_marker deploy
        if test -e "$(marker_path stop)"; then
            require_marker stop
            require_stopped_boundary
            printf 'coffer_companion_lifecycle phase=stop result=passed idempotent=yes\n'
            exit 0
        fi
        require_deployed_boundary
        run_companion stop 1800
        require_stopped_boundary
        write_marker stop
        ;;
esac

printf 'coffer_companion_lifecycle phase=%s result=passed marker=complete\n' \
    "${action}"
