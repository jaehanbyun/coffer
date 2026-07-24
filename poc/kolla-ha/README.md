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

For a bounded Stage 5 application update, build a separate Coffer tag while
the accepted runtime stays on the original image:

```text
poc/kolla-ha/build-distribute-coffer-update.sh preflight <ssh-target>
poc/kolla-ha/build-distribute-coffer-update.sh status <ssh-target>
poc/kolla-ha/build-distribute-coffer-update.sh build <ssh-target>
```

This path archives only pinned local commit
`a6f476e65f89048860309dc277406c96fd7fa0e7`, verifies the complete archive and
installed quota-module digests, and builds
`localhost/coffer:stage5-quota-retry` without publishing it. The identical
image is streamed directly to controller-2/3. Acceptance requires every
running API/edge/registry container to retain its original image ID and health;
the original `localhost/coffer:stage5` image remains the rollback input. This
phase creates no container and performs no Kolla action.

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

Before `prechecks` and the first `deploy`, the complete companion `ready` gate and
external RGW audit must pass. Prechecks must leave all Coffer runtime,
database, catalog, listener, and rendered-service state absent. Deploy adds
three API, three edge, and three private Distribution replicas, then requires
container health, nine verified-TLS service backends plus nine nonlocal-VIP
frontend sockets, one-shot migration head, Keystone service/user/endpoints,
sole public edge routing, private-port denial, Kolla `check`, and healthy
external RGW before its marker is written.

An accepted `status` also collects API, edge, and Distribution logs from all
three controllers into root-only temporary files on controller-1. It scans
them against Kolla and companion secrets plus private-key, Authorization, and
JWT patterns, then removes every temporary file before returning. A repeated
`deploy` validates the same complete boundary and returns idempotently without
replacing its marker, lifecycle logs, or service containers. OCI
tenant/isolation and disruptive-fault acceptance remain later phases.

If an operator-role correction is required after the immutable functional
images have already been built, prepare a separate exact operator source:

```text
poc/kolla-ha/prepare-coffer-operator-source.sh status <ssh-target>
poc/kolla-ha/prepare-coffer-operator-source.sh prepare <ssh-target>
```

This phase clones the still-clean published source locally on controller-1
and installs only the two SHA-256-pinned operator files admitted by the
harness. Version 2 supplies the one-shot bootstrap CA input and makes edge
trust the Kolla internal-VIP CA while preserving the separate Coffer leaf CA.
It does not rebuild or relabel runtime images, modify the published source
checkout, or use a registry. The resulting Git state must retain the
published base commit, exactly two modified paths, no untracked files, and a
root-only completion marker. The companion lifecycle validates this exact
overlay before any resumed deploy.

Prepare the finite two-project tenant fixture only after the replicated
companion boundary is accepted:

```text
poc/kolla-ha/run-coffer-tenant-fixture.sh preflight <ssh-target>
poc/kolla-ha/run-coffer-tenant-fixture.sh prepare <ssh-target>
poc/kolla-ha/run-coffer-tenant-fixture.sh renew-preflight <ssh-target>
poc/kolla-ha/run-coffer-tenant-fixture.sh renew <ssh-target>
poc/kolla-ha/run-coffer-tenant-fixture.sh status <ssh-target>
poc/kolla-ha/run-coffer-tenant-fixture.sh cleanup <ssh-target>
```

Every action first reruns the full companion, routing, runtime-log, and
external-RGW status gate. `preflight` requires the exact project, user,
credential, owner-client, Docker image, CA override, and transfer namespaces
to be absent. The isolated external VIP has no persistent DNS record, so an
absent `registry.coffer.stage5` resolution is accepted only as
`dns=override-required`; a later client phase must install and exactly restore
its temporary owner-local mapping.

`prepare` uses the already deployed `kolla_toolbox` identity SDK and the
internal Keystone endpoint. The existing Kolla admin password is materialized
only as a root-owned mode-0600 `/run` transfer and removed on every exit. It
creates exactly two projects, two users with only the project `member` role,
and two unrestricted-false application credentials with a twelve-hour expiry.
The credential state and marker remain mode `0600` only on controller-1.
Controller-2/3 retain no client material. Repeated prepare validates the same
identities without rotating them. `cleanup` removes the exact credentials,
users, and projects from the recorded immutable IDs; it is reserved for the
final fixture teardown after dependent acceptance and fault phases.

`renew-preflight` is read-only and admits renewal only from the exact
two-project/two-user/two-credential state. `renew` preserves the project and
user IDs: it creates and authenticates two fresh twelve-hour credentials,
atomically records their owner-only state together with the two retiring IDs,
then deletes only those retiring credentials and atomically finalizes the
state. A mode-0600 completion marker makes the accepted renewal idempotent.
An interrupted finalization retains enough state for an exact retry; unknown
or additional credentials fail closed.

