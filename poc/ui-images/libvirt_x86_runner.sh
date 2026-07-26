#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

readonly URI="qemu:///system"
readonly NAME="coffer-ui-x86-qualification-1"
readonly POOL="coffer-rgw"
readonly NETWORK="default"
readonly ROOT_VOLUME="${NAME}-root.qcow2"
readonly SEED_VOLUME="${NAME}-seed.iso"
readonly MEMORY_MIB="24576"
readonly VCPUS="8"
readonly ROOT_CAPACITY="120G"
readonly CLOUD_BASE="https://cloud-images.ubuntu.com/releases/noble/release"
readonly CLOUD_IMAGE="ubuntu-24.04-server-cloudimg-amd64.img"
readonly CLOUD_IMAGE_SHA256="ffe6203da54deeb6db5d2a98a83f9ec8e55f149d3f7ba622e1abe5fa966ee3d6"
readonly UBUNTU_KEYRING="/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg"

work_dir=""
create_complete=0

usage() {
    echo "usage: $0 {status|create SSH_PUBLIC_KEY_FILE|destroy}" >&2
    exit 64
}

domain_exists() {
    virsh -c "${URI}" dominfo "${NAME}" >/dev/null 2>&1
}

volume_exists() {
    virsh -c "${URI}" vol-info --pool "${POOL}" "$1" >/dev/null 2>&1
}

destroy_exact_candidate() {
    if domain_exists; then
        if [[ "$(virsh -c "${URI}" domstate "${NAME}")" == "running" ]]; then
            virsh -c "${URI}" destroy "${NAME}" >/dev/null
        fi
        virsh -c "${URI}" undefine "${NAME}" >/dev/null
    fi
    for volume in "${SEED_VOLUME}" "${ROOT_VOLUME}"; do
        if volume_exists "${volume}"; then
            virsh -c "${URI}" vol-delete --pool "${POOL}" "${volume}" >/dev/null
        fi
    done
}

remove_work_dir() {
    if [[ -z "${work_dir}" ]]; then
        return
    fi
    case "${work_dir}" in
        "${HOME}"/.coffer-ui-x86-runner.*)
            rm -rf -- "${work_dir}"
            ;;
        *)
            echo "refusing unsafe runner work path" >&2
            return 1
            ;;
    esac
    work_dir=""
}

cleanup_create() {
    local exit_code=$?
    if [[ "${create_complete}" -ne 1 ]]; then
        destroy_exact_candidate
    fi
    remove_work_dir
    exit "${exit_code}"
}

status() {
    local domain_state="absent"
    local root_state="absent"
    local seed_state="absent"
    local address=""
    if domain_exists; then
        domain_state="$(virsh -c "${URI}" domstate "${NAME}")"
        address="$(
            virsh -c "${URI}" domifaddr "${NAME}" --source lease 2>/dev/null \
                | awk '$3 == "ipv4" {sub("/.*", "", $4); print $4; exit}'
        )"
    fi
    if volume_exists "${ROOT_VOLUME}"; then
        root_state="present"
    fi
    if volume_exists "${SEED_VOLUME}"; then
        seed_state="present"
    fi
    printf 'name=%s\nstate=%s\nroot_volume=%s\nseed_volume=%s\naddress=%s\n' \
        "${NAME}" "${domain_state}" "${root_state}" "${seed_state}" "${address}"
}

