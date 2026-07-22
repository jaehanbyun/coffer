# Real Keystone and Ceph RGW PoC Runbook

- Status: ready for environment binding; not yet executed
- Related plan: `docs/exec-plans/0002-thin-vertical-poc.md`
- Purpose: close the M1 identity lifecycle and M3 RGW evidence that synthetic fixtures cannot prove

## Safety Boundary

Run this only in a disposable non-production OpenStack region and Ceph RGW bucket approved for destructive testing. Do not paste credentials into this repository, command arguments, captured logs, issue trackers, plans, or handoffs. Disable shell tracing before handling secrets:

```bash
set +x
umask 077
```

Use named `clouds.yaml` entries or an approved credential broker outside the repository. Use an OS credential helper for Docker. Use an AWS profile or workload credential outside the repository for RGW. Evidence belongs under ignored `work/real-poc/<run-id>/` only after tokens, secrets, private keys, and raw authentication responses have been removed.

The operator must approve and supply these non-secret bindings before execution:

| Variable | Meaning |
|---|---|
| `COFFER_ADMIN_CLOUD` | disposable cloud entry allowed to create/disable test identities and assignments |
| `COFFER_CLOUD_A_MEMBER`, `COFFER_CLOUD_A_READER`, `COFFER_CLOUD_A_ADMIN` | project-A user contexts |
| `COFFER_CLOUD_B_MEMBER` | project-B member context in a different domain |
| `COFFER_PROJECT_A_ID`, `COFFER_PROJECT_B_ID` | immutable and unequal project UUIDs |
| `COFFER_API_URL` | TLS Coffer control/token endpoint |
| `COFFER_REGISTRY_HOST` | TLS registry authority without a path |
| `COFFER_RGW_ENDPOINT` | TLS S3 endpoint |
| `COFFER_RGW_BUCKET` | disposable private service bucket |
| `COFFER_RGW_OTHER_BUCKET` | bucket the service identity must not access |
| `COFFER_RGW_AWS_PROFILE` | external least-privilege S3 credential profile |
| `COFFER_RGW_KMS_KEY_ID` | approved test KMS key ID when SSE-KMS is in scope |

Stop if either endpoint is plaintext, TLS verification requires `--insecure`, the two project IDs match, the bucket is shared with non-PoC data, or the environment cannot be reset.

## Phase 0 — Inventory and Evidence Directory

Record versions and immutable IDs, not configuration dumps:

```bash
COFFER_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
COFFER_EVIDENCE_DIR="work/real-poc/${COFFER_RUN_ID}"
mkdir -p "${COFFER_EVIDENCE_DIR}"

openstack --version >"${COFFER_EVIDENCE_DIR}/versions.txt"
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}' \
  >>"${COFFER_EVIDENCE_DIR}/versions.txt"
aws --version >>"${COFFER_EVIDENCE_DIR}/versions.txt" 2>&1
curl --version | head -n 1 >>"${COFFER_EVIDENCE_DIR}/versions.txt"

openstack --os-cloud "${COFFER_CLOUD_A_MEMBER}" token issue -f json | \
  jq '{project_id, user_id, expires}' \
  >"${COFFER_EVIDENCE_DIR}/project-a-identity.json"
openstack --os-cloud "${COFFER_CLOUD_B_MEMBER}" token issue -f json | \
  jq '{project_id, user_id, expires}' \
  >"${COFFER_EVIDENCE_DIR}/project-b-identity.json"
test "${COFFER_PROJECT_A_ID}" != "${COFFER_PROJECT_B_ID}"
```

The administrator must separately confirm that the two users and projects deliberately reuse the same human-readable names across two domains. Preserve only domain, project, and user IDs in evidence.

## Phase 1 — TLS and Dependency Preconditions

All commands must pass without disabling certificate verification:

```bash
curl --fail-with-body --silent --show-error \
  "https://${COFFER_REGISTRY_HOST}/v2/" \
  --dump-header "${COFFER_EVIDENCE_DIR}/registry-challenge.headers" \
  --output /dev/null || test "$?" -eq 22

rg -q '^HTTP/.* 401' "${COFFER_EVIDENCE_DIR}/registry-challenge.headers"
rg -q 'Bearer realm="https://' "${COFFER_EVIDENCE_DIR}/registry-challenge.headers"
rg -q 'service="' "${COFFER_EVIDENCE_DIR}/registry-challenge.headers"

aws --profile "${COFFER_RGW_AWS_PROFILE}" \
  --endpoint-url "${COFFER_RGW_ENDPOINT}" \
  s3api head-bucket --bucket "${COFFER_RGW_BUCKET}"
```

