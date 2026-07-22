#!/usr/bin/env bash

set -euo pipefail

cephadm_source="${1:-/tmp/cephadm-20.2.2}"
ceph_release="20.2.2"
ceph_series="tentacle"
cephadm_sha256="42daa0d45411be4c8bb16fe92e265c59cc21fc86cd0040b96409c80ba0da884c"
mon_ip="192.168.122.200"
osd_device="/dev/vdb"
ceph_image_tag="quay.io/ceph/ceph:v${ceph_release}"
ceph_image_digest="sha256:6b4b5ae33acd3d736eb26d2a19238bce71a22f9cfb99cca887ba6312d0957644"
ceph_image="quay.io/ceph/ceph@${ceph_image_digest}"

test "$(id -u)" -eq 0
test "$(uname -m)" = x86_64
test -f "${cephadm_source}"
printf '%s  %s\n' "${cephadm_sha256}" "${cephadm_source}" | sha256sum --check --status

test -b "${osd_device}"
test "$(lsblk -dn -o SIZE "${osd_device}" | tr -d ' ')" = 200G
test -z "$(lsblk -dn -o MOUNTPOINTS "${osd_device}" | tr -d ' ')"

cluster_initialized=false
if test -f /etc/ceph/ceph.conf && test -f /etc/ceph/ceph.client.admin.keyring; then
  cluster_initialized=true
elif test -e /etc/ceph/ceph.conf || test -e /etc/ceph/ceph.client.admin.keyring; then
  printf 'refusing to continue from an inconsistent Ceph configuration\n' >&2
  exit 20
fi

if ! ${cluster_initialized}; then
  test ! -e /var/lib/ceph/mon
  test -z "$(lsblk -dn -o FSTYPE "${osd_device}" | tr -d ' ')"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y chrony jq lvm2 podman skopeo
systemctl enable --now chrony

install -m 0755 "${cephadm_source}" /usr/local/sbin/cephadm-bootstrap
test "$(/usr/local/sbin/cephadm-bootstrap version | awk '{print $3}')" = "${ceph_release}"

/usr/local/sbin/cephadm-bootstrap add-repo --release "${ceph_series}"
/usr/local/sbin/cephadm-bootstrap install
test "$(cephadm version | awk '{print $3}')" = "${ceph_release}"

resolved_ceph_image_digest="$(skopeo inspect --format '{{.Digest}}' "docker://${ceph_image_tag}")"
test "${resolved_ceph_image_digest}" = "${ceph_image_digest}"

if ${cluster_initialized}; then
  test -f /etc/ceph/coffer-poc-release.txt
  grep -Fqx "release=${ceph_release}" /etc/ceph/coffer-poc-release.txt
  grep -Fqx "cephadm_sha256=${cephadm_sha256}" /etc/ceph/coffer-poc-release.txt
  grep -Fqx "image=${ceph_image}" /etc/ceph/coffer-poc-release.txt
  grep -Fqx "mon_ip=${mon_ip}" /etc/ceph/coffer-poc-release.txt
  grep -Fqx "osd_device=${osd_device}" /etc/ceph/coffer-poc-release.txt
fi

install -d -m 0700 /etc/ceph
{
  printf 'release=%s\n' "${ceph_release}"
  printf 'cephadm_sha256=%s\n' "${cephadm_sha256}"
  printf 'image=%s\n' "${ceph_image}"
  printf 'mon_ip=%s\n' "${mon_ip}"
  printf 'osd_device=%s\n' "${osd_device}"
} >/etc/ceph/coffer-poc-release.txt
chmod 0600 /etc/ceph/coffer-poc-release.txt

if ! ${cluster_initialized}; then
  bootstrap_help="$(cephadm bootstrap --help)"
  for required_flag in --config --single-host-defaults --skip-dashboard --skip-monitoring-stack; do
    grep -Fq -- "${required_flag}" <<<"${bootstrap_help}"
  done

  bootstrap_config="$(mktemp)"
  trap 'rm -f "${bootstrap_config}"' EXIT
  chmod 0600 "${bootstrap_config}"
  {
    printf '[global]\n'
    printf 'mon_target_pg_per_osd = 50\n'
    printf 'osd_pool_default_size = 1\n'
    printf 'osd_pool_default_min_size = 1\n'
  } >"${bootstrap_config}"

  cephadm --image "${ceph_image}" bootstrap \
    --config "${bootstrap_config}" \
    --mon-ip "${mon_ip}" \
    --single-host-defaults \
    --skip-dashboard \
    --skip-monitoring-stack
  rm -f "${bootstrap_config}"
  trap - EXIT
fi

cephadm shell -- ceph config set global osd_pool_default_size 1
cephadm shell -- ceph config set global osd_pool_default_min_size 1
cephadm shell -- ceph config set global mon_target_pg_per_osd 50
cephadm shell -- ceph orch device ls --refresh

osd_count="$(cephadm shell -- ceph osd stat --format json | jq -r '.num_osds')"
case "${osd_count}" in
  0)
    device_available="$(
      cephadm shell -- ceph orch device ls --format json | \
        jq -r \
          --arg host "$(hostname)" \
          --arg path "${osd_device}" \
          '.[] | select(.name == $host) | .devices[] | select(.path == $path) | .available'
    )"
    test "${device_available}" = true
    cephadm shell -- ceph orch daemon add osd "$(hostname):${osd_device}"
    ;;
  1)
    ;;
  *)
    printf 'expected zero or one OSD, found %s\n' "${osd_count}" >&2
    exit 40
    ;;
esac

for _attempt in $(seq 1 90); do
  up_osds="$(cephadm shell -- ceph osd stat --format json | jq -r '.num_up_osds')"
  if test "${up_osds}" -eq 1; then
    break
  fi
  sleep 2
done
test "$(cephadm shell -- ceph osd stat --format json | jq -r '.num_up_osds')" -eq 1

cephadm shell -- ceph versions --format json-pretty
cephadm shell -- ceph status --format json-pretty
