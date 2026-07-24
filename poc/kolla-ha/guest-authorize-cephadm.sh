#!/usr/bin/env bash

set -Eeuo pipefail

expected_hostname="$1"
public_key_base64="$2"
begin_marker="# BEGIN COFFER STAGE5 CEPHADM"
end_marker="# END COFFER STAGE5 CEPHADM"

case "${expected_hostname}" in
    coffer-rgw-ha-stage5-storage-2|coffer-rgw-ha-stage5-storage-3) ;;
    *)
        echo "refusing a non-allowlisted cephadm SSH target" >&2
        exit 20
        ;;
esac
test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"

temporary_directory="$(mktemp -d)"
cleanup() {
    rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

printf '%s' "${public_key_base64}" |
    base64 --decode >"${temporary_directory}/ceph.pub"
test "$(wc -l <"${temporary_directory}/ceph.pub")" -eq 1
if ! grep -Eq \
    '^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}( .*)?$' \
    "${temporary_directory}/ceph.pub"; then
    echo "refusing an invalid cephadm public key" >&2
    exit 21
fi

install -d -o root -g root -m 0700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
awk \
    -v begin="${begin_marker}" \
    -v end="${end_marker}" \
    '
    $0 == begin {inside = 1; next}
    $0 == end {inside = 0; next}
    !inside {print}
    ' /root/.ssh/authorized_keys >"${temporary_directory}/authorized_keys"
{
    printf '%s\n' "${begin_marker}"
    cat "${temporary_directory}/ceph.pub"
    printf '%s\n' "${end_marker}"
} >>"${temporary_directory}/authorized_keys"
install -o root -g root -m 0600 \
    "${temporary_directory}/authorized_keys" /root/.ssh/authorized_keys

printf '%s cephadm_public_key=installed\n' "${expected_hostname}"
