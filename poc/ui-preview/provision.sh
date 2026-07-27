#!/usr/bin/env bash

set -euo pipefail

action="${1:-}"
domain_name="coffer-ui-preview-1"
pool_name="coffer-rgw"
root_volume="${domain_name}-root.qcow2"
seed_volume="${domain_name}-seed.iso"
base_volume="${domain_name}-ubuntu-20260725.qcow2"
base_url="https://cloud-images.ubuntu.com/noble/20260725/noble-server-cloudimg-amd64.img"
base_sha256="d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac"
management_mac="52:54:00:cf:fe:27"
external_mac="52:54:00:cf:fe:28"
management_address="192.168.122.204"
internal_vip="192.168.122.205"
external_vip="192.168.122.221"
libvirt_uri="qemu:///system"

virsh_command=(virsh --connect "${libvirt_uri}")

status() {
    "${virsh_command[@]}" dominfo "${domain_name}"
    "${virsh_command[@]}" domifaddr "${domain_name}" --source arp || true
    "${virsh_command[@]}" domblklist "${domain_name}" --details
}

stop() {
    if ! "${virsh_command[@]}" dominfo "${domain_name}" >/dev/null 2>&1; then
        echo "${domain_name} is absent" >&2
        exit 69
    fi
    if "${virsh_command[@]}" domstate "${domain_name}" |
        grep -qvE 'shut off|shutoff'; then
        "${virsh_command[@]}" shutdown "${domain_name}"
    fi
}

start() {
    if ! "${virsh_command[@]}" dominfo "${domain_name}" >/dev/null 2>&1; then
        echo "${domain_name} is absent" >&2
        exit 69
    fi
    if "${virsh_command[@]}" domstate "${domain_name}" |
        grep -qE 'shut off|shutoff'; then
        "${virsh_command[@]}" start "${domain_name}"
    fi
    "${virsh_command[@]}" autostart --disable "${domain_name}"
}

destroy() {
    if "${virsh_command[@]}" dominfo "${domain_name}" >/dev/null 2>&1; then
        if "${virsh_command[@]}" domstate "${domain_name}" |
            grep -qvE 'shut off|shutoff'; then
            "${virsh_command[@]}" destroy "${domain_name}"
        fi
        "${virsh_command[@]}" undefine "${domain_name}"
    fi

    for volume in "${seed_volume}" "${root_volume}" "${base_volume}"; do
        if "${virsh_command[@]}" vol-info \
            "${volume}" --pool "${pool_name}" >/dev/null 2>&1; then
            "${virsh_command[@]}" vol-delete \
                "${volume}" --pool "${pool_name}"
        fi
    done
}

assert_address_free() {
    local address="$1"
    if ping -c 1 -W 1 "${address}" >/dev/null 2>&1; then
        echo "planned preview address ${address} is already responding" >&2
        exit 73
    fi
    if "${virsh_command[@]}" net-dumpxml default |
        grep -Fq "${address}"; then
        echo "planned preview address ${address} is reserved by libvirt" >&2
        exit 73
    fi
}

create() {
    if "${virsh_command[@]}" dominfo "${domain_name}" >/dev/null 2>&1; then
        echo "${domain_name} already exists" >&2
        exit 73
    fi
    for volume in "${root_volume}" "${seed_volume}" "${base_volume}"; do
        if "${virsh_command[@]}" vol-info \
            "${volume}" --pool "${pool_name}" >/dev/null 2>&1; then
            echo "${volume} already exists" >&2
            exit 73
        fi
    done
    for address in \
        "${management_address}" "${internal_vip}" "${external_vip}"; do
        assert_address_free "${address}"
    done
    if "${virsh_command[@]}" list --all --name |
        while IFS= read -r existing_domain; do
            test -n "${existing_domain}" || continue
            "${virsh_command[@]}" dumpxml "${existing_domain}" 2>/dev/null || true
        done |
        grep -qE "${management_mac}|${external_mac}"; then
        echo "planned preview MAC is already used by a libvirt domain" >&2
        exit 73
    fi

    authorized_key_count="$(
        awk '!/^#/ && NF {count += 1} END {print count + 0}' \
            "${HOME}/.ssh/authorized_keys"
    )"
    if [[ "${authorized_key_count}" -eq 0 ]]; then
        echo "no public SSH key is available for the preview guest" >&2
        exit 77
    fi

    temporary_directory="$(mktemp -d)"
    cleanup_temporary() {
        rm -rf -- "${temporary_directory}"
    }
    cleanup_partial() {
        cleanup_temporary
        destroy
    }
    trap cleanup_partial ERR INT TERM
    trap cleanup_temporary EXIT

    curl --fail --location --silent --show-error \
        --output "${temporary_directory}/ubuntu.img" "${base_url}"
    printf '%s  %s\n' \
        "${base_sha256}" "${temporary_directory}/ubuntu.img" |
        sha256sum --check --strict --status

    cat >"${temporary_directory}/meta-data" <<EOF
