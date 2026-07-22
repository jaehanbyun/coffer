#!/usr/bin/env bash

set -euo pipefail

runtime_env="/etc/coffer-rgw/barbican.env"
distribution_script="/tmp/guest-run-distribution.sh"

test "$(id -u)" -eq 0
test -f "${runtime_env}"
test "$(stat -c '%a' "${runtime_env}")" = 600
test -f "${distribution_script}"
grep -Eq '^COFFER_KMS_KEY_ID=[0-9a-f-]{36}$' "${runtime_env}"

# This file is generated and installed by the owner-only binding harness.
# shellcheck disable=SC1090
source "${runtime_env}"
export COFFER_DISTRIBUTION_S3_ENCRYPT=true
export COFFER_DISTRIBUTION_S3_KEY_ID="${COFFER_KMS_KEY_ID}"
bash "${distribution_script}"
unset COFFER_KMS_USER_PASSWORD COFFER_KMS_KEY_ID
unset COFFER_DISTRIBUTION_S3_ENCRYPT COFFER_DISTRIBUTION_S3_KEY_ID
