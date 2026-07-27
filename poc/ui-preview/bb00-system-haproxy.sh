#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
system_config="/etc/haproxy/haproxy.cfg"
backup_config="/etc/haproxy/haproxy.cfg.coffer-ui-preview.bak"
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
snippet="${source_root}/bb00-system-haproxy.cfg"
legacy_snippet="${source_root}/bb00-system-haproxy-v1.cfg"
tailscale_address="100.123.168.66"
registry_fqdn="bb00.tail23b778.ts.net"
horizon_port="18443"
skyline_port="19999"
registry_port="18788"
tls_source_root="/home/jh.byun/coffer-registry-tls"
registry_cert_source="${tls_source_root}/registry.crt"
registry_key_source="${tls_source_root}/registry.key"
registry_ca_source="${tls_source_root}/registry-ca.crt"
backend_ca_source="${tls_source_root}/coffer-backend-ca.crt"
registry_pem="/etc/haproxy/certs/coffer-registry-preview.pem"
backend_ca="/etc/haproxy/ca-certificates/coffer-backend-ca.crt"
docker_ca_directory="/etc/docker/certs.d/${registry_fqdn}:${registry_port}"
docker_ca="${docker_ca_directory}/ca.crt"
begin_marker="# BEGIN COFFER UI PREVIEW"
end_marker="# END COFFER UI PREVIEW"

require_host() {
    test "$(id -u)" -eq 0
    test "$(hostname -s)" = "bb00"
    test -f "${system_config}"
    test ! -L "${system_config}"
    test -r "${snippet}"
    test -r "${legacy_snippet}"
    command -v haproxy >/dev/null
    command -v openssl >/dev/null
    command -v systemctl >/dev/null
}

validate_tls_sources() {
    for path in \
        "${registry_cert_source}" \
        "${registry_key_source}" \
        "${registry_ca_source}" \
        "${backend_ca_source}"; do
        test -f "${path}"
        test ! -L "${path}"
        test -s "${path}"
        test "$(stat -c '%U:%G' "${path}")" = "jh.byun:jh.byun"
    done
    test "$(stat -c '%a' "${registry_key_source}")" = 600
    test "$(stat -c '%a' "${registry_ca_source}")" = 600
    test "$(stat -c '%a' "${backend_ca_source}")" = 600
    openssl verify \
        -CAfile "${registry_ca_source}" \
        "${registry_cert_source}" >/dev/null
    openssl x509 \
        -in "${registry_cert_source}" \
        -checkhost "${registry_fqdn}" -noout >/dev/null
    openssl x509 \
        -in "${registry_cert_source}" \
        -checkend 86400 -noout >/dev/null
    local key_hash
    local cert_hash
    key_hash="$(
        openssl pkey -in "${registry_key_source}" -pubout -outform DER \
            2>/dev/null |
            sha256sum |
            cut -d' ' -f1
    )"
    cert_hash="$(
        openssl x509 -in "${registry_cert_source}" -pubkey -noout |
            openssl pkey -pubin -outform DER 2>/dev/null |
            sha256sum |
            cut -d' ' -f1
    )"
    test "${key_hash}" = "${cert_hash}"
}

install_tls_material() (
    local temporary_pem

    validate_tls_sources
    install -d -o root -g root -m 0750 /etc/haproxy/certs
    install -d -o root -g root -m 0755 /etc/haproxy/ca-certificates
    install -d -o root -g root -m 0755 "${docker_ca_directory}"
    temporary_pem="$(mktemp /etc/haproxy/certs/.coffer-registry.XXXXXX)"
    trap 'rm -f -- "${temporary_pem}"' EXIT
    (
        umask 077
        cp "${registry_key_source}" "${temporary_pem}"
        cat "${registry_cert_source}" >>"${temporary_pem}"
    )
    install -o root -g root -m 0600 "${temporary_pem}" "${registry_pem}"
    install -o root -g root -m 0644 "${backend_ca_source}" "${backend_ca}"
    install -o root -g root -m 0644 "${registry_ca_source}" "${docker_ca}"
)

remove_tls_material() {
    rm -f -- "${registry_pem}" "${backend_ca}" "${docker_ca}"
    rmdir -- "${docker_ca_directory}" 2>/dev/null || true
}

