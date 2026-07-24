#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {preflight|status|upgrade|rollback}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    preflight|status|upgrade|rollback)
        ;;
    *)
        echo "refusing an unknown Coffer rolling-update action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
source_root="${state_root}/coffer-operator-source"
entrypoint="${source_root}/ansible/kolla-ansible-coffer"
venv="${state_root}/venv"
inventory="/etc/kolla/multinode"
config_root="/etc/kolla"
passwords="${config_root}/passwords.yml"
coffer_globals="${config_root}/coffer-globals.yml"
update_marker="${state_root}/coffer-update-images/complete"
rolling_root="${state_root}/rolling-update"
owner_marker="${rolling_root}/owner"
upgrade_marker="${rolling_root}/upgrade.complete"
rollback_marker="${rolling_root}/rollback.complete"
upgrade_log="${rolling_root}/upgrade.log"
rollback_log="${rolling_root}/rollback.log"
temporary_globals="/run/coffer-stage5-rolling-globals.yml"
owner_value="coffer-stage5-rolling-update-v1"
current_image="localhost/coffer:stage5"
update_image="localhost/coffer:stage5-quota-retry"
registry_image="localhost/coffer-registry:stage5"
hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test -x "${entrypoint}"
test -x "${venv}/bin/kolla-ansible"
test "$(stat -c '%U:%G:%a' "${inventory}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${passwords}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${coffer_globals}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${deployment_key}")" = ubuntu:ubuntu:600
test "$(stat -c '%U:%G:%a' "${known_hosts}")" = ubuntu:ubuntu:644
test "$(stat -c '%U:%G:%a' "${update_marker}")" = root:root:600
grep -Fxq 'schema=coffer-stage5-update-images-v1' "${update_marker}"
current_image_id="$(sed -n 's/^current_image_id=//p' "${update_marker}")"
update_image_id="$(sed -n 's/^update_image_id=//p' "${update_marker}")"
[[ "${current_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "${update_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
test "${current_image_id}" != "${update_image_id}"
test "$(docker image inspect --format '{{.Id}}' "${current_image}")" = \
    "${current_image_id}"
test "$(docker image inspect --format '{{.Id}}' "${update_image}")" = \
    "${update_image_id}"
registry_image_id="$(
    docker image inspect --format '{{.Id}}' "${registry_image}"
)"
[[ "${registry_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]
test ! -e "${temporary_globals}"

ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=9
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
)

run_on_controller() {
    local index="$1"
    shift

    if test "${index}" -eq 0; then
        "$@"
    else
        sudo -u ubuntu ssh "${ssh_options[@]}" \
            "ubuntu@${addresses[${index}]}" \
            sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 "$@"
    fi
}

node_state() {
    local index="$1"
    local result

    if ! result="$(
        run_on_controller "${index}" bash -s -- \
            "${hostnames[${index}]}" "${current_image_id}" \
            "${update_image_id}" "${registry_image_id}" <<'REMOTE'
set -Eeuo pipefail
expected_hostname="$1"
current_image_id="$2"
update_image_id="$3"
registry_image_id="$4"
test "$(hostname)" = "${expected_hostname}"
for container in coffer_api coffer_edge coffer_registry; do
    test "$(docker inspect -f '{{.State.Running}}' "${container}")" = true
    test "$(docker inspect -f '{{.State.Health.Status}}' "${container}")" = healthy
done
api_id="$(docker inspect -f '{{.Image}}' coffer_api)"
edge_id="$(docker inspect -f '{{.Image}}' coffer_edge)"
registry_id="$(docker inspect -f '{{.Image}}' coffer_registry)"
test "${api_id}" = "${edge_id}"
case "${api_id}" in
    "${current_image_id}")
        state=current
        ;;
    "${update_image_id}")
        state=updated
        ;;
    *)
        exit 1
        ;;
esac
test "${registry_id}" = "${registry_image_id}"
printf 'host=%s state=%s api=healthy edge=healthy registry=current\n' \
    "${expected_hostname}" "${state}"
REMOTE
    )"; then
        return 1
    fi
    printf '%s\n' "${result}"
}

