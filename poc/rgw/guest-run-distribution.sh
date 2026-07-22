#!/usr/bin/env bash

set -euo pipefail

distribution_image="docker.io/library/registry@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
distribution_digest="sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
state_directory="/etc/coffer-rgw"
tls_directory="${state_directory}/distribution-tls"
config_path="${state_directory}/distribution-config.yml"
s3_env_path="${state_directory}/distribution.env"
runtime_env_path="${state_directory}/distribution-runtime.env"
http_secret_path="${state_directory}/distribution-http-secret"
container_name="coffer-distribution-rgw"
registry_host="coffer-rgw-poc"
registry_port="5443"
auth_realm="${COFFER_DISTRIBUTION_AUTH_REALM:-}"
auth_service="${COFFER_DISTRIBUTION_AUTH_SERVICE:-}"
auth_issuer="${COFFER_DISTRIBUTION_AUTH_ISSUER:-}"
auth_jwks_path="${COFFER_DISTRIBUTION_AUTH_JWKS:-}"
auth_container_jwks="/etc/distribution/jwks.json"
s3_encrypt="${COFFER_DISTRIBUTION_S3_ENCRYPT:-}"
s3_key_id="${COFFER_DISTRIBUTION_S3_KEY_ID:-}"
expected_status=200
auth_volume_args=()

test "$(id -u)" -eq 0
test -f /etc/ceph/coffer-rgw-root-ca.crt
test -f "${s3_env_path}"
test "$(stat -c '%a' "${s3_env_path}")" = 600
test "$(wc -l <"${s3_env_path}" | tr -d ' ')" -eq 2
grep -Eq '^REGISTRY_STORAGE_S3_ACCESSKEY=[[:alnum:]]+$' "${s3_env_path}"
grep -Eq '^REGISTRY_STORAGE_S3_SECRETKEY=[^[:space:]]+$' "${s3_env_path}"

if test -n "${auth_realm}"; then
  test -n "${auth_service}"
  test -n "${auth_issuer}"
  test -f "${auth_jwks_path}"
  jq -e '.keys | type == "array" and length >= 1' "${auth_jwks_path}" \
    >/dev/null
  expected_status=401
  auth_volume_args+=(
    --volume "${auth_jwks_path}:${auth_container_jwks}:ro"
  )
elif test -n "${auth_service}${auth_issuer}${auth_jwks_path}"; then
  printf 'Distribution token auth settings must be supplied together\n' >&2
  exit 21
fi

if test -z "${s3_encrypt}${s3_key_id}"; then
  s3_encrypt=false