render_candidate() {
    local operation="$1"
    local output="$2"

    python3 - \
        "${system_config}" "${snippet}" "${legacy_snippet}" "${output}" \
        "${operation}" "${begin_marker}" "${end_marker}" <<'PY'
from pathlib import Path
import sys

config_path, snippet_path, legacy_path, output_path = map(Path, sys.argv[1:5])
operation, begin_marker, end_marker = sys.argv[5:]
config = config_path.read_text(encoding="utf-8")
snippet = snippet_path.read_text(encoding="utf-8").strip()
legacy = legacy_path.read_text(encoding="utf-8").strip()
begin_count = config.count(begin_marker)
end_count = config.count(end_marker)
if begin_count != end_count or begin_count > 1:
    raise SystemExit("Coffer preview marker ownership is invalid")

if begin_count:
    begin = config.index(begin_marker)
    end = config.index(end_marker, begin) + len(end_marker)
    current = config[begin:end].strip()
else:
    begin = end = -1
    current = ""

if current and current not in {snippet, legacy}:
    raise SystemExit("refusing to change a different Coffer preview block")

if operation == "install":
    if current == snippet:
        rendered = config
    elif current == legacy:
        rendered = config[:begin] + snippet + config[end:]
    else:
        rendered = config.rstrip() + "\n\n" + snippet + "\n"
elif operation == "remove":
    if not current:
        rendered = config
    else:
        rendered = (config[:begin].rstrip() + "\n\n" + config[end:].lstrip())
else:
    raise SystemExit(f"unsupported operation: {operation}")

Path(output_path).write_text(rendered, encoding="utf-8")
PY
}

apply_config() (
    local operation="$1"
    local previous_config
    local temporary_config

    temporary_config="$(mktemp /etc/haproxy/haproxy.cfg.coffer.XXXXXX)"
    previous_config="$(mktemp /etc/haproxy/haproxy.cfg.previous.XXXXXX)"
    trap 'rm -f -- "${temporary_config}" "${previous_config}"' EXIT
    cp --archive "${system_config}" "${previous_config}"
    if test "${operation}" = install; then
        install_tls_material
    fi
    render_candidate "${operation}" "${temporary_config}"
    haproxy -c -f "${temporary_config}"
    if cmp --silent "${system_config}" "${temporary_config}"; then
        return
    fi
    if test ! -e "${backup_config}"; then
        cp --archive "${system_config}" "${backup_config}"
    fi
    install -o root -g root -m 0644 "${temporary_config}" "${system_config}"
    if ! systemctl reload haproxy ||
        ! systemctl is-active --quiet haproxy; then
        install -o root -g root -m 0644 \
            "${previous_config}" "${system_config}"
        systemctl reload haproxy
        echo "HAProxy reload failed; restored the previous config" >&2
        exit 1
    fi
)

status() {
    local response_headers
    local status_code

    systemctl is-active haproxy
    grep -Fq "${begin_marker}" "${system_config}"
    ss -H -lnt \
        "sport = :${horizon_port} or sport = :${skyline_port} or sport = :${registry_port}"
    test "$(stat -c '%U:%G:%a' "${registry_pem}")" = "root:root:600"
    test "$(stat -c '%U:%G:%a' "${docker_ca}")" = "root:root:644"
    openssl x509 \
        -in "${registry_pem}" \
        -checkhost "${registry_fqdn}" -noout >/dev/null
    curl --insecure --fail --silent --show-error \
        --output /dev/null \
        --write-out "horizon_https=%{http_code}\n" \
        "https://${tailscale_address}:${horizon_port}/auth/login/"
    curl --insecure --fail --silent --show-error \
        --output /dev/null \
        --write-out "skyline_https=%{http_code}\n" \
        "https://${tailscale_address}:${skyline_port}/"
    response_headers="$(mktemp)"
    status_code="$(
        curl --silent --show-error \
            --cacert "${registry_ca_source}" \
            --dump-header "${response_headers}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "https://${registry_fqdn}:${registry_port}/v2/"
    )"
    test "${status_code}" = 401
    grep -Fqi \
        "realm=\"https://${registry_fqdn}:${registry_port}/auth/token\"" \
        "${response_headers}"
    rm -f -- "${response_headers}"
    echo "registry_https=${status_code}"
}

require_host
case "${action}" in
    install)
        apply_config install
        status
        ;;
    status)
        status
        ;;
    remove)
        apply_config remove
        remove_tls_material
        ;;
    *)
        echo "usage: $0 {install|status|remove}" >&2
        exit 64
        ;;
esac
