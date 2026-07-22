#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/../.." && pwd)"
work_dir="${repo_dir}/work/devstack"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
ca_file="${work_dir}/devstack-ca.pem"
bindings_file="${work_dir}/bindings.env"

command -v limactl >/dev/null || {
  printf 'missing required command: limactl\n' >&2
  exit 1
}

instance_ip="$(limactl shell "${instance}" ip -4 route get 1.1.1.1 | \
  awk '{for (field = 1; field <= NF; field++) if ($field == "src") {print $(field + 1); exit}}')"

mkdir -p "${work_dir}"
chmod 700 "${work_dir}"
rm -f "${ca_file}"
limactl copy \
  "${instance}:/opt/stack/data/CA/int-ca/ca-chain.pem" "${ca_file}"
chmod 600 "${ca_file}"

umask 077
{
  printf 'COFFER_DEVSTACK_INSTANCE=%q\n' "${instance}"
  printf 'COFFER_DEVSTACK_IP=%q\n' "${instance_ip}"
  printf 'COFFER_DEVSTACK_AUTH_URL=%q\n' \
    "https://${instance_ip}/identity/v3"
  printf 'COFFER_DEVSTACK_CAFILE=%q\n' "${ca_file}"
} >"${bindings_file}"

printf 'Exported public DevStack CA: %s\n' "${ca_file}"
printf 'Wrote non-secret bindings: %s\n' "${bindings_file}"
