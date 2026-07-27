#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
registry_fqdn="bb00.tail23b778.ts.net"
remote_host="jh.byun@100.123.168.66"
local_root="${HOME}/Library/Application Support/Coffer/preview-tls"
remote_root="/home/jh.byun/coffer-registry-tls"
root_key="${local_root}/registry-ca.key"
root_cert="${local_root}/registry-ca.crt"
leaf_key="${local_root}/registry.key"
leaf_request="${local_root}/registry.csr"
leaf_cert="${local_root}/registry.crt"
serial_file="${local_root}/registry-ca.srl"
openssl_binary="/opt/homebrew/opt/openssl@3/bin/openssl"

create() {
    umask 077
    test -x "${openssl_binary}"
    install -d -m 0700 "${local_root}"
    for path in "${root_key}" "${root_cert}" "${leaf_key}" "${leaf_cert}"; do
        test ! -L "${path}"
    done
    if test -e "${root_key}" || test -e "${root_cert}"; then
        test -s "${root_key}"
        test -s "${root_cert}"
    else
        "${openssl_binary}" req -x509 -newkey rsa:3072 -nodes \
            -keyout "${root_key}" \
            -out "${root_cert}" \
            -days 30 \
            -subj "/CN=Coffer owner preview CA" \
            -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
            -addext "keyUsage=critical,keyCertSign,cRLSign" \
            -addext "subjectKeyIdentifier=hash" >/dev/null 2>&1
    fi
    if test -e "${leaf_cert}"; then
        test -s "${leaf_key}"
        test -s "${leaf_cert}"
    else
        if test -s "${leaf_key}"; then
            "${openssl_binary}" req -new \
                -key "${leaf_key}" \
                -out "${leaf_request}" \
                -subj "/CN=${registry_fqdn}" \
                -addext "basicConstraints=critical,CA:FALSE" \
                -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
                -addext "extendedKeyUsage=serverAuth" \
                -addext "subjectAltName=DNS:${registry_fqdn}" >/dev/null 2>&1
        else
            "${openssl_binary}" req -new -newkey rsa:3072 -nodes \
                -keyout "${leaf_key}" \
                -out "${leaf_request}" \
                -subj "/CN=${registry_fqdn}" \
                -addext "basicConstraints=critical,CA:FALSE" \
                -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
                -addext "extendedKeyUsage=serverAuth" \
                -addext "subjectAltName=DNS:${registry_fqdn}" >/dev/null 2>&1
        fi
        "${openssl_binary}" x509 -req \
            -in "${leaf_request}" \
            -CA "${root_cert}" \
            -CAkey "${root_key}" \
            -CAcreateserial \
            -out "${leaf_cert}" \
            -days 14 \
            -copy_extensions copy >/dev/null 2>&1
        rm -f -- "${leaf_request}" "${serial_file}"
    fi
    chmod 0600 "${root_key}" "${root_cert}" "${leaf_key}" "${leaf_cert}"
    status
}

status() {
    test -d "${local_root}"
    test ! -L "${local_root}"
    test "$(stat -f '%Su:%Sg:%Lp' "${local_root}")" = \
        "${USER}:staff:700"
    for path in "${root_key}" "${root_cert}" "${leaf_key}" "${leaf_cert}"; do
        test -f "${path}"
        test ! -L "${path}"
        test "$(stat -f '%Su:%Sg:%Lp' "${path}")" = \
            "${USER}:staff:600"
    done
    "${openssl_binary}" verify \
        -CAfile "${root_cert}" "${leaf_cert}" >/dev/null
    "${openssl_binary}" x509 \
        -in "${leaf_cert}" \
        -checkhost "${registry_fqdn}" -noout >/dev/null
    "${openssl_binary}" x509 \
        -in "${leaf_cert}" -checkend 86400 -noout >/dev/null
    local key_hash
    local cert_hash
    key_hash="$(
        "${openssl_binary}" pkey \
            -in "${leaf_key}" -pubout -outform DER 2>/dev/null |
            shasum -a 256 |
            cut -d' ' -f1
    )"
    cert_hash="$(
        "${openssl_binary}" x509 -in "${leaf_cert}" -pubkey -noout |
            "${openssl_binary}" pkey -pubin -outform DER 2>/dev/null |
            shasum -a 256 |
            cut -d' ' -f1
    )"
    test "${key_hash}" = "${cert_hash}"
    echo "registry_tls=valid"
}

stage() {
    status
    ssh -o BatchMode=yes "${remote_host}" \
        "install -d -m 0700 '${remote_root}'"
    scp -q \
        "${root_cert}" \
        "${leaf_cert}" \
        "${leaf_key}" \
        "${remote_host}:${remote_root}/"
    ssh -o BatchMode=yes "${remote_host}" \
        "chmod 0600 '${remote_root}/registry-ca.crt' '${remote_root}/registry.crt' '${remote_root}/registry.key'; test \"\$(stat -c '%U:%G' '${remote_root}/registry.key')\" = 'jh.byun:jh.byun'"
    echo "registry_tls=staged"
}

case "${action}" in
    create)
        create
        ;;
    status)
        status
        ;;
    stage)
        stage
        ;;
    *)
        echo "usage: $0 {create|status|stage}" >&2
        exit 64
        ;;
esac
