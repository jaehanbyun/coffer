#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
expected_hostname="coffer-kolla-ha-stage5-controller-1"
commit="cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc"
state_root="/home/ubuntu/coffer-stage5"
owner_marker="${state_root}/OWNER"
source_root="${state_root}/kolla-ansible"
venv="${state_root}/venv"
install_marker="${state_root}/INSTALL_COMPLETE"
private_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
public_key="${private_key}.pub"
config_root="/etc/kolla"
certificate_root="${config_root}/certificates-stage5"

case "${action}" in
    key)
        test "$#" -eq 1 || exit 64
        ;;
    install)
        test "$#" -eq 3 || exit 64
        ;;
    *)
        echo "refusing an unknown Kolla primary preparation action" >&2
        exit 64
        ;;
esac

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"

ensure_owner() {
    if test -e "${state_root}" && test ! -f "${owner_marker}"; then
        echo "refusing an unowned controller-1 Kolla state directory" >&2
        exit 20
    fi
    install -d -o ubuntu -g ubuntu -m 0700 "${state_root}"
    if test -f "${owner_marker}"; then
        test "$(cat "${owner_marker}")" = "${commit}"
    else
        printf '%s\n' "${commit}" >"${owner_marker}"
        chown ubuntu:ubuntu "${owner_marker}"
        chmod 0600 "${owner_marker}"
    fi
}

ensure_key() {
    install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/.ssh
    if test -e "${private_key}" || test -e "${public_key}"; then
        test -f "${private_key}"
        test -f "${public_key}"
    else
        sudo -u ubuntu ssh-keygen \
            -q -t ed25519 -N '' \
            -C coffer-stage5-kolla \
            -f "${private_key}"
    fi
    test "$(stat -c '%U:%G:%a' "${private_key}")" = ubuntu:ubuntu:600
    test "$(stat -c '%U:%G:%a' "${public_key}")" = ubuntu:ubuntu:644
    test "$(wc -l <"${public_key}" | tr -d ' ')" -eq 1
    grep -Eq \
        '^ssh-ed25519 [A-Za-z0-9+/=]+ coffer-stage5-kolla$' \
        "${public_key}"
    ssh-keygen -l -f "${public_key}" >/dev/null
}

validate_config_inputs() {
    local inventory="$1"
    local globals="$2"

    test -f "${inventory}"
    test -f "${globals}"
    grep -Fq \
        "# Upstream commit: ${commit}" \
        "${inventory}"
    test "$(grep -c '^coffer-kolla-ha-stage5-controller-' "${inventory}")" \
        -eq 6
    python3 - "${globals}" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
required = (
    'openstack_release: "2026.1"',
    'kolla_internal_vip_address: "192.168.252.10"',
    'kolla_external_vip_address: "192.168.254.10"',
    "enable_openstack_core: false",
    "enable_keystone: true",
    "kolla_enable_tls_external: true",
)
if any(item not in text for item in required):
    raise SystemExit("Kolla globals contract mismatch")
PY
}

install_kolla() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y \
        build-essential \
        git \
        libffi-dev \
        libssl-dev \
        python3-dbus \
        python3-dev \
        python3-venv

    if test -e "${source_root}" && test ! -d "${source_root}/.git"; then
        echo "refusing non-Git Kolla source state" >&2
        exit 21
    fi
    if test ! -d "${source_root}/.git"; then
        sudo -u ubuntu git clone \
            --filter=blob:none \
            https://opendev.org/openstack/kolla-ansible \
            "${source_root}"
    fi
    sudo -u ubuntu git -C "${source_root}" fetch \
        --depth=1 origin "${commit}"
    sudo -u ubuntu git -C "${source_root}" checkout \
        --detach "${commit}"
    test "$(git -C "${source_root}" rev-parse HEAD)" = "${commit}"

    if test ! -x "${venv}/bin/python3"; then
        sudo -u ubuntu python3 -m venv \
            --system-site-packages "${venv}"
    fi
    if test ! -f "${install_marker}"; then
        sudo -u ubuntu env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
            "${venv}/bin/python3" -m pip install \
            --disable-pip-version-check --no-cache-dir --upgrade pip
        sudo -u ubuntu env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
            "${venv}/bin/python3" -m pip install \
            --disable-pip-version-check --no-cache-dir \
            docker "${source_root}"
        sudo -u ubuntu env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
            "${venv}/bin/kolla-ansible" install-deps
        printf '%s\n' "${commit}" >"${install_marker}"
        chown ubuntu:ubuntu "${install_marker}"
        chmod 0600 "${install_marker}"
    fi
    test "$(cat "${install_marker}")" = "${commit}"
    test -x "${venv}/bin/kolla-ansible"
    test -x "${venv}/bin/ansible-inventory"
    "${venv}/bin/python3" -c 'import dbus, docker, kolla_ansible'
}

