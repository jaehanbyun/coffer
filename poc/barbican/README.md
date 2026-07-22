# Disposable Barbican KMS Lab

This harness adds the pinned Barbican `stable/2026.1` DevStack plugin to the
existing `coffer-devstack` Keystone-only identity VM. It is a disposable
OpenStack-native KMS integration target for Ceph RGW, not a production
Barbican deployment or HSM design.

The bootstrap pins Barbican commit
`586152c223b9e1373f5e422276bcaa152686b761`, enables the plugin's required
RabbitMQ service, and preserves the pre-Barbican `local.conf` in owner-only
guest state. DevStack's private installation log remains mode `0600` inside
the guest and is never copied to the repository or retained host evidence.

Run:

```bash
make -C poc/barbican bootstrap
make -C poc/barbican provision
make -C poc/barbican verify
make -C poc/barbican bind-rgw
make -C poc/barbican configure-rgw-kms
make -C poc/barbican enable-distribution-kms
make -C poc/barbican verify-distribution-kms
make -C poc/barbican verify-fail-closed
```

The public service remains under DevStack's existing verified TLS proxy at
`https://<devstack-ip>/key-manager`. Public CA and redacted evidence are kept
under ignored `work/` paths. Runtime credentials and Barbican secret payloads
must never enter Git, command output, or retained logs.

Provisioning creates one exact project/user pair named
`coffer-rgw-kms-poc`, grants only the exact effective Barbican `creator` role
assignment, and has Barbican
store a random 256-bit AES/CBC secret. The payload exists only in the client
process and Barbican; the harness retains its UUID plus the caller password in
guest-root mode `0600` state for RGW binding. Host evidence contains non-secret
identity IDs and metadata only; the key UUID and all secret values are absent.

`bind-rgw` streams that owner-only binding directly from DevStack guest root
to RGW guest root; it never writes the credential to the Mac filesystem. It
installs only the public DevStack CA, creates an ignored SSH control socket for
a loopback-only reverse tunnel, redeploys `rgw.coffer` with a read-only CA
bundle mount, and proves Barbican plus Keystone TLS reachability from both the
RGW host and daemon container. Use `make tunnel-check` or `make tunnel-stop`
to inspect or stop that disposable lab tunnel.

The pinned Ceph image is CentOS-based, so the CA bundle is mounted at its
observed libcurl trust path, `/etc/pki/tls/certs/ca-bundle.crt`, rather than a
Debian-family certificate path.

`configure-rgw-kms` loads the owner-only caller binding only in the RGW guest,
sets the documented Ceph Barbican/Keystone option names for
`client.rgw.coffer`, restarts the service, and writes one fixed small direct S3
proof object with `aws:kms`. Its public JSON evidence reports only a key-ID
match boolean, object location, size, and payload digest. The Ceph configuration
helper reads secret-bearing files inside the guest and does not place their
values in helper process arguments.

`enable-distribution-kms` restarts the pinned unmodified Distribution with
the upstream S3 driver's `encrypt: true`, owner-only UUID `keyid`, and
`multipartcopythresholdsize: 0`. Tentacle 20.2.2 rejects an encrypted source
ordinary `CopyObject`, while the forced multipart path succeeds for positive
object sizes. The
generic RGW runner remains backward-compatible: it emits those settings only
when both bounded environment variables are supplied together.

`verify-distribution-kms` creates a deterministic novel OCI layout, pushes it
through unmodified Skopeo and Distribution, requires five repository objects
and the three global manifest/config/compressed-layer payload blobs to report
`aws:kms` plus the selected key, and checks both the new digest and a pre-KMS
digest after fresh Distribution and RGW processes. Retained output contains
only match booleans, counts, paths, and content digests.

`verify-fail-closed` uses distinct novel layouts to prove that a random missing
key and a combined Barbican/Keystone tunnel outage after a fresh RGW process
both reject writes and leave zero repository/global objects and incomplete
multipart uploads. It also records Tentacle's fail-closed zero-byte encrypted
move limitation: size zero remains on ordinary `CopyObject` and is not covered
by the positive-size multipart workaround. It restores the correct key, proves
recovery, removes exactly the isolated proof objects after checking their key
metadata, proves bucket-wide selected-key residue and multipart uploads are
zero, removes the Ceph KMS options, restarts the non-encrypted Distribution
baseline, stops the tunnel and DevStack, and confirms the pre-KMS repository
still reads.
The stopped disposable Barbican identity/key and owner-only bindings are kept
for an exact rerun; no retained object depends on them.

The pinned plugin initially derives an HTTP `host_href` and catalog URL from
DevStack's internal service protocol even when `tls-proxy` is active. The
harness explicitly changes Barbican's published reference and all three
catalog interfaces to the verified HTTPS URL; unauthenticated `/v1` returns
the expected 401 challenge.
