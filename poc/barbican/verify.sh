#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
ca_path="${repository_root}/work/devstack/devstack-ca.pem"
bindings_path="${repository_root}/work/devstack/bindings.env"

test -f "${ca_path}"
test -f "${bindings_path}"
# shellcheck disable=SC1090
source "${bindings_path}"
endpoint="https://${COFFER_DEVSTACK_IP}/key-manager/v1"

trusted_status="$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --cacert "${ca_path}" "${endpoint}")"
test "${trusted_status}" = 401
if curl --silent --show-error --output /dev/null "${endpoint}" \
  2>/dev/null; then
  printf 'Barbican unexpectedly trusted without the exported CA\n' >&2
  exit 1
fi

# The command substitution intentionally runs in the guest shell.
# shellcheck disable=SC2016
limactl shell "${instance}" bash -lc \
  'set -eu; test "$(sudo stat -c "%a" /etc/coffer-barbican/rgw.env)" = 600; test "$(sudo stat -c "%a" /etc/coffer-barbican)" = 700; systemctl is-active --quiet devstack@barbican-svc.service; systemctl is-active --quiet rabbitmq-server.service'

printf 'Barbican strict-TLS and owner-only runtime verification passed\n'
