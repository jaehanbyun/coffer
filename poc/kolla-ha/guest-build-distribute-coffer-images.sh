#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {status|build}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    status|build)
        ;;
    *)
        echo "refusing an unknown Coffer image action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
owner_marker="${state_root}/images.owner"
complete_marker="${state_root}/images.complete"
profile_marker="${state_root}/production-profile.prepared"
lifecycle_root="${state_root}/lifecycle"
source_root="${state_root}/coffer-source"
build_root="${state_root}/image-build"
kolla_source="${build_root}/kolla-source"
build_venv="${build_root}/venv"
build_work="${build_root}/contexts"
build_logs="${build_root}/logs"
build_log="${build_logs}/build.log"
install_marker="${build_root}/INSTALL_COMPLETE"
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
deployment_known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"
source_commit="4f1ff7ddfd89d21f17ab7cbb531c335e85d94542"
kolla_commit="686c6d13dc1c31092b22c6c481e16a7329e935ea"
docker_sdk_version="7.2.0"
ubuntu_amd64_sha256="52df9b1ee71626e0088f7d400d5c6b5f7bb916f8f0c82b474289a4ece6cf3faf"
owner_value="coffer-stage5-images-v1 ${source_commit} ${kolla_commit}"
coffer_image="localhost/coffer:stage5"
registry_image="localhost/coffer-registry:stage5"
build_prefix="coffer-stage5-"
build_coffer_image="localhost/${build_prefix}coffer:stage5"
build_registry_image="localhost/${build_prefix}coffer-registry:stage5"
build_base_image="localhost/${build_prefix}base:stage5"
controller_hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
controller_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(uname -m)" = x86_64
systemctl is-active --quiet docker
test "$(stat -c '%U:%G:%a' "${deployment_key}")" = ubuntu:ubuntu:600
test "$(stat -c '%U:%G:%a' "${deployment_known_hosts}")" = ubuntu:ubuntu:644
test "$(stat -c '%U:%G:%a' "${profile_marker}")" = root:root:600
test "$(cat "${profile_marker}")" = coffer-stage5-production-profile-v3
for phase in bootstrap prechecks pull deploy reconfigure; do
    marker="${lifecycle_root}/${phase}.complete"
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
done

ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=9
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${deployment_known_hosts}"
)

run_on_controller() {
    local index="$1"
    shift

    if test "${index}" -eq 0; then
        "$@"
    else
        sudo -u ubuntu ssh "${ssh_options[@]}" \
            "ubuntu@${controller_addresses[${index}]}" \
            sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 "$@"
    fi
}

require_runtime_absent() {
    local index="$1"
    local snapshot

    snapshot="$(
        run_on_controller "${index}" bash -s -- \
            "${controller_hostnames[${index}]}" <<'REMOTE'
set -Eeuo pipefail
expected_hostname="$1"
test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(uname -m)" = x86_64
systemctl is-active --quiet docker
actual_containers="$(docker ps -a --format '{{.Names}}' | sort)"
expected_containers="$(
    printf '%s\n' \
        cron fluentd haproxy keepalived keystone keystone_fernet \
        keystone_ssh kolla_toolbox mariadb memcached proxysql rabbitmq |
        sort
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
for container in \
    coffer_api coffer_edge coffer_registry coffer_reconcile \
    bootstrap_coffer; do
    ! docker container inspect "${container}" >/dev/null 2>&1
done
for path in \
    /etc/kolla/config/coffer \
    /etc/kolla/coffer-globals.yml \
    /etc/kolla/coffer-api \
    /etc/kolla/coffer-edge \
    /etc/kolla/coffer-registry \
    /etc/kolla/coffer-reconcile \
    /etc/kolla/coffer-bootstrap; do
    test ! -e "${path}"
done
for port in 8787 8788 8789; do
    ! ss -H -lnt |
        awk '{print $4}' |
        grep -Eq "(^|[.:])${port}$"
done
printf 'host=%s runtime=absent containers=12\n' "${expected_hostname}"
REMOTE
    )"
    test "${snapshot}" = \
        "host=${controller_hostnames[${index}]} runtime=absent containers=12"
}

image_id() {
    local index="$1"
    local image="$2"
    local snapshot

    if snapshot="$(
        run_on_controller \
            "${index}" bash -s -- "${image}" 2>/dev/null <<'REMOTE'
set -Eeuo pipefail
docker image inspect --format '{{.Id}}' "$1"
REMOTE
    )"; then
        [[ "${snapshot}" =~ ^sha256:[0-9a-f]{64}$ ]]
        printf '%s\n' "${snapshot}"
    else
        printf 'absent\n'
    fi
}

