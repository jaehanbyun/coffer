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
primary_management_address="192.168.252.11"
management_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
remote_public_key="/tmp/coffer-stage5-kolla.pub"
remote_inventory="/tmp/coffer-stage5-kolla-multinode"
remote_globals="/tmp/coffer-stage5-kolla-globals.yml"
local_public_key=

jump_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

cleanup() {
    local address

    if test -n "${local_public_key}"; then
        rm -f -- "${local_public_key}"
    fi
    for address in "${management_addresses[@]}"; do
        ssh "${jump_options[@]}" "ubuntu@${address}" \
            rm -f -- "${remote_public_key}" >/dev/null 2>&1 || true
    done
    ssh "${jump_options[@]}" \
        "ubuntu@${primary_management_address}" \
        rm -f -- "${remote_inventory}" "${remote_globals}" \
        >/dev/null 2>&1 || true
}
trap cleanup EXIT

ssh "${jump_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo env LC_ALL=C LANG=C bash -s key \
    <"${harness}/guest-prepare-kolla-primary.sh"

mkdir -p "${work}"
umask 077
local_public_key="$(mktemp "${work}/kolla-public-key.XXXXXX")"
ssh "${jump_options[@]}" \
    "ubuntu@${primary_management_address}" \
    cat /home/ubuntu/.ssh/coffer-stage5-kolla.pub \
    >"${local_public_key}"
test "$(wc -l <"${local_public_key}" | tr -d ' ')" -eq 1
grep -Eq \
    '^ssh-ed25519 [A-Za-z0-9+/=]+ coffer-stage5-kolla$' \
    "${local_public_key}"
ssh-keygen -l -f "${local_public_key}" >/dev/null

for index in "${!management_addresses[@]}"; do
    scp "${jump_options[@]}" "${local_public_key}" \
        "ubuntu@${management_addresses[${index}]}:${remote_public_key}"
    ssh "${jump_options[@]}" \
        "ubuntu@${management_addresses[${index}]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${hostnames[${index}]}" "${remote_public_key}" \
        <"${harness}/guest-authorize-kolla-controller.sh"
done

for index in "${!management_addresses[@]}"; do
    # Fixed key, known-hosts, user, address, and hostname expand locally.
    # shellcheck disable=SC2029
    actual_hostname="$(
        ssh "${jump_options[@]}" \
            "ubuntu@${primary_management_address}" \
            sudo -u ubuntu ssh \
            -i /home/ubuntu/.ssh/coffer-stage5-kolla \
            -o BatchMode=yes \
            -o ConnectTimeout=10 \
            -o StrictHostKeyChecking=accept-new \
            -o UserKnownHostsFile=/home/ubuntu/.ssh/coffer-stage5-known_hosts \
            "ubuntu@${management_addresses[${index}]}" hostname
    )"
    test "${actual_hostname}" = "${hostnames[${index}]}"
done

test -f "${work}/kolla-multinode"
scp "${jump_options[@]}" \
    "${work}/kolla-multinode" \
    "ubuntu@${primary_management_address}:${remote_inventory}"
scp "${jump_options[@]}" \
    "${harness}/kolla-globals.yml" \
    "ubuntu@${primary_management_address}:${remote_globals}"

ssh "${jump_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s install \
    "${remote_inventory}" "${remote_globals}" \
    <"${harness}/guest-prepare-kolla-primary.sh"

ssh "${jump_options[@]}" \
    "ubuntu@${primary_management_address}" \
    sudo -u ubuntu env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    /home/ubuntu/coffer-stage5/venv/bin/ansible \
    -i /etc/kolla/multinode control -m ping

for address in "${management_addresses[@]}"; do
    ssh "${jump_options[@]}" "ubuntu@${address}" \
        test ! -e "${remote_public_key}"
done
ssh "${jump_options[@]}" \
    "ubuntu@${primary_management_address}" \
    test ! -e "${remote_inventory}" -a ! -e "${remote_globals}"

cleanup
trap - EXIT
printf 'kolla_prepare controllers=3 deployment_key_recipients=3 source=pinned venv=ready passwords=owner-only tls=ready bootstrap=not-run\n'
