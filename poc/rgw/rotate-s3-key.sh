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
  "${script_dir}/guest-run-distribution.sh" \
  "${script_dir}/guest-rotate-s3-key.sh" \
  "${guest}:/tmp/"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-rotate-s3-key.sh'
ssh "${ssh_options[@]}" "${guest}" \
  'rm -f /tmp/guest-run-distribution.sh /tmp/guest-rotate-s3-key.sh'
"${script_dir}/export-s3-profile.sh"

printf 'Owner-only registry S3 profile rotated and refreshed\n'