validate_image() {
    local index="$1"
    local image="$2"
    local expected_user="$3"
    local snapshot

    snapshot="$(
        run_on_controller "${index}" bash -s -- \
            "${image}" "${expected_user}" <<'REMOTE'
set -Eeuo pipefail
image="$1"
expected_user="$2"
snapshot="$(
    docker image inspect \
        --format '{{.Id}} {{.Architecture}} {{.Os}} {{.Config.User}}' \
        "${image}"
)"
actual_user="${snapshot##* }"
test "${actual_user}" = "${expected_user}"
printf '%s\n' "${snapshot}"
REMOTE
    )"
    [[ "${snapshot}" =~ ^sha256:[0-9a-f]{64}\ amd64\ linux\ ${expected_user}$ ]]
    printf '%s\n' "${snapshot%% *}"
}

validate_source() {
    local path="$1"
    local commit="$2"
    local origin="$3"

    test -d "${path}/.git"
    test "$(git -C "${path}" rev-parse HEAD)" = "${commit}"
    test "$(git -C "${path}" remote get-url origin)" = "${origin}"
    test -z "$(git -C "${path}" status --porcelain --untracked-files=all)"
}

validate_owner() {
    test "$(stat -c '%U:%G:%a' "${owner_marker}")" = root:root:600
    test "$(cat "${owner_marker}")" = "${owner_value}"
}

