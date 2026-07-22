#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
cpus="${COFFER_DEVSTACK_CPUS:-4}"
memory="${COFFER_DEVSTACK_MEMORY_GIB:-8}"
disk="${COFFER_DEVSTACK_DISK_GIB:-50}"
template="${COFFER_DEVSTACK_TEMPLATE:-ubuntu-24.04}"
branch="${COFFER_DEVSTACK_BRANCH:-stable/2026.1}"
commit="${COFFER_DEVSTACK_COMMIT:-da2f4d73f5ad74fc8ecfbe15bd7e20f6b0982dbb}"

require_command() {
  command -v "$1" >/dev/null || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 1
  }
}

require_command limactl

if [[ ! "${instance}" =~ ^[a-zA-Z0-9-]+$ ]]; then
  printf 'invalid Lima instance name: %s\n' "${instance}" >&2
  exit 1
fi

instance_status="$(limactl list --format '{{.Name}} {{.Status}}' | \
  awk -v instance="${instance}" '$1 == instance {print $2}')"
if [[ -z "${instance_status}" ]]; then
  limactl start --tty=false --name="${instance}" --cpus="${cpus}" \
    --memory="${memory}" --disk="${disk}" --vm-type=vz \
    --network=vzNAT --containerd=none --mount-none \
    "template:${template}"
else
  if [[ "${instance_status}" != Running ]]; then
    limactl start "${instance}"
  fi
fi

for guest_script in guest-install.sh guest-verify.sh; do
  limactl copy "${script_dir}/${guest_script}" \
    "${instance}:/tmp/${guest_script}"
done
limactl shell "${instance}" chmod 700 \
  /tmp/guest-install.sh /tmp/guest-verify.sh

limactl shell "${instance}" env \
  COFFER_DEVSTACK_BRANCH="${branch}" \
  COFFER_DEVSTACK_COMMIT="${commit}" \
  /tmp/guest-install.sh

"${script_dir}/export-ca.sh"

instance_ip="$(limactl shell "${instance}" ip -4 route get 1.1.1.1 | \
  awk '{for (field = 1; field <= NF; field++) if ($field == "src") {print $(field + 1); exit}}')"
printf 'DevStack identity endpoint: https://%s/identity/v3\n' "${instance_ip}"
printf 'Next: make -C %s verify\n' "${script_dir}"
