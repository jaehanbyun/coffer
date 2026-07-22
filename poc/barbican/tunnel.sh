#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
work_directory="${repository_root}/work/barbican"
control_path="${work_directory}/rgw-kms-tunnel.sock"
devstack_ip="${COFFER_DEVSTACK_IP:-192.168.64.6}"

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
  -o "ControlPath=${control_path}"
)

check_tunnel() {
  ssh "${ssh_options[@]}" -O check "${guest}" >/dev/null 2>&1
}

case "${1:-}" in
  start)
    install -d -m 0700 "${work_directory}"
    if check_tunnel; then
      printf 'RGW Barbican reverse tunnel is already running\n'
      exit 0
    fi
    rm -f "${control_path}"
    ssh "${ssh_options[@]}" \
      -o ControlMaster=yes \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=3 \
      -fNT -R "127.0.0.1:19311:${devstack_ip}:443" "${guest}"
    check_tunnel
    printf 'RGW Barbican reverse tunnel started\n'
    ;;
  check)
    check_tunnel
    printf 'RGW Barbican reverse tunnel is running\n'
    ;;
  stop)
    if check_tunnel; then
      ssh "${ssh_options[@]}" -O exit "${guest}" >/dev/null
    fi
    rm -f "${control_path}"
    printf 'RGW Barbican reverse tunnel stopped\n'
    ;;
  *)
    printf 'usage: %s {start|check|stop}\n' "$0" >&2
    exit 2
    ;;
esac