validate_complete() {
    local coffer_id
    local index
    local registry_id

    validate_owner
    test "$(stat -c '%U:%G:%a' "${complete_marker}")" = root:root:600
    test "$(wc -l <"${complete_marker}" | tr -d ' ')" -eq 3
    grep -Fxq 'schema=coffer-stage5-images-v1' "${complete_marker}"
    coffer_id="$(sed -n 's/^coffer_id=//p' "${complete_marker}")"
    registry_id="$(sed -n 's/^registry_id=//p' "${complete_marker}")"
    [[ "${coffer_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
    [[ "${registry_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
    for index in "${!controller_addresses[@]}"; do
        test "$(validate_image "${index}" "${coffer_image}" coffer)" = \
            "${coffer_id}"
        test "$(validate_image "${index}" "${registry_image}" registry)" = \
            "${registry_id}"
        require_runtime_absent "${index}"
    done
    validate_source \
        "${source_root}" "${source_commit}" \
        https://github.com/jaehanbyun/coffer.git
    printf 'coffer_images state=complete controllers=3 coffer_id=%s registry_id=%s runtime=absent\n' \
        "${coffer_id}" "${registry_id}"
}

if test -f "${complete_marker}"; then
    validate_complete
    exit 0
fi

if test ! -e "${owner_marker}"; then
    test ! -e "${source_root}"
    test ! -e "${build_root}"
    for index in "${!controller_addresses[@]}"; do
        require_runtime_absent "${index}"
        test "$(image_id "${index}" "${coffer_image}")" = absent
        test "$(image_id "${index}" "${registry_image}")" = absent
    done
    if test "${action}" = status; then
        printf 'coffer_images state=absent controllers=3 runtime=absent mutation=none\n'
        exit 0
    fi
    printf '%s\n' "${owner_value}" >"${owner_marker}"
    chown root:root "${owner_marker}"
    chmod 0600 "${owner_marker}"
fi

validate_owner
if test "${action}" = status; then
    present=0
    for index in "${!controller_addresses[@]}"; do
        require_runtime_absent "${index}"
        if test "$(image_id "${index}" "${coffer_image}")" != absent; then
            present="$((present + 1))"
        fi
        if test "$(image_id "${index}" "${registry_image}")" != absent; then
            present="$((present + 1))"
        fi
    done
    printf 'coffer_images state=partial controllers=3 images_present=%s/6 runtime=absent mutation=none\n' \
        "${present}"
    exit 0
fi

for index in "${!controller_addresses[@]}"; do
    require_runtime_absent "${index}"
done

install -d -o root -g root -m 0700 "${build_root}" "${build_logs}"
if test ! -d "${source_root}/.git"; then
    GIT_TERMINAL_PROMPT=0 git clone \
        --filter=blob:none \
        https://github.com/jaehanbyun/coffer.git \
        "${source_root}"
    git -C "${source_root}" fetch --depth=1 origin "${source_commit}"
    git -C "${source_root}" checkout --detach "${source_commit}"
fi
validate_source \
    "${source_root}" "${source_commit}" \
    https://github.com/jaehanbyun/coffer.git

if test ! -d "${kolla_source}/.git"; then
    GIT_TERMINAL_PROMPT=0 git clone \
        --filter=blob:none \
        https://opendev.org/openstack/kolla \
        "${kolla_source}"
    git -C "${kolla_source}" fetch --depth=1 origin "${kolla_commit}"
    git -C "${kolla_source}" checkout --detach "${kolla_commit}"
fi
validate_source \
    "${kolla_source}" "${kolla_commit}" \
    https://opendev.org/openstack/kolla

if test ! -x "${build_venv}/bin/python3"; then
    python3 -m venv "${build_venv}"
fi
if test ! -f "${install_marker}"; then
    "${build_venv}/bin/python3" -m pip install \
        --disable-pip-version-check --no-cache-dir \
        "${kolla_source}" "docker==${docker_sdk_version}"
    "${build_venv}/bin/python3" -c 'import docker, kolla'
    printf '%s\n' "${kolla_commit}" >"${install_marker}"
    chmod 0600 "${install_marker}"
fi
test "$(stat -c '%U:%G:%a' "${install_marker}")" = root:root:600
test "$(cat "${install_marker}")" = "${kolla_commit}"
test -x "${build_venv}/bin/kolla-build"
test "$(
    "${build_venv}/bin/python3" -c \
        'import docker; print(docker.__version__)'
)" = "${docker_sdk_version}"

install -o root -g root -m 0600 /dev/null "${build_log}"
if ! timeout 5400 "${build_venv}/bin/kolla-build" \
    --engine docker \
    --config-file "${source_root}/poc/production-images/kolla-build.conf" \
    --docker-dir "${source_root}/docker" \
    --locals-base "${source_root}" \
    --work-dir "${build_work}" \
    --logs-dir "${build_logs}" \
    --base ubuntu \
    --base-image ubuntu \
    --base-tag "24.04@sha256:${ubuntu_amd64_sha256}" \
    --base-arch x86_64 \
    --debian-arch amd64 \
    --platform linux/amd64 \
    --openstack-release 2026.1 \
    --namespace localhost \
    --image-name-prefix "${build_prefix}" \
    --tag stage5 \
    --threads 1 \
    '^(coffer|coffer-registry)$' \
    >"${build_log}" 2>&1; then
    echo "Coffer image build failed; owner-only log retained on controller-1" >&2
    exit 30
fi

validate_image 0 "${build_coffer_image}" coffer >/dev/null
validate_image 0 "${build_registry_image}" registry >/dev/null
docker tag "${build_coffer_image}" "${coffer_image}"
docker tag "${build_registry_image}" "${registry_image}"
for command in coffer-api coffer-edge coffer-reconcile coffer-bootstrap; do
    docker run --rm --pull=never --entrypoint "${command}" \
        "${coffer_image}" --help >/dev/null
done
docker run --rm --pull=never --entrypoint registry \
    "${registry_image}" --version |
    grep -Fq '3.1.1'

coffer_id="$(validate_image 0 "${coffer_image}" coffer)"
registry_id="$(validate_image 0 "${registry_image}" registry)"
for index in 1 2; do
    node_coffer_id="$(image_id "${index}" "${coffer_image}")"
    node_registry_id="$(image_id "${index}" "${registry_image}")"
    if test "${node_coffer_id}" != "${coffer_id}" ||
        test "${node_registry_id}" != "${registry_id}"; then
        if ! docker save "${coffer_image}" "${registry_image}" |
            sudo -u ubuntu timeout 1800 ssh "${ssh_options[@]}" \
                "ubuntu@${controller_addresses[${index}]}" \
                sudo docker load >/dev/null; then
            echo "Coffer image transfer failed; partial owned state retained" >&2
            exit 31
        fi
    fi
    test "$(validate_image "${index}" "${coffer_image}" coffer)" = \
        "${coffer_id}"
    test "$(validate_image "${index}" "${registry_image}" registry)" = \
        "${registry_id}"
done

docker image rm "${build_coffer_image}" "${build_registry_image}" \
    "${build_base_image}" >/dev/null

temporary_marker="$(mktemp "${state_root}/images.complete.XXXXXX")"
cleanup_marker() {
    rm -f -- "${temporary_marker}"
}
trap cleanup_marker EXIT
{
    printf 'schema=coffer-stage5-images-v1\n'
    printf 'coffer_id=%s\n' "${coffer_id}"
    printf 'registry_id=%s\n' "${registry_id}"
} >"${temporary_marker}"
chown root:root "${temporary_marker}"
chmod 0600 "${temporary_marker}"
mv -f -- "${temporary_marker}" "${complete_marker}"
trap - EXIT

validate_complete
