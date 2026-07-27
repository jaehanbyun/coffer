#!/usr/bin/env bash

set -euo pipefail

expected_host="coffer-ui-preview-1"
config_root="/etc/kolla/config/coffer"
secret_directory="${config_root}/secrets"
public_directory="${config_root}/public"
inventory="/etc/kolla/all-in-one"
coffer_globals="/etc/kolla/coffer-globals.yml"
rgw_state="/home/ubuntu/coffer-ui-preview-1-rgw-user.json"
rgw_ca_input="/home/ubuntu/coffer-ui-preview-1-rgw-ca.crt"
key_id="ui-preview-20260727"
python_binary="/home/ubuntu/coffer-ui-preview/venv/bin/python3"
source_root="/home/ubuntu/coffer"
inventory_marker="# BEGIN COFFER UI PREVIEW GROUPS"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_host}"
test -x "${python_binary}"
test -f "${source_root}/poc/ui-preview/coffer-globals.yml"
test -f "${inventory}"
umask 077

if ! grep -Fq "${inventory_marker}" "${inventory}"; then
    cat >>"${inventory}" <<'EOF'

# BEGIN COFFER UI PREVIEW GROUPS
[coffer:children]
coffer-api
coffer-edge
coffer-registry
coffer-reconcile

[coffer-api:children]
control

[coffer-edge:children]
control

[coffer-registry:children]
control

[coffer-reconcile:children]
control
# END COFFER UI PREVIEW GROUPS
EOF
fi
test "$(grep -Fxc "${inventory_marker}" "${inventory}")" -eq 1
install -o root -g root -m 0644 \
    "${source_root}/poc/ui-preview/coffer-globals.yml" \
    "${coffer_globals}"

install -d -m 0700 "${secret_directory}"
install -d -m 0755 "${public_directory}"

write_random_file() {
    local output_path="$1"
    local encoding="$2"
    if test -e "${output_path}"; then
        test -s "${output_path}"
        test "$(stat -c '%a' "${output_path}")" = 600
        return
    fi
    case "${encoding}" in
        base64)
            openssl rand -base64 48 >"${output_path}"
            ;;
        hex)
            openssl rand -hex 32 >"${output_path}"
            ;;
        *)
            return 64
            ;;
    esac
    chmod 0600 "${output_path}"
}

write_random_file "${secret_directory}/database-password" base64
write_random_file "${secret_directory}/keystone-service-password" base64
write_random_file "${secret_directory}/distribution-http-secret" hex

if ! test -s "${secret_directory}/signing-key.pem"; then
    openssl genpkey \
        -algorithm RSA \
        -pkeyopt rsa_keygen_bits:3072 \
        -out "${secret_directory}/signing-key.pem" >/dev/null 2>&1
fi
chmod 0600 "${secret_directory}/signing-key.pem"

if ! test -s "${public_directory}/backend-ca.crt"; then
    openssl req -x509 -newkey rsa:3072 -nodes \
        -keyout "${secret_directory}/backend-ca-key.pem" \
        -out "${public_directory}/backend-ca.crt" \
        -days 14 \
        -subj "/CN=Coffer UI Preview backend CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "subjectKeyIdentifier=hash" >/dev/null 2>&1
fi
chmod 0600 "${secret_directory}/backend-ca-key.pem"
chmod 0644 "${public_directory}/backend-ca.crt"