Run tenant OCI acceptance only after that finite fixture is prepared:

```text
poc/kolla-ha/run-coffer-tenant-acceptance.sh preflight <ssh-target>
poc/kolla-ha/run-coffer-tenant-acceptance.sh accept <ssh-target>
poc/kolla-ha/run-coffer-tenant-acceptance.sh status <ssh-target>
```

The clean preflight requires zero target repository and quota rows plus zero
client residue. `accept` creates or resumes exactly one project-A repository.
It first sets a one-byte logical quota, uploads two small valid descriptors,
and requires manifest admission to return OCI `TOOMANYREQUESTS` with HTTP
429. It then raises the quota to 2 GiB, tags the already present functional
Coffer image, and runs Docker push and pull through the sole external port
443 frontend on the unique VIP owner.

The same owner-local client requires project-B Docker pull/push and direct
tag/blob requests to fail, then uploads a deterministic 2-MiB blob with two
separate PATCH requests and a final digest commit. Its temporary
`/etc/hosts` entry, Docker CA directory, auth files, secret copy, and tenant
image tags are restored or removed by an EXIT trap. Completion also requires
zero reserved quota, retained manifest/blob digests, exact control-plane
isolation, and a nine-container runtime-log scan against both tenant
passwords, both application credential secrets, private-key, Authorization,
and JWT patterns. Repository/evidence/markers stay root-only on controller-1
for the later fault matrix. Repeated `accept` performs the read-only boundary
and does not replace them.

After tenant acceptance, run the exact controller-3 service-replica matrix:

```text
poc/kolla-ha/test-coffer-service-failover.sh preflight <ssh-target>
poc/kolla-ha/test-coffer-service-failover.sh run <ssh-target>
```

The mutation-free preflight requires all nine Coffer containers healthy,
the complete tenant/digest/isolation boundary, and either zero or only the
three allowlisted root-owned completion markers. `run` stops only
controller-3's API, edge, and unmodified Distribution containers, one at a
time. While each replica is unavailable it requires three authenticated
manifest/blob reads plus project-B denial through the surviving external
path. Every target is restarted and required healthy before the next fault;
an EXIT trap restores the current exact container after an intermediate
failure. A repeated run validates the complete boundary and skips all
completed faults without replacing their markers.

After the service-replica matrix, run the active Kolla HAProxy fault:

```text
poc/kolla-ha/test-kolla-haproxy-failover.sh preflight <ssh-target>
poc/kolla-ha/test-kolla-haproxy-failover.sh run <ssh-target>
```

The preflight dynamically resolves the one controller that owns both Kolla
VIPs and requires all three HAProxy containers healthy, all three Keepalived
checks passing, and the complete tenant boundary. `run` stops only that
owner's HAProxy container. Keepalived remains running and must move both VIPs
to one different allowlisted controller. Three authenticated tenant probes
then pass through the surviving HAProxy path; each probe admits only three
bounded attempts for VRRP/ARP/backend convergence. The exact original
HAProxy is restarted and required healthy, its Keepalived check must pass,
and full acceptance must finish with one shared internal/external VIP owner.
An EXIT trap restores the stopped HAProxy. Repeated runs validate state and
skip the completed fault without replacing the root-only marker.

After HAProxy recovery, run the exact Galera reader-member fault:

```text
poc/kolla-ha/test-kolla-galera-failover.sh preflight <ssh-target>
poc/kolla-ha/test-kolla-galera-failover.sh run <ssh-target>
```

The preflight requires all three MariaDB and ProxySQL containers healthy,
Galera size 3/Primary/Synced, the exact controller-1 writer plus
controller-2/3 reader topology on all three ProxySQL instances, and the full
tenant boundary. `run` pauses only controller-3 MariaDB; stop/start is not
used because an external Kolla control path may restart a stopped database
container. The surviving cluster must become size 2/Primary/Synced, and all
ProxySQL instances must move controller-3 into offline hostgroup 3.

During the pause, three database probes each change the accepted project's
quota limit from 2 GiB to 2 GiB plus one byte, read it back, restore 2 GiB
under an EXIT guard, and rerun digest/isolation checks. The exact target is
then unpaused and must return healthy; Galera must recover size 3/Synced and
all ProxySQL readers must return online before full acceptance and the
root-only completion marker. The outer EXIT trap unpauses the target after
any intermediate failure. Repeated runs perform no pause and retain marker
metadata.
