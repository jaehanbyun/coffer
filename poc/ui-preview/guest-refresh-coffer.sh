#!/usr/bin/env bash

set -Eeuo pipefail

source_root="/home/ubuntu/coffer"
image="localhost/coffer:ui-preview"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"
test -f "${source_root}/poc/kolla-runtime/Containerfile.coffer"

docker build \
    --network host \
    --file "${source_root}/poc/kolla-runtime/Containerfile.coffer" \
    --tag "${image}" \
    "${source_root}"
for command_name in \
    coffer-api \
    coffer-edge \
    coffer-reconcile \
    coffer-bootstrap \
    coffer-config-validate; do
    docker run --rm --network none \
        "${image}" "${command_name}" --help >/dev/null
done
docker image inspect \
    --format 'coffer_image_id={{.Id}}' "${image}"
