#!/usr/bin/env bash

set -Eeuo pipefail

source_root="/home/ubuntu/coffer"
state_root="/home/ubuntu/coffer-ui-preview"
marker="${state_root}/images.complete"
horizon_wheel="${source_root}/work/ui-image-qualification/wheels/coffer_horizon-0.1.0-py3-none-any.whl"
horizon_wheel_sha256="629960734a4ca7b39ebce285241b7f936542b7e46b49eee6f03161f89c6829aa"
contract_root="/etc/kolla/config/coffer/ui"
image_globals="/etc/kolla/coffer-ui-images.yml"
image_tag="localhost:5000/coffer-horizon:ui-preview"
python_binary="${state_root}/venv/bin/python3"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"
test "$(uname -m)" = x86_64
test "$(cat "${marker}")" = "coffer-ui-preview-images-v1"
test -x "${python_binary}"
test -s "${horizon_wheel}"
test -s "${image_globals}"
printf '%s  %s\n' "${horizon_wheel_sha256}" "${horizon_wheel}" |
    sha256sum --check --strict --status

horizon_base="$(
    "${python_binary}" - "${image_globals}" <<'PY'
from pathlib import Path
import re
import sys

import yaml

document = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = document.get("coffer_horizon_fallback_image_full", "")
if not re.fullmatch(
    r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}",
    value,
):
    raise SystemExit("invalid Horizon fallback image in preview globals")
print(value)
PY
)"

temporary_directory="$(mktemp -d /home/ubuntu/coffer-ui-horizon.XXXXXX)"
cleanup() {
    rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT
install -m 0644 "${horizon_wheel}" \
    "${temporary_directory}/coffer_horizon-0.1.0-py3-none-any.whl"
install -m 0644 "${source_root}/ui/images/install_horizon.py" \
    "${temporary_directory}/install_horizon.py"
docker build \
    --network host \
    --build-arg "BASE_IMAGE=${horizon_base}" \
    --file "${source_root}/ui/images/horizon.Containerfile" \
    --tag "${image_tag}" \
    "${temporary_directory}"
docker push "${image_tag}" >/dev/null

mapfile -t horizon_images < <(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' \
        "${image_tag}" |
        grep -E '^localhost:5000/coffer-horizon@sha256:[0-9a-f]{64}$' |
        sort -u
)
test "${#horizon_images[@]}" -eq 1
horizon_image="${horizon_images[0]}"
docker pull "${horizon_image}" >/dev/null

contract_stage_directory="$(
    mktemp -d "${contract_root}/.horizon-contract.XXXXXX"
)"
temporary_contract="${contract_stage_directory}/horizon-image.json"
temporary_globals="$(mktemp /etc/kolla/.coffer-ui-images.XXXXXX)"
cleanup_all() {
    rm -f -- "${temporary_contract}" "${temporary_globals}"
    rmdir -- "${contract_stage_directory}" 2>/dev/null || true
    cleanup
}
trap cleanup_all EXIT
"${python_binary}" "${source_root}/ui/images/write_contract.py" \
    --surface horizon \
    --artifact "${horizon_wheel}" \
    --image "${horizon_image}" \
    --base-image "${horizon_base}" \
    --output "${temporary_contract}"
chown root:root "${temporary_contract}"
chmod 0640 "${temporary_contract}"

"${python_binary}" - \
    "${image_globals}" "${temporary_globals}" "${horizon_image}" <<'PY'
from pathlib import Path
import sys

import yaml

source = Path(sys.argv[1])
target = Path(sys.argv[2])
image = sys.argv[3]
document = yaml.safe_load(source.read_text(encoding="utf-8"))
expected = {
    "coffer_horizon_image_full",
    "coffer_horizon_fallback_image_full",
    "coffer_skyline_console_image_full",
    "coffer_skyline_console_fallback_image_full",
}
if set(document) != expected:
    raise SystemExit("unexpected preview image globals keys")
document["coffer_horizon_image_full"] = image
target.write_text(
    yaml.safe_dump(document, sort_keys=False),
    encoding="utf-8",
)
PY
chmod 0644 "${temporary_globals}"
mv "${temporary_contract}" "${contract_root}/horizon-image.json"
rmdir -- "${contract_stage_directory}"
mv "${temporary_globals}" "${image_globals}"
trap cleanup EXIT
cleanup
trap - EXIT

printf 'Coffer Horizon preview image refreshed image=%s\n' "${horizon_image}"
