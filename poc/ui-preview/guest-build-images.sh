#!/usr/bin/env bash

set -Eeuo pipefail

source_root="/home/ubuntu/coffer"
state_root="/home/ubuntu/coffer-ui-preview"
marker="${state_root}/images.complete"
horizon_wheel="${source_root}/work/ui-image-qualification/wheels/coffer_horizon-0.1.0-py3-none-any.whl"
skyline_wheel="${source_root}/work/ui-image-qualification/wheels/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
contract_root="/etc/kolla/config/coffer/ui"
image_globals="/etc/kolla/coffer-ui-images.yml"
base_image="localhost/coffer-stage2-base:2026.1"
coffer_image="localhost/coffer:ui-preview"
registry_image="localhost/coffer-registry:ui-preview"
bootstrap_registry_image="docker.io/library/registry:3.1.1@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"
test "$(uname -m)" = x86_64
test -s "${horizon_wheel}"
test -s "${skyline_wheel}"
printf '%s  %s\n' \
    "629960734a4ca7b39ebce285241b7f936542b7e46b49eee6f03161f89c6829aa" \
    "${horizon_wheel}" |
    sha256sum --check --strict --status
printf '%s  %s\n' \
    "52f3d9ffb1f119903b182d1101d13105797a9bfa90a421fc1a25497b874d8b1d" \
    "${skyline_wheel}" |
    sha256sum --check --strict --status

if test -e "${marker}"; then
    test "$(cat "${marker}")" = "coffer-ui-preview-images-v1"
    test -s "${image_globals}"
    echo "Coffer UI preview images already prepared"
    exit 0
fi

docker build \
    --network host \
    --file "${source_root}/poc/kolla-runtime/Containerfile.base" \
    --tag "${base_image}" \
    "${source_root}"
docker build \
    --network host \
    --file "${source_root}/poc/kolla-runtime/Containerfile.coffer" \
    --tag "${coffer_image}" \
    "${source_root}"
docker build \
    --network host \
    --build-arg DISTRIBUTION_VERSION=3.1.1 \
    --build-arg DISTRIBUTION_ARCH=amd64 \
    --build-arg DISTRIBUTION_SHA256=6f330a3ba9ea1d23a6ee189f449d792595240585bb2f159123d76ac594f70dd8 \
    --file "${source_root}/poc/kolla-runtime/Containerfile.registry" \
    --tag "${registry_image}" \
    "${source_root}"
for command in coffer-api coffer-edge coffer-reconcile coffer-bootstrap; do
    docker run --rm --network none \
        "${coffer_image}" "${command}" --help >/dev/null
done
docker run --rm --network none \
    "${registry_image}" /usr/local/bin/registry --version |
    grep -Fq "3.1.1"

docker pull "${bootstrap_registry_image}" >/dev/null
if ! docker container inspect coffer-bootstrap-registry >/dev/null 2>&1; then
    docker volume create coffer-ui-preview-bootstrap-registry >/dev/null
    docker run --detach \
        --name coffer-bootstrap-registry \
        --restart unless-stopped \
        --network host \
        --env REGISTRY_HTTP_ADDR=127.0.0.1:5000 \
        --volume coffer-ui-preview-bootstrap-registry:/var/lib/registry \
        "${bootstrap_registry_image}" >/dev/null
fi
test "$(
    docker container inspect \
        --format '{{.HostConfig.RestartPolicy.Name}}' \
        coffer-bootstrap-registry
)" = "unless-stopped"

horizon_base="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' \
        quay.io/openstack.kolla/horizon:2026.1-ubuntu-noble |
        grep -E '^quay\.io/openstack\.kolla/horizon@sha256:[0-9a-f]{64}$' |
        head -n 1
)"
skyline_base="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' \
        quay.io/openstack.kolla/skyline-console:2026.1-ubuntu-noble |
        grep -E '^quay\.io/openstack\.kolla/skyline-console@sha256:[0-9a-f]{64}$' |
        head -n 1
)"
test -n "${horizon_base}"
test -n "${skyline_base}"

temporary_directory="$(mktemp -d /home/ubuntu/coffer-ui-build.XXXXXX)"
cleanup() {
    rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT
install -m 0644 "${horizon_wheel}" \
    "${temporary_directory}/coffer_horizon-0.1.0-py3-none-any.whl"
install -m 0644 "${source_root}/ui/images/install_horizon.py" \
    "${temporary_directory}/install_horizon.py"
docker build \
    --network host \
    --build-arg "BASE_IMAGE=${horizon_base}" \
    --file "${source_root}/ui/images/horizon.Containerfile" \
    --tag localhost:5000/coffer-horizon:ui-preview \
    "${temporary_directory}"

rm -f -- \
    "${temporary_directory}/coffer_horizon-0.1.0-py3-none-any.whl" \
    "${temporary_directory}/install_horizon.py"
install -m 0644 "${skyline_wheel}" \
    "${temporary_directory}/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
docker build \
    --network host \
    --build-arg "BASE_IMAGE=${skyline_base}" \
    --file "${source_root}/ui/images/skyline-console.Containerfile" \
    --tag localhost:5000/coffer-skyline-console:ui-preview \
    "${temporary_directory}"

docker push localhost:5000/coffer-horizon:ui-preview >/dev/null
docker push localhost:5000/coffer-skyline-console:ui-preview >/dev/null
horizon_image="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' \
        localhost:5000/coffer-horizon:ui-preview |
        grep -E '^localhost:5000/coffer-horizon@sha256:[0-9a-f]{64}$' |
        head -n 1
)"
skyline_image="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' \
        localhost:5000/coffer-skyline-console:ui-preview |
        grep -E '^localhost:5000/coffer-skyline-console@sha256:[0-9a-f]{64}$' |
        head -n 1
)"
test -n "${horizon_image}"
test -n "${skyline_image}"

install -d -o root -g root -m 0750 "${contract_root}"
"${state_root}/venv/bin/python3" \
    "${source_root}/ui/images/write_contract.py" \
    --surface horizon \
    --artifact "${horizon_wheel}" \
    --image "${horizon_image}" \
    --base-image "${horizon_base}" \
    --output "${contract_root}/horizon-image.json"
"${state_root}/venv/bin/python3" \
    "${source_root}/ui/images/write_contract.py" \
    --surface skyline \
    --artifact "${skyline_wheel}" \
    --image "${skyline_image}" \
    --base-image "${skyline_base}" \
    --output "${contract_root}/skyline-image.json"
chown root:root "${contract_root}"/*.json
chmod 0640 "${contract_root}"/*.json

temporary_globals="$(mktemp /etc/kolla/.coffer-ui-images.XXXXXX)"
trap 'rm -f -- "${temporary_globals}"; cleanup' EXIT
printf '%s\n' \
    "---" \
    "coffer_horizon_image_full: \"${horizon_image}\"" \
    "coffer_horizon_fallback_image_full: \"${horizon_base}\"" \
    "coffer_skyline_console_image_full: \"${skyline_image}\"" \
    "coffer_skyline_console_fallback_image_full: \"${skyline_base}\"" \
    >"${temporary_globals}"
chmod 0644 "${temporary_globals}"
mv "${temporary_globals}" "${image_globals}"
trap cleanup EXIT
printf '%s\n' "coffer-ui-preview-images-v1" >"${marker}"
chmod 0600 "${marker}"
echo "Coffer runtime and immutable UI preview images prepared"
