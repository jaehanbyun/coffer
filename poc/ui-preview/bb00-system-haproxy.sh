#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
system_config="/etc/haproxy/haproxy.cfg"
backup_config="/etc/haproxy/haproxy.cfg.coffer-ui-preview.bak"
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
snippet="${source_root}/bb00-system-haproxy.cfg"
tailscale_address="100.123.168.66"
horizon_port="18443"
skyline_port="19999"
begin_marker="# BEGIN COFFER UI PREVIEW"
end_marker="# END COFFER UI PREVIEW"

require_host() {
    test "$(id -u)" -eq 0
    test "$(hostname -s)" = "bb00"
    test -f "${system_config}"
    test ! -L "${system_config}"
    test -r "${snippet}"
    command -v haproxy >/dev/null
    command -v systemctl >/dev/null
}

render_candidate() {
    local operation="$1"
    local output="$2"

    python3 - \
        "${system_config}" "${snippet}" "${output}" \
        "${operation}" "${begin_marker}" "${end_marker}" <<'PY'
from pathlib import Path
import sys

config_path, snippet_path, output_path = map(Path, sys.argv[1:4])
operation, begin_marker, end_marker = sys.argv[4:]
config = config_path.read_text(encoding="utf-8")
snippet = snippet_path.read_text(encoding="utf-8").strip()
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

if current and current != snippet:
    raise SystemExit("refusing to change a different Coffer preview block")

if operation == "install":
    rendered = config if current else config.rstrip() + "\n\n" + snippet + "\n"
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
    systemctl is-active haproxy
    grep -Fq "${begin_marker}" "${system_config}"
    ss -H -lnt "sport = :${horizon_port} or sport = :${skyline_port}"
    curl --insecure --fail --silent --show-error \
        --output /dev/null \
        --write-out "horizon_https=%{http_code}\n" \
        "https://${tailscale_address}:${horizon_port}/auth/login/"
    curl --insecure --fail --silent --show-error \
        --output /dev/null \
        --write-out "skyline_https=%{http_code}\n" \
        "https://${tailscale_address}:${skyline_port}/"
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
        ;;
    *)
        echo "usage: $0 {install|status|remove}" >&2
        exit 64
        ;;
esac
