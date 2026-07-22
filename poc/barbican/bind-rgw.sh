#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
public_ca="${repository_root}/work/devstack/devstack-ca.pem"
guest_binding_script="${script_dir}/guest-bind-rgw.sh"
guest_rgw_script="${repository_root}/poc/rgw/guest-deploy-rgw.sh"

test -f "${known_hosts}"
test -f "${public_ca}"
test -f "${guest_binding_script}"
test -f "${guest_rgw_script}"

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

scp "${ssh_options[@]}" \
  "${public_ca}" "${guest}:/tmp/coffer-devstack-ca.pem"
scp "${ssh_options[@]}" \
  "${guest_binding_script}" "${guest}:/tmp/coffer-guest-bind-rgw.sh"
scp "${ssh_options[@]}" \
  "${guest_rgw_script}" "${guest}:/tmp/guest-deploy-rgw.sh"

# Stream the private binding from guest root to guest root. It is never copied
# to the Mac filesystem or emitted to command output.
limactl shell "${instance}" sudo cat /etc/coffer-barbican/rgw.env | \
  ssh "${ssh_options[@]}" "${guest}" \
    'sudo env LC_ALL=C LANG=C bash /tmp/coffer-guest-bind-rgw.sh install'

"${script_dir}/tunnel.sh" start
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-deploy-rgw.sh'
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/coffer-guest-bind-rgw.sh verify'
ssh "${ssh_options[@]}" "${guest}" \
  'rm -f /tmp/coffer-guest-bind-rgw.sh /tmp/guest-deploy-rgw.sh'

printf 'Owner-only Barbican binding and RGW daemon TLS reachability passed\n'
