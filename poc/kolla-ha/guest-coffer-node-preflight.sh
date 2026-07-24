#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "usage: $0 {clean|ready} HOST INDEX" >&2
    exit 64
fi

action="$1"
expected_hostname="$2"
index="$3"
coffer_image="localhost/coffer:stage5"
registry_image="localhost/coffer-registry:stage5"
expected_containers="$(
    printf '%s\n' \
        cron \
        fluentd \
        haproxy \
        keepalived \
        keystone \
        keystone_fernet \
        keystone_ssh \
        kolla_toolbox \
        mariadb \
        memcached \
        proxysql \
        rabbitmq
)"
coffer_containers=(
    coffer_api
    coffer_edge
    coffer_registry
    coffer_reconcile
    bootstrap_coffer
)
coffer_config_paths=(
    /etc/kolla/coffer-api
    /etc/kolla/coffer-edge
    /etc/kolla/coffer-registry
    /etc/kolla/coffer-reconcile
    /etc/kolla/coffer-bootstrap
    /var/lib/docker/volumes/kolla_logs/_data/coffer
    /var/lib/docker/volumes/kolla_logs/_data/coffer-registry
)

case "${action}" in
    clean|ready)
        ;;
    *)
        echo "refusing an unknown Coffer preflight action" >&2
        exit 64
        ;;
esac
if [[ ! "${index}" =~ ^[123]$ ]]; then
    echo "refusing an invalid controller index" >&2
    exit 64
fi

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(uname -m)" = x86_64
systemctl is-active --quiet docker

actual_containers="$(
    docker ps -a --format '{{.Names}}' | sort
)"
test "${actual_containers}" = "${expected_containers}"
test "$(
    docker ps -a --format '{{.State}}' |
        awk '$1 != "running" {count += 1} END {print count + 0}'
)" -eq 0
test "$(
    docker ps -a --format '{{.Status}}' |
        awk '/\(unhealthy\)/ {count += 1} END {print count + 0}'
)" -eq 0

for container in "${coffer_containers[@]}"; do
    if docker container inspect "${container}" >/dev/null 2>&1; then
        echo "unexpected Coffer container exists: ${container}" >&2
        exit 20
    fi
done
for port in 8787 8788 8789; do
    if ss -H -lnt |
        awk '{print $4}' |
        grep -Eq "(^|[.:])${port}$"; then
        echo "reserved Coffer port is already listening: ${port}" >&2
        exit 21
    fi
done
for path in "${coffer_config_paths[@]}"; do
    test ! -e "${path}"
done
if grep -ERiq \
    'coffer_api|coffer_edge|coffer_registry|oci-registry' \
    /etc/kolla/haproxy 2>/dev/null; then
    echo "unexpected Coffer HAProxy state exists" >&2
    exit 22
fi

coffer_image_id=absent
registry_image_id=absent
case "${action}" in
    clean)
        if docker image inspect "${coffer_image}" >/dev/null 2>&1 ||
            docker image inspect "${registry_image}" >/dev/null 2>&1; then
            echo "Coffer pilot image exists before image preparation" >&2
            exit 23
        fi
        ;;
    ready)
        coffer_image_id="$(
            docker image inspect --format '{{.Id}}' "${coffer_image}"
        )"
        registry_image_id="$(
            docker image inspect --format '{{.Id}}' "${registry_image}"
        )"
        [[ "${coffer_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
        [[ "${registry_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
        ;;
esac

printf 'coffer_node_preflight action=%s host=%s index=%s containers=12 runtime=absent ports=free config=absent coffer_image=%s registry_image=%s\n' \
    "${action}" "${expected_hostname}" "${index}" \
    "${coffer_image_id}" "${registry_image_id}"
