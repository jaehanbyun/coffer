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
poc/kolla-ha/run-kolla-lifecycle.sh reconfigure <ssh-target>
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

Before preparing or deploying Coffer, preserve the exact clean boundary:

```text
poc/kolla-ha/preflight-coffer-ha.sh clean <ssh-target>
poc/kolla-ha/preflight-coffer-ha.sh ready <ssh-target>
```

`clean` requires the same twelve healthy Kolla baseline containers on every
controller and rejects any Coffer container, listener, service configuration,
HAProxy route, image, Galera schema/user, Keystone service/user, companion
inventory group, source checkout, or owner-controlled input. It also proves
the three-node external RGW healthy, requires its credentials and public CA
only on storage-1, and reads the retained 4-MiB sentinel without changing it.

`ready` is a later pre-deploy gate. It retains the zero-runtime, zero-database,
and zero-catalog requirements while additionally requiring identical
`localhost/coffer:stage5` and `localhost/coffer-registry:stage5` image IDs on
all controllers, the published product source commit, three-host companion
groups, internal/external Kolla TLS, the single external frontend on port
443, the `registry.coffer.stage5` certificate name, complete verified backend
TLS recipients, and exact owner-only Coffer inputs. It must fail before the
companion role runs if any recipient, image, group, certificate, RGW input, or
source pin differs.

Prepare the Kolla-side production TLS/frontend inputs without reconfiguring a
running container:

```text
poc/kolla-ha/prepare-kolla-production-profile.sh status <ssh-target>
poc/kolla-ha/prepare-kolla-production-profile.sh prepare <ssh-target>
```

The first `prepare` requires the complete Coffer `clean` preflight. It retains
the existing Stage 5 CA, generates a short-lived internal VIP certificate and
replaces only the source external certificate with IP
`192.168.254.10` plus DNS `registry.coffer.stage5`, prepares the ProxySQL
CA/certificate/key recipients, then changes four allowlisted globals:
internal TLS, the single external frontend, public port `443`, and the
container CA bundle path.
The existing globals and external PEM are held only in a root temporary
directory during the atomic action. Any failure restores those two files and
removes only the newly created internal PEM and completion marker.

Acceptance compares the names, IDs, and start times of the exact twelve Kolla
containers before and after preparation, requires Coffer runtime/images/inputs
to remain absent, and leaves no temporary key, serial, or backup. A repeated
`prepare` validates the marker, certificate identities, globals, and unchanged
runtime without rotating certificates. Kolla reconfiguration is a separate
guarded lifecycle phase.

The exact `reconfigure` phase requires the accepted deploy and prepared-profile
markers. It retains the same no-log and generated-credential scan, then proves
all 36 Kolla containers healthy, three-member Galera and RabbitMQ quorums,
exactly one owner for each VIP, trusted internal HTTPS, the sole external
frontend on port `443`, denial of plaintext, untrusted TLS, and the retired
external port `5000`, the canonical Keystone internal/public catalog URLs,
DNS certificate identity, and zero Coffer state. Its root-only completion
marker is written only after the independent external Ceph/RGW health audit
also passes.

Build and distribute the two functional x86_64 pilot images only after that
reconfigure is accepted:

```text
poc/kolla-ha/build-distribute-coffer-images.sh status <ssh-target>
poc/kolla-ha/build-distribute-coffer-images.sh build <ssh-target>
```

The builder checks out published Coffer commit
`4f1ff7ddfd89d21f17ab7cbb531c335e85d94542` and pinned Kolla image commit
`686c6d13dc1c31092b22c6c481e16a7329e935ea` on controller-1. It builds only
`localhost/coffer:stage5` and `localhost/coffer-registry:stage5` for x86_64,
validates their non-root process entry points, and streams Docker archives
directly through the existing controller deployment key to controller-2/3.
No bootstrap or tenant registry is used and no image is published.

The phase has a separate owner marker and root-only build log. A failed build
or transfer retains resumable owned state but cannot create the completion
marker. Acceptance requires the same two image IDs on all three controllers,
the exact source commit, 36 unchanged healthy Kolla containers, zero Coffer
runtime/config/listeners, and a healthy external Ceph/RGW boundary. Companion
inventory, owner-only inputs, database, catalog, and role execution remain
later phases.

Prepare the companion inventory and owner-controlled inputs only after the
image phase is accepted:

```text
poc/kolla-ha/prepare-coffer-companion.sh status <ssh-target>
poc/kolla-ha/prepare-coffer-companion.sh prepare <ssh-target>
```

`status` is mutation-free and rejects any temporary transfer residue. The
first `prepare` appends the four exact three-controller Coffer groups, stages
the production-profile globals, creates the signing/JWKS and backend-TLS
inputs, and transfers only the existing registry access key, secret key, and
public RGW CA directly from storage-1 to controller-1 through the encrypted
SSH path. No credential archive or value is retained on the local workstation,
and secret source files remain root-owned mode `0600` only on controller-1.

The guest phase uses a root temporary directory and restores the original
inventory while removing partially installed globals and inputs on failure.
The outer completion marker is created only after the independent `ready`
preflight proves exact groups, images, TLS identities, secret recipients,
external RGW access, and the continued absence of Coffer runtime, database,
catalog, and HAProxy routes. A repeated `prepare` validates the committed
state without rotating keys or certificates. Companion role `prechecks` and
deployment remain separate later phases.

Run the companion role only through its guarded lifecycle:

```text
poc/kolla-ha/run-coffer-companion-lifecycle.sh status <ssh-target>
poc/kolla-ha/run-coffer-companion-lifecycle.sh prechecks <ssh-target>
poc/kolla-ha/run-coffer-companion-lifecycle.sh deploy <ssh-target>
```

The wrapper invokes the published source's `ansible/kolla-ansible-coffer`
entry point from controller-1 with the pinned Kolla venv, exact inventory,
Kolla config/password files, and companion globals. `prechecks` and `deploy`
are separately locked, timeout-bounded, and ordered by root-only completion
markers. Their logs are replaced as root-only files and scanned against both
Kolla-generated passwords and every companion secret in raw and encoded
forms; a failed or contaminated phase cannot create its marker.

Before `prechecks` and `deploy`, the complete companion `ready` gate and
external RGW audit must pass. Prechecks must leave all Coffer runtime,
database, catalog, listener, and rendered-service state absent. Deploy adds
three API, three edge, and three private Distribution replicas, then requires
container health, nine verified-TLS backend listeners, one-shot migration
head, Keystone service/user/endpoints, sole public edge routing, private-port
denial, Kolla `check`, and healthy external RGW before its marker is written.
OCI tenant/isolation and disruptive-fault acceptance remain later phases.

If an operator-role correction is required after the immutable functional
images have already been built, prepare a separate exact operator source:

```text
poc/kolla-ha/prepare-coffer-operator-source.sh status <ssh-target>
poc/kolla-ha/prepare-coffer-operator-source.sh prepare <ssh-target>
```

This phase clones the still-clean published source locally on controller-1
and installs only the two SHA-256-pinned operator files admitted by the
harness. It does not rebuild or relabel runtime images, modify the published
source checkout, or use a registry. The resulting Git state must retain the
published base commit, exactly two modified paths, no untracked files, and a
root-only completion marker. The companion lifecycle validates this exact
overlay before any resumed deploy.
