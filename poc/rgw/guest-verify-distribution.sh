#!/usr/bin/env bash

set -euo pipefail

container_name="coffer-distribution-rgw"
registry_host="coffer-rgw-poc"
registry_port="5443"
registry_url="https://${registry_host}:${registry_port}"
registry_ca="/etc/coffer-rgw/distribution-tls/ca.crt"
repository="p/00000000-0000-0000-0000-000000000003/real-rgw"
image_ref="${registry_host}:${registry_port}/${repository}:image"
busybox_ref="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
temporary_directory="$(mktemp -d /tmp/coffer-rgw-distribution.XXXXXX)"

cleanup() {
  rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

test "$(id -u)" -eq 0
test -f "${registry_ca}"
test -f /etc/coffer-rgw/distribution-runtime.env
test "$(podman inspect "${container_name}" --format '{{.State.Running}}')" = true
test "$(skopeo inspect "docker://${busybox_ref}" | jq -r '.Digest')" = \
  'sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028'

wait_for_distribution() {
  local status_code

  for _attempt in $(seq 1 60); do
    status_code="$(
      curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 3 --max-time 5 \
        --cacert "${registry_ca}" "${registry_url}/v2/" || true
    )"
    if test "${status_code}" = 200; then
      return 0
    fi
    sleep 2
  done
  return 1
}

pull_to_oci() {
  local destination="$1"

  skopeo copy --retry-times 3 \
    "docker://${image_ref}" "oci:${destination}:image" >/dev/null
  skopeo inspect --format '{{.Digest}}' "oci:${destination}:image"
}

wait_for_distribution
skopeo copy --retry-times 3 \
  "docker://${busybox_ref}" "docker://${image_ref}" >/dev/null
subject_digest="$(skopeo inspect --format '{{.Digest}}' "docker://${image_ref}")"
test -n "${subject_digest}"

before_digest="$(pull_to_oci "${temporary_directory}/before")"
test "${before_digest}" = "${subject_digest}"

podman restart "${container_name}" >/dev/null
wait_for_distribution
after_distribution_digest="$(pull_to_oci "${temporary_directory}/after-distribution")"
test "${after_distribution_digest}" = "${subject_digest}"

cephadm shell -- ceph orch restart rgw.coffer >/dev/null
for _attempt in $(seq 1 60); do
  rgw_status="$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 3 --max-time 5 \
      --cacert /etc/ceph/coffer-rgw-root-ca.crt \
      --resolve coffer-rgw-poc:8443:192.168.122.200 \
      https://coffer-rgw-poc:8443/ || true
  )"
  case "${rgw_status}" in
    200|403)
      break
      ;;
  esac
  sleep 2
done
case "${rgw_status}" in
  200|403) ;;
  *) exit 50 ;;
esac
wait_for_distribution
after_rgw_digest="$(pull_to_oci "${temporary_directory}/after-rgw")"
test "${after_rgw_digest}" = "${subject_digest}"

manifest_path="${temporary_directory}/manifest.json"
curl --fail --silent --show-error \
  --cacert "${registry_ca}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "${registry_url}/v2/${repository}/manifests/${subject_digest}" >"${manifest_path}"
layer_digest="$(jq -r '.layers[0].digest' "${manifest_path}")"
case "${layer_digest}" in
  sha256:[0-9a-f][0-9a-f]*) ;;
  *) exit 51 ;;
esac

headers_path="${temporary_directory}/blob-headers.txt"
blob_path="${temporary_directory}/blob"
blob_status="$(
  curl --silent --show-error \
    --dump-header "${headers_path}" \
    --output "${blob_path}" \
    --write-out '%{http_code}' \
    --cacert "${registry_ca}" \
    "${registry_url}/v2/${repository}/blobs/${layer_digest}"
)"
test "${blob_status}" = 200
if grep -Eiq '^location:' "${headers_path}"; then
  printf 'registry unexpectedly redirected a blob to the private RGW endpoint\n' >&2
  exit 52
fi
test "sha256:$(sha256sum "${blob_path}" | cut -d' ' -f1)" = "${layer_digest}"

bucket_object_count="$(
  cephadm shell -- radosgw-admin bucket stats --bucket coffer-registry-poc | \
    jq -r '.usage["rgw.main"].num_objects'
)"
test "${bucket_object_count}" -gt 0

log_path="${temporary_directory}/distribution.log"
podman logs "${container_name}" >"${log_path}" 2>&1
while IFS='=' read -r _name secret_value; do
  test -n "${secret_value}"
  if grep -Fq -- "${secret_value}" "${log_path}"; then
    printf 'Distribution log contains a runtime secret\n' >&2
    exit 53
  fi
done </etc/coffer-rgw/distribution-runtime.env

cephadm shell -- ceph config set global mon_target_pg_per_osd 50 >/dev/null
manager_pg_target="$(
  cephadm shell -- ceph tell mgr.* config get mon_target_pg_per_osd | \
    jq -r '.mon_target_pg_per_osd'
)"
if test "${manager_pg_target}" -ne 50; then
  cephadm shell -- ceph orch restart mgr >/dev/null
  for _attempt in $(seq 1 60); do
    manager_pg_target="$(
      cephadm shell -- ceph tell mgr.* config get mon_target_pg_per_osd 2>/dev/null | \
        jq -r '.mon_target_pg_per_osd // 0' 2>/dev/null || true
    )"
    if test "${manager_pg_target:-0}" -eq 50; then
      break
    fi
    sleep 2
  done
  test "${manager_pg_target:-0}" -eq 50
fi

data_pool_pg_num="$(
  cephadm shell -- ceph osd pool get default.rgw.buckets.data pg_num --format json | \
    jq -r '.pg_num'
)"
if test "${data_pool_pg_num}" -gt 64; then
  cephadm shell -- ceph osd pool set default.rgw.buckets.data pg_num 64 >/dev/null
fi
cephadm shell -- ceph osd pool set \
  default.rgw.buckets.non-ec pg_autoscale_mode off >/dev/null
non_ec_pg_num="$(
  cephadm shell -- ceph osd pool get default.rgw.buckets.non-ec pg_num --format json | \
    jq -r '.pg_num'
)"
if test "${non_ec_pg_num}" -gt 16; then
  cephadm shell -- ceph osd pool set default.rgw.buckets.non-ec pg_num 16 >/dev/null
fi
for _attempt in $(seq 1 120); do
  pg_state="$(cephadm shell -- ceph pg stat --format json)"
  total_pgs="$(printf '%s' "${pg_state}" | jq -r '.pg_summary.num_pgs')"
  inactive_pgs="$(
    printf '%s' "${pg_state}" | \
      jq '[.pg_summary.num_pg_by_state[]? | select(.name != "active+clean") | .num] | add // 0'
  )"
  if test "${total_pgs}" -le 250 && test "${inactive_pgs}" -eq 0; then
    break
  fi
  sleep 2
done
test "${total_pgs}" -le 250
test "${inactive_pgs}" -eq 0
after_pg_merge_digest="$(pull_to_oci "${temporary_directory}/after-pg-merge")"
test "${after_pg_merge_digest}" = "${subject_digest}"

unexpected_health_count="$(
  cephadm shell -- ceph health --format json | \
    jq '[.checks | keys[]? | select(. != "POOL_NO_REDUNDANCY")] | length'
)"
test "${unexpected_health_count}" -eq 0

printf 'Distribution/RGW persistence passed digest=%s objects=%s\n' \
  "${subject_digest}" "${bucket_object_count}"
