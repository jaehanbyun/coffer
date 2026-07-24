#!/usr/bin/env bash

set -Eeuo pipefail

expected_hostname="$1"
host_map_base64="$2"
cephadm_source="/tmp/cephadm-20.2.2"
cephadm_sha256="42daa0d45411be4c8bb16fe92e265c59cc21fc86cd0040b96409c80ba0da884c"
ceph_release="20.2.2"
ceph_image_tag="quay.io/ceph/ceph:v${ceph_release}"
ceph_image_digest="sha256:6b4b5ae33acd3d736eb26d2a19238bce71a22f9cfb99cca887ba6312d0957644"
osd_device="/dev/vdb"
osd_size_bytes="68719476736"
begin_marker="# BEGIN COFFER STAGE5 STORAGE"
end_marker="# END COFFER STAGE5 STORAGE"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(uname -m)" = x86_64
test -f "${cephadm_source}"
printf '%s  %s\n' "${cephadm_sha256}" "${cephadm_source}" |
    sha256sum --check --status

temporary_directory="$(mktemp -d)"
cleanup() {
    rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

printf '%s' "${host_map_base64}" |
    base64 --decode >"${temporary_directory}/host-map"
test "$(wc -l <"${temporary_directory}/host-map")" -eq 3
if grep -Evq \
    '^192\.168\.253\.(31|32|33) coffer-rgw-ha-stage5-storage-[123]$' \
    "${temporary_directory}/host-map"; then
    echo "refusing an unexpected Stage 5 storage host map" >&2
    exit 20
fi

awk \
    -v begin="${begin_marker}" \
    -v end="${end_marker}" \
    '
    $0 == begin {inside = 1; next}
    $0 == end {inside = 0; next}
    $1 == "127.0.1.1" &&
        $0 ~ /coffer-rgw-ha-stage5-storage-[123]/ {next}
    !inside {print}
    ' /etc/hosts >"${temporary_directory}/hosts"
{
    printf '%s\n' "${begin_marker}"
    cat "${temporary_directory}/host-map"
    printf '%s\n' "${end_marker}"
} >>"${temporary_directory}/hosts"
install -o root -g root -m 0644 "${temporary_directory}/hosts" /etc/hosts
printf '%s\n' 'manage_etc_hosts: false' |
    install -o root -g root -m 0644 /dev/stdin \
        /etc/cloud/cloud.cfg.d/99-coffer-stage5-hosts.cfg

while read -r storage_address storage_hostname; do
    test "$(
        getent ahostsv4 "${storage_hostname}" |
            awk 'NR == 1 {print $1}'
    )" = "${storage_address}"
done <"${temporary_directory}/host-map"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ca-certificates \
    chrony \
    curl \
    jq \
    lvm2 \
    podman \
    skopeo
systemctl enable --now chrony
test "$(systemctl is-active chrony)" = active

test -b "${osd_device}"
test "$(lsblk -dn -o TYPE "${osd_device}")" = disk
test "$(blockdev --getsize64 "${osd_device}")" = "${osd_size_bytes}"
test "$(lsblk -nr -o NAME "${osd_device}" | wc -l)" -eq 1
test -z "$(lsblk -dn -o FSTYPE "${osd_device}" | tr -d ' ')"
test -z "$(lsblk -dn -o MOUNTPOINTS "${osd_device}" | tr -d ' ')"
test -z "$(wipefs --no-act "${osd_device}")"
if pvs --noheadings -o pv_name 2>/dev/null |
    awk '{$1=$1};1' |
    grep -Fxq "${osd_device}"; then
    echo "refusing an OSD device that is already an LVM PV" >&2
    exit 21
fi

resolved_ceph_digest="$(
    skopeo inspect --format '{{.Digest}}' "docker://${ceph_image_tag}"
)"
test "${resolved_ceph_digest}" = "${ceph_image_digest}"

printf '%s prepared osd=%s size_bytes=%s ceph=%s\n' \
    "${expected_hostname}" "${osd_device}" "${osd_size_bytes}" \
    "${ceph_release}"
