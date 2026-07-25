#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {status|cleanup} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    status|cleanup)
        ;;
    *)
        echo "refusing an unknown Ceph S3 cleanup action" >&2
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
primary_management_address="192.168.252.31"
secondary_management_addresses=(
    192.168.252.32
    192.168.252.33
)
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

companion_status="$(
    "${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"
)"
printf '%s\n' "${companion_status}"
if test "${action}" = cleanup; then
    grep -Fq \
        'coffer_companion_lifecycle state=stopped ' \
        <<<"${companion_status}"
fi

ssh "${ssh_options[@]}" "ubuntu@${primary_management_address}" \
    sudo env LC_ALL=C LANG=C bash -s -- "${action}" \
    <"${harness}/guest-cleanup-ceph-s3.sh"

for address in "${secondary_management_addresses[@]}"; do
    ssh "${ssh_options[@]}" "ubuntu@${address}" \
        sudo test ! -e /etc/coffer-stage5-rgw
done

if test "${action}" = cleanup; then
    ssh "${ssh_options[@]}" "ubuntu@${primary_management_address}" \
        sudo env LC_ALL=C LANG=C bash -s -- status \
        <"${harness}/guest-cleanup-ceph-s3.sh"
fi

printf 'ceph_s3_cleanup action=%s result=passed secondary_residue=0\n' \
    "${action}"
