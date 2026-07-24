#!/usr/bin/env bash

set -euo pipefail

action="${1:-}"
uid="coffer-kolla-aio-stage4"
state_file="/root/coffer-kolla-aio-stage4-user.json"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-rgw-poc"

case "${action}" in
  prepare)
    if cephadm shell -- radosgw-admin user info \
      --uid="${uid}" >/dev/null 2>&1; then
      echo "refusing to replace existing Stage 4 RGW identity" >&2
      exit 17
    fi
    test ! -e "${state_file}"
    temporary_state="$(mktemp /root/coffer-kolla-aio-stage4.XXXXXX)"
    trap 'rm -f -- "${temporary_state}"' EXIT
    cephadm shell -- radosgw-admin user create \
      --uid="${uid}" \
      --display-name="Coffer Kolla AIO Stage 4" \
      --max-buckets=1 \
      --generate-key=true >"${temporary_state}"
    jq -e \
      '.user_id == "coffer-kolla-aio-stage4" and (.keys | length) == 1' \
      "${temporary_state}" >/dev/null
    chmod 0600 "${temporary_state}"
    mv "${temporary_state}" "${state_file}"
    trap - EXIT
    echo "Stage 4 RGW identity created"
    ;;
  cleanup)
    if cephadm shell -- radosgw-admin user info \
      --uid="${uid}" >/dev/null 2>&1; then
      cephadm shell -- radosgw-admin user rm \
        --uid="${uid}" \
        --purge-data
    fi
    rm -f -- "${state_file}"
    if cephadm shell -- radosgw-admin user info \
      --uid="${uid}" >/dev/null 2>&1; then
      echo "Stage 4 RGW identity cleanup failed" >&2
      exit 1
    fi
    echo "Stage 4 RGW identity removed"
    ;;
  *)
    echo "usage: $0 prepare|cleanup" >&2
    exit 64
    ;;
esac