if ! test -s "${public_directory}/backend.crt"; then
    temporary_config="$(mktemp /tmp/coffer-ui-preview-openssl.XXXXXX)"
    temporary_request="$(mktemp /tmp/coffer-ui-preview-request.XXXXXX)"
    trap 'rm -f -- "${temporary_config}" "${temporary_request}"' EXIT
    printf '%s\n' \
        '[req]' \
        'distinguished_name = dn' \
        'prompt = no' \
        'req_extensions = req_ext' \
        '[dn]' \
        "CN = ${expected_host}" \
        '[req_ext]' \
        "subjectAltName = DNS:${expected_host},IP:192.168.122.204,IP:192.168.122.205" \
        '[server_ext]' \
        'basicConstraints = critical,CA:FALSE' \
        'keyUsage = critical,digitalSignature,keyEncipherment' \
        'extendedKeyUsage = serverAuth' \
        "subjectAltName = DNS:${expected_host},IP:192.168.122.204,IP:192.168.122.205" \
        'subjectKeyIdentifier = hash' \
        'authorityKeyIdentifier = keyid,issuer' \
        >"${temporary_config}"
    openssl req -new -newkey rsa:3072 -nodes \
        -keyout "${secret_directory}/backend-key.pem" \
        -out "${temporary_request}" \
        -config "${temporary_config}" >/dev/null 2>&1
    openssl x509 -req \
        -in "${temporary_request}" \
        -CA "${public_directory}/backend-ca.crt" \
        -CAkey "${secret_directory}/backend-ca-key.pem" \
        -CAcreateserial \
        -out "${public_directory}/backend.crt" \
        -days 14 \
        -extensions server_ext \
        -extfile "${temporary_config}" >/dev/null 2>&1
    rm -f -- "${temporary_config}" "${temporary_request}"
    trap - EXIT
fi
chmod 0600 "${secret_directory}/backend-key.pem"
chmod 0644 "${public_directory}/backend.crt"
rm -f -- "${public_directory}/backend-ca.srl"

"${python_binary}" - \
    "${secret_directory}/signing-key.pem" \
    "${public_directory}/jwks.json" \
    "${key_id}" <<'PY'
import base64
import json
import os
import sys
import tempfile

from cryptography.hazmat.primitives import serialization

private_key_path, output_path, key_id = sys.argv[1:]
with open(private_key_path, "rb") as stream:
    public_numbers = serialization.load_pem_private_key(
        stream.read(), password=None
    ).public_key().public_numbers()


def encode(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


document = {
    "keys": [
        {
            "alg": "RS256",
            "e": encode(public_numbers.e),
            "kid": key_id,
            "kty": "RSA",
            "n": encode(public_numbers.n),
            "use": "sig",
        }
    ]
}
directory = os.path.dirname(output_path)
descriptor, temporary_path = tempfile.mkstemp(dir=directory)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True)
        stream.write("\n")
    os.chmod(temporary_path, 0o644)
    os.replace(temporary_path, output_path)
finally:
    if os.path.exists(temporary_path):
        os.unlink(temporary_path)
PY

if test -e "${rgw_state}" || test -e "${rgw_ca_input}"; then
    test "$(stat -c '%U:%G:%a' "${rgw_state}")" = ubuntu:ubuntu:600
    test -s "${rgw_ca_input}"
    test "$(jq -er '.user_id' "${rgw_state}")" = "coffer-ui-preview-1"
    test "$(jq -er '.keys | length' "${rgw_state}")" = 1
    jq -er '.keys[0].access_key' "${rgw_state}" \
        >"${secret_directory}/rgw-access-key"
    jq -er '.keys[0].secret_key' "${rgw_state}" \
        >"${secret_directory}/rgw-secret-key"
    install -o root -g root -m 0644 \
        "${rgw_ca_input}" "${public_directory}/rgw-ca.crt"
    chmod 0600 \
        "${secret_directory}/rgw-access-key" \
        "${secret_directory}/rgw-secret-key"
    rm -f -- "${rgw_state}" "${rgw_ca_input}"
fi

test -s "${secret_directory}/rgw-access-key"
test -s "${secret_directory}/rgw-secret-key"
test -s "${public_directory}/rgw-ca.crt"
openssl pkey \
    -in "${secret_directory}/signing-key.pem" \
    -check -noout >/dev/null 2>&1
openssl verify \
    -CAfile "${public_directory}/backend-ca.crt" \
    "${public_directory}/backend.crt" >/dev/null
openssl verify \
    -CAfile "${public_directory}/backend-ca.crt" \
    -verify_ip 192.168.122.204 \
    "${public_directory}/backend.crt" >/dev/null
"${python_binary}" -m json.tool "${public_directory}/jwks.json" >/dev/null

if find "${secret_directory}" -type f ! -perm 0600 -print -quit |
    grep -q .; then
    echo "owner-only Coffer secret mode validation failed" >&2
    exit 1
fi

echo "Coffer UI preview owner-only inputs prepared"
