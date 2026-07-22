#!/usr/bin/env bash

set -euo pipefail

remote="${COFFER_RGW_REMOTE:-bb00}"
vm_name="${COFFER_RGW_VM_NAME:-coffer-rgw-poc}"
pool_name="${COFFER_RGW_POOL:-coffer-rgw}"
pool_path="${COFFER_RGW_POOL_PATH:-/srv/nfs/coffer-libvirt}"
root_volume="${COFFER_RGW_ROOT_VOLUME:-coffer-rgw-poc-root.qcow2}"
osd_volume="${COFFER_RGW_OSD_VOLUME:-coffer-rgw-poc-osd.raw}"
seed_volume="${COFFER_RGW_SEED_VOLUME:-coffer-rgw-poc-seed.iso}"
base_image="${COFFER_RGW_BASE_IMAGE:-/var/lib/libvirt/images/templates/ubuntu24.04.img}"
vm_ip="${COFFER_RGW_VM_IP:-192.168.122.200}"
vm_mac="${COFFER_RGW_VM_MAC:-52:54:00:cf:fe:01}"
vm_vcpus="${COFFER_RGW_VM_VCPUS:-8}"
vm_memory_mib="${COFFER_RGW_VM_MEMORY_MIB:-24576}"
root_capacity_gib="${COFFER_RGW_ROOT_GIB:-60}"
osd_capacity_gib="${COFFER_RGW_OSD_GIB:-200}"

ssh -o BatchMode=yes -o ConnectTimeout=10 "${remote}" bash -s -- \
  "${vm_name}" "${pool_name}" "${pool_path}" "${root_volume}" \
  "${osd_volume}" "${seed_volume}" "${base_image}" "${vm_ip}" \
  "${vm_mac}" "${vm_vcpus}" "${vm_memory_mib}" \
  "${root_capacity_gib}" "${osd_capacity_gib}" <<'REMOTE'
set -euo pipefail

vm_name="$1"
pool_name="$2"
pool_path="$3"
root_volume="$4"
osd_volume="$5"
seed_volume="$6"
base_image="$7"
vm_ip="$8"
vm_mac="$9"
vm_vcpus="${10}"
vm_memory_mib="${11}"
root_capacity_gib="${12}"
osd_capacity_gib="${13}"
uri="qemu:///system"
network="default"

case "${pool_path}" in
  /srv/nfs/coffer-libvirt) ;;
  *)
    printf 'refusing unexpected pool path: %s\n' "${pool_path}" >&2
    exit 20
    ;;
esac

case "${vm_ip}" in
  192.168.122.*) ;;
  *)
    printf 'refusing IP outside the default libvirt network: %s\n' "${vm_ip}" >&2
    exit 21
    ;;
esac

test -f "${base_image}"
test "$(uname -m)" = x86_64
test "$(awk 'NF && $1 ~ /^(ssh-|ecdsa-|sk-)/ {n++} END{print n+0}' "${HOME}/.ssh/authorized_keys")" -gt 0

if virsh -c "${uri}" dominfo "${vm_name}" >/dev/null 2>&1; then
  printf 'domain already exists; refusing to mutate it: %s\n' "${vm_name}" >&2
  exit 22
fi

if ! virsh -c "${uri}" pool-info "${pool_name}" >/dev/null 2>&1; then
  test ! -e "${pool_path}"
  virsh -c "${uri}" pool-define-as "${pool_name}" dir --target "${pool_path}"
  virsh -c "${uri}" pool-build "${pool_name}"
  virsh -c "${uri}" pool-start "${pool_name}"
  virsh -c "${uri}" pool-autostart "${pool_name}"
fi

if test "$(virsh -c "${uri}" pool-info "${pool_name}" | awk -F: '/^State:/{gsub(/ /,"",$2); print $2}')" != running; then
  virsh -c "${uri}" pool-start "${pool_name}"
fi

if ! virsh -c "${uri}" vol-info --pool "${pool_name}" "${root_volume}" >/dev/null 2>&1; then
  printf '%s\n' \
    "<volume><name>${root_volume}</name><capacity unit=\"GiB\">${root_capacity_gib}</capacity><allocation unit=\"bytes\">0</allocation><target><format type=\"qcow2\"/></target><backingStore><path>${base_image}</path><format type=\"qcow2\"/></backingStore></volume>" | \
    virsh -c "${uri}" vol-create "${pool_name}" /dev/stdin
fi

if ! virsh -c "${uri}" vol-info --pool "${pool_name}" "${osd_volume}" >/dev/null 2>&1; then
  virsh -c "${uri}" vol-create-as "${pool_name}" "${osd_volume}" \
    "${osd_capacity_gib}G" --allocation 0 --format raw
fi

