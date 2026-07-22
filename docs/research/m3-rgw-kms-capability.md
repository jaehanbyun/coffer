# M3 Ceph Tentacle RGW KMS Capability

- Date: 2026-07-22
- Target: Ceph Tentacle 20.2.2, `rgw.coffer`, Distribution v3.1.1
- Outcome: supported bindings identified read-only; no KMS configuration or key was created

## Live Cluster Result

The installed Tentacle option schema reports:

- `rgw_crypt_s3_kms_backend` choices: `barbican`, `vault`, `testing`, and `kmip`; default `barbican`; daemon restart required;
- `rgw_crypt_require_ssl=true`; this option is live-update capable, but the PoC must not disable it;
- no configured `rgw_crypt*`, `rgw_barbican*`, or `rgw_keystone_barbican*` override in `ceph config dump`;
- no `rgw_crypt_sse_algorithm` option in this pinned release, so later-development documentation for selectable AES-GCM must not be attributed to Tentacle evidence.

The current RGW endpoint already uses verified HTTPS. The running cluster is therefore transport-ready but has no KMS authority, key, endpoint, credential, CA binding, or mounted secret file.

Distribution's upstream S3 driver exposes `encrypt: true` and optional `keyid`. The KMS run must add both to the existing verified-TLS, SigV4, path-style S3 configuration. `keyid` is ignored unless encryption is enabled.

## Supported Backend Bindings

| Backend | Required non-secret bindings | Required secret/private bindings | Lab meaning |
|---|---|---|---|
| Barbican | RGW backend `barbican`, Barbican HTTPS URL, Keystone URL, domain, project, service user, key UUID, CA trust | Barbican service-user password or an approved equivalent delivery path | Best OpenStack-native product evidence; current DevStack does not deploy Barbican |
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

## Current Blocker

The live environment has no approved KMS endpoint/key and the current DevStack intentionally contains only Keystone, MySQL, and TLS. M3-B cannot proceed safely without an explicit backend/deployment choice and credential delivery authorization.

## Primary References

- [Ceph Tentacle Object Gateway configuration reference](https://docs.ceph.com/en/tentacle/radosgw/config-ref/)
- [Ceph Tentacle Object Gateway encryption](https://docs.ceph.com/en/tentacle/radosgw/encryption/)
- [CNCF Distribution S3 storage driver](https://distribution.github.io/distribution/storage-drivers/s3/)
- Live `ceph config help` and filtered `ceph config dump` evidence from `coffer-rgw-poc`
