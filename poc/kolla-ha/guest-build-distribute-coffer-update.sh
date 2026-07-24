#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -lt 1 ]]; then
    echo "usage: $0 {preflight|status|build} [SOURCE_ARCHIVE]" >&2
    exit 64
fi

action="$1"
case "${action}" in
    preflight|status)
        test "$#" -eq 1 || exit 64
        ;;
    build)
        test "$#" -eq 2 || exit 64
        ;;
    *)
        echo "refusing an unknown Coffer update-image action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
image_marker="${state_root}/images.complete"
update_root="${state_root}/coffer-update-images"
owner_marker="${update_root}/owner"
complete_marker="${update_root}/complete"
source_root="${update_root}/source"
build_root="${update_root}/build"
build_work="${build_root}/contexts"
build_logs="${build_root}/logs"
build_log="${build_logs}/build.log"
kolla_source="${state_root}/image-build/kolla-source"
build_venv="${state_root}/image-build/venv"
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"
source_commit="a6f476e65f89048860309dc277406c96fd7fa0e7"
source_archive_sha256="7fcaeba415837c624b7618adeaf23be2be5eaa6269b4702be4795aa640c5684f"
quota_sha256="2c20f6d8e7fe27a8b487d1082c7b30ac600d0243eaa311228da8fc7403a90c9e"
quota_import_sha256="3ada8b907e7c9144f733f97a9f17974a796ad73090b955f93ae2166f47afa117"
kolla_commit="686c6d13dc1c31092b22c6c481e16a7329e935ea"
ubuntu_amd64_sha256="52df9b1ee71626e0088f7d400d5c6b5f7bb916f8f0c82b474289a4ece6cf3faf"
update_image="localhost/coffer:stage5-quota-retry"
build_prefix="coffer-stage5-update-"
build_image="localhost/${build_prefix}coffer:quota-retry"
owner_value="coffer-stage5-update-images-v1 ${source_commit} ${source_archive_sha256}"
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
test "$(stat -c '%U:%G:%a' "${known_hosts}")" = ubuntu:ubuntu:644
test "$(stat -c '%U:%G:%a' "${image_marker}")" = root:root:600
grep -Fxq 'schema=coffer-stage5-images-v1' "${image_marker}"
current_image_id="$(sed -n 's/^coffer_id=//p' "${image_marker}")"
registry_image_id="$(sed -n 's/^registry_id=//p' "${image_marker}")"
[[ "${current_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "${registry_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]

ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=9
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
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

image_id() {
    local index="$1"
    local image="$2"
    local result

    if result="$(
        run_on_controller "${index}" \
            docker image inspect --format '{{.Id}}' "${image}" 2>/dev/null
    )"; then
        [[ "${result}" =~ ^sha256:[0-9a-f]{64}$ ]]
        printf '%s\n' "${result}"
    else
        printf 'absent\n'
    fi
}

require_runtime_unchanged() {
    local index="$1"
    local result

    if ! result="$(
        run_on_controller "${index}" bash -s -- \
            "${controller_hostnames[${index}]}" \
            "${current_image_id}" "${registry_image_id}" <<'REMOTE'
set -Eeuo pipefail
expected_hostname="$1"
current_image_id="$2"
registry_image_id="$3"
test "$(hostname)" = "${expected_hostname}"
for container in coffer_api coffer_edge coffer_registry; do
    test "$(docker inspect -f '{{.State.Running}}' "${container}")" = true
    test "$(docker inspect -f '{{.State.Health.Status}}' "${container}")" = healthy
done
test "$(docker inspect -f '{{.Image}}' coffer_api)" = "${current_image_id}"
test "$(docker inspect -f '{{.Image}}' coffer_edge)" = "${current_image_id}"
test "$(docker inspect -f '{{.Image}}' coffer_registry)" = "${registry_image_id}"
printf 'host=%s runtime=current\n' "${expected_hostname}"
REMOTE
    )"; then
        return 1
    fi
    test "${result}" = \
        "host=${controller_hostnames[${index}]} runtime=current"
}