instance-id: ${domain_name}
local-hostname: ${domain_name}
EOF
    cat >"${temporary_directory}/user-data" <<EOF
#cloud-config
hostname: ${domain_name}
manage_etc_hosts: true
users:
  - default
  - name: ubuntu
    groups: [adm, sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
EOF
    awk '!/^#/ && NF {print "      - " $0}' \
        "${HOME}/.ssh/authorized_keys" \
        >>"${temporary_directory}/user-data"
    cat >>"${temporary_directory}/user-data" <<EOF
ssh_pwauth: false
disable_root: true
package_update: false
packages:
  - qemu-guest-agent
runcmd:
  - [systemctl, enable, --now, qemu-guest-agent]
EOF
    cat >"${temporary_directory}/network-config" <<EOF
version: 2
ethernets:
  ens3:
    match:
      macaddress: "${management_mac}"
    set-name: ens3
    dhcp4: false
    addresses:
      - ${management_address}/24
    routes:
      - to: default
        via: 192.168.122.1
    nameservers:
      addresses: [1.1.1.1, 8.8.8.8]
  ens4:
    match:
      macaddress: "${external_mac}"
    set-name: ens4
    dhcp4: false
    optional: true
EOF
    cloud-localds \
        --network-config="${temporary_directory}/network-config" \
        "${temporary_directory}/seed.iso" \
        "${temporary_directory}/user-data" \
        "${temporary_directory}/meta-data"

    base_size="$(
        qemu-img info --output=json "${temporary_directory}/ubuntu.img" |
            python3 -c \
                'import json, sys; print(json.load(sys.stdin)["virtual-size"])'
    )"
    "${virsh_command[@]}" vol-create-as \
        "${pool_name}" "${base_volume}" "${base_size}" --format qcow2
    "${virsh_command[@]}" vol-upload \
        "${base_volume}" "${temporary_directory}/ubuntu.img" \
        --pool "${pool_name}"
    "${virsh_command[@]}" pool-refresh "${pool_name}"
    "${virsh_command[@]}" vol-create-as \
        "${pool_name}" "${root_volume}" 220G \
        --format qcow2 \
        --backing-vol "${base_volume}" \
        --backing-vol-format qcow2
    seed_size="$(stat -c %s "${temporary_directory}/seed.iso")"
    "${virsh_command[@]}" vol-create-as \
        "${pool_name}" "${seed_volume}" "${seed_size}" --format raw
    "${virsh_command[@]}" vol-upload \
        "${seed_volume}" "${temporary_directory}/seed.iso" \
        --pool "${pool_name}"

    virt-install \
        --connect "${libvirt_uri}" \
        --name "${domain_name}" \
        --memory 40960 \
        --vcpus 8 \
        --cpu host-passthrough \
        --os-variant ubuntu24.04 \
        --import \
        --disk "vol=${pool_name}/${root_volume},bus=virtio,cache=none,discard=unmap" \
        --disk "vol=${pool_name}/${seed_volume},device=cdrom,bus=sata" \
        --network "network=default,model=virtio,mac=${management_mac}" \
        --network "network=default,model=virtio,mac=${external_mac}" \
        --rng /dev/urandom \
        --graphics none \
        --noautoconsole

    "${virsh_command[@]}" autostart --disable "${domain_name}"
    trap - ERR INT TERM
    status
}

case "${action}" in
    create)
        create
        ;;
    status)
        status
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    destroy)
        destroy
        ;;
    *)
        echo "usage: $0 {create|status|start|stop|destroy}" >&2
        exit 64
        ;;
esac
