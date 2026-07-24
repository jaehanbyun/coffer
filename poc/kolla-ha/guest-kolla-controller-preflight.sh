#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 6 ]]; then
    echo "usage: $0 HOST MGMT_IP STORAGE_IP MGMT_MAC STORAGE_MAC EXTERNAL_MAC" >&2
    exit 64
fi

expected_hostname="$1"
management_address="$2"
storage_address="$3"
management_mac="$4"
storage_mac="$5"
external_mac="$6"
reserved_ports=(
    80 443 3306 4444 4567 4568 5000 5001 5672 6032 6033 8404 11211 15672
)

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(uname -m)" = x86_64
test "$(nproc)" -eq 8
test "$(
    awk '/MemTotal:/ {print int($2 / 1024)}' /proc/meminfo
)" -ge 15000
test "$(
    df --output=avail -BM / | tail -1 | tr -dc '0-9'
)" -ge 70000
test "$(stat -c '%a' /home/ubuntu/.ssh/authorized_keys)" = 600
sudo -n true

# Runtime-owned Ubuntu release metadata is intentionally sourced.
# shellcheck disable=SC1091
. /etc/os-release
test "${ID}" = ubuntu
test "${VERSION_ID}" = 24.04
test "$(cloud-init status --format json | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["status"])')" = "done"
test "$(timedatectl show -p NTPSynchronized --value)" = yes

test "$(cat /sys/class/net/ens3/address)" = "${management_mac}"
test "$(cat /sys/class/net/ens4/address)" = "${storage_mac}"
test "$(cat /sys/class/net/ens5/address)" = "${external_mac}"
test "$(
    ip -4 -o address show dev ens3 |
        awk '{print $4}'
)" = "${management_address}/24"
test "$(
    ip -4 -o address show dev ens4 |
        awk '{print $4}'
)" = "${storage_address}/24"
test -z "$(ip -4 -o address show dev ens5)"
ip route show default |
    awk '
        $1 == "default" &&
        $2 == "via" &&
        $3 == "192.168.252.1" &&
        $4 == "dev" &&
        $5 == "ens3" {found = 1}
        END {exit !found}
    '

for vip in 192.168.252.10 192.168.254.10; do
    if ip -4 -o address show |
        awk '{print $4}' |
        cut -d/ -f1 |
        grep -Fxq "${vip}"; then
        echo "reserved Kolla VIP is already assigned" >&2
        exit 20
    fi
done

for port in "${reserved_ports[@]}"; do
    if ss -H -lnt |
        awk '{print $4}' |
        grep -Eq "(^|[.:])${port}$"; then
        echo "reserved Kolla TCP port is already listening: ${port}" >&2
        exit 21
    fi
done

test ! -e /etc/kolla
test ! -e /var/lib/kolla
if command -v docker >/dev/null 2>&1; then
    test -z "$(docker ps -aq)"
fi
if command -v podman >/dev/null 2>&1; then
    test -z "$(podman ps -aq)"
fi

python3 - <<'PY'
import socket

for host, port in (
    ("quay.io", 443),
    ("github.com", 443),
    ("192.168.253.30", 8443),
):
    with socket.create_connection((host, port), timeout=10):
        pass
PY

printf 'kolla_controller_preflight host=%s vcpus=8 memory_mib>=15000 root_free_mib>=70000 ports=free state=clean\n' \
    "${expected_hostname}"
