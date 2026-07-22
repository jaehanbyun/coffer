#!/usr/bin/env bash
set -euo pipefail

devstack_dir="${COFFER_DEVSTACK_DIR:-${HOME}/devstack}"
devstack_commit="da2f4d73f5ad74fc8ecfbe15bd7e20f6b0982dbb"
barbican_commit="${COFFER_BARBICAN_COMMIT:-586152c223b9e1373f5e422276bcaa152686b761}"
barbican_repo="https://opendev.org/openstack/barbican.git"
state_dir="${HOME}/.coffer-barbican"
stack_log="${state_dir}/stack.log"
marker="${state_dir}/installed.env"
local_conf="${devstack_dir}/local.conf"
ca_file="/opt/stack/data/CA/int-ca/ca-chain.pem"
literal_dollar='$'

test "$(id -u)" -ne 0
test "$(git -C "${devstack_dir}" rev-parse HEAD)" = "${devstack_commit}"
test -f "${local_conf}"
test "$(stat -c '%a' "${local_conf}")" = 600

host_ip="$(awk -F= '$1 == "HOST_IP" {print $2; exit}' "${local_conf}")"
test -n "${host_ip}"

install -d -m 0700 "${state_dir}"
if [[ ! -f "${state_dir}/local.conf.before-barbican" ]]; then
  install -m 0600 "${local_conf}" \
    "${state_dir}/local.conf.before-barbican"
fi

if ! grep -Eq '^RABBIT_PASSWORD=' "${local_conf}"; then
  printf 'RABBIT_PASSWORD=%sADMIN_PASSWORD\n' "${literal_dollar}" \
    >>"${local_conf}"
fi
if ! grep -Eq '^BARBICAN_HOST_HREF=' "${local_conf}"; then
  printf 'BARBICAN_HOST_HREF=https://%s/key-manager\n' "${host_ip}" \
    >>"${local_conf}"
fi

if ! grep -Fq 'enable_plugin barbican ' "${local_conf}"; then
  {
    printf '\n# Coffer disposable Barbican KMS PoC\n'
    printf 'enable_service rabbit\n'
    printf 'enable_plugin barbican %s %s\n' \
      "${barbican_repo}" "${barbican_commit}"
  } >>"${local_conf}"
fi

grep -Fxq "RABBIT_PASSWORD=${literal_dollar}ADMIN_PASSWORD" "${local_conf}"
grep -Fxq "BARBICAN_HOST_HREF=https://${host_ip}/key-manager" "${local_conf}"
grep -Fxq 'enable_service rabbit' "${local_conf}"
grep -Fxq "enable_plugin barbican ${barbican_repo} ${barbican_commit}" \
  "${local_conf}"

barbican_is_healthy() {
  test -f "${marker}" &&
    test -d /opt/stack/barbican/.git &&
    test "$(git -C /opt/stack/barbican rev-parse HEAD)" = \
      "${barbican_commit}" &&
    systemctl is-active --quiet devstack@barbican-svc.service &&
    systemctl is-active --quiet devstack@barbican-retry.service &&
    systemctl is-active --quiet devstack@barbican-keystone-listener.service &&
    systemctl is-active --quiet rabbitmq-server.service &&
    test "$(curl --silent --show-error --output /dev/null \
      --write-out '%{http_code}' --cacert "${ca_file}" \
      "https://${host_ip}/key-manager/v1")" = 401
}

if ! barbican_is_healthy; then
  umask 077
  if ! (cd "${devstack_dir}" && ./stack.sh) >"${stack_log}" 2>&1; then
    printf 'Barbican DevStack installation failed; private log retained at %s\n' \
      "${stack_log}" >&2
    printf 'error_line_count=%s\n' \
      "$(grep -Eic 'error|failed|traceback' "${stack_log}" || true)" >&2
    exit 1
  fi
  chmod 600 "${stack_log}"
  {
    printf 'devstack_commit=%s\n' "${devstack_commit}"
    printf 'barbican_commit=%s\n' "${barbican_commit}"
    printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"${marker}"
  chmod 600 "${marker}"
fi

barbican_is_healthy
set +u
# DevStack generates this runtime file inside the guest.
# shellcheck disable=SC1091
source "${devstack_dir}/openrc" admin admin
set -u

current_host_href="$(sudo awk -F= \
  '$1 ~ /^[[:space:]]*host_href[[:space:]]*$/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit}' \
  /etc/barbican/barbican.conf)"
if [[ "${current_host_href}" != "https://${host_ip}/key-manager" ]]; then
  test "$(sudo grep -Ec '^[[:space:]]*host_href[[:space:]]*=' \
    /etc/barbican/barbican.conf)" = 1
  sudo sed -i -E \
    "s|^([[:space:]]*host_href[[:space:]]*=).*|\\1 https://${host_ip}/key-manager|" \
    /etc/barbican/barbican.conf
  sudo systemctl restart devstack@barbican-svc.service
  systemctl is-active --quiet devstack@barbican-svc.service
fi

while read -r endpoint_id; do
  test -n "${endpoint_id}"
  openstack endpoint set --url "https://${host_ip}/key-manager" \
    "${endpoint_id}"
done < <(openstack endpoint list --service barbican -f value -c ID)

service_type="$(openstack service show barbican -f value -c type)"
test "${service_type}" = key-manager
endpoint_url="$(openstack endpoint list --service barbican --interface public \
  -f value -c URL)"
test "${endpoint_url}" = "https://${host_ip}/key-manager"

jq -n \
  --arg devstack_commit "${devstack_commit}" \
  --arg barbican_commit "${barbican_commit}" \
  --arg service_type "${service_type}" \
  --arg endpoint_url "${endpoint_url}" \
  --argjson tls_status 401 \
  '{devstack_commit:$devstack_commit, barbican_commit:$barbican_commit,
    service_type:$service_type, endpoint_url:$endpoint_url,
    tls_status:$tls_status, secrets_present:false}' \
  >/tmp/coffer-barbican-bootstrap-evidence.json
chmod 600 /tmp/coffer-barbican-bootstrap-evidence.json

printf 'Barbican service is healthy at the verified DevStack TLS endpoint\n'
