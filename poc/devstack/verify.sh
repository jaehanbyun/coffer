#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/../.." && pwd)"
work_dir="${repo_dir}/work/devstack"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
secret_tmp=""
authentication_ndjson=""
deletion_ndjson=""

cleanup() {
  limactl shell "${instance}" \
    /tmp/guest-verify.sh cleanup-host-fixture >/dev/null 2>&1 || true
  limactl shell "${instance}" \
    /tmp/guest-verify.sh cleanup-control-fixture >/dev/null 2>&1 || true
  if [[ -n "${secret_tmp}" && -d "${secret_tmp}" ]]; then
    rm -rf "${secret_tmp}"
  fi
  rm -f "${authentication_ndjson}" "${deletion_ndjson}"
}
trap cleanup EXIT

for command_name in curl jq limactl uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

mkdir -p "${work_dir}"
chmod 700 "${work_dir}"
"${script_dir}/export-ca.sh" >/dev/null
limactl copy "${script_dir}/guest-verify.sh" \
  "${instance}:/tmp/guest-verify.sh"
limactl shell "${instance}" chmod 700 /tmp/guest-verify.sh

# shellcheck disable=SC1091
source "${work_dir}/bindings.env"
curl --fail --silent --show-error --cacert "${COFFER_DEVSTACK_CAFILE}" \
  "${COFFER_DEVSTACK_AUTH_URL}" >/dev/null

limactl shell "${instance}" \
  /tmp/guest-verify.sh matrix | \
  tee "${work_dir}/keystone-verification.json"

secret_tmp="$(mktemp -d)"
chmod 700 "${secret_tmp}"
authentication_ndjson="${work_dir}/coffer-authentication.ndjson"
deletion_ndjson="${work_dir}/coffer-deletion.ndjson"
: >"${authentication_ndjson}"
: >"${deletion_ndjson}"

for requested_role in reader member admin service; do
  limactl shell "${instance}" \
    /tmp/guest-verify.sh prepare-host-fixture "${requested_role}" >/dev/null
  rm -f "${secret_tmp}/credential.json"
  limactl copy "${instance}:/tmp/coffer-host-credential.json" \
    "${secret_tmp}/credential.json"
  chmod 600 "${secret_tmp}/credential.json"

  if [[ "${requested_role}" = service ]]; then
    uv run --project "${repo_dir}" python \
      "${script_dir}/verify-coffer-auth.py" \
      --auth-url "${COFFER_DEVSTACK_AUTH_URL}" \
      --ca-file "${COFFER_DEVSTACK_CAFILE}" \
      --credential-file "${secret_tmp}/credential.json" \
      --expect valid --expect-role "${requested_role}" \
      --forbid-registry-roles | tee -a "${authentication_ndjson}"
  else
    uv run --project "${repo_dir}" python \
      "${script_dir}/verify-coffer-auth.py" \
      --auth-url "${COFFER_DEVSTACK_AUTH_URL}" \
      --ca-file "${COFFER_DEVSTACK_CAFILE}" \
      --credential-file "${secret_tmp}/credential.json" \
      --expect valid --expect-role "${requested_role}" | \
      tee -a "${authentication_ndjson}"
  fi

  limactl shell "${instance}" \
    /tmp/guest-verify.sh delete-host-credential >/dev/null
  uv run --project "${repo_dir}" python \
    "${script_dir}/verify-coffer-auth.py" \
    --auth-url "${COFFER_DEVSTACK_AUTH_URL}" \
    --ca-file "${COFFER_DEVSTACK_CAFILE}" \
    --credential-file "${secret_tmp}/credential.json" \
    --expect invalid | tee -a "${deletion_ndjson}"
done

jq -s . "${authentication_ndjson}" >"${work_dir}/coffer-authentication.json"
jq -s . "${deletion_ndjson}" >"${work_dir}/coffer-deletion.json"
rm -f "${authentication_ndjson}" "${deletion_ndjson}"
authentication_ndjson=""
deletion_ndjson=""

limactl shell "${instance}" \
  /tmp/guest-verify.sh cleanup-host-fixture >/dev/null
limactl shell "${instance}" \
  /tmp/guest-verify.sh prepare-control-fixture >/dev/null
rm -f "${secret_tmp}/control-fixture.json"
limactl copy "${instance}:/tmp/coffer-control-fixture.json" \
  "${secret_tmp}/control-fixture.json"
chmod 600 "${secret_tmp}/control-fixture.json"
uv run --project "${repo_dir}" python \
  "${script_dir}/verify-coffer-control.py" \
  --auth-url "${COFFER_DEVSTACK_AUTH_URL}" \
  --ca-file "${COFFER_DEVSTACK_CAFILE}" \
  --fixture-file "${secret_tmp}/control-fixture.json" \
  --instance "${instance}" \
  --database-file "${secret_tmp}/coffer-control.sqlite" | \
  tee "${work_dir}/coffer-control.json"
limactl shell "${instance}" \
  /tmp/guest-verify.sh cleanup-control-fixture >/dev/null

if rg -n -i 'secret|password|authorization|x-auth-token' \
  "${work_dir}/keystone-verification.json" \
  "${work_dir}/coffer-authentication.json" \
  "${work_dir}/coffer-deletion.json" \
  "${work_dir}/coffer-control.json"; then
  printf 'retained verification evidence contains a secret-shaped field\n' >&2
  exit 1
fi

printf 'Real Keystone TLS and Coffer application-credential verification passed.\n'
