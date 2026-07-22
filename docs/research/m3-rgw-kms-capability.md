# M3 Ceph Tentacle RGW KMS Capability

- Date: 2026-07-22
- Target: Ceph Tentacle 20.2.2, `rgw.coffer`, Distribution v3.1.1
- Outcome: initial read-only capability assessment completed; later Barbican execution passed with a pinned-release encrypted-copy limitation

## Initial Read-Only Cluster Result

The installed Tentacle option schema reports:

- `rgw_crypt_s3_kms_backend` choices: `barbican`, `vault`, `testing`, and `kmip`; default `barbican`; daemon restart required;
- `rgw_crypt_require_ssl=true`; this option is live-update capable, but the PoC must not disable it;
- no configured `rgw_crypt*`, `rgw_barbican*`, or `rgw_keystone_barbican*` override in `ceph config dump`;
- no `rgw_crypt_sse_algorithm` option in this pinned release, so later-development documentation for selectable AES-GCM must not be attributed to Tentacle evidence.

At the time of this initial snapshot, the RGW endpoint already used verified HTTPS and was transport-ready, but no KMS authority, key, endpoint, credential, CA binding, or mounted secret file existed. The later authorized execution result is recorded below.

Distribution's upstream S3 driver exposes `encrypt: true` and optional `keyid`. The KMS run must add both to the existing verified-TLS, SigV4, path-style S3 configuration. `keyid` is ignored unless encryption is enabled.

## Supported Backend Bindings

| Backend | Required non-secret bindings | Required secret/private bindings | Lab meaning |
|---|---|---|---|
| Barbican | RGW backend `barbican`, Barbican HTTPS URL, Keystone URL, domain, project, service user, key UUID, CA trust | Barbican service-user password or an approved equivalent delivery path | Best OpenStack-native product evidence; the initial DevStack snapshot did not deploy Barbican |
| Vault | RGW backend `vault`, Vault HTTPS address, auth mode `token` or `agent`, transit engine, restricted prefix, key name/ID, CA trust | owner-only token file, agent socket/state, or mTLS client key | Fastest independent KMS functional path, but not Barbican/OpenStack service integration evidence |
| KMIP | RGW backend `kmip`, server address, CA, client certificate, key-name template | client private key and optional username/password | Appropriate only if an operator already owns a KMIP service and PKI |
| Testing | local test-key mapping | test key material | Explicitly inadmissible for M3-B security evidence |

Tentacle exposes Vault CA verification and optional client certificate/key paths. KMIP exposes server address, CA, client certificate/key, key template, and optional username/password. Most endpoint, identity, and file-path settings are not runtime-update capable; RGW must restart under a tested rollback plan.

## Recommended Decision

For the product's OpenStack-native claim, **Barbican is the preferred M3-B backend** if the operator accepts deploying it and creating a disposable key/service identity. This proves the intended Keystone/Barbican lifecycle rather than only generic KMS compatibility.

Vault is the recommended fallback when the immediate goal is only to qualify RGW/Distribution SSE-KMS behavior. A Vault result must be labeled storage encryption evidence, not OpenStack-native key-management integration. KMIP should be selected only when an existing approved endpoint and certificate lifecycle are available.

Do not silently choose or deploy one. Every option introduces new credentials and changes the RGW data security boundary.

## Required Operator Inputs and Approval

Before M3-B execution, the operator must approve and supply through a non-repository channel:

1. backend choice: Barbican, Vault, or KMIP;
2. disposable HTTPS endpoint and verified CA chain;
3. exact KMS key UUID/name and permission scope;
4. RGW credential mechanism and owner-only mount/delivery path;
5. whether Coffer may deploy a new lab service or must consume an existing one;
6. authorization to restart `rgw.coffer` and to induce bounded key-not-found/KMS-outage cases;
7. cleanup/rotation owner and whether test ciphertext/key state must be retained.

No token, password, client key, KMS key material, kubeconfig, or credential-bearing service spec belongs in Git, execution plans, handoffs, or retained logs.

## M3-B Verification Sequence

1. Record the exact backend, endpoint hostname, CA fingerprint, key identifier, RGW daemon/image versions, and non-secret config names.
2. Deliver credentials/private files owner-only, validate certificate/key pairs without printing them, apply the RGW config, and restart one disposable RGW service.
3. Set Distribution `storage.s3.encrypt=true` and the approved `keyid`; retain TLS verification, SigV4, private bucket, and redirect disablement.
4. Push new unique small and multipart content. Confirm Distribution push/pull digest integrity and RGW S3 HEAD encryption headers/key ID for newly written registry objects.
5. Confirm pre-KMS objects remain readable and do not claim retroactive encryption.
6. Use RGW/object metadata evidence to distinguish encrypted payload objects from registry metadata; verify the actual selected-release behavior rather than only request headers.
7. Exercise wrong key ID and bounded KMS outage. New writes must fail closed without plaintext fallback or secret leakage. After any key-cache TTL relevant to the backend, reads of encrypted objects must exhibit the documented failure mode.
8. Restore KMS, verify the original digest, restart RGW and Distribution, and verify again.
9. Scan RGW, Distribution, KMS, and client logs for credentials, key material, Authorization headers, and bearer JWTs.
10. Rotate or destroy disposable credentials/key state only under the approved cleanup decision.

