#!/usr/bin/env bash

set -Eeuo pipefail

primary_hostname="coffer-rgw-ha-stage5-storage-1"
primary_address="192.168.253.31"
storage_network="192.168.253.0/24"
cephadm_source="/tmp/cephadm-20.2.2"
ceph_release="20.2.2"
ceph_series="tentacle"
cephadm_sha256="42daa0d45411be4c8bb16fe92e265c59cc21fc86cd0040b96409c80ba0da884c"
ceph_image_digest="sha256:6b4b5ae33acd3d736eb26d2a19238bce71a22f9cfb99cca887ba6312d0957644"
ceph_image="quay.io/ceph/ceph@${ceph_image_digest}"
release_record="/etc/ceph/coffer-stage5-release.txt"

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"
test -f "${cephadm_source}"
printf '%s  %s\n' "${cephadm_sha256}" "${cephadm_source}" |
    sha256sum --check --status
test -z "$(wipefs --no-act /dev/vdb)"

cluster_initialized=false
if test -f /etc/ceph/ceph.conf &&
    test -f /etc/ceph/ceph.client.admin.keyring; then
    cluster_initialized=true
elif test -e /etc/ceph/ceph.conf ||
    test -e /etc/ceph/ceph.client.admin.keyring; then
    echo "refusing inconsistent Ceph bootstrap state" >&2
    exit 20
fi

if ! command -v cephadm >/dev/null 2>&1; then
    install -m 0755 "${cephadm_source}" /usr/local/sbin/cephadm-bootstrap
    test "$(
        /usr/local/sbin/cephadm-bootstrap version | awk '{print $3}'
    )" = "${ceph_release}"
    /usr/local/sbin/cephadm-bootstrap add-repo --release "${ceph_series}"
    /usr/local/sbin/cephadm-bootstrap install
fi
test "$(cephadm version | awk '{print $3}')" = "${ceph_release}"

resolved_ceph_digest="$(
    skopeo inspect --format '{{.Digest}}' \
        "docker://quay.io/ceph/ceph:v${ceph_release}"
)"
test "${resolved_ceph_digest}" = "${ceph_image_digest}"

if ! ${cluster_initialized}; then
    if test -d /var/lib/ceph; then
        test -z "$(find /var/lib/ceph -mindepth 1 -maxdepth 1 -print -quit)"
    fi
    bootstrap_config="$(mktemp)"
    cleanup() {
        rm -f -- "${bootstrap_config}"
    }
    trap cleanup EXIT
    chmod 0600 "${bootstrap_config}"
    cat >"${bootstrap_config}" <<EOF
[global]
public_network = ${storage_network}
cluster_network = ${storage_network}
osd_pool_default_size = 3
osd_pool_default_min_size = 2
mon_target_pg_per_osd = 50
EOF
    cephadm --image "${ceph_image}" bootstrap \
        --config "${bootstrap_config}" \
        --mon-ip "${primary_address}" \
        --cluster-network "${storage_network}" \
        --skip-dashboard \
        --skip-monitoring-stack
    cleanup
    trap - EXIT
fi

test -f /etc/ceph/ceph.conf
test -f /etc/ceph/ceph.client.admin.keyring
install -d -m 0700 /etc/ceph
{
    printf 'release=%s\n' "${ceph_release}"
    printf 'cephadm_sha256=%s\n' "${cephadm_sha256}"
    printf 'image=%s\n' "${ceph_image}"
    printf 'primary=%s\n' "${primary_hostname}"
    printf 'mon_ip=%s\n' "${primary_address}"
    printf 'network=%s\n' "${storage_network}"
} >"${release_record}"
chmod 0600 "${release_record}"

cephadm shell -- ceph config set global osd_pool_default_size 3 </dev/null
cephadm shell -- ceph config set global osd_pool_default_min_size 2 </dev/null
cephadm shell -- ceph config set global mon_target_pg_per_osd 50 </dev/null
test "$(
    cephadm shell -- ceph osd stat --format json </dev/null |
        jq -r '.num_osds'
)" -eq 0
test -z "$(wipefs --no-act /dev/vdb)"

printf '%s bootstrap_ready release=%s osds=0\n' \
    "${primary_hostname}" "${ceph_release}"