cluster_state() {
    local current=0
    local index
    local snapshot
    local updated=0

    for index in "${!addresses[@]}"; do
        snapshot="$(node_state "${index}")"
        case "${snapshot}" in
            *" state=current "*)
                current="$((current + 1))"
                ;;
            *" state=updated "*)
                updated="$((updated + 1))"
                ;;
            *)
                return 1
                ;;
        esac
    done
    printf 'current=%s updated=%s\n' "${current}" "${updated}"
}

wait_cluster_state() {
    local attempt
    local expected="$1"
    local snapshot=""

    for attempt in $(seq 1 90); do
        if snapshot="$(cluster_state)" && test "${snapshot}" = "${expected}"; then
            printf 'coffer_rolling_update convergence=%s attempt=%s\n' \
                "${expected// /,}" "${attempt}"
            return 0
        fi
        sleep 2
    done
    printf 'coffer_rolling_update convergence=failed expected=%s last=%s\n' \
        "${expected// /,}" "${snapshot:-unavailable}" >&2
    return 1
}

require_owner() {
    test "$(stat -c '%U:%G:%a' "${rolling_root}")" = root:root:700
    test "$(stat -c '%U:%G:%a' "${owner_marker}")" = root:root:600
    test "$(cat "${owner_marker}")" = "${owner_value}"
}

write_marker() {
    local marker="$1"
    local value="$2"
    local temporary="${marker}.tmp.$$"

    printf '%s\n' "${value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${marker}"
}

require_marker() {
    local marker="$1"
    local value="$2"

    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${value}"
}

