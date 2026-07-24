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
        echo "refusing an unknown Coffer companion action" >&2
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
storage="192.168.252.31"
complete_marker="/home/ubuntu/coffer-stage5/companion.prepared"
inputs_marker="/home/ubuntu/coffer-stage5/companion.inputs-prepared"
remote_prepare="/tmp/coffer-stage5-prepare-companion.sh"
remote_export="/tmp/coffer-stage5-export-rgw.py"
remote_globals="/tmp/coffer-stage5-coffer-globals.yml"
remote_archive="/tmp/coffer-stage5-rgw-inputs.tar"

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

cleanup() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo rm -f -- \
        "${remote_prepare}" "${remote_globals}" "${remote_archive}" \
        >/dev/null 2>&1 || true
    ssh "${ssh_options[@]}" "ubuntu@${storage}" \
        sudo rm -f -- "${remote_export}" >/dev/null 2>&1 || true
}

assert_no_temporary_residue() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo test ! -e "${remote_prepare}" \
        -a ! -e "${remote_globals}" \
        -a ! -e "${remote_archive}"
    ssh "${ssh_options[@]}" "ubuntu@${storage}" \
        sudo test ! -e "${remote_export}"
}

if test "${action}" = status; then
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- status \
        <"${harness}/guest-prepare-coffer-companion.sh"
    if ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo test -f "${inputs_marker}"; then
        "${harness}/preflight-coffer-ha.sh" ready "${ssh_target}"
    else
        "${harness}/build-distribute-coffer-images.sh" status "${ssh_target}"
    fi
    assert_no_temporary_residue
    printf 'coffer_companion action=status result=passed temporary_residue=none\n'
    exit 0
fi

if ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo test -f "${complete_marker}"; then
    "${harness}/preflight-coffer-ha.sh" ready "${ssh_target}"
    assert_no_temporary_residue
    printf 'coffer_companion action=prepare result=passed idempotent=yes\n'
    exit 0
fi

trap cleanup EXIT

if ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo test -f "${inputs_marker}"; then
    "${harness}/preflight-coffer-ha.sh" ready "${ssh_target}"
    scp "${ssh_options[@]}" \
        "${harness}/guest-prepare-coffer-companion.sh" \
        "ubuntu@${controller}:${remote_prepare}"
else
    "${harness}/build-distribute-coffer-images.sh" status "${ssh_target}"
    scp "${ssh_options[@]}" \
        "${harness}/guest-prepare-coffer-companion.sh" \
        "ubuntu@${controller}:${remote_prepare}"
    scp "${ssh_options[@]}" \
        "${harness}/coffer-globals.yml" \
        "ubuntu@${controller}:${remote_globals}"
    scp "${ssh_options[@]}" \
        "${harness}/guest-export-coffer-rgw-inputs.py" \
        "ubuntu@${storage}:${remote_export}"
    # All expanded remote paths are fixed allowlisted constants.
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" "ubuntu@${storage}" \
        sudo python3 "${remote_export}" |
        ssh "${ssh_options[@]}" "ubuntu@${controller}" \
            "sudo sh -c 'umask 077; cat > ${remote_archive}'"
    # All expanded remote paths are fixed allowlisted constants.
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
        bash "${remote_prepare}" prepare "${remote_globals}" "${remote_archive}"
fi

"${harness}/preflight-coffer-ha.sh" ready "${ssh_target}"
ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    bash "${remote_prepare}" complete
"${harness}/preflight-coffer-ha.sh" ready "${ssh_target}"

cleanup
trap - EXIT
assert_no_temporary_residue

printf 'coffer_companion action=prepare result=passed groups=4 hosts=3 inputs=owner-only runtime=absent\n'