root_format="$(virsh -c "${uri}" vol-dumpxml --pool "${pool_name}" "${root_volume}" | sed -n "s/.*<format type='\([^']*\)'.*/\1/p" | head -n 1)"
osd_format="$(virsh -c "${uri}" vol-dumpxml --pool "${pool_name}" "${osd_volume}" | sed -n "s/.*<format type='\([^']*\)'.*/\1/p" | head -n 1)"
test "${root_format}" = qcow2
test "${osd_format}" = raw

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf -- "${tmp_dir}"
}
trap cleanup EXIT
chmod 700 "${tmp_dir}"

{
  printf '%s\n' '#cloud-config'
  printf '%s\n' "hostname: ${vm_name}"
  printf '%s\n' 'manage_etc_hosts: true'
  printf '%s\n' 'disable_root: true'
  printf '%s\n' 'ssh_pwauth: false'
  printf '%s\n' 'users:'
  printf '%s\n' '  - name: coffer'
  printf '%s\n' '    gecos: Coffer PoC Operator'
  printf '%s\n' '    groups: [adm, sudo]'
  printf '%s\n' '    shell: /bin/bash'
  printf '%s\n' '    lock_passwd: true'
  printf '%s\n' '    sudo: ALL=(ALL) NOPASSWD:ALL'
  printf '%s\n' '    ssh_authorized_keys:'
  awk 'NF && $1 ~ /^(ssh-|ecdsa-|sk-)/ {printf "      - %s\n", $0}' "${HOME}/.ssh/authorized_keys"
  printf '%s\n' 'growpart:'
  printf '%s\n' '  mode: auto'
  printf '%s\n' '  devices: [/]'
  printf '%s\n' 'resize_rootfs: true'
  printf '%s\n' 'package_update: true'
  printf '%s\n' 'packages:'
  printf '%s\n' '  - ca-certificates'
  printf '%s\n' '  - curl'
  printf '%s\n' '  - jq'
  printf '%s\n' '  - qemu-guest-agent'
  printf '%s\n' 'runcmd:'
  printf '%s\n' '  - [systemctl, enable, --now, qemu-guest-agent]'
} >"${tmp_dir}/user-data"

{
  printf '%s\n' "instance-id: ${vm_name}-v1"
  printf '%s\n' "local-hostname: ${vm_name}"
} >"${tmp_dir}/meta-data"

cloud-localds "${tmp_dir}/seed.iso" "${tmp_dir}/user-data" "${tmp_dir}/meta-data"

if virsh -c "${uri}" vol-info --pool "${pool_name}" "${seed_volume}" >/dev/null 2>&1; then
  virsh -c "${uri}" vol-delete --pool "${pool_name}" "${seed_volume}"
fi
virsh -c "${uri}" vol-create-as "${pool_name}" "${seed_volume}" 4M --allocation 0 --format raw
virsh -c "${uri}" vol-upload --pool "${pool_name}" "${seed_volume}" "${tmp_dir}/seed.iso"

network_xml="$(virsh -c "${uri}" net-dumpxml "${network}")"
if grep -Fq "mac='${vm_mac}'" <<<"${network_xml}"; then
  grep -Fq "ip='${vm_ip}'" <<<"${network_xml}" || {
    printf 'MAC reservation exists with an unexpected IP\n' >&2
    exit 23
  }
elif grep -Fq "ip='${vm_ip}'" <<<"${network_xml}"; then
  printf 'IP reservation exists with an unexpected MAC\n' >&2
  exit 24
else
  virsh -c "${uri}" net-update "${network}" add ip-dhcp-host \
    "<host mac='${vm_mac}' name='${vm_name}' ip='${vm_ip}'/>" \
    --live --config
fi

virt-install \
  --connect "${uri}" \
  --name "${vm_name}" \
  --memory "${vm_memory_mib}" \
  --vcpus "${vm_vcpus}" \
  --cpu host-passthrough \
  --os-variant ubuntu24.04 \
  --import \
  --disk "vol=${pool_name}/${root_volume},bus=virtio,cache=none,discard=unmap" \
  --disk "vol=${pool_name}/${osd_volume},bus=virtio,cache=none,discard=unmap" \
  --disk "vol=${pool_name}/${seed_volume},device=cdrom" \
  --network "network=${network},model=virtio,mac=${vm_mac}" \
  --rng /dev/urandom \
  --graphics none \
  --console pty,target_type=serial \
  --noautoconsole

test "$(virsh -c "${uri}" domstate "${vm_name}" | tr -d '\r')" = running
test "$(virsh -c "${uri}" dominfo "${vm_name}" | awk -F: '/^Autostart:/{gsub(/ /,"",$2); print $2}')" = disable
printf 'created %s at reserved address %s\n' "${vm_name}" "${vm_ip}"
REMOTE
