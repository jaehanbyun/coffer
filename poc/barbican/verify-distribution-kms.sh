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
  "${script_dir}/guest-assert-secrets-absent.py" \
  "${script_dir}/guest-create-oci-layout.py" \
  "${script_dir}/guest-verify-distribution-kms.sh" \
  "${script_dir}/guest-inspect-distribution-kms.py" \
  "${script_dir}/guest-kms-scenario-storage.py" \
  "${script_dir}/guest-restart-rgw.sh" \
  "${guest}:/tmp/"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-verify-distribution-kms.sh'
ssh "${ssh_options[@]}" "${guest}" \
  'rm -f /tmp/guest-assert-secrets-absent.py /tmp/guest-create-oci-layout.py /tmp/guest-verify-distribution-kms.sh /tmp/guest-inspect-distribution-kms.py /tmp/guest-kms-scenario-storage.py /tmp/guest-restart-rgw.sh'