The test must record whether the pinned Tentacle release uses its legacy encryption algorithm and must not import later-release AES-GCM claims. Encryption-at-rest acceptance requires observed ciphertext/encryption metadata and failure behavior, not merely a successful `encrypt: true` configuration parse.

## Executed Barbican Result

The authorized follow-up deployed exact Barbican commit `586152c223b9e1373f5e422276bcaa152686b761` in the disposable DevStack, created a dedicated project/user with only its exact effective `creator` assignment, stored a random 256-bit AES/CBC secret, and streamed the owner-only caller binding between guest-root contexts. Host evidence retained non-secret identity IDs and metadata but no key UUID, password, payload, S3 key, or bearer token.

The hardened matrix produced these bounded results against Ceph Tentacle 20.2.2 and Distribution v3.1.1:

- a direct S3 proof and five repository plus three global novel OCI payload objects reported `aws:kms` with the selected key;
- the novel digest and pre-KMS digest remained readable after fresh Distribution and RGW processes;
- a random wrong key and a fresh RGW process with both Barbican and Keystone reachability removed failed closed with zero novel objects and zero incomplete multipart uploads;
- recovery with a unique layout succeeded after restoring the correct endpoints/key;
- cleanup removed 17 isolated objects, found zero bucket-wide selected-key residue and multipart uploads, removed all nine Ceph KMS options, restored the non-KMS Distribution baseline, and stopped DevStack and the tunnel.

### Tentacle encrypted-copy boundary

Distribution finalizes an S3 blob by moving it, and the v3.1.1 S3 driver uses ordinary `CopyObject` at or below its multipart-copy threshold. Ceph Tentacle 20.2.2 intentionally rejects ordinary copy when the source object is server-side encrypted, returning 501. The bounded PoC sets `multipartcopythresholdsize: 0`, which routes every positive-size move through RGW's supported multipart decrypt-and-re-encrypt path; an explicit chunk size and bounded concurrency are retained.

This is not complete compatibility. Distribution's size check keeps a zero-byte blob on ordinary `CopyObject`, so an encrypted zero-byte registry write still fails closed. Production SSE-KMS promotion therefore requires either a released Ceph fix/backport for encrypted source copy or a separately proven release/backend combination that supports positive-size and zero-byte paths. The harness also checks and aborts incomplete multipart uploads because Distribution v3.1.1 does not clean up a failed destination multipart copy in every failure path.

Primary source evidence for this boundary:

- [Ceph Tentacle encrypted-source CopyObject rejection](https://github.com/ceph/ceph/blob/v20.2.2/src/rgw/driver/rados/rgw_rados.cc#L5002-L5014)
- [Ceph S3 error mapping for the unsupported copy](https://github.com/ceph/ceph/blob/v20.2.2/src/rgw/rgw_common.cc#L132-L134)
- [Ceph rationale commit](https://github.com/ceph/ceph/commit/a1513efe21af694e04db466a4d1d63cfd857876e)
- [Distribution blob-writer move on commit](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/blobwriter.go#L58-L75)
- [Distribution S3 move and multipart threshold implementation](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/driver/s3-aws/s3.go#L841-L940)
- [Distribution S3 multipart-copy parameters](https://distribution.github.io/distribution/storage-drivers/s3/#parameters)
- [OCI image-spec empty descriptor guidance](https://github.com/opencontainers/image-spec/blob/main/manifest.md#guidance-for-an-empty-descriptor)

## Resolved Authorization Gate

The original blocker was resolved by explicit user authorization for the Barbican backend, disposable service identity/key, owner-only delivery, RGW restart, and bounded wrong-key/outage tests. The disposable identity/key is retained owner-only for an exact rerun after proving that no retained object depends on it. This authorization does not extend to a production deployment or to destroying retained key state.

## Primary References

- [Ceph Tentacle Object Gateway configuration reference](https://docs.ceph.com/en/tentacle/radosgw/config-ref/)
- [Ceph Tentacle Object Gateway encryption](https://docs.ceph.com/en/tentacle/radosgw/encryption/)
- [CNCF Distribution S3 storage driver](https://distribution.github.io/distribution/storage-drivers/s3/)
- Live `ceph config help` and filtered `ceph config dump` evidence from `coffer-rgw-poc`
