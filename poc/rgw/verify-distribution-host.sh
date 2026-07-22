#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
ca_path="${repository_root}/work/rgw/distribution-ca.crt"
local_port="${COFFER_DISTRIBUTION_LOCAL_PORT:-15443}"
server_name="coffer-rgw-poc"

test -f "${ca_path}"
openssl x509 -in "${ca_path}" -noout -checkend 86400

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ExitOnForwardFailure=yes
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

ssh "${ssh_options[@]}" \
  -N -L "127.0.0.1:${local_port}:127.0.0.1:5443" "${guest}" &
tunnel_pid=$!
cleanup() {
  kill "${tunnel_pid}" 2>/dev/null || true
  wait "${tunnel_pid}" 2>/dev/null || true
}
trap cleanup EXIT

for _attempt in $(seq 1 30); do
  status_code="$(
    curl --noproxy '*' --silent --show-error \
      --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 2 --max-time 5 \
      --cacert "${ca_path}" \
      --resolve "${server_name}:${local_port}:127.0.0.1" \
      "https://${server_name}:${local_port}/v2/" || true
  )"
  if test "${status_code}" = 200; then
    break
  fi
  sleep 1
done
test "${status_code}" = 200

if curl --noproxy '*' --silent --show-error --output /dev/null \
  --connect-timeout 2 --max-time 5 \
  --resolve "${server_name}:${local_port}:127.0.0.1" \
  "https://${server_name}:${local_port}/v2/" 2>/dev/null; then
  printf 'Distribution unexpectedly trusted without the exported lab CA\n' >&2
  exit 60
fi

printf 'Tunneled Distribution HTTPS verification passed\n'