validate_update_image() {
    local index="$1"
    local result

    if ! result="$(
        run_on_controller "${index}" bash -s -- \
            "${update_image}" "${quota_sha256}" \
            "${quota_import_sha256}" <<'REMOTE'
set -Eeuo pipefail
image="$1"
quota_sha256="$2"
quota_import_sha256="$3"
metadata="$(
    docker image inspect \
        --format '{{.Id}} {{.Architecture}} {{.Os}} {{.Config.User}}' \
        "${image}"
)"
[[ "${metadata}" =~ ^sha256:[0-9a-f]{64}\ amd64\ linux\ coffer$ ]]
snapshot="$(
    docker run --rm --pull=never -i \
        --entrypoint /var/lib/kolla/venv/bin/python3 \
        "${image}" - "${quota_sha256}" "${quota_import_sha256}" <<'PY'
from pathlib import Path
import hashlib
import sys

import coffer.quota as quota

root = Path(quota.__file__).parent
actual = (
    hashlib.sha256((root / "quota.py").read_bytes()).hexdigest(),
    hashlib.sha256((root / "quota_import.py").read_bytes()).hexdigest(),
)
if actual != tuple(sys.argv[1:]):
    raise SystemExit("installed quota source digest changed")
if quota.MAX_TRANSACTION_ATTEMPTS != 3:
    raise SystemExit("quota transaction attempt bound changed")
print("retry=3 source=verified")
PY
)"
test "${snapshot}" = 'retry=3 source=verified'
printf '%s\n' "${metadata%% *}"
REMOTE
    )"; then
        return 1
    fi
    [[ "${result}" =~ ^sha256:[0-9a-f]{64}$ ]]
    printf '%s\n' "${result}"
}

validate_complete() {
    local expected_update_id
    local index

    test "$(stat -c '%U:%G:%a' "${owner_marker}")" = root:root:600
    test "$(cat "${owner_marker}")" = "${owner_value}"
    test "$(stat -c '%U:%G:%a' "${complete_marker}")" = root:root:600
    grep -Fxq 'schema=coffer-stage5-update-images-v1' "${complete_marker}"
    grep -Fxq "source_commit=${source_commit}" "${complete_marker}"
    grep -Fxq "current_image_id=${current_image_id}" "${complete_marker}"
    expected_update_id="$(sed -n 's/^update_image_id=//p' "${complete_marker}")"
    [[ "${expected_update_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
    test "${expected_update_id}" != "${current_image_id}"
    for index in "${!controller_addresses[@]}"; do
        require_runtime_unchanged "${index}"
        test "$(validate_update_image "${index}")" = "${expected_update_id}"
    done
    printf 'coffer_update_images state=complete controllers=3 current_id=%s update_id=%s runtime=unchanged\n' \
        "${current_image_id}" "${expected_update_id}"
}

validate_empty_partial_marker() {
    test "$(stat -c '%U:%G:%a' "${complete_marker}")" = root:root:600
    test "$(wc -l <"${complete_marker}" | tr -d ' ')" -eq 4
    grep -Fxq 'schema=coffer-stage5-update-images-v1' "${complete_marker}"
    grep -Fxq "source_commit=${source_commit}" "${complete_marker}"
    grep -Fxq "current_image_id=${current_image_id}" "${complete_marker}"
    grep -Fxq 'update_image_id=' "${complete_marker}"
}

for index in "${!controller_addresses[@]}"; do
    require_runtime_unchanged "${index}"
done

if test -e "${complete_marker}"; then
    recorded_update_id="$(
        sed -n 's/^update_image_id=//p' "${complete_marker}"
    )"
    if [[ "${recorded_update_id}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        validate_complete
        exit 0
    fi
    test "${action}" = build
    validate_empty_partial_marker
fi

if test "${action}" = preflight; then
    test ! -e "${update_root}"
    for index in "${!controller_addresses[@]}"; do
        test "$(image_id "${index}" "${update_image}")" = absent
    done
    printf 'coffer_update_images state=clean controllers=3 runtime=unchanged mutation=none\n'
    exit 0
fi

if test "${action}" = status; then
    present=0
    for index in "${!controller_addresses[@]}"; do
        if test "$(image_id "${index}" "${update_image}")" != absent; then
            present="$((present + 1))"
        fi
    done
    printf 'coffer_update_images state=partial controllers=%s/3 runtime=unchanged mutation=none\n' \
        "${present}"
    exit 0
fi

archive="$2"
test -f "${archive}"
test "$(
    sha256sum "${archive}" | awk '{print $1}'
)" = "${source_archive_sha256}"
test -z "$(
    tar -tf "${archive}" |
        awk '
            $0 !~ /^coffer\// ||
            $0 ~ /(^|\/)\.\.(\/|$)/ ||
            $0 ~ /^\/|\/\// {print}
        '
)"
test -z "$(tar -tvf "${archive}" | awk '$1 ~ /^l/ {print}')"

install -d -o root -g root -m 0700 \
    "${update_root}" "${build_root}" "${build_logs}"
if test ! -e "${owner_marker}"; then
    printf '%s\n' "${owner_value}" >"${owner_marker}"
    chown root:root "${owner_marker}"
    chmod 0600 "${owner_marker}"
fi
test "$(stat -c '%U:%G:%a' "${owner_marker}")" = root:root:600
test "$(cat "${owner_marker}")" = "${owner_value}"

if test ! -d "${source_root}"; then
    temporary_source="$(mktemp -d "${update_root}/source.XXXXXX")"
    cleanup_source() {
        if [[ "${temporary_source}" == "${update_root}"/source.* ]]; then
            rm -rf -- "${temporary_source}"
        fi
    }
    trap cleanup_source EXIT
    tar -xf "${archive}" -C "${temporary_source}"
    test "$(
        sha256sum "${temporary_source}/coffer/src/coffer/quota.py" |
            awk '{print $1}'
    )" = "${quota_sha256}"
    test "$(
        sha256sum "${temporary_source}/coffer/src/coffer/quota_import.py" |
            awk '{print $1}'
    )" = "${quota_import_sha256}"
    mv "${temporary_source}/coffer" "${source_root}"
    cleanup_source
    trap - EXIT
