#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {healthy|degraded}" >&2
    exit 64
fi

expected_state="$1"
case "${expected_state}" in
    healthy|degraded)
        ;;
    *)
        echo "refusing an unknown Galera state" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
venv="/home/ubuntu/coffer-stage5/venv"
passwords="/etc/kolla/passwords.yml"
proxysql_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(stat -c '%U:%G:%a' "${passwords}")" = root:root:600
test -x "${venv}/bin/python3"
test "$(docker inspect -f '{{.State.Running}}' mariadb)" = true
test "$(docker inspect -f '{{.State.Health.Status}}' mariadb)" = healthy

password_value() {
    local key="$1"

    "${venv}/bin/python3" - "${passwords}" "${key}" <<'PY'
from pathlib import Path
import sys
import yaml

value = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))[sys.argv[2]]
if not isinstance(value, str) or not value:
    raise SystemExit("required password is unavailable")
print(value, end="")
PY
}

query_galera() {
    local query="$1"
    local password

    password="$(password_value database_password)"
    printf '%s\n%s\n' "${password}" "${query}" |
        docker exec -i mariadb bash -c '
            set -Eeuo pipefail
            IFS= read -r MYSQL_PWD
            export MYSQL_PWD
            IFS= read -r query
            exec mariadb -uroot -Nse "${query}"
        '
    unset password
}

query_proxysql() {
    local address="$1"
    local query="$2"
    local password

    case "${address}" in
        192.168.252.11|192.168.252.12|192.168.252.13)
            ;;
        *)
            echo "refusing a non-controller ProxySQL address" >&2
            return 64
            ;;
    esac
    password="$(password_value proxysql_admin_password)"
    printf '%s\n%s\n' "${password}" "${query}" |
        docker exec -i mariadb bash -c '
            set -Eeuo pipefail
            IFS= read -r MYSQL_PWD
            export MYSQL_PWD
            IFS= read -r query
            exec mariadb --skip-ssl -h"$1" -P6032 \
                -ukolla-admin -Nse "${query}"
        ' -- "${address}"
    unset password
}

status_value() {
    local snapshot="$1"
    local field="$2"

    awk -F'\t' -v field="${field}" '$1 == field {print $2}' \
        <<<"${snapshot}"
}

proxysql_status() {
    local snapshot="$1"
    local hostgroup="$2"
    local address="$3"

    awk -F'\t' -v hostgroup="${hostgroup}" -v address="${address}" '
        $1 == hostgroup && $2 == address {
            print $3
        }
    ' <<<"${snapshot}"
}

galera="$(
    query_galera \
        "SHOW GLOBAL STATUS WHERE Variable_name IN ('wsrep_cluster_size','wsrep_cluster_status','wsrep_local_state_comment','wsrep_ready','wsrep_connected','wsrep_incoming_addresses');"
)"
test "$(status_value "${galera}" wsrep_cluster_status)" = Primary
test "$(status_value "${galera}" wsrep_local_state_comment)" = Synced
test "$(status_value "${galera}" wsrep_ready)" = ON
test "$(status_value "${galera}" wsrep_connected)" = ON

incoming="$(
    status_value "${galera}" wsrep_incoming_addresses |
        tr ',' '\n' |
        LC_ALL=C sort |
        paste -sd, -
)"
case "${expected_state}" in
    healthy)
        test "$(status_value "${galera}" wsrep_cluster_size)" = 3
        test "${incoming}" = \
            "192.168.252.11:3306,192.168.252.12:3306,192.168.252.13:3306"
        ;;
    degraded)
        test "$(status_value "${galera}" wsrep_cluster_size)" = 2
        test "${incoming}" = \
            "192.168.252.11:3306,192.168.252.12:3306"
        ;;
esac

for address in "${proxysql_addresses[@]}"; do
    proxysql="$(
        query_proxysql "${address}" \
            "SELECT hostgroup_id,hostname,status FROM runtime_mysql_servers ORDER BY hostgroup_id,hostname;"
    )"
    case "${expected_state}" in
        healthy)
            test "$(wc -l <<<"${proxysql}")" -eq 5
            test "$(proxysql_status "${proxysql}" 0 192.168.252.11)" = ONLINE
            test "$(proxysql_status "${proxysql}" 0 192.168.252.12)" = SHUNNED
            test "$(proxysql_status "${proxysql}" 0 192.168.252.13)" = SHUNNED
            test "$(proxysql_status "${proxysql}" 1 192.168.252.12)" = ONLINE
            test "$(proxysql_status "${proxysql}" 1 192.168.252.13)" = ONLINE
            reader_three_state=online
            ;;
        degraded)
            test "$(wc -l <<<"${proxysql}")" -eq 4
            test "$(proxysql_status "${proxysql}" 0 192.168.252.11)" = ONLINE
            test "$(proxysql_status "${proxysql}" 0 192.168.252.12)" = SHUNNED
            test "$(proxysql_status "${proxysql}" 1 192.168.252.12)" = ONLINE
            test -z "$(proxysql_status "${proxysql}" 0 192.168.252.13)"
            test -z "$(proxysql_status "${proxysql}" 1 192.168.252.13)"
            test "$(proxysql_status "${proxysql}" 3 192.168.252.13)" = SHUNNED
            reader_three_state=offline-hostgroup-3
            ;;
    esac
done

printf 'kolla_galera state=%s cluster_size=%s primary=yes synced=yes proxysql=3 writer=controller-1 reader-2=online reader-3=%s\n' \
    "${expected_state}" "$(status_value "${galera}" wsrep_cluster_size)" \
    "${reader_three_state}"