Record the deployed Keystone, Ceph, Distribution, database, and Coffer versions using operator inventory APIs. Do not copy complete service configuration or environment variables into evidence.

## Phase 2 — Explicit Repository Authority

Create the repository through the control API before any registry push. The project token is request-local and must be unset immediately:

```bash
COFFER_PROJECT_A_TOKEN="$(
  openstack --os-cloud "${COFFER_CLOUD_A_MEMBER}" token issue -f value -c id
)"
curl --fail-with-body --silent --show-error \
  --request POST \
  --header "X-Auth-Token: ${COFFER_PROJECT_A_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{"name":"poc","immutable_tags":false}' \
  "${COFFER_API_URL}/v1/repositories" | \
  jq '{repository: .repository | {id, project_id, name, immutable_tags}}' \
  >"${COFFER_EVIDENCE_DIR}/repository.json"
unset COFFER_PROJECT_A_TOKEN
```

Assert the returned `project_id` equals `COFFER_PROJECT_A_ID`. A token request for `p/<project-A-id>/missing` must contain no grant, and the Registry API must return 401 for that repository.

## Phase 3 — Finite Credentials and OS Credential Helper

Application credentials must use an explicit future expiration, the default `--restricted` behavior, and exactly the role under test. Do not add Keystone API access rules in the normal path; the current PoC deliberately rejects access-rule-bearing credentials.

Create a private temporary directory outside the repository. The generated JSON contains a one-time secret:

```bash
COFFER_SECRET_TMP="$(mktemp -d)"
chmod 700 "${COFFER_SECRET_TMP}"
COFFER_APP_CRED_EXPIRES_AT='<YYYY-mm-ddTHH:MM:SS in UTC>'

openstack --os-cloud "${COFFER_CLOUD_A_MEMBER}" \
  application credential create coffer-poc-member \
  --restricted --role member \
  --expiration "${COFFER_APP_CRED_EXPIRES_AT}" \
  -f json >"${COFFER_SECRET_TMP}/project-a-member.json"
chmod 600 "${COFFER_SECRET_TMP}/project-a-member.json"

COFFER_APP_CRED_ID_A="$(jq -er '.id' \
  "${COFFER_SECRET_TMP}/project-a-member.json")"
COFFER_APP_CRED_SECRET_A="$(jq -er '.secret' \
  "${COFFER_SECRET_TMP}/project-a-member.json")"
test -n "${COFFER_APP_CRED_ID_A}"
test -n "${COFFER_APP_CRED_SECRET_A}"
```

Configure the operator-approved Docker helper in a dedicated config directory. Common helper suffixes include `osxkeychain`, `secretservice`, `pass`, and `wincred`; select the installed platform helper:

```bash
COFFER_DOCKER_CONFIG="$(mktemp -d)"
chmod 700 "${COFFER_DOCKER_CONFIG}"
COFFER_DOCKER_HELPER='<approved helper suffix>'
command -v "docker-credential-${COFFER_DOCKER_HELPER}"
jq -n --arg helper "${COFFER_DOCKER_HELPER}" \
  '{credsStore: $helper}' >"${COFFER_DOCKER_CONFIG}/config.json"
chmod 600 "${COFFER_DOCKER_CONFIG}/config.json"

printf '%s' "${COFFER_APP_CRED_SECRET_A}" | \
  DOCKER_CONFIG="${COFFER_DOCKER_CONFIG}" \
  docker login "${COFFER_REGISTRY_HOST}" \
    --username "${COFFER_APP_CRED_ID_A}" --password-stdin
```

Inspect only the config structure and confirm it contains `credsStore` and no `auths.*.auth` value. Never run a helper command that prints stored credentials into evidence.

## Phase 4 — Role, Project, and Lifecycle Matrix

Create separate finite credentials for each row. Never reuse one credential after a destructive lifecycle test.

| Case | Setup | Expected new token exchange |
|---|---|---|
| project-A reader | `--role reader` | pull grant only |
| project-A member | `--role member` | pull/push, no delete |
| project-A admin | `--role admin` | pull/push/delete subject to policy |
| project-B member requesting A | distinct project UUID | no A grant |
| standalone `service` role | no standard project role | no tenant grant |
| domain-scoped role | domain token/assignment | no tenant grant |
| system-scoped role | system token/assignment | no tenant grant |
| access rules for another service | `--access-rules` using `compute` | 401 from Coffer |
| explicit empty access rules | environment/API permitting empty list | 401 from Coffer |
| deleted application credential | delete after a successful exchange | 401 |
| expired application credential | wait beyond explicit expiration | 401 |
| delegated role removed | administrator removes delegated project role | 401 |
| owner disabled | administrator disables dedicated test user | 401 |
| Keystone unavailable | approved network fault or isolated Coffer replica | 503, no cached success |