install_config() {
    local inventory="$1"
    local globals="$2"

    install -d -o root -g root -m 0755 "${config_root}"
    install -o root -g root -m 0644 "${inventory}" \
        "${config_root}/multinode"
    install -o root -g root -m 0644 "${globals}" \
        "${config_root}/globals.yml"

    if test ! -e "${config_root}/passwords.yml"; then
        temporary_passwords="$(mktemp /etc/kolla/passwords.yml.XXXXXX)"
        cleanup_passwords() {
            rm -f -- "${temporary_passwords}"
        }
        trap cleanup_passwords EXIT
        install -o root -g root -m 0600 \
            "${source_root}/etc/kolla/passwords.yml" \
            "${temporary_passwords}"
        "${venv}/bin/kolla-genpwd" -p "${temporary_passwords}"
        mv -f -- "${temporary_passwords}" \
            "${config_root}/passwords.yml"
        trap - EXIT
    fi
    test "$(stat -c '%U:%G:%a' "${config_root}/passwords.yml")" = \
        root:root:600
    "${venv}/bin/python3" - "${config_root}/passwords.yml" <<'PY'
from pathlib import Path
import sys

import yaml

document = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in (
    "database_password",
    "keystone_admin_password",
    "keystone_database_password",
    "proxysql_admin_password",
    "rabbitmq_password",
):
    value = document.get(key)
    if not isinstance(value, str) or len(value) < 16:
        raise SystemExit(f"missing generated password: {key}")
PY
}

install_certificate() {
    local present=0
    local path
    local paths=(
        "${certificate_root}/private/root/root.key"
        "${certificate_root}/private/root/root.crt"
        "${certificate_root}/ca/root.crt"
        "${certificate_root}/haproxy.pem"
    )

    for path in "${paths[@]}"; do
        if test -e "${path}"; then
            present="$((present + 1))"
        fi
    done
    if test "${present}" -ne 0 && test "${present}" -ne 4; then
        echo "refusing an incomplete Kolla certificate set" >&2
        exit 22
    fi
    if test "${present}" -eq 0; then
        temporary="$(mktemp -d /etc/kolla/certificates-stage5.XXXXXX)"
        cleanup_certificate() {
            rm -rf -- "${temporary}"
        }
        trap cleanup_certificate EXIT
        openssl req -x509 -newkey rsa:3072 -nodes -sha256 \
            -keyout "${temporary}/root.key" \
            -out "${temporary}/root.crt" \
            -days 14 \
            -subj "/CN=Coffer Stage 5 Kolla CA" \
            -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
            -addext "keyUsage=critical,keyCertSign,cRLSign" \
            -addext "subjectKeyIdentifier=hash" >/dev/null 2>&1
        openssl req -new -newkey rsa:3072 -nodes -sha256 \
            -keyout "${temporary}/haproxy.key" \
            -out "${temporary}/haproxy.csr" \
            -subj "/CN=192.168.254.10" \
            -addext "subjectAltName=IP:192.168.254.10" >/dev/null 2>&1
        cat >"${temporary}/haproxy.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:192.168.254.10
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
        openssl x509 -req -sha256 -days 14 \
            -in "${temporary}/haproxy.csr" \
            -CA "${temporary}/root.crt" \
            -CAkey "${temporary}/root.key" \
            -CAcreateserial \
            -extfile "${temporary}/haproxy.ext" \
            -out "${temporary}/haproxy.crt" >/dev/null 2>&1
        install -d -o root -g root -m 0700 \
            "${certificate_root}/private/root"
        install -d -o root -g root -m 0755 \
            "${certificate_root}/ca"
        install -o root -g root -m 0600 \
            "${temporary}/root.key" \
            "${certificate_root}/private/root/root.key"
        install -o root -g root -m 0644 \
            "${temporary}/root.crt" \
            "${certificate_root}/private/root/root.crt"
        install -o root -g root -m 0644 \
            "${temporary}/root.crt" \
            "${certificate_root}/ca/root.crt"
        {
            cat "${temporary}/haproxy.crt"
            cat "${temporary}/haproxy.key"
        } >"${certificate_root}/haproxy.pem"
        chmod 0600 "${certificate_root}/haproxy.pem"
        cleanup_certificate
        trap - EXIT
    fi

    test "$(stat -c '%a' "${certificate_root}/private/root/root.key")" = 600
    test "$(stat -c '%a' "${certificate_root}/haproxy.pem")" = 600
    openssl verify \
        -CAfile "${certificate_root}/ca/root.crt" \
        "${certificate_root}/haproxy.pem" >/dev/null
    openssl x509 -in "${certificate_root}/haproxy.pem" \
        -noout -checkend 86400
    openssl x509 -in "${certificate_root}/haproxy.pem" \
        -noout -ext subjectAltName |
        grep -Fq 'IP Address:192.168.254.10'
}

ensure_owner
ensure_key

case "${action}" in
    key)
        printf 'kolla_primary key=ready private_mode=0600 owner=ubuntu\n'
        ;;
    install)
        inventory="$2"
        globals="$3"
        validate_config_inputs "${inventory}" "${globals}"
        install_kolla
        install_config "${inventory}" "${globals}"
        install_certificate
        printf 'kolla_primary source=%s venv=ready passwords=owner-only tls=ready bootstrap=not-run\n' \
            "${commit}"
        ;;
esac
