#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
profile_path="${repository_root}/work/rgw/distribution.env"

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

umask 077
temporary_profile="$(mktemp "${profile_path}.XXXXXX")"
trap 'rm -f "${temporary_profile}"' EXIT
ssh "${ssh_options[@]}" "${guest}" \
  'sudo cat /etc/coffer-rgw/distribution.env' >"${temporary_profile}"

test "$(wc -l <"${temporary_profile}" | tr -d ' ')" -eq 2
grep -Eq '^REGISTRY_STORAGE_S3_ACCESSKEY=[[:alnum:]]+$' "${temporary_profile}"
grep -Eq '^REGISTRY_STORAGE_S3_SECRETKEY=[^[:space:]]+$' "${temporary_profile}"
install -m 0600 "${temporary_profile}" "${profile_path}"
