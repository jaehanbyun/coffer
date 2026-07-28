#!/usr/bin/env bash

set -Eeuo pipefail

source_root="/home/ubuntu/coffer"
state_root="/home/ubuntu/coffer-ui-preview"
marker="${state_root}/images.complete"
skyline_wheel="${source_root}/work/ui-image-qualification/wheels/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
skyline_wheel_sha256="52f3d9ffb1f119903b182d1101d13105797a9bfa90a421fc1a25497b874d8b1d"
contract_root="/etc/kolla/config/coffer/ui"
image_globals="/etc/kolla/coffer-ui-images.yml"
image_tag="localhost:5000/coffer-skyline-console:ui-preview"
python_binary="${state_root}/venv/bin/python3"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"
test "$(uname -m)" = x86_64
test "$(cat "${marker}")" = "coffer-ui-preview-images-v1"
test -x "${python_binary}"
test -s "${skyline_wheel}"
test -s "${image_globals}"
printf '%s  %s\n' "${skyline_wheel_sha256}" "${skyline_wheel}" |
    sha256sum --check --strict --status

skyline_base="$(
    "${python_binary}" - "${image_globals}" <<'PY'
from pathlib import Path
import re
import sys

import yaml

document = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = document.get("coffer_skyline_console_fallback_image_full", "")
if not re.fullmatch(
    r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}",
    value,
):
    raise SystemExit("invalid Skyline fallback image in preview globals")
print(value)
PY
)"

temporary_directory="$(mktemp -d /home/ubuntu/coffer-ui-skyline.XXXXXX)"
cleanup() {
    rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT
install -m 0644 "${skyline_wheel}" \
    "${temporary_directory}/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
docker build \
    --network host \
    --build-arg "BASE_IMAGE=${skyline_base}" \
    --file "${source_root}/ui/images/skyline-console.Containerfile" \
    --tag "${image_tag}" \
    "${temporary_directory}"
docker push "${image_tag}" >/dev/null

mapfile -t skyline_images < <(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' \
        "${image_tag}" |
        grep -E '^localhost:5000/coffer-skyline-console@sha256:[0-9a-f]{64}$' |
        sort -u
)
test "${#skyline_images[@]}" -eq 1
skyline_image="${skyline_images[0]}"
docker pull "${skyline_image}" >/dev/null

contract_stage_directory="$(
    mktemp -d "${contract_root}/.skyline-contract.XXXXXX"
)"
temporary_contract="${contract_stage_directory}/skyline-image.json"
temporary_globals="$(mktemp /etc/kolla/.coffer-ui-images.XXXXXX)"
cleanup_all() {
    rm -f -- "${temporary_contract}" "${temporary_globals}"
    rmdir -- "${contract_stage_directory}" 2>/dev/null || true
    cleanup
}
trap cleanup_all EXIT
"${python_binary}" "${source_root}/ui/images/write_contract.py" \
    --surface skyline \
    --artifact "${skyline_wheel}" \
    --image "${skyline_image}" \
    --base-image "${skyline_base}" \
    --output "${temporary_contract}"
chown root:root "${temporary_contract}"
chmod 0640 "${temporary_contract}"

"${python_binary}" - \
    "${image_globals}" "${temporary_globals}" "${skyline_image}" <<'PY'
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
document["coffer_skyline_console_image_full"] = image
target.write_text(
    yaml.safe_dump(document, sort_keys=False),
    encoding="utf-8",
)
PY
chmod 0644 "${temporary_globals}"
mv "${temporary_contract}" "${contract_root}/skyline-image.json"
rmdir -- "${contract_stage_directory}"
mv "${temporary_globals}" "${image_globals}"
trap cleanup EXIT
cleanup
trap - EXIT

printf 'Coffer Skyline preview image refreshed image=%s\n' "${skyline_image}"
