#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
cephadm_source="${repository_root}/work/rgw/cephadm-20.2.2"
installer_source="${repository_root}/poc/rgw/guest-install-ceph.sh"
cephadm_sha256="42daa0d45411be4c8bb16fe92e265c59cc21fc86cd0040b96409c80ba0da884c"

test -f "${cephadm_source}"
test -f "${installer_source}"
printf '%s  %s\n' "${cephadm_sha256}" "${cephadm_source}" | shasum -a 256 --check --status

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=accept-new
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

scp "${ssh_options[@]}" \
  "${cephadm_source}" "${guest}:/tmp/cephadm-20.2.2"
scp "${ssh_options[@]}" \
  "${installer_source}" "${guest}:/tmp/guest-install-ceph.sh"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-install-ceph.sh /tmp/cephadm-20.2.2'
