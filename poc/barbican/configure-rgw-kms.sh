#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

scp "${ssh_options[@]}" \
  "${script_dir}/guest-ceph-kms-config.py" \
  "${script_dir}/guest-configure-rgw-kms.sh" \
  "${script_dir}/guest-restart-rgw.sh" \
  "${script_dir}/guest-verify-rgw-kms.sh" \
  "${script_dir}/guest-verify-rgw-kms.py" \
  "${guest}:/tmp/"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-configure-rgw-kms.sh'
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-verify-rgw-kms.sh'
ssh "${ssh_options[@]}" "${guest}" \
  'rm -f /tmp/guest-ceph-kms-config.py /tmp/guest-configure-rgw-kms.sh /tmp/guest-restart-rgw.sh /tmp/guest-verify-rgw-kms.sh /tmp/guest-verify-rgw-kms.py'

printf 'Direct RGW Barbican SSE-KMS verification passed\n'
