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
secondary_addresses=(192.168.252.32 192.168.252.33)
secondary_hostnames=(
    coffer-rgw-ha-stage5-storage-2
    coffer-rgw-ha-stage5-storage-3
)

ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

ssh "${ssh_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo env LC_ALL=C LANG=C bash -s \
    <"${harness}/guest-bootstrap-ceph-primary.sh"

cephadm_public_key="$(
    ssh "${ssh_options[@]}" \
        "ubuntu@${primary_management_address}" \
        sudo cephadm shell -- ceph cephadm get-pub-key </dev/null
)"
test "$(wc -l <<<"${cephadm_public_key}")" -eq 1
if ! grep -Eq \
    '^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( .*)?$' \
    <<<"${cephadm_public_key}"; then
    echo "refusing an invalid cephadm public key" >&2
    exit 20
fi
public_key_base64="$(
    printf '%s\n' "${cephadm_public_key}" | base64 | tr -d '\n'
)"

for index in "${!secondary_addresses[@]}"; do
    ssh "${ssh_options[@]}" \
        "ubuntu@${secondary_addresses[$index]}" \
        sudo bash -s -- \
        "${secondary_hostnames[$index]}" "${public_key_base64}" \
        <"${harness}/guest-authorize-cephadm.sh"
done

ssh "${ssh_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo env LC_ALL=C LANG=C bash -s \
    <"${harness}/guest-adopt-ceph-hosts.sh"
