#!/usr/bin/env bash

set -euo pipefail

service_name="rgw.coffer"
container_filter='name=ceph-.*-rgw-coffer'
current_container=""
stable_container=""
previous_container="$(podman ps --filter "${container_filter}" \
  --format '{{.ID}}' | head -1)"
test -n "${previous_container}"
cephadm shell -- ceph orch restart "${service_name}" >/dev/null
for _attempt in $(seq 1 120); do
  current_container="$(podman ps --filter "${container_filter}" \
    --format '{{.ID}}' | head -1)"
  if test -n "${current_container}" &&
    test "${current_container}" != "${previous_container}"; then
    sleep 5
    stable_container="$(podman ps --filter "${container_filter}" \
      --format '{{.ID}}' | head -1)"
    if test "${stable_container}" = "${current_container}"; then
      break
    fi
  fi
  sleep 2
done
test -n "${current_container}"
test "${current_container}" != "${previous_container}"
test "${stable_container}" = "${current_container}"
for _attempt in $(seq 1 60); do
  status="$(curl --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --connect-timeout 3 --max-time 5 \
    --cacert /etc/ceph/coffer-rgw-root-ca.crt \
    --resolve coffer-rgw-poc:8443:192.168.122.200 \
    https://coffer-rgw-poc:8443/ || true)"
  case "${status}" in
    200|403) break ;;
  esac
  sleep 2
done
case "${status}" in
  200|403) ;;
  *) exit 30 ;;
esac
printf 'RGW restarted with a fresh process\n'
