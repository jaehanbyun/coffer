#!/usr/bin/env bash

set -euo pipefail

expected_host="coffer-kolla-aio-stage4"
config_root="/etc/kolla/config/coffer"
secret_directory="${config_root}/secrets"
public_directory="${config_root}/public"
backend_address="192.168.122.202"
key_id="stage4-20260724"
python_binary="${COFFER_STAGE4_PYTHON:-/home/ubuntu/kolla-venv/bin/python3}"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_host}"
test -x "${python_binary}"
umask 077

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
    base64) openssl rand -base64 48 >"${output_path}" ;;
    hex) openssl rand -hex 32 >"${output_path}" ;;
    *) return 64 ;;
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

backend_ca_is_usable() {
  test -s "${public_directory}/backend-ca.crt" &&
    test -s "${secret_directory}/backend-ca-key.pem" &&
    openssl x509 \
      -in "${public_directory}/backend-ca.crt" \
      -noout -ext basicConstraints 2>/dev/null |
      grep -Fq 'CA:TRUE' &&
    openssl x509 \
      -in "${public_directory}/backend-ca.crt" \
      -noout -ext keyUsage 2>/dev/null |
      grep -Fq 'Certificate Sign'
}

if ! backend_ca_is_usable; then
  rm -f -- \
    "${public_directory}/backend-ca.crt" \
    "${public_directory}/backend.crt" \
    "${secret_directory}/backend-ca-key.pem" \
    "${secret_directory}/backend-key.pem"
  openssl req -x509 -newkey rsa:3072 -nodes \
    -keyout "${secret_directory}/backend-ca-key.pem" \
    -out "${public_directory}/backend-ca.crt" \
    -days 7 \
    -subj "/CN=Coffer Stage 4 backend CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" >/dev/null 2>&1
fi
chmod 0600 "${secret_directory}/backend-ca-key.pem"
chmod 0644 "${public_directory}/backend-ca.crt"

if ! test -s "${public_directory}/backend.crt"; then
  temporary_config="$(mktemp /tmp/coffer-stage4-openssl.XXXXXX)"
  temporary_request="$(mktemp /tmp/coffer-stage4-request.XXXXXX)"
  trap 'rm -f -- "${temporary_config}" "${temporary_request}"' EXIT
  printf '%s\n' \
    '[req]' \
    'distinguished_name = dn' \
    'prompt = no' \
    'req_extensions = req_ext' \
    '[dn]' \
    "CN = ${expected_host}" \
    '[req_ext]' \
    "subjectAltName = DNS:${expected_host},IP:${backend_address}" \
    '[server_ext]' \
    'basicConstraints = critical,CA:FALSE' \
    'keyUsage = critical,digitalSignature,keyEncipherment' \
    'extendedKeyUsage = serverAuth' \
    "subjectAltName = DNS:${expected_host},IP:${backend_address}" \
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
    -days 7 \
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
    "keys": [{
        "alg": "RS256",
        "e": encode(public_numbers.e),
        "kid": key_id,
        "kty": "RSA",
        "n": encode(public_numbers.n),
        "use": "sig",
    }]
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

test -s "${secret_directory}/rgw-access-key"
test -s "${secret_directory}/rgw-secret-key"
chmod 0600 \
  "${secret_directory}/rgw-access-key" \
  "${secret_directory}/rgw-secret-key"
test -s "${public_directory}/rgw-ca.crt"
chmod 0644 "${public_directory}/rgw-ca.crt"

openssl pkey \
  -in "${secret_directory}/signing-key.pem" \
  -check -noout >/dev/null 2>&1
openssl verify \
  -CAfile "${public_directory}/backend-ca.crt" \
  "${public_directory}/backend.crt" >/dev/null
"${python_binary}" -m json.tool "${public_directory}/jwks.json" >/dev/null

find "${secret_directory}" -type f ! -perm 0600 -print -quit | \
  grep -q . && {
    echo "owner-only Coffer secret mode validation failed" >&2
    exit 1
  }

echo "Coffer Stage 4 owner-only inputs prepared"
