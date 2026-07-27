#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
primary_edge="/etc/kolla/coffer-edge"
primary_registry="/etc/kolla/coffer-registry"
replica_edge="/etc/kolla/coffer-edge-replica"
replica_registry="/etc/kolla/coffer-registry-replica"
edge_container="coffer_edge_replica"
registry_container="coffer_registry_replica"
edge_image="localhost/coffer:ui-preview"
registry_image="localhost/coffer-registry:ui-preview"
backend_ca="${replica_edge}/backend-ca.crt"
guest_address="192.168.122.204"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"

remove_replicas() {
    for container in "${edge_container}" "${registry_container}"; do
        if docker container inspect "${container}" >/dev/null 2>&1; then
            docker container rm --force "${container}" >/dev/null
        fi
    done
    rm -rf -- "${replica_edge}" "${replica_registry}"
}

prepare_config() {
    test -d "${primary_edge}"
    test -d "${primary_registry}"
    test ! -L "${primary_edge}"
    test ! -L "${primary_registry}"
    rm -rf -- "${replica_edge}" "${replica_registry}"
    cp --archive "${primary_edge}" "${replica_edge}"
    cp --archive "${primary_registry}" "${replica_registry}"
    test "$(
        grep -Fxc "bind_port = 8788" "${replica_edge}/coffer.conf"
    )" -eq 1
    test "$(
        grep -Fc "registry_upstream_url = https://${guest_address}:8789" \
            "${replica_edge}/coffer.conf"
    )" -eq 1
    test "$(
        grep -Fc "addr: ${guest_address}:8789" \
            "${replica_registry}/config.yml"
    )" -eq 1
    sed -i \
        -e 's/^bind_port = 8788$/bind_port = 18888/' \
        -e "s#registry_upstream_url = https://${guest_address}:8789#registry_upstream_url = https://${guest_address}:18889#" \
        "${replica_edge}/coffer.conf"
    sed -i \
        "s#addr: ${guest_address}:8789#addr: ${guest_address}:18889#" \
        "${replica_registry}/config.yml"
    test "$(
        grep -Fxc "bind_port = 18888" "${replica_edge}/coffer.conf"
    )" -eq 1
    test "$(
        grep -Fc "addr: ${guest_address}:18889" \
            "${replica_registry}/config.yml"
    )" -eq 1
}

start_replicas() {
    remove_replicas
    prepare_config
    docker run --detach \
        --name "${registry_container}" \
        --network host \
        --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
        --env KOLLA_SERVICE_NAME=coffer-registry-replica \
        --volume "${replica_registry}:/var/lib/kolla/config_files:ro" \
        --volume /etc/localtime:/etc/localtime:ro \
        --volume kolla_logs:/var/log/kolla \
        "${registry_image}" >/dev/null
    docker run --detach \
        --name "${edge_container}" \
        --network host \
        --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
        --env KOLLA_SERVICE_NAME=coffer-edge-replica \
        --volume "${replica_edge}:/var/lib/kolla/config_files:ro" \
        --volume /etc/localtime:/etc/localtime:ro \
        --volume kolla_logs:/var/log/kolla \
        "${edge_image}" >/dev/null
    for _attempt in $(seq 1 60); do
        if test "$(
            curl --silent --show-error \
                --cacert "${backend_ca}" \
                --output /dev/null \
                --write-out '%{http_code}' \
                "https://${guest_address}:18888/v2/" 2>/dev/null || true
        )" = 401; then
            break
        fi
        sleep 1
    done
    test "$(
        curl --silent --show-error \
            --cacert "${backend_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "https://${guest_address}:18888/v2/"
    )" = 401
}

status() {
    docker container inspect \
        --format '{{.Name}} running={{.State.Running}} image={{.Config.Image}}' \
        "${edge_container}" "${registry_container}"
    grep -F \
        'realm: "https://bb00.tail23b778.ts.net:18788/auth/token"' \
        "${replica_registry}/config.yml" >/dev/null
    echo "replica_challenge_realm=verified"
}

case "${action}" in
    start)
        start_replicas
        status
        ;;
    status)
        status
        ;;
    stop)
        remove_replicas
        ;;
    *)
        echo "usage: $0 {start|status|stop}" >&2
        exit 64
        ;;
esac
