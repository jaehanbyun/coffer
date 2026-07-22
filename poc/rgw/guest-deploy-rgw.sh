#!/usr/bin/env bash

set -euo pipefail

service_name="rgw.coffer"
host_name="coffer-rgw-poc"
bind_network="192.168.122.0/24"
https_port="8443"
ca_path="/etc/ceph/coffer-rgw-root-ca.crt"
barbican_ca_bundle="/etc/coffer-rgw/devstack-ca-bundle.crt"

test "$(id -u)" -eq 0
test "$(hostname)" = "${host_name}"
test -f /etc/ceph/ceph.conf
test -f /etc/ceph/ceph.client.admin.keyring
grep -Fqx 'release=20.2.2' /etc/ceph/coffer-poc-release.txt

unexpected_rgw_services="$(
  cephadm shell -- ceph orch ls --format json | \
    jq -r --arg expected "${service_name}" \
      '.[] | select(.service_type == "rgw" and .service_name != $expected) | .service_name'
)"
test -z "${unexpected_rgw_services}"

apply_spec() {
  local extra_container_args=""
  if test -f "${barbican_ca_bundle}"; then
    extra_container_args="extra_container_args:
  - \"-v\"
  - \"${barbican_ca_bundle}:/etc/pki/tls/certs/ca-bundle.crt:ro\""
  fi
  cephadm shell -- ceph orch apply -i - "$@" <<EOF
service_type: rgw
service_id: coffer
placement:
  hosts:
    - ${host_name}
  count: 1
networks:
  - ${bind_network}
${extra_container_args}
spec:
  rgw_frontend_port: ${https_port}
  rgw_frontend_type: beast
  ssl: true
  generate_cert: true
  only_bind_port_on_networks: true
EOF
}

apply_spec --dry-run --format json-pretty
apply_spec

for _attempt in $(seq 1 120); do
  running_count="$(
    cephadm shell -- ceph orch ps --service_name "${service_name}" --format json | \
      jq '[.[] | select(.daemon_type == "rgw" and .status_desc == "running")] | length'
  )"
  if test "${running_count}" -eq 1; then
    break
  fi
  sleep 2
done
test "$(
  cephadm shell -- ceph orch ps --service_name "${service_name}" --format json | \
    jq '[.[] | select(.daemon_type == "rgw" and .status_desc == "running")] | length'
)" -eq 1

cephadm shell -- ceph orch certmgr cert get cephadm_root_ca_cert >"${ca_path}"
chmod 0644 "${ca_path}"
openssl x509 -in "${ca_path}" -noout -checkend 86400

for _attempt in $(seq 1 60); do
  status_code="$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 5 --max-time 10 \
      --cacert "${ca_path}" \
      --resolve "${host_name}:${https_port}:192.168.122.200" \
      "https://${host_name}:${https_port}/" || true
  )"
  case "${status_code}" in
    200|403)
      break
      ;;
  esac
  sleep 2
done
case "${status_code}" in
  200|403) ;;
  *)
    printf 'RGW HTTPS returned unexpected status %s\n' "${status_code}" >&2
    exit 51
    ;;
esac

if curl --silent --show-error --output /dev/null \
  --connect-timeout 5 --max-time 10 \
  --resolve "${host_name}:${https_port}:192.168.122.200" \
  "https://${host_name}:${https_port}/" 2>/dev/null; then
  printf 'RGW unexpectedly trusted without the cephadm root CA\n' >&2
  exit 50
fi

if curl --silent --show-error --output /dev/null \
  --connect-timeout 5 --max-time 10 \
  --resolve "${host_name}:${https_port}:192.168.122.200" \
  "http://${host_name}:${https_port}/" 2>/dev/null; then
  printf 'RGW TLS port unexpectedly accepted plaintext HTTP\n' >&2
  exit 52
fi

for _attempt in $(seq 1 60); do
  inactive_pgs="$(
    cephadm shell -- ceph pg stat --format json | \
      jq '[.pg_summary.num_pg_by_state[]? | select(.name != "active+clean") | .num] | add // 0'
  )"
  if test "${inactive_pgs}" -eq 0; then
    break
  fi
  sleep 2
done
test "${inactive_pgs}" -eq 0

pool_shape_valid="$(
  cephadm shell -- ceph osd pool ls detail --format json | \
    jq 'length > 0 and all(.[]; .size == 1 and .min_size == 1)'
)"
test "${pool_shape_valid}" = true

too_few_osds="$(
  cephadm shell -- ceph health --format json | \
    jq '[.checks | keys[]? | select(. == "TOO_FEW_OSDS")] | length'
)"
if test "${too_few_osds}" -ne 0; then
  manager_default_size="$(
    cephadm shell -- ceph tell mgr.* config get osd_pool_default_size | \
      jq -r '.osd_pool_default_size'
  )"
  if test "${manager_default_size}" -ne 1; then
    cephadm shell -- ceph orch restart mgr
  fi
fi

original_stray_interval="$(
  cephadm shell -- ceph config get mgr mgr/cephadm/stray_daemon_check_interval
)"
restore_stray_interval() {
  cephadm shell -- ceph config set mgr \
    mgr/cephadm/stray_daemon_check_interval "${original_stray_interval}" >/dev/null
}
trap restore_stray_interval EXIT
cephadm shell -- ceph config set mgr mgr/cephadm/stray_daemon_check_interval 5
for _attempt in $(seq 1 12); do
  stale_health_count="$(
    cephadm shell -- ceph health --format json | \
      jq '[.checks | keys[]? | select(
        . == "CEPHADM_STRAY_DAEMON" or
        . == "CEPHADM_STRAY_HOST" or
        . == "TOO_FEW_OSDS" or
        . == "PG_AVAILABILITY"
      )] | length'
  )"
  if test "${stale_health_count}" -eq 0; then
    break
  fi
  sleep 5
done
test "${stale_health_count}" -eq 0
restore_stray_interval
trap - EXIT

cephadm shell -- ceph orch ls --service_name "${service_name}" --format json-pretty
cephadm shell -- ceph orch ps --service_name "${service_name}" --format json-pretty
cephadm shell -- ceph status --format json-pretty
