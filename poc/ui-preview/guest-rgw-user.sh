#!/usr/bin/env bash

set -euo pipefail

action="${1:-}"
uid="coffer-ui-preview-1"
state_file="/home/coffer/coffer-ui-preview-1-user.json"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-rgw-poc"

case "${action}" in
    prepare)
        if cephadm shell -- radosgw-admin user info \
            --uid="${uid}" >/dev/null 2>&1; then
            echo "refusing to replace existing UI preview RGW identity" >&2
            exit 17
        fi
        test ! -e "${state_file}"
        temporary_state="$(mktemp /home/coffer/.coffer-ui-preview-1.XXXXXX)"
        trap 'rm -f -- "${temporary_state}"' EXIT
        cephadm shell -- radosgw-admin user create \
            --uid="${uid}" \
            --display-name="Coffer UI Preview 1" \
            --max-buckets=1 \
            --generate-key=true >"${temporary_state}"
        jq -e \
            '.user_id == "coffer-ui-preview-1" and (.keys | length) == 1' \
            "${temporary_state}" >/dev/null
        chown coffer:coffer "${temporary_state}"
        chmod 0600 "${temporary_state}"
        mv "${temporary_state}" "${state_file}"
        trap - EXIT
        echo "UI preview RGW identity created"
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
            echo "UI preview RGW identity cleanup failed" >&2
            exit 1
        fi
        echo "UI preview RGW identity removed"
        ;;
    *)
        echo "usage: $0 prepare|cleanup" >&2
        exit 64
        ;;
esac
