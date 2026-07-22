#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
completed=false

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

remote_sudo() {
  # The argument is one of the fixed guest scripts copied by this harness.
  # shellcheck disable=SC2029
  ssh "${ssh_options[@]}" "${guest}" \
    sudo env LC_ALL=C LANG=C bash "$1"
}

rollback_on_failure() {
  local status=$?
  local cleanup_complete=false
  trap - EXIT
  if test "${completed}" != true; then
    if "${script_dir}/tunnel.sh" start >/dev/null 2>&1 &&
      remote_sudo /tmp/guest-restart-rgw.sh >/dev/null 2>&1 &&
      remote_sudo '/tmp/guest-run-kms-scenario.sh cleanup' >/dev/null 2>&1; then
      cleanup_complete=true
    fi
    if test "${cleanup_complete}" = true; then
      remote_sudo /tmp/guest-rollback-rgw-kms.sh >/dev/null 2>&1 || true
      "${script_dir}/tunnel.sh" stop >/dev/null 2>&1 || true
    else
      printf 'KMS cleanup requires recovery; preserving the KMS path and tunnel\n' >&2
    fi
  fi
  exit "${status}"
}
trap rollback_on_failure EXIT

scp "${ssh_options[@]}" \
  "${repository_root}/poc/rgw/guest-run-distribution.sh" \
  "${script_dir}/guest-assert-secrets-absent.py" \
  "${script_dir}/guest-ceph-kms-config.py" \
  "${script_dir}/guest-create-oci-layout.py" \
  "${script_dir}/guest-inspect-distribution-kms.py" \
  "${script_dir}/guest-kms-scenario-storage.py" \
  "${script_dir}/guest-restart-rgw.sh" \
  "${script_dir}/guest-rollback-rgw-kms.sh" \
  "${script_dir}/guest-run-kms-scenario.sh" \
  "${script_dir}/guest-verify-rgw-kms.py" \
  "${guest}:/tmp/"

"${script_dir}/tunnel.sh" start
remote_sudo '/tmp/guest-run-kms-scenario.sh zero-byte'
remote_sudo '/tmp/guest-run-kms-scenario.sh wrong-key'

"${script_dir}/tunnel.sh" stop
remote_sudo /tmp/guest-restart-rgw.sh
remote_sudo '/tmp/guest-run-kms-scenario.sh outage'

"${script_dir}/tunnel.sh" start
remote_sudo /tmp/guest-restart-rgw.sh
remote_sudo '/tmp/guest-run-kms-scenario.sh recovery'
remote_sudo '/tmp/guest-run-kms-scenario.sh cleanup'
remote_sudo /tmp/guest-rollback-rgw-kms.sh
"${script_dir}/tunnel.sh" stop
limactl stop "${instance}"

ssh "${ssh_options[@]}" "${guest}" \
  'rm -f /tmp/guest-run-distribution.sh /tmp/guest-assert-secrets-absent.py /tmp/guest-ceph-kms-config.py /tmp/guest-create-oci-layout.py /tmp/guest-inspect-distribution-kms.py /tmp/guest-kms-scenario-storage.py /tmp/guest-restart-rgw.sh /tmp/guest-rollback-rgw-kms.sh /tmp/guest-run-kms-scenario.sh /tmp/guest-verify-rgw-kms.py'
completed=true
trap - EXIT
printf 'Wrong-key, KMS-outage, recovery, and deterministic rollback passed\n'
