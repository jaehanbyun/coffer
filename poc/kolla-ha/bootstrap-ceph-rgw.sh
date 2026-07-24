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
work="${root}/work/kolla-ha"
known_hosts="${work}/known_hosts"
primary_management_address="192.168.252.31"
management_addresses=(
    192.168.252.31
    192.168.252.32
    192.168.252.33
)
ingress_vip="192.168.253.30"
ca_local_path="${work}/rgw-ingress-ca.crt"

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
    <"${harness}/guest-bootstrap-ceph-rgw.sh"

vip_owner_count=0
for address in "${management_addresses[@]}"; do
    node_vip_count="$(
        ssh "${ssh_options[@]}" "ubuntu@${address}" \
            ip -j address show |
            jq --arg vip "${ingress_vip}" \
                '[.[].addr_info[] | select(.local == $vip)] | length'
    )"
    test "${node_vip_count}" -le 1
    vip_owner_count="$((vip_owner_count + node_vip_count))"
done
test "${vip_owner_count}" -eq 1

mkdir -p "${work}"
umask 077
temporary_ca="$(mktemp "${work}/rgw-ingress-ca.crt.tmp.XXXXXX")"
cleanup() {
    rm -f -- "${temporary_ca}"
}
trap cleanup EXIT
ssh "${ssh_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo cat -- /etc/ceph/coffer-stage5-ingress/ca.crt >"${temporary_ca}"
openssl x509 -in "${temporary_ca}" -noout -checkend 86400
chmod 0644 "${temporary_ca}"
mv -f -- "${temporary_ca}" "${ca_local_path}"
trap - EXIT

printf 'ceph_rgw vip_owners=1 public_ca=%s\n' "${ca_local_path}"
