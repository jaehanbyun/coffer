#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|status|build} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|status|build)
        ;;
    *)
        echo "refusing an unknown Coffer update-image action" >&2
        exit 64
        ;;
esac
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
known_hosts="${root}/work/kolla-ha/known_hosts"
archive="${root}/work/kolla-ha/coffer-update-a6f476e.tar"
remote_guest="/tmp/coffer-stage5-build-update.sh"
remote_archive="/tmp/coffer-stage5-update-source.tar"
controller="192.168.252.11"
source_commit="a6f476e65f89048860309dc277406c96fd7fa0e7"
source_archive_sha256="7fcaeba415837c624b7618adeaf23be2be5eaa6269b4702be4795aa640c5684f"
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=9
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

"${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"

cleanup_local() {
    rm -f -- "${archive}"
}
cleanup_remote() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo rm -f -- "${remote_guest}" "${remote_archive}" \
        >/dev/null 2>&1 || true
}
trap 'cleanup_local; cleanup_remote' EXIT

if test "${action}" = build; then
    test "$(git -C "${root}" rev-parse "${source_commit}^{commit}")" = \
        "${source_commit}"
    mkdir -p "$(dirname "${archive}")"
    git -C "${root}" archive \
        --format=tar \
        --prefix=coffer/ \
        --output="${archive}" \
        "${source_commit}"
    test "$(
        shasum -a 256 "${archive}" | awk '{print $1}'
    )" = "${source_archive_sha256}"
    scp "${ssh_options[@]}" \
        "${harness}/guest-build-distribute-coffer-update.sh" \
        "ubuntu@${controller}:${remote_guest}"
    scp "${ssh_options[@]}" \
        "${archive}" \
        "ubuntu@${controller}:${remote_archive}"
    # All expanded remote paths are fixed allowlisted constants.
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
        bash "${remote_guest}" build "${remote_archive}"
else
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${action}" \
        <"${harness}/guest-build-distribute-coffer-update.sh"
fi

cleanup_local
cleanup_remote
trap - EXIT
"${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"
printf 'coffer_update_images action=%s result=passed runtime=unchanged publication=none\n' \
    "${action}"
