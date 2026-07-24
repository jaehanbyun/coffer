# Kolla multinode and HA pilot

This directory owns the disposable Stage 5 harness. It must create only the
names and networks declared in `topology.yml`, keep every domain autostart
disabled, and use the existing `coffer-rgw` libvirt pool without modifying the
retained `coffer-rgw-poc` domain or its three volumes.

The preferred pilot uses three minimal Kolla controllers and three independent
Ceph/RGW storage guests. Controller guests provide Galera, HAProxy/Keepalived,
Keystone, and replicated Coffer services. Storage guests provide a
three-member Ceph cluster, one RGW per host, and a redundant ingress VIP.
Kolla images come from an independent bootstrap source; the tenant Coffer
registry never bootstraps itself.

The networks are dedicated to Stage 5:

- `coffer-stage5-mgmt` provides NAT for package and image retrieval plus the
  Kolla internal VIP.
- `coffer-stage5-storage` is isolated and carries Ceph/RGW traffic.
- `coffer-stage5-external` is isolated and carries only the Kolla external
  VIP. Acceptance clients reach it through a bounded SSH tunnel to `bb00`;
  no shared-host port is published.

Before any create action, run the secret-safe read-only inventory:

```text
poc/kolla-ha/inventory-host.sh <ssh-target> \
  > work/kolla-ha/host-inventory.json
```

The evidence file stays ignored under `work/`. It records aggregate capacity,
libvirt names and sizes, operational network state, listeners, and restricted
Docker fields. It does not read command lines, environment variables,
configuration contents, credentials, keys, or certificates.

The provision wrapper accepts four explicit actions:

```text
poc/kolla-ha/provision.sh preflight <ssh-target>
poc/kolla-ha/provision.sh status <ssh-target>
poc/kolla-ha/provision.sh create <ssh-target>
poc/kolla-ha/provision.sh destroy <ssh-target>
```

`preflight` and `status` are read-only. `create` always reruns preflight, then
defines only the three declared networks, sixteen declared volumes, and six
declared domains. It downloads the date-pinned Ubuntu image on the host,
verifies its SHA-256 before upload, keeps every network and domain autostart
disabled, and rolls back only resources recorded as created by that invocation
if a later step fails.

`destroy` is destructive and intentionally exact: the remote helper has a
second hard-coded Stage 5 allowlist and refuses any other domain, network,
bridge, pool, base volume, or MAC prefix. It removes the six declared domains
before their volumes, removes the shared Stage 5 base last, then removes only
the three Stage 5 networks. It never uses `--remove-all-storage`, a wildcard,
or a domain/pool prefix query as a deletion target.

The current preflight requires all declared names, MAC addresses, networks,
volumes, and subnets to be free while leaving at least 40 GiB host memory and
250 GiB storage available after the complete six-guest budget.

After create, verify cloud-init, resources, disk shape, fixed addresses,
external-interface shape, and the guest agent through the jump host:

```text
poc/kolla-ha/verify-guests.sh <ssh-target>
```

This verification stores only guest host keys under ignored `work/` and emits
aggregate host/resource readiness. It does not read guest credentials or
configuration contents.

Prepare the three storage nodes and establish the Ceph control plane in
separate, fail-closed phases:

```text
poc/kolla-ha/prepare-storage.sh <ssh-target>
poc/kolla-ha/bootstrap-ceph-control.sh <ssh-target>
```

The preparation phase installs pinned prerequisites and proves `/dev/vdb` is
the sole empty 64-GiB OSD candidate on each storage node. The control phase
bootstraps only storage-1, distributes only cephadm's public key to storage-2/3,
registers the three exact storage addresses, and converges on three MONs and
two MGRs while requiring zero OSDs and zero RGW services.

Only after the control-plane health gate passes, initialize the three exact
OSD devices:

```text
poc/kolla-ha/bootstrap-ceph-osds.sh <ssh-target>
```

The OSD phase never selects all available devices. It admits only `/dev/vdb`
on the three hard-coded storage hostnames, supports an exact partial resume,
and exits only when one OSD per host is `up` and `in`, cluster health is OK,
replica defaults remain size 3/minimum 2, and RGW is still absent.

Deploy RGW and its redundant VIP only after the OSD gate:

```text
poc/kolla-ha/bootstrap-ceph-rgw.sh <ssh-target>
```

This phase deploys one TLS RGW backend per storage host on port `9443`, two
HAProxy/Keepalived ingress pairs on storage-1/2, and the reserved
`192.168.253.30:8443` VIP. The backend uses cephadm-signed certificates. The
frontend uses a short-lived lab CA and server key generated owner-only on the
primary; only the public CA is exported under ignored `work/kolla-ha/`.
Acceptance requires verified backend/frontend TLS, exactly one VIP owner,
healthy replicated pools, and zero S3 users. User/bucket provisioning and
failure testing are later phases.

Create the disposable private S3 fixtures only after the RGW HA endpoint
passes:

```text
poc/kolla-ha/provision-ceph-s3.sh <ssh-target>
```