validate_public_key() {
    local key_file="$1"
    if [[ "${key_file}" != /* || ! -f "${key_file}" || -L "${key_file}" ]]; then
        echo "SSH public key input is invalid" >&2
        exit 65
    fi
    local key
    key="$(<"${key_file}")"
    if [[ ! "${key}" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ coffer-ui-x86-qualification$ ]]; then
        echo "SSH public key does not match the bounded runner contract" >&2
        exit 65
    fi
    printf '%s' "${key}"
}

create() {
    local key_file="$1"
    local public_key
    public_key="$(validate_public_key "${key_file}")"
    for command_name in cloud-localds curl gpgv sha256sum stat virsh virt-install; do
        command -v "${command_name}" >/dev/null 2>&1 \
            || { echo "missing runner command: ${command_name}" >&2; exit 69; }
    done
    [[ -r "${UBUNTU_KEYRING}" ]] \
        || { echo "Ubuntu cloud image keyring is unavailable" >&2; exit 69; }
    virsh -c "${URI}" pool-info "${POOL}" >/dev/null
    virsh -c "${URI}" net-info "${NETWORK}" >/dev/null
    if domain_exists || volume_exists "${ROOT_VOLUME}" \
        || volume_exists "${SEED_VOLUME}"; then
        echo "refusing pre-existing x86 qualification runner" >&2
        exit 73
    fi

    work_dir="$(mktemp -d "${HOME}/.coffer-ui-x86-runner.XXXXXX")"
    trap cleanup_create EXIT
    curl --fail --location --proto '=https' --tlsv1.2 \
        --output "${work_dir}/SHA256SUMS" "${CLOUD_BASE}/SHA256SUMS"
    curl --fail --location --proto '=https' --tlsv1.2 \
        --output "${work_dir}/SHA256SUMS.gpg" "${CLOUD_BASE}/SHA256SUMS.gpg"
    gpgv --keyring "${UBUNTU_KEYRING}" \
        "${work_dir}/SHA256SUMS.gpg" "${work_dir}/SHA256SUMS" >/dev/null
    local signed_hash
    signed_hash="$(
        awk -v name="${CLOUD_IMAGE}" '$2 == "*" name {print $1}' \
            "${work_dir}/SHA256SUMS"
    )"
    if [[ "${signed_hash}" != "${CLOUD_IMAGE_SHA256}" ]]; then
        echo "signed Ubuntu image digest is not the accepted release" >&2
        exit 65
    fi
    curl --fail --location --proto '=https' --tlsv1.2 \
        --output "${work_dir}/${CLOUD_IMAGE}" \
        "${CLOUD_BASE}/${CLOUD_IMAGE}"
    (
        cd "${work_dir}"
        printf '%s  %s\n' "${CLOUD_IMAGE_SHA256}" "${CLOUD_IMAGE}" \
            | sha256sum --check --status
    )

    {
        echo '#cloud-config'
        echo 'users:'
        echo '  - name: coffer'
        echo '    groups: [adm, sudo]'
        echo '    shell: /bin/bash'
        echo '    sudo: ALL=(ALL) NOPASSWD:ALL'
        echo '    lock_passwd: true'
        echo '    ssh_authorized_keys:'
        printf '      - %s\n' "${public_key}"
        echo 'disable_root: true'
        echo 'ssh_pwauth: false'
        echo 'package_update: false'
        echo 'package_upgrade: false'
    } >"${work_dir}/user-data"
    {
        printf 'instance-id: %s\n' "${NAME}"
        printf 'local-hostname: %s\n' "${NAME}"
    } >"${work_dir}/meta-data"
    cloud-localds "${work_dir}/${SEED_VOLUME}" \
        "${work_dir}/user-data" "${work_dir}/meta-data"

    local image_size
    image_size="$(stat --format '%s' "${work_dir}/${CLOUD_IMAGE}")"
    virsh -c "${URI}" vol-create-as --pool "${POOL}" \
        "${ROOT_VOLUME}" "${image_size}" --format qcow2 >/dev/null
    virsh -c "${URI}" vol-upload --pool "${POOL}" \
        "${ROOT_VOLUME}" "${work_dir}/${CLOUD_IMAGE}"
    virsh -c "${URI}" vol-resize --pool "${POOL}" \
        "${ROOT_VOLUME}" "${ROOT_CAPACITY}" >/dev/null

    local seed_size
    seed_size="$(stat --format '%s' "${work_dir}/${SEED_VOLUME}")"
    virsh -c "${URI}" vol-create-as --pool "${POOL}" \
        "${SEED_VOLUME}" "${seed_size}" --format raw >/dev/null
    virsh -c "${URI}" vol-upload --pool "${POOL}" \
        "${SEED_VOLUME}" "${work_dir}/${SEED_VOLUME}"

    virt-install --connect "${URI}" \
        --name "${NAME}" \
        --memory "${MEMORY_MIB}" \
        --vcpus "${VCPUS}" \
        --cpu host-passthrough \
        --os-variant ubuntu24.04 \
        --import \
        --disk "vol=${POOL}/${ROOT_VOLUME},bus=virtio" \
        --disk "vol=${POOL}/${SEED_VOLUME},device=cdrom" \
        --network "network=${NETWORK},model=virtio" \
        --graphics none \
        --console pty,target_type=serial \
        --noautoconsole >/dev/null
    if [[ "$(virsh -c "${URI}" domstate "${NAME}")" != "running" ]]; then
        echo "x86 qualification runner did not start" >&2
        exit 70
    fi
    if [[ "$(virsh -c "${URI}" dominfo "${NAME}" \
        | awk -F: '$1 == "Autostart" {gsub(/^[ \t]+/, "", $2); print $2}')" \
        != "disable" ]]; then
        echo "x86 qualification runner unexpectedly has autostart" >&2
        exit 70
    fi
    create_complete=1
    remove_work_dir
    trap - EXIT
    status
}

action="${1:-}"
case "${action}" in
    status)
        [[ "$#" -eq 1 ]] || usage
        status
        ;;
    create)
        [[ "$#" -eq 2 ]] || usage
        create "$2"
        ;;
    destroy)
        [[ "$#" -eq 1 ]] || usage
        destroy_exact_candidate
        status
        ;;
    *)
        usage
        ;;
esac
