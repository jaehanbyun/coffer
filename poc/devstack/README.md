# Disposable Mac DevStack Identity Lab

This harness runs a real, deliberately narrow Keystone environment inside an
Ubuntu 24.04 Lima VM. It exists to close Coffer's local identity evidence
gap without treating macOS, MinIO, or a synthetic token fixture as production
OpenStack evidence.

The pinned guest enables only:

- Keystone;
- MySQL;
- the DevStack TLS proxy.

Nova, Neutron, Cinder, Horizon, Swift, Ceph, and RGW are intentionally absent.
The lab validates real Keystone TLS, domain/project UUID isolation, scoped
tokens, reader/member/admin/service application-credential roles, domain and
system nonproject isolation, finite expiration, delegated-role removal, owner
disablement, deletion, Coffer's `keystoneauth1` exchange, the real
`keystonemiddleware` control path, incoming service-role enforcement, a
bounded single-process cache, and outage failure. It cannot close shared
production SQL/memcache or the Ceph RGW, SSE-KMS, HA, quota, and GC gates in
`docs/runbooks/real-keystone-rgw-poc.md`.

## Host prerequisites

- macOS on Apple Silicon or Intel;
- at least 16 GiB host RAM and 50 GiB free disk;
- Lima, `curl`, `jq`, and `uv`.

Install Lima from the Homebrew formula if it is not already present:

```bash
brew install lima
```

## Bootstrap and verify

```bash
make -C poc/devstack bootstrap
make -C poc/devstack verify
```

Defaults are an instance named `coffer-devstack`, four virtual CPUs, 8 GiB
RAM, a 50 GiB disk, the Lima `ubuntu-24.04` template, DevStack
`stable/2026.1`, and commit
`da2f4d73f5ad74fc8ecfbe15bd7e20f6b0982dbb`. Override resources through
`COFFER_DEVSTACK_INSTANCE`, `COFFER_DEVSTACK_CPUS`,
`COFFER_DEVSTACK_MEMORY_GIB`, and `COFFER_DEVSTACK_DISK_GIB` before bootstrap.

The bootstrap generates alphanumeric passwords inside the guest and keeps the
DevStack `local.conf` mode `0600`. Verification creates finite credentials in
the guest, transfers each role-restricted fixture through a host `mktemp`
directory solely to exercise Coffer's real authenticator, deletes it, proves
that reuse fails, and removes both temporary copies. No secret is written
under the repository. Public CA
and redacted non-secret evidence are retained only under ignored
`work/devstack/`. The harness uses Lima's Apple Virtualization framework and a
`vzNAT` interface so the host can verify the guest's TLS endpoint directly.

Inspect or stop the environment without deleting it:

```bash
make -C poc/devstack info
make -C poc/devstack stop
make -C poc/devstack start
```

Deletion is intentionally not wrapped by the Makefile. Resolve the exact
instance with `limactl list coffer-devstack`, then explicitly delete that
disposable instance with Lima when its evidence is no longer needed.

## Network troubleshooting

The host connects to the guest's `vzNAT` IPv4 address. A corporate VPN or local
firewall can intercept that subnet. If host TLS verification fails while guest
verification passes, inspect `limactl list coffer-devstack`, the macOS route
for the VM address, and VPN split-routing before changing any certificate
setting. Never work around a failure with `insecure=true` or `curl -k`.