For deletion, use the owning cloud context and the exact disposable ID:

```bash
openstack --os-cloud "${COFFER_CLOUD_A_MEMBER}" \
  application credential delete "${COFFER_APP_CRED_ID_A}"
```

Role removal and user disablement are administrator operations. Before each change, resolve and record the exact project/user/role IDs. Re-enable the user and restore assignments during cleanup; do not run these tests against a human or shared service user.

The successful authentication response exposes issued Keystone-token expiry, not proof that the credential record has a future `expires_at`. Record the non-secret application-credential metadata before deletion and verify that every normal test credential has an explicit expiration. This is the acceptance evidence required by proposed ADR 0008.

## Phase 5 — Push, Pull, Restart, and Isolation

Use a small pinned image already approved for the environment:

```bash
COFFER_REPOSITORY="p/${COFFER_PROJECT_A_ID}/poc"
COFFER_IMAGE="${COFFER_REGISTRY_HOST}/${COFFER_REPOSITORY}:real-poc"
COFFER_SOURCE_IMAGE='<approved source image pinned by digest>'

docker pull "${COFFER_SOURCE_IMAGE}"
docker tag "${COFFER_SOURCE_IMAGE}" "${COFFER_IMAGE}"
DOCKER_CONFIG="${COFFER_DOCKER_CONFIG}" docker push "${COFFER_IMAGE}"
COFFER_IMAGE_DIGEST="$(
  DOCKER_CONFIG="${COFFER_DOCKER_CONFIG}" \
    docker inspect --format '{{index .RepoDigests 0}}' "${COFFER_IMAGE}" | \
    awk -F@ '{print $2}'
)"
test -n "${COFFER_IMAGE_DIGEST}"
```

Restart every Coffer and Distribution process through the environment's normal orchestrator, not an ad hoc kill. Remove the local image or use an independent clean client, then pull by digest and verify the manifest and one blob digest directly through the Registry API. Record only the repository, digests, HTTP status, timing, and restart event IDs.

Log in as project B using its separate helper entry and assert that pull of the project-A digest is denied before manifest/blob disclosure. Repeat the positive same-project and negative cross-project mount flows from `poc/m2/verify.sh` against explicit repositories.

## Phase 6 — Ceph RGW Least Privilege, Persistence, and Encryption

The Distribution S3 configuration under test must use HTTPS with verification, Signature v4, a pre-created private bucket, a dedicated root prefix, redirects disabled, and a least-privilege service identity. `secure=false`, `skipverify=true`, anonymous access, and public redirect endpoints fail acceptance.

Verify bucket boundaries with the external profile:

```bash
aws --profile "${COFFER_RGW_AWS_PROFILE}" \
  --endpoint-url "${COFFER_RGW_ENDPOINT}" \
  s3api list-objects-v2 --bucket "${COFFER_RGW_BUCKET}" \
  --prefix '<configured rootdirectory>' --max-items 5 \
  --query '{KeyCount:KeyCount,Keys:Contents[].Key}' \
  >"${COFFER_EVIDENCE_DIR}/rgw-objects.json"

if aws --profile "${COFFER_RGW_AWS_PROFILE}" \
  --endpoint-url "${COFFER_RGW_ENDPOINT}" \
  s3api list-objects-v2 --bucket "${COFFER_RGW_OTHER_BUCKET}" \
  --max-items 1 >/dev/null 2>&1; then
  printf 'service identity unexpectedly reached another bucket\n' >&2
  exit 1
fi
```

An anonymous `HEAD`/`GET` of the bucket and a TLS request with an intentionally wrong CA must fail. Run those negative checks without `--no-verify-ssl` and without preserving authorization headers.

For the selected stable Ceph release, configure bucket SSE-KMS through the operator's approved RGW/KMS procedure. Distribution's S3 driver must use `encrypt: true` and the approved `keyid`. Verify the actual stored object metadata:

```bash
aws --profile "${COFFER_RGW_AWS_PROFILE}" \
  --endpoint-url "${COFFER_RGW_ENDPOINT}" \
  s3api get-bucket-encryption --bucket "${COFFER_RGW_BUCKET}" \
  >"${COFFER_EVIDENCE_DIR}/rgw-bucket-encryption.json"

aws --profile "${COFFER_RGW_AWS_PROFILE}" \
  --endpoint-url "${COFFER_RGW_ENDPOINT}" \
  s3api head-object --bucket "${COFFER_RGW_BUCKET}" --key '<verified object key>' \
  --query '{ServerSideEncryption:ServerSideEncryption,SSEKMSKeyId:SSEKMSKeyId}' \
  >"${COFFER_EVIDENCE_DIR}/rgw-object-encryption.json"
```

