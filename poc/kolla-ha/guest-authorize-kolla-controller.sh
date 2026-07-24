#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 EXPECTED_HOST PUBLIC_KEY_FILE" >&2
    exit 64
fi

expected_hostname="$1"
public_key_file="$2"
authorized_keys="/home/ubuntu/.ssh/authorized_keys"
begin_marker="# BEGIN COFFER STAGE5 KOLLA"
end_marker="# END COFFER STAGE5 KOLLA"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test -f "${public_key_file}"
test "$(wc -l <"${public_key_file}" | tr -d ' ')" -eq 1
public_key="$(cat "${public_key_file}")"
[[ "${public_key}" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ coffer-stage5-kolla$ ]]
ssh-keygen -l -f "${public_key_file}" >/dev/null

begin_count="$(grep -Fxc "${begin_marker}" "${authorized_keys}" || true)"
end_count="$(grep -Fxc "${end_marker}" "${authorized_keys}" || true)"
test "${begin_count}" -eq "${end_count}"
test "${begin_count}" -le 1

if test "${begin_count}" -eq 1; then
    existing="$(
        sed -n \
            "/^${begin_marker}$/,/^${end_marker}$/p" \
            "${authorized_keys}"
    )"
    test "${existing}" = "$(
        printf '%s\n%s\n%s' \
            "${begin_marker}" "${public_key}" "${end_marker}"
    )"
else
    temporary="$(mktemp /home/ubuntu/.ssh/authorized_keys.XXXXXX)"
    cleanup() {
        rm -f -- "${temporary}" "${public_key_file}"
    }
    trap cleanup EXIT
    {
        cat "${authorized_keys}"
        printf '%s\n%s\n%s\n' \
            "${begin_marker}" "${public_key}" "${end_marker}"
    } >"${temporary}"
    chown ubuntu:ubuntu "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${authorized_keys}"
    trap - EXIT
fi

rm -f -- "${public_key_file}"
test "$(stat -c '%U:%G:%a' "${authorized_keys}")" = ubuntu:ubuntu:600
test "$(grep -Fxc "${begin_marker}" "${authorized_keys}")" -eq 1
test "$(grep -Fxc "${end_marker}" "${authorized_keys}")" -eq 1
printf 'kolla_authorize host=%s marker=1 private_key=absent\n' \
    "${expected_hostname}"
