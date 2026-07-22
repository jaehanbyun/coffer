#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
barbican_commit="${COFFER_BARBICAN_COMMIT:-586152c223b9e1373f5e422276bcaa152686b761}"
work_dir="${repository_root}/work/barbican"

for command_name in jq limactl; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

instance_status="$(limactl list --format '{{.Name}} {{.Status}}' | \
  awk -v instance="${instance}" '$1 == instance {print $2}')"
test -n "${instance_status}"
if [[ "${instance_status}" != Running ]]; then
  limactl start "${instance}"
fi

limactl copy "${script_dir}/guest-install.sh" \
  "${instance}:/tmp/coffer-guest-install-barbican.sh"
limactl shell "${instance}" chmod 700 \
  /tmp/coffer-guest-install-barbican.sh
limactl shell "${instance}" env \
  COFFER_BARBICAN_COMMIT="${barbican_commit}" \
  /tmp/coffer-guest-install-barbican.sh

mkdir -p "${work_dir}"
chmod 700 "${work_dir}"
limactl copy "${instance}:/tmp/coffer-barbican-bootstrap-evidence.json" \
  "${work_dir}/bootstrap-evidence.json"
chmod 600 "${work_dir}/bootstrap-evidence.json"
limactl shell "${instance}" rm -f \
  /tmp/coffer-barbican-bootstrap-evidence.json

"${repository_root}/poc/devstack/export-ca.sh"
jq -e --arg commit "${barbican_commit}" \
  '.barbican_commit == $commit and .service_type == "key-manager" and
   .tls_status == 401' "${work_dir}/bootstrap-evidence.json" >/dev/null

printf 'Pinned Barbican bootstrap passed\n'