This phase creates one non-system registry identity and one independently
owned denial identity with one-bucket limits and no admin caps. Credentials
and the future Distribution environment stay mode `0600` only on storage-1;
secondary hosts and the local workspace receive no S3 secret. The fixture
proves anonymous, cross-owner, and extra-bucket denial, then retains one
deterministic 4-MiB private object for replica-loss testing. Repeated execution
must verify the existing key identities and object digest rather than rotate or
overwrite them.

After the fixture passes, exercise the bounded daemon-level failure baseline:

```text
poc/kolla-ha/test-ceph-rgw-failover.sh <ssh-target>
```

The harness first stops only the RGW replica on storage-3, performs five
read-only sentinel round trips through the VIP, and restores the replica. It
then stops the exact Keepalived and HAProxy daemons on the current VIP owner,
requires the VIP to move to the surviving ingress host, performs five more
read-only round trips, and restores both ingress pairs. An exit trap attempts
full exact-service restoration on every failure. This phase does not stop an
OSD, MON, MGR, VM, network, or host service outside the Ceph-managed RGW and
ingress allowlists.

After daemon-level recovery passes, exercise one exact storage VM power-loss
boundary:

```text
poc/kolla-ha/test-ceph-storage-vm-failover.sh <ssh-target>
```

This phase validates the complete libvirt XML and autostart-disabled state of
storage-3, then uses `virsh destroy` only as an abrupt power-off simulation.
It never undefines the domain or removes storage. While storage-3 is off,
acceptance requires two-MON quorum, two of three OSDs up, two RGWs, both
ingress pairs, no inactive PG, one VIP owner, and five private sentinel reads.
The same domain is then started and must return to three-MON quorum, three
up/in OSDs, three RGWs, clean PGs, and `HEALTH_OK`. An exit trap starts the
exact target and attempts the same recovery gate after any intermediate
failure.

Before installing Kolla on the three controller guests, run the mutation-free
controller preflight:

```text
poc/kolla-ha/preflight-kolla-controllers.sh <ssh-target>
```

It renders the official pinned Kolla-Ansible 2026.1 multinode inventory into
ignored `work/kolla-ha/`, validates the control/network/database/identity
groups, and checks the committed minimal Keystone/Galera/HAProxy globals. Each
controller must still have its exact three-interface shape, clean Kolla and
container state, at least 15 GiB RAM and 70 GiB root space, synchronized time,
free reserved ports, outbound bootstrap access, and reachability to the
external RGW VIP. The retained storage cluster must remain fully healthy.
This preflight does not install a package, create an SSH key, generate a
password, assign a VIP, or start a container.

After the clean preflight is preserved, prepare the controller-1 deployment
host without running Kolla:

```text
poc/kolla-ha/prepare-kolla-controllers.sh <ssh-target>
```

The phase generates one owner-only Ed25519 deployment key on controller-1 and
adds only its public-key marker to the three exact controller accounts. It
checks out the exact Kolla-Ansible commit into an owner-marked state directory,
creates a dedicated venv, installs its pinned Galaxy dependencies, renders
`/etc/kolla/multinode`, and generates root-only passwords plus a short-lived
external-VIP certificate. A final Ansible ping must reach all three
controllers from controller-1. Public-key and config transfer files are
removed. This phase does not run `bootstrap-servers`, install Docker on the
secondary controllers, assign either Kolla VIP, or start a container.

Run the Kolla control-plane lifecycle as separately resumable phases:

```text
poc/kolla-ha/run-kolla-lifecycle.sh status <ssh-target>
poc/kolla-ha/run-kolla-lifecycle.sh bootstrap <ssh-target>
poc/kolla-ha/run-kolla-lifecycle.sh prechecks <ssh-target>
poc/kolla-ha/run-kolla-lifecycle.sh pull <ssh-target>
poc/kolla-ha/run-kolla-lifecycle.sh deploy <ssh-target>
```

Only `prechecks` receives Kolla's `--use-test-images` exception. Every
mutating phase requires the preceding success marker, takes a non-blocking
single-run lock, has a hard timeout, and replaces an owner-only phase log on
controller-1. Failed phases retain their log but do not create a completion
marker, so the same phase can be diagnosed and resumed. The wrapper proves the
external Ceph/RGW HA endpoint healthy before and after every phase. `status`
only reads the exact three controllers and reports aggregate Docker, image,
container, VIP, and phase-marker state without creating lifecycle state.

If lifecycle-log acceptance ever exposes the disposable RabbitMQ monitoring
credential, first remove only the invalid deploy marker and sanitize the
owner-only logs, then rotate exactly that one generated password:

```text
poc/kolla-ha/rotate-kolla-monitoring-password.sh <ssh-target>
```

The helper refuses an accepted deploy, validates the three preceding
lifecycle markers, changes only `rabbitmq_monitoring_password` in the
root-only Kolla password file, creates no backup, and never outputs either
value. The control plane must immediately be reconciled by rerunning the
bounded `deploy` phase; rotation alone is not an accepted steady state.