fi
test "$(
    sha256sum "${source_root}/src/coffer/quota.py" | awk '{print $1}'
)" = "${quota_sha256}"
test "$(
    sha256sum "${source_root}/src/coffer/quota_import.py" | awk '{print $1}'
)" = "${quota_import_sha256}"
test "$(git -C "${kolla_source}" rev-parse HEAD)" = "${kolla_commit}"
test -x "${build_venv}/bin/kolla-build"

if test "$(image_id 0 "${update_image}")" = absent; then
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
        --tag quota-retry \
        --threads 1 \
        '^coffer$' \
        >"${build_log}" 2>&1; then
        echo "Coffer update image build failed; owner-only log retained" >&2
        exit 30
    fi
    docker tag "${build_image}" "${update_image}"
fi
update_image_id="$(validate_update_image 0)"
[[ "${update_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
for index in 1 2; do
    if test "$(image_id "${index}" "${update_image}")" != "${update_image_id}"; then
        docker save "${update_image}" |
            sudo -u ubuntu timeout 1800 ssh "${ssh_options[@]}" \
                "ubuntu@${controller_addresses[${index}]}" \
                sudo docker load >/dev/null
    fi
    test "$(validate_update_image "${index}")" = "${update_image_id}"
done

temporary_marker="$(mktemp "${update_root}/complete.XXXXXX")"
{
    printf 'schema=coffer-stage5-update-images-v1\n'
    printf 'source_commit=%s\n' "${source_commit}"
    printf 'current_image_id=%s\n' "${current_image_id}"
    printf 'update_image_id=%s\n' "${update_image_id}"
} >"${temporary_marker}"
chown root:root "${temporary_marker}"
chmod 0600 "${temporary_marker}"
mv -f -- "${temporary_marker}" "${complete_marker}"
validate_complete
