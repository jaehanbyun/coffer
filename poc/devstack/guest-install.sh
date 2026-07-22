#!/usr/bin/env bash
set -euo pipefail

devstack_dir="${COFFER_DEVSTACK_DIR:-${HOME}/devstack}"
branch="${COFFER_DEVSTACK_BRANCH:-stable/2026.1}"
commit="${COFFER_DEVSTACK_COMMIT:-da2f4d73f5ad74fc8ecfbe15bd7e20f6b0982dbb}"
marker="${HOME}/.coffer-devstack-installed"

if [[ "$(id -u)" -eq 0 ]]; then
  printf 'run guest-install.sh as the non-root Ubuntu user\n' >&2
  exit 1
fi

sudo chmod 755 "${HOME}"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git jq openssl

if [[ ! -d "${devstack_dir}/.git" ]]; then
  git clone --branch "${branch}" \
    https://opendev.org/openstack/devstack.git "${devstack_dir}"
fi

git -C "${devstack_dir}" fetch origin "${branch}"
git -C "${devstack_dir}" checkout --detach "${commit}"

host_ip="$(ip -4 route get 1.1.1.1 | \
  awk '{for (field = 1; field <= NF; field++) if ($field == "src") {print $(field + 1); exit}}')"
if [[ -z "${host_ip}" ]]; then
  printf 'could not determine the Lima IPv4 address\n' >&2
  exit 1
fi

ca_file="/opt/stack/data/CA/int-ca/ca-chain.pem"
if [[ -f "${marker}" ]] && \
  curl --fail --silent --show-error --cacert "${ca_file}" \
    "https://${host_ip}/identity/v3" >/dev/null; then
  test "$(git -C "${devstack_dir}" rev-parse HEAD)" = "${commit}"
  printf 'Pinned DevStack is already healthy at https://%s/identity/v3\n' \
    "${host_ip}"
  exit 0
fi

if [[ ! -f "${devstack_dir}/local.conf" ]]; then
  admin_password="$(openssl rand -hex 16)"
  literal_dollar='$'
  umask 077
  {
    printf '[[local|localrc]]\n\n'
    printf 'HOST_IP=%s\n' "${host_ip}"
    printf 'ADMIN_PASSWORD=%s\n' "${admin_password}"
    printf 'DATABASE_PASSWORD=%sADMIN_PASSWORD\n' "${literal_dollar}"
    printf 'SERVICE_PASSWORD=%sADMIN_PASSWORD\n\n' "${literal_dollar}"
    printf 'disable_all_services\n'
    printf 'enable_service key mysql tls-proxy\n\n'
    printf 'LOGFILE=%sDEST/logs/stack.sh.log\n' "${literal_dollar}"
    printf 'LOGDAYS=1\n'
  } >"${devstack_dir}/local.conf"
  chmod 600 "${devstack_dir}/local.conf"
  unset admin_password
fi

cd "${devstack_dir}"
./stack.sh

test -r "${ca_file}"
curl --fail --silent --show-error --cacert "${ca_file}" \
  "https://${host_ip}/identity/v3" >/dev/null

umask 077
{
  printf 'commit=%s\n' "$(git rev-parse HEAD)"
  printf 'host_ip=%s\n' "${host_ip}"
  printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >"${marker}"
chmod 600 "${marker}"

printf 'Pinned Keystone-only DevStack is healthy at https://%s/identity/v3\n' \
  "${host_ip}"
