#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
expected_hostname="coffer-ui-preview-1"
kolla_commit="cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc"
state_root="/home/ubuntu/coffer-ui-preview"
source_root="${state_root}/kolla-ansible"
venv="${state_root}/venv"
config_root="/etc/kolla"
inventory="${config_root}/all-in-one"
passwords="${config_root}/passwords.yml"
certificate_root="${config_root}/certificates-ui-preview"
coffer_source="/home/ubuntu/coffer"
log_root="${state_root}/logs"
owner_marker="${state_root}/OWNER"
install_marker="${state_root}/INSTALL_COMPLETE"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"

case "${action}" in
    prepare|status|bootstrap|prechecks|pull|deploy|post-deploy|reconfigure-skyline)
        ;;
    *)
        echo "usage: $0 {prepare|status|bootstrap|prechecks|pull|deploy|post-deploy|reconfigure-skyline}" >&2
        exit 64
        ;;
esac

install_certificate() {
    local temporary

    if test -s "${certificate_root}/haproxy.pem"; then
        openssl verify \
            -CAfile "${certificate_root}/ca/root.crt" \
            "${certificate_root}/haproxy.pem" >/dev/null
        return
    fi
    test ! -e "${certificate_root}"
    temporary="$(mktemp -d /etc/kolla/certificates-ui-preview.XXXXXX)"
    cleanup_certificate() {
        rm -rf -- "${temporary}"
    }
    trap cleanup_certificate EXIT
    openssl req -x509 -newkey rsa:3072 -nodes -sha256 \
        -keyout "${temporary}/root.key" \
        -out "${temporary}/root.crt" \
        -days 14 \
        -subj "/CN=Coffer UI Preview Kolla CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -addext "subjectKeyIdentifier=hash" >/dev/null 2>&1
    openssl req -new -newkey rsa:3072 -nodes -sha256 \
        -keyout "${temporary}/haproxy.key" \
        -out "${temporary}/haproxy.csr" \
        -subj "/CN=192.168.122.221" \
        -addext "subjectAltName=IP:192.168.122.221" >/dev/null 2>&1
    cat >"${temporary}/haproxy.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:192.168.122.221
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
    install -d -o root -g root -m 0755 "${certificate_root}/ca"
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
    openssl verify \
        -CAfile "${certificate_root}/ca/root.crt" \
        "${certificate_root}/haproxy.pem" >/dev/null
}

prepare() {
    export DEBIAN_FRONTEND=noninteractive

    test -f "${coffer_source}/poc/ui-preview/globals.yml"
    test -f "${coffer_source}/poc/ui-preview/skyline.yaml"
    install -d -o ubuntu -g ubuntu -m 0700 "${state_root}" "${log_root}"
    if test -e "${owner_marker}"; then
        test "$(cat "${owner_marker}")" = "${kolla_commit}"
    else
        printf '%s\n' "${kolla_commit}" >"${owner_marker}"
        chown ubuntu:ubuntu "${owner_marker}"
        chmod 0600 "${owner_marker}"
    fi

    apt-get update
    apt-get install -y \
        build-essential \
        curl \
        git \
        jq \
        libffi-dev \
        libssl-dev \
        python3-dbus \
        python3-dev \
        python3-venv

    if test ! -d "${source_root}/.git"; then
        sudo -u ubuntu git clone \
            --filter=blob:none \
            https://opendev.org/openstack/kolla-ansible \
            "${source_root}"
    fi
    sudo -u ubuntu git -C "${source_root}" fetch \
        --depth=1 origin "${kolla_commit}"
    sudo -u ubuntu git -C "${source_root}" checkout --detach "${kolla_commit}"
    test "$(git -C "${source_root}" rev-parse HEAD)" = "${kolla_commit}"

    if test ! -x "${venv}/bin/python3"; then
        sudo -u ubuntu python3 -m venv --system-site-packages "${venv}"
    fi
    if test ! -e "${install_marker}"; then
        sudo -u ubuntu env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
            "${venv}/bin/python3" -m pip install \
            --disable-pip-version-check --no-cache-dir --upgrade pip
        sudo -u ubuntu env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
            "${venv}/bin/python3" -m pip install \
            --disable-pip-version-check --no-cache-dir \
            docker "${source_root}"
        sudo -u ubuntu env \
            PATH="${venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
            LC_ALL=C.UTF-8 LANG=C.UTF-8 \
            "${venv}/bin/kolla-ansible" install-deps
        printf '%s\n' "${kolla_commit}" >"${install_marker}"
        chown ubuntu:ubuntu "${install_marker}"
        chmod 0600 "${install_marker}"
    fi
    "${venv}/bin/python3" -c 'import dbus, docker, kolla_ansible'

    install -d -o root -g root -m 0755 "${config_root}"
    if test ! -e "${inventory}"; then
        install -o root -g root -m 0644 \
            "${source_root}/ansible/inventory/all-in-one" "${inventory}"
    fi
    test -s "${inventory}"
    install -o root -g root -m 0644 \
        "${coffer_source}/poc/ui-preview/globals.yml" \
        "${config_root}/globals.yml"
    install -d -o root -g root -m 0755 \
        "${config_root}/config/skyline"
    install -o root -g root -m 0644 \
        "${coffer_source}/poc/ui-preview/skyline.yaml" \
        "${config_root}/config/skyline/skyline.yaml"
    if test ! -e "${passwords}"; then
        install -o root -g root -m 0600 \
            "${source_root}/etc/kolla/passwords.yml" "${passwords}"
        "${venv}/bin/kolla-genpwd" -p "${passwords}"
    fi
    chmod 0600 "${passwords}"
    install_certificate

    if ! grep -Fq '192.168.122.200 coffer-rgw-poc' /etc/hosts; then
        printf '%s\n' '192.168.122.200 coffer-rgw-poc' >>/etc/hosts
    fi
    printf '%s\n' "${kolla_commit}" >"${state_root}/prepare.complete"
    chmod 0600 "${state_root}/prepare.complete"
    printf 'preview_kolla prepared commit=%s passwords=owner-only tls=ready\n' \
        "${kolla_commit}"
}