Ceph's online documentation may describe a development release. Bind the run to the operator's exact stable Ceph version and archive that version's relevant configuration reference. HTTPS is mandatory because RGW server-side encryption does not protect plaintext in transit.

## Phase 7 — Outage, Audit, and Redaction

Exercise approved, bounded dependency faults one at a time:

- Keystone unreachable: new exchange returns 503; an already-issued registry JWT remains usable only until `exp`.
- SQL unreachable: repository/token authorization fails closed and readiness reports dependency failure.
- RGW unreachable: upload/pull fails without redirecting clients to object storage; recovery needs no content rewrite.
- KMS unavailable: encrypted writes fail and emit a dependency error without a key or credential value.
- wrong Keystone/RGW CA: connection fails closed; never retry with verification disabled.

For every token decision, verify request ID, JTI, project/user IDs, Keystone audit IDs, normalized requested grants, reduced grants, and result. For registry requests, record Distribution request IDs, repository/action/result, digest when present, and storage error class. Metrics must expose request/error/latency and dependency health without labels containing user IDs, repositories, tokens, or unbounded values.

Run secret scans only over project-owned code and redacted evidence:

```bash
rg -n -i \
  'authorization:|x-auth-token|application_credential_secret|private key|aws_secret_access_key' \
  "${COFFER_EVIDENCE_DIR}" && exit 1 || true
rg -n 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${COFFER_EVIDENCE_DIR}" && exit 1 || true
gitleaks dir . --redact --no-banner --exit-code 1
```

Review each match manually before retaining evidence. Do not treat redaction as permission to capture raw secrets first.

## Phase 8 — Cleanup

Cleanup is a required test phase. Resolve every target by immutable ID before mutation.

1. `docker logout` through the dedicated helper and remove its disposable config directory.
2. Delete every disposable application credential by ID using its owner context.
3. Re-enable dedicated test users and restore or delete only the test role assignments according to the environment reset plan.
4. Delete the PoC repository through the future control API deletion path when implemented; until then, reset the disposable control database through the environment owner.
5. Delete only the approved RGW prefix/bucket after the operator confirms no non-PoC objects exist.
6. Revoke or delete the disposable S3 identity and KMS grants.
7. Unset all token/secret variables and delete the secure temporary directories.
8. Re-run the service health checks and secret scan.

Example local credential cleanup:

```bash
DOCKER_CONFIG="${COFFER_DOCKER_CONFIG}" \
  docker logout "${COFFER_REGISTRY_HOST}" || true
unset COFFER_APP_CRED_SECRET_A COFFER_APP_CRED_ID_A
rm -rf "${COFFER_SECRET_TMP}" "${COFFER_DOCKER_CONFIG}"
```

The two paths above must come directly from successful `mktemp -d` calls in this shell. If either variable is empty or was reassigned, stop and remove it manually after inspection.

## Acceptance Record

The run is accepted only when all required rows are recorded with timestamps, exact non-secret versions, commands or orchestrator actions, expected result, actual result, and redacted evidence path:

- real Keystone TLS authentication and finite metadata;
- reader/member/admin plus service/system/domain and cross-domain collision matrix;
- deletion, expiration, role removal, owner disable, and outage behavior;
- access-rule-bearing credential rejection;
- explicit repository and cross-project isolation;
- helper-backed unmodified Docker flow with no refresh token;
- push/pull by digest after Coffer and Distribution restart from a clean client;
- Ceph RGW object presence, other-bucket/anonymous denial, TLS verification, and selected-release SSE-KMS evidence;
- correlated audit/health/metrics evidence and zero retained secrets.

Do not mark M1 or M3 complete from a partial run or from local MinIO/fixture substitutions.

## Primary References

- [OpenStack application-credential CLI](https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/application-credentials.html)
- [Keystone application credentials and access rules](https://docs.openstack.org/keystone/latest/user/application_credentials.html)
- [Docker login and credential stores](https://docs.docker.com/reference/cli/docker/login/)
- [Distribution S3 storage driver](https://distribution.github.io/distribution/storage-drivers/s3/)
- [Distribution configuration](https://distribution.github.io/distribution/about/configuration/)
- [Ceph RGW S3 authentication](https://docs.ceph.com/en/latest/radosgw/s3/authentication/)
- [Ceph RGW encryption](https://docs.ceph.com/en/latest/radosgw/encryption/)