elif test "${s3_encrypt}" = true &&
  [[ "${s3_key_id}" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]; then
  :
else
  printf 'Distribution S3 encryption requires true plus one UUID key ID\n' >&2
  exit 22
fi

umask 077
install -d -m 0700 "${state_directory}" "${tls_directory}"

tls_files=(ca.key ca.crt registry.key registry.csr registry.crt)
existing_tls_files=0
for tls_file in "${tls_files[@]}"; do
  if test -f "${tls_directory}/${tls_file}"; then
    existing_tls_files=$((existing_tls_files + 1))
  fi
done
if test "${existing_tls_files}" -ne 0 && test "${existing_tls_files}" -ne "${#tls_files[@]}"; then
  printf 'refusing to replace a partial Distribution TLS state\n' >&2
  exit 20
fi

if test "${existing_tls_files}" -eq 0; then
  extension_file="$(mktemp "${tls_directory}/extensions.XXXXXX")"
  trap 'rm -f "${extension_file}"' EXIT
  {
    printf 'basicConstraints=critical,CA:FALSE\n'
    printf 'keyUsage=critical,digitalSignature,keyEncipherment\n'
    printf 'extendedKeyUsage=serverAuth\n'
    printf 'subjectAltName=DNS:%s,DNS:coffer-registry-poc,IP:192.168.122.200\n' "${registry_host}"
  } >"${extension_file}"
  openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 30 \
    -subj '/CN=Coffer Distribution PoC CA' \
    -keyout "${tls_directory}/ca.key" \
    -out "${tls_directory}/ca.crt" >/dev/null 2>&1
  openssl req -new -newkey rsa:3072 -nodes -sha256 \
    -subj "/CN=${registry_host}" \
    -keyout "${tls_directory}/registry.key" \
    -out "${tls_directory}/registry.csr" >/dev/null 2>&1
  openssl x509 -req -sha256 -days 30 \
    -in "${tls_directory}/registry.csr" \
    -CA "${tls_directory}/ca.crt" \
    -CAkey "${tls_directory}/ca.key" \
    -CAcreateserial \
    -extfile "${extension_file}" \
    -out "${tls_directory}/registry.crt" >/dev/null 2>&1
  rm -f "${extension_file}"
  trap - EXIT
fi

chmod 0600 "${tls_directory}/ca.key" "${tls_directory}/registry.key"
chmod 0644 "${tls_directory}/ca.crt" "${tls_directory}/registry.crt"
openssl x509 -in "${tls_directory}/ca.crt" -noout -checkend 86400
openssl x509 -in "${tls_directory}/registry.crt" -noout -checkend 86400
certificate_sans="$(openssl x509 -in "${tls_directory}/registry.crt" -noout -ext subjectAltName)"
grep -Fq "DNS:${registry_host}" <<<"${certificate_sans}"
grep -Fq 'IP Address:192.168.122.200' <<<"${certificate_sans}"
key_fingerprint="$(openssl pkey -in "${tls_directory}/registry.key" -pubout 2>/dev/null | sha256sum | cut -d' ' -f1)"
cert_fingerprint="$(openssl x509 -in "${tls_directory}/registry.crt" -pubkey -noout | sha256sum | cut -d' ' -f1)"
test "${key_fingerprint}" = "${cert_fingerprint}"

if ! test -f "${http_secret_path}"; then
  openssl rand -hex 32 >"${http_secret_path}"
fi
chmod 0600 "${http_secret_path}"
test "$(wc -c <"${http_secret_path}" | tr -d ' ')" -eq 65

install -m 0600 "${s3_env_path}" "${runtime_env_path}"
printf 'REGISTRY_HTTP_SECRET=%s\n' "$(tr -d '\n' <"${http_secret_path}")" >>"${runtime_env_path}"
chmod 0600 "${runtime_env_path}"

{
  cat <<'EOF'
version: 0.1

log:
  level: info
  formatter: json
  fields:
    service: coffer-m3-rgw-distribution
EOF

  if test -n "${auth_realm}"; then
    cat <<EOF

auth:
  token:
    realm: ${auth_realm}
    service: ${auth_service}
    issuer: ${auth_issuer}
    jwks: ${auth_container_jwks}
    signingalgorithms: [RS256]
EOF
  fi

  cat <<'EOF'

storage:
  delete:
    enabled: true
  redirect:
    disable: true
  s3:
    region: us-east-1
    regionendpoint: https://192.168.122.200:8443
    forcepathstyle: true
    bucket: coffer-registry-poc
    rootdirectory: /distribution
    secure: true
    skipverify: false
    v4auth: true
EOF
  if test "${s3_encrypt}" = true; then
    printf '    encrypt: true\n'
    printf '    keyid: %s\n' "${s3_key_id}"
    # Tentacle returns S3 NotImplemented for an SSE-KMS CopyObject. Distribution
    # finalizes uploads with Move, so select its supported multipart-copy path.
    printf '    multipartcopythresholdsize: 0\n'
    printf '    multipartcopychunksize: 5242880\n'
    printf '    multipartcopymaxconcurrency: 4\n'
  fi
  cat <<'EOF'
  maintenance:
    uploadpurging:
      enabled: true
      age: 24h
      interval: 1h
      dryrun: false

http:
  addr: :5443
  tls:
    certificate: /etc/distribution/tls/registry.crt
    key: /etc/distribution/tls/registry.key
  headers:
    X-Content-Type-Options: [nosniff]

health:
  storagedriver:
    enabled: true
    interval: 10s
    threshold: 3
EOF
} >"${config_path}"
chmod 0644 "${config_path}"

install -d -m 0755 "/etc/containers/certs.d/${registry_host}:${registry_port}"
install -m 0644 "${tls_directory}/ca.crt" \
  "/etc/containers/certs.d/${registry_host}:${registry_port}/ca.crt"

test "$(skopeo inspect "docker://${distribution_image}" | jq -r '.Digest')" = "${distribution_digest}"
podman pull "${distribution_image}" >/dev/null
podman image inspect "${distribution_image}" --format '{{json .RepoDigests}}' | \
  jq -e --arg digest "${distribution_digest}" 'any(.[]; endswith("@" + $digest))' >/dev/null

if podman container exists "${container_name}"; then
  podman rm --force "${container_name}" >/dev/null
fi
podman run --detach \
  --name "${container_name}" \
  --label io.coffer.poc=distribution-rgw \
  --restart=no \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop=all \
  --security-opt no-new-privileges \
  --env-file "${runtime_env_path}" \
  --env SSL_CERT_FILE=/etc/distribution/rgw-ca.crt \
  --publish "${registry_port}:${registry_port}" \
  --volume "${config_path}:/etc/distribution/config.yml:ro" \
  --volume "/etc/ceph/coffer-rgw-root-ca.crt:/etc/distribution/rgw-ca.crt:ro" \
  --volume "${tls_directory}:/etc/distribution/tls:ro" \
  "${auth_volume_args[@]}" \
  "${distribution_image}" >/dev/null

for _attempt in $(seq 1 60); do
  status_code="$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 3 --max-time 5 \
      --cacert "${tls_directory}/ca.crt" \
      "https://${registry_host}:${registry_port}/v2/" || true
  )"
  if test "${status_code}" = "${expected_status}"; then
    break
  fi
  sleep 2
done
test "${status_code}" = "${expected_status}"

if curl --silent --show-error --output /dev/null \
  --connect-timeout 3 --max-time 5 \
  "https://${registry_host}:${registry_port}/v2/" 2>/dev/null; then
  printf 'Distribution unexpectedly trusted without its private lab CA\n' >&2
  exit 40
fi
plaintext_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 3 --max-time 5 \
    "http://${registry_host}:${registry_port}/v2/" 2>/dev/null || true
)"
test "${plaintext_status}" = 400

podman ps --filter "name=^${container_name}$" \
  --format 'name={{.Names}} image={{.Image}} status={{.Status}} ports={{.Ports}}'
