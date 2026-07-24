#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -lt 1 ]]; then
    echo "usage: $0 {status|prepare} [CONFIG_TASKS BOOTSTRAP_TEMPLATE]" >&2
    exit 64
fi

action="$1"
case "${action}" in
    status)
        test "$#" -eq 1 || exit 64
        ;;
    prepare)
        test "$#" -eq 3 || exit 64
        ;;
    *)
        echo "refusing an unknown Coffer operator-source action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
base_source="${state_root}/coffer-source"
operator_source="${state_root}/coffer-operator-source"
marker="${state_root}/coffer-operator-source.prepared"
marker_value="coffer-stage5-operator-source-v1"
base_commit="4f1ff7ddfd89d21f17ab7cbb531c335e85d94542"
config_relative="ansible/roles/coffer/tasks/config.yml"
template_relative="docker/config/coffer-bootstrap.json.j2"
config_sha256="b4e0bf378ea88943f700df0adfca4bc3df44ac34369541bc8853ce769ebe3208"
template_sha256="96758f497c0b821e02091668cc3b2b215ac9addb7a5c2541f93c27af92ee2d04"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(git -C "${base_source}" rev-parse HEAD)" = "${base_commit}"
test -z "$(git -C "${base_source}" status --porcelain --untracked-files=all)"

validate_operator_source() {
    local actual_names

    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${marker_value}"
    test -d "${operator_source}/.git"
    test "$(git -C "${operator_source}" rev-parse HEAD)" = "${base_commit}"
    test "$(
        sha256sum "${operator_source}/${config_relative}" |
            awk '{print $1}'
    )" = "${config_sha256}"
    test "$(
        sha256sum "${operator_source}/${template_relative}" |
            awk '{print $1}'
    )" = "${template_sha256}"
    actual_names="$(
        git -C "${operator_source}" diff --name-only |
            LC_ALL=C sort
    )"
    test "${actual_names}" = "$(
        printf '%s\n' "${config_relative}" "${template_relative}" |
            LC_ALL=C sort
    )"
    test -z "$(
        git -C "${operator_source}" status --porcelain --untracked-files=all |
            awk '$1 != "M" {print}'
    )"
    git -C "${operator_source}" diff --check
}

if test "${action}" = status; then
    if test -e "${marker}"; then
        validate_operator_source
        state=ready
    else
        test ! -e "${operator_source}"
        state=absent
    fi
    printf 'coffer_operator_source state=%s base_commit=%s modifications=%s\n' \
        "${state}" "${base_commit:0:7}" \
        "$([[ "${state}" = ready ]] && printf 2 || printf 0)"
    exit 0
fi

config_input="$2"
template_input="$3"
test "$(
    sha256sum "${config_input}" | awk '{print $1}'
)" = "${config_sha256}"
test "$(
    sha256sum "${template_input}" | awk '{print $1}'
)" = "${template_sha256}"
if test -e "${marker}"; then
    validate_operator_source
    printf 'coffer_operator_source state=ready idempotent=yes\n'
    exit 0
fi
test ! -e "${operator_source}"

temporary="$(mktemp -d "${state_root}/coffer-operator-source.prepare.XXXXXX")"
operator_installed=false
committed=false
cleanup() {
    local exit_code=$?

    if test "${committed}" != true; then
        if test "${operator_installed}" = true; then
            rm -rf -- "${operator_source}"
            rm -f -- "${marker}"
        fi
    fi
    if [[ "${temporary}" == \
"${state_root}"/coffer-operator-source.prepare.* ]]; then
        rm -rf -- "${temporary}"
    fi
    exit "${exit_code}"
}
trap cleanup EXIT

git clone --quiet --no-hardlinks "${base_source}" "${temporary}/source"
install -o root -g root -m 0644 \
    "${config_input}" "${temporary}/source/${config_relative}"
install -o root -g root -m 0644 \
    "${template_input}" "${temporary}/source/${template_relative}"
mv "${temporary}/source" "${operator_source}"
operator_installed=true
printf '%s\n' "${marker_value}" >"${marker}"
chown root:root "${marker}"
chmod 0600 "${marker}"
validate_operator_source
committed=true
printf 'coffer_operator_source state=ready modifications=2 runtime=unchanged\n'