create_globals() {
    local image="$1"

    test ! -e "${temporary_globals}"
    awk -v replacement="coffer_image_full: \"${image}\"" '
        $0 == "coffer_image_full: \"localhost/coffer:stage5\"" {
            print replacement
            replacements += 1
            next
        }
        {print}
        END {
            if (replacements != 1) {
                exit 1
            }
        }
    ' "${coffer_globals}" >"${temporary_globals}"
    chown root:root "${temporary_globals}"
    chmod 0600 "${temporary_globals}"
    "${venv}/bin/python3" - \
        "${coffer_globals}" "${temporary_globals}" "${image}" <<'PY'
from pathlib import Path
import sys

import yaml

original = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
updated = yaml.safe_load(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_image = sys.argv[3]
changed = {
    key
    for key in set(original) | set(updated)
    if original.get(key) != updated.get(key)
}
expected_changed = (
    set()
    if original["coffer_image_full"] == expected_image
    else {"coffer_image_full"}
)
if changed != expected_changed:
    raise SystemExit("rolling globals changed outside the Coffer image")
if updated["coffer_image_full"] != expected_image:
    raise SystemExit("rolling globals selected an unexpected Coffer image")
PY
}

verify_log() {
    local log="$1"

    test "$(stat -c '%U:%G:%a' "${log}")" = root:root:600
    ! grep -Eiq \
        '(authorization:|application_credential_secret|private key|password[=:])' \
        "${log}"
}

run_serial_upgrade() {
    local image="$1"
    local log="$2"
    local rc

    create_globals "${image}"
    cleanup_globals() {
        rm -f -- "${temporary_globals}"
    }
    trap cleanup_globals EXIT
    install -o root -g root -m 0600 /dev/null "${log}"
    set +e
    env \
        PATH="${venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        LC_ALL=C.UTF-8 \
        LANG=C.UTF-8 \
        ANSIBLE_NOCOLOR=1 \
        ANSIBLE_NO_LOG=True \
        ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
        KOLLA_ANSIBLE_PYTHON="${venv}/bin/python3" \
        timeout --signal=INT --kill-after=120 7200 \
        "${entrypoint}" upgrade \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        -e "@${temporary_globals}" \
        -e kolla_serial=1 \
        >"${log}" 2>&1
    rc="$?"
    set -e
    cleanup_globals
    trap - EXIT
    verify_log "${log}"
    if test "${rc}" -ne 0; then
        printf 'coffer_rolling_update ansible=failed rc=%s log=%s\n' \
            "${rc}" "${log}" >&2
        return "${rc}"
    fi
    awk '
        /^PLAY RECAP/ {capture = 1; next}
        capture && NF {print "coffer_rolling_recap " $0}
        capture && !NF {exit}
    ' "${log}"
}

snapshot="$(cluster_state)"
current_count="${snapshot%% *}"
current_count="${current_count#current=}"
updated_count="${snapshot##*updated=}"

if test "${action}" = preflight; then
    test ! -e "${rolling_root}"
    test "${current_count}" -eq 3
    test "${updated_count}" -eq 0
    printf 'coffer_rolling_update state=ready current=3 updated=0 mutation=none\n'
    exit 0
fi

if test "${action}" = status; then
    if test ! -e "${rolling_root}"; then
        test "${current_count}" -eq 3
        test "${updated_count}" -eq 0
        state=ready
    else
        require_owner
        if test -e "${rollback_marker}"; then
            require_marker \
                "${upgrade_marker}" \
                "from=${current_image_id} to=${update_image_id}"
            require_marker \
                "${rollback_marker}" \
                "from=${update_image_id} to=${current_image_id}"
            test "${current_count}" -eq 3
            test "${updated_count}" -eq 0
            state=rolled-back
        elif test -e "${upgrade_marker}"; then
            require_marker \
                "${upgrade_marker}" \
                "from=${current_image_id} to=${update_image_id}"
            test "${current_count}" -eq 0
            test "${updated_count}" -eq 3
            state=updated
        else
            test "${current_count}" -ge 0
            test "${updated_count}" -ge 0
            test "$((current_count + updated_count))" -eq 3
            state=partial
        fi
    fi
    printf 'coffer_rolling_update state=%s current=%s updated=%s mutation=none\n' \
        "${state}" "${current_count}" "${updated_count}"
    exit 0
fi

exec 9>/run/lock/coffer-stage5-rolling-update.lock
if ! flock -n 9; then
    echo "refusing concurrent Coffer rolling-update execution" >&2
    exit 75
fi
if test ! -e "${rolling_root}"; then
    install -d -o root -g root -m 0700 "${rolling_root}"
    write_marker "${owner_marker}" "${owner_value}"
fi
require_owner

case "${action}" in
    upgrade)
        test ! -e "${rollback_marker}"
        if test -e "${upgrade_marker}"; then
            require_marker \
                "${upgrade_marker}" \
                "from=${current_image_id} to=${update_image_id}"
            test "${current_count}" -eq 0
            test "${updated_count}" -eq 3
            printf 'coffer_rolling_update phase=upgrade result=passed idempotent=yes\n'
            exit 0
        fi
        test "$((current_count + updated_count))" -eq 3
        if test "${current_count}" -eq 0 && test "${updated_count}" -eq 3; then
            printf 'coffer_rolling_update phase=upgrade resume=postcheck\n'
        else
            run_serial_upgrade "${update_image}" "${upgrade_log}"
        fi
        wait_cluster_state 'current=0 updated=3'
        write_marker \
            "${upgrade_marker}" \
            "from=${current_image_id} to=${update_image_id}"
        ;;
    rollback)
        require_marker \
            "${upgrade_marker}" \
            "from=${current_image_id} to=${update_image_id}"
        if test -e "${rollback_marker}"; then
            require_marker \
                "${rollback_marker}" \
                "from=${update_image_id} to=${current_image_id}"
            test "${current_count}" -eq 3
            test "${updated_count}" -eq 0
            printf 'coffer_rolling_update phase=rollback result=passed idempotent=yes\n'
            exit 0
        fi
        test "$((current_count + updated_count))" -eq 3
        if test "${current_count}" -eq 3 && test "${updated_count}" -eq 0; then
            printf 'coffer_rolling_update phase=rollback resume=postcheck\n'
        else
            run_serial_upgrade "${current_image}" "${rollback_log}"
        fi
        wait_cluster_state 'current=3 updated=0'
        write_marker \
            "${rollback_marker}" \
            "from=${update_image_id} to=${current_image_id}"
        ;;
esac

test ! -e "${temporary_globals}"
printf 'coffer_rolling_update phase=%s result=passed serial=1\n' "${action}"
