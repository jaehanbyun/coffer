#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
ca_path="${repository_root}/work/rgw/cephadm-root-ca.crt"
local_port="${COFFER_RGW_LOCAL_PORT:-19443}"
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
  -N -L "127.0.0.1:${local_port}:192.168.122.200:8443" "${guest}" &
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
      "https://${server_name}:${local_port}/" || true
  )"
  case "${status_code}" in
    200|403)
      break
      ;;
  esac
  sleep 1
done
case "${status_code}" in
  200|403) ;;
  *)
    printf 'tunneled RGW HTTPS returned unexpected status %s\n' "${status_code}" >&2
    exit 60
    ;;
esac

if curl --noproxy '*' --silent --show-error --output /dev/null \
  --connect-timeout 2 --max-time 5 \
  --resolve "${server_name}:${local_port}:127.0.0.1" \
  "https://${server_name}:${local_port}/" 2>/dev/null; then
  printf 'RGW unexpectedly trusted without the exported cephadm root CA\n' >&2
  exit 61
fi

certificate_sans="$(
  openssl s_client \
    -connect "127.0.0.1:${local_port}" \
    -servername "${server_name}" \
    -CAfile "${ca_path}" </dev/null 2>/dev/null | \
    openssl x509 -noout -ext subjectAltName
)"
grep -Fq "DNS:${server_name}" <<<"${certificate_sans}"
grep -Fq 'IP Address:192.168.122.200' <<<"${certificate_sans}"

printf 'RGW HTTPS verification passed with status %s\n' "${status_code}"
