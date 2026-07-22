# Disposable Ceph RGW Lab

This harness creates the x86_64 VM used to validate Coffer's real Ceph RGW
storage path. It keeps the existing Mac DevStack guest as the Keystone
identity baseline and places Ceph on the separate `bb00` libvirt host.

The default VM is deliberately a functional single-host lab, not an HA or
performance reference:

- domain `coffer-rgw-poc` on `qemu:///system`;
- 8 vCPUs and 24 GiB RAM;
- Ubuntu 24.04 x86_64;
- a 60 GiB qcow2 root overlay;
- a separate 200 GiB sparse raw OSD disk;
- reserved libvirt NAT address `192.168.122.200`;
- autostart disabled.

The default directory pool is `/srv/nfs/coffer-libvirt`. That path is on a
local XFS filesystem on `bb00`; the existing NFS exports are sibling
directories rather than this pool. The rotational device may be used for
functional persistence and failure tests, but results from it are not Ceph
performance or physical-failure-domain evidence.

Run the bootstrap from the repository root:

```bash
make -C poc/rgw bootstrap-vm
make -C poc/rgw install-ceph
make -C poc/rgw deploy-rgw
make -C poc/rgw verify-rgw
make -C poc/rgw export-s3-profile
make -C poc/rgw verify-distribution
make -C poc/rgw verify-distribution-host
make -C poc/rgw verify-distribution-ha
make -C poc/rgw verify-gc-dry-run
```

The Ceph installer pins Tentacle 20.2.2, verifies the downloaded `cephadm`
artifact by SHA-256, resolves and records the exact `quay.io/ceph/ceph`
manifest digest, skips the dashboard and monitoring stack, and consumes only
the empty `/dev/vdb` device as the single OSD. The single-OSD lab sets new
pool size and minimum size to one; this is acceptable only for the disposable
functional PoC and is not a durability claim.

The RGW target is a single cephadm-managed Beast frontend on TCP 8443. Cephadm
generates its server certificate from the cluster-local root CA and includes
the guest hostname and inventory IP in the certificate SANs. The harness
exports only the public root certificate to ignored `work/rgw/` state and
verifies the endpoint through an SSH tunnel without disabling TLS validation.
Port 8443 does not accept plaintext HTTP. This internal CA is a disposable lab
trust anchor, not a proposed production PKI design.

S3 provisioning creates two ordinary, non-system RGW users. The registry user
owns only `coffer-registry-poc`; a second user owns `coffer-denial-poc` so the
harness can prove other-owner denial. Both users have zero admin capabilities
and `max-buckets=1`. Provisioning verifies an authenticated object round trip,
anonymous denial, other-bucket denial, and additional-bucket denial. Generated
keys remain in root-only guest state. `export-s3-profile` copies only the
registry key pair into an owner-only, ignored `work/rgw/distribution.env` file
for the next Distribution test; neither key is printed or checked into Git.

The final M3-A storage target runs the pinned, unmodified CNCF Distribution
v3.1.1 image inside the guest. It uses verified TLS both on its client-facing
endpoint and to RGW, forces S3 path-style addressing, disables object-store
redirects, and reads the service key from root-only runtime state. The fixture
copies a pinned image with Skopeo, pulls the same digest before and after both
a Distribution restart and an RGW restart, checks a blob directly without a
redirect, confirms RGW object presence, and scans logs for every runtime
secret. Distribution v3.1.1 remains PoC-only under ADR 0006; this storage
result does not waive its security or conformance gates.

`verify-gc-dry-run` is deliberately non-destructive. It requires redacted
evidence from a successful `poc/integration` run, stops the single registry so
no writes can race the mark phase, records the RGW object count, runs the
pinned image's `garbage-collect --dry-run`, verifies the count is unchanged,
restarts Distribution, and re-pulls the baseline, integrated Skopeo, and
integrated Podman manifests. It retains the collector log and a redacted JSON
summary under ignored `work/rgw/`. It never invokes a real collection; that
would require a separately reviewed maintenance window and explicit approval.

`verify-distribution-ha` starts a temporary second Distribution process on
guest port 5444 with the exact same RGW configuration and HTTP secret. It
uploads the first half of a random two-MiB blob through replica 1, stops that
process, rewrites only the upload Location authority to replica 2, finalizes
the upload there, restarts replica 1, and verifies the blob plus a selected
manifest from both endpoints. The temporary replica is always removed. This
proves shared upload-state compatibility on one VM; it is not load-balancer,
separate-host, RGW-HA, or failure-domain evidence.

The remote host must already be reachable as SSH alias `bb00`, and the
caller's public key must already be in the remote account's
`~/.ssh/authorized_keys`. The harness copies only public keys into cloud-init;
it does not copy private keys, passwords, tokens, or S3 credentials. It never
enables VM autostart.

The bootstrap refuses to mutate an existing domain. Deletion is intentionally
not wrapped: resolve the exact domain and storage volumes with `virsh` before
performing any destructive cleanup.