verify_log_secret_free() {
    local log="$1"

    "${venv}/bin/python3" - "${passwords}" "${log}" <<'PY'
from pathlib import Path
import base64
import sys
import urllib.parse

import yaml

passwords = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
data = Path(sys.argv[2]).read_bytes()
for value in passwords.values():
    if not isinstance(value, str) or len(value) < 8:
        continue
    raw = value.encode()
    candidates = {
        raw,
        urllib.parse.quote(value, safe="").encode(),
        base64.b64encode(raw),
    }
    if any(candidate in data for candidate in candidates):
        raise SystemExit("generated credential found in Kolla lifecycle log")
PY
}

run_kolla() {
    local phase="$1"
    local timeout_seconds="$2"
    shift 2
    local log="${log_root}/${phase}.log"
    local rc

    install -o root -g root -m 0600 /dev/null "${log}"
    set +e
    env \
        PATH="${venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        LC_ALL=C.UTF-8 \
        LANG=C.UTF-8 \
        ANSIBLE_NOCOLOR=1 \
        ANSIBLE_NO_LOG=True \
        ANSIBLE_DEPRECATION_WARNINGS=False \
        ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
        timeout --signal=INT --kill-after=120 "${timeout_seconds}" \
        "${venv}/bin/kolla-ansible" "$@" \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        >"${log}" 2>&1
    rc="$?"
    set -e
    verify_log_secret_free "${log}"
    if test "${rc}" -ne 0; then
        tail -n 80 "${log}" >&2
        return "${rc}"
    fi
    awk '
        /^PLAY RECAP/ {capture = 1; next}
        capture && NF {print "kolla_recap " $0}
        capture && !NF {exit}
    ' "${log}"
    printf '%s\n' "${kolla_commit}" >"${state_root}/${phase}.complete"
    chmod 0600 "${state_root}/${phase}.complete"
}

require_phase() {
    local phase="$1"
    test "$(cat "${state_root}/${phase}.complete")" = "${kolla_commit}"
}

status() {
    local containers=0
    local nonrunning=0
    local unhealthy=0
    local internal_vip=0
    local external_vip=0
    local phase
    local phases=()

    for phase in bootstrap prechecks pull deploy post-deploy; do
        if test -f "${state_root}/${phase}.complete"; then
            phases+=("${phase}")
        fi
    done
    if command -v docker >/dev/null; then
        containers="$(docker ps -a --format '{{.Names}}' | wc -l)"
        nonrunning="$(
            docker ps -a --format '{{.Status}}' |
                awk '$1 != "Up" {count += 1} END {print count + 0}'
        )"
        unhealthy="$(
            docker ps --filter health=unhealthy --format '{{.Names}}' | wc -l
        )"
    fi
    if ip address show ens3 | grep -Fq '192.168.122.205/32'; then
        internal_vip=1
    fi
    if ip address show | grep -Fq '192.168.122.221/32'; then
        external_vip=1
    fi
    printf 'preview_kolla phases=%s containers=%s nonrunning=%s unhealthy=%s internal_vip=%s external_vip=%s\n' \
        "$(
            if test "${#phases[@]}" -eq 0; then
                printf none
            else
                IFS=,
                printf '%s' "${phases[*]}"
            fi
        )" \
        "${containers}" "${nonrunning}" "${unhealthy}" \
        "${internal_vip}" "${external_vip}"
}

case "${action}" in
    prepare)
        prepare
        ;;
    status)
        status
        ;;
    bootstrap)
        require_phase prepare
        run_kolla bootstrap 3600 bootstrap-servers
        ;;
    prechecks)
        require_phase bootstrap
        run_kolla prechecks 1800 prechecks --use-test-images
        ;;
    pull)
        require_phase prechecks
        run_kolla pull 5400 pull
        ;;
    deploy)
        require_phase pull
        run_kolla deploy 7200 deploy
        ;;
    post-deploy)
        require_phase deploy
        run_kolla post-deploy 1800 post-deploy
        ;;
    reconfigure-skyline)
        require_phase deploy
        run_kolla reconfigure-skyline 3600 reconfigure --tags skyline
        ;;
esac
