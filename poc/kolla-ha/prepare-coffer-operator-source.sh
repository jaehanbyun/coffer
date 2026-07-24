#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {status|prepare} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    status|prepare)
        ;;
    *)
        echo "refusing an unknown Coffer operator-source action" >&2
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
controller="192.168.252.11"
remote_guest="/tmp/coffer-stage5-prepare-operator-source.sh"
remote_config="/tmp/coffer-stage5-operator-config.yml"
remote_template="/tmp/coffer-stage5-bootstrap-config.json.j2"

mkdir -p "$(dirname "${known_hosts}")"
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

assert_no_temporary_residue() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo test ! -e "${remote_guest}" \
        -a ! -e "${remote_config}" \
        -a ! -e "${remote_template}"
}

if test "${action}" = status; then
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- status \
        <"${harness}/guest-prepare-coffer-operator-source.sh"
    assert_no_temporary_residue
    printf 'coffer_operator_source action=status result=passed temporary_residue=none\n'
    exit 0
fi

cleanup() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo rm -f -- \
        "${remote_guest}" "${remote_config}" "${remote_template}" \
        >/dev/null 2>&1 || true
}
trap cleanup EXIT

scp "${ssh_options[@]}" \
    "${harness}/guest-prepare-coffer-operator-source.sh" \
    "ubuntu@${controller}:${remote_guest}"
scp "${ssh_options[@]}" \
    "${root}/ansible/roles/coffer/tasks/config.yml" \
    "ubuntu@${controller}:${remote_config}"
scp "${ssh_options[@]}" \
    "${root}/docker/config/coffer-bootstrap.json.j2" \
    "ubuntu@${controller}:${remote_template}"
# All expanded remote paths are fixed allowlisted constants.
# shellcheck disable=SC2029
ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    bash "${remote_guest}" prepare "${remote_config}" "${remote_template}"

cleanup
trap - EXIT
assert_no_temporary_residue
"$0" status "${ssh_target}"
printf 'coffer_operator_source action=prepare result=passed runtime=unchanged\n'
