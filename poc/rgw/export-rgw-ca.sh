#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
ca_path="${repository_root}/work/rgw/cephadm-root-ca.crt"

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

umask 077
temporary_ca="$(mktemp "${ca_path}.XXXXXX")"
trap 'rm -f "${temporary_ca}"' EXIT
ssh "${ssh_options[@]}" "${guest}" \
  'sudo cat /etc/ceph/coffer-rgw-root-ca.crt' >"${temporary_ca}"
openssl x509 -in "${temporary_ca}" -noout -checkend 86400
install -m 0644 "${temporary_ca}" "${ca_path}"
