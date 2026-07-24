#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 <ssh-target>" >&2
    exit 64
fi

ssh_target="$1"
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
known_hosts="${root}/work/kolla-ha/known_hosts"
primary_management_address="192.168.252.31"
secondary_management_addresses=(
    192.168.252.32
    192.168.252.33
)
remote_helper="/tmp/coffer-stage5-s3.py"

ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

scp "${ssh_options[@]}" \
    "${harness}/guest-stage5-s3.py" \
    "ubuntu@${primary_management_address}:${remote_helper}"

cleanup() {
    ssh "${ssh_options[@]}" \
        "ubuntu@${primary_management_address}" \
        rm -f -- "${remote_helper}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

ssh "${ssh_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo env LC_ALL=C LANG=C bash -s -- "${remote_helper}" \
    <"${harness}/guest-provision-ceph-s3.sh"

for address in "${secondary_management_addresses[@]}"; do
    ssh "${ssh_options[@]}" "ubuntu@${address}" \
        sudo test ! -e /etc/coffer-stage5-rgw
done

cleanup
trap - EXIT
printf 'ceph_s3 credential_recipients=1 secondary_residue=0\n'
