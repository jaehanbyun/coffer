# Live Horizon and Skyline Coffer preview

This directory owns the retained, isolated, non-production UI preview on
`bb00`. It creates only the autostart-disabled `coffer-ui-preview-1` domain
and the three same-prefix volumes in the existing `coffer-rgw` libvirt pool.
It never changes an unrelated `dev11-*` domain, the host listener set, the
default network definition, or the retained `coffer-rgw-poc` service.

## Fixed ownership contract

| Resource | Value |
|---|---|
| Domain | `coffer-ui-preview-1` |
| Root storage | `coffer-rgw/coffer-ui-preview-1-root.qcow2` |
| Management address | `192.168.122.204` |
| Internal Kolla VIP | `192.168.122.205` |
| External Kolla VIP | `192.168.122.221` |
| Management/external MAC | `52:54:00:cf:fe:27`, `52:54:00:cf:fe:28` |
| Capacity | 8 vCPU, 40 GiB RAM, 220 GiB sparse root |
| Ubuntu input | Noble serial `20260725`, pinned by SHA-256 |
| Kolla-Ansible input | `stable/2026.1` commit `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc` |
| RGW identity/bucket | `coffer-ui-preview-1` |

The provisioner checks that all exact domain, volume, address, and MAC inputs
are unused before creation. `destroy` is intentionally exact: it removes only
the named domain and its three named volumes. The preview stays retained until
the owner explicitly runs that action.

## Operator lifecycle

Run `provision.sh` on `bb00` as the existing libvirt-group user:

```text
./provision.sh create
./provision.sh status
./provision.sh stop
./provision.sh start
./provision.sh destroy
```

Kolla uses `globals.yml` and merges `skyline.yaml` through its standard
`/etc/kolla/config/skyline/skyline.yaml` override. The latter maps Keystone's
proposed `oci-registry` service type to Skyline's `coffer` endpoint key. The
companion role additionally uses `coffer-globals.yml`. Horizon is served on
the Kolla external TLS listener at port 443. Skyline Console uses port 9999
and proxies Skyline API and OpenStack service calls through its own Nginx
origin. Coffer's sole public ingress is port 8788.

After rebuilding the pinned Skyline wheel, `guest-refresh-skyline.sh` replaces
only the exact Skyline preview image, image contract, and corresponding
companion global. It preserves Horizon and all Coffer runtime images.

From the user's Mac, create local-only tunnels without opening a host port:

```text
ssh -N \
  -L 18080:192.168.122.205:80 \
  -L 19000:192.168.122.205:9999 \
  -L 18789:192.168.122.205:8788 \
  bb00
```

The internal HTTP listeners are protected by the local-only SSH tunnel and
avoid a browser warning for the preview IP certificate. Open
`http://localhost:18080` for Horizon and `http://localhost:19000` for
Skyline. Coffer's OCI/control ingress is available at
`http://localhost:18789`.

For retained owner access without an SSH tunnel,
`bb00-system-haproxy.sh install` adds one marker-owned block to the existing
system HAProxy on `bb00`. It binds only the host's Tailscale address, not the
LAN or wildcard addresses. The dashboard streams remain TLS passthrough. The
registry frontend terminates an owner-generated preview certificate and
re-encrypts to two Coffer Edge processes with exact backend-CA and hostname
verification:

```text
https://100.123.168.66:18443  Horizon
https://100.123.168.66:19999  Skyline
https://bb00.tail23b778.ts.net:18788  Coffer control, token, and OCI
```

The backend preview certificate was issued for `192.168.122.221`, so a browser
using the dashboard addresses requires a one-time certificate-warning bypass.
The registry name uses an owner-local preview CA because this tailnet does not
allow Tailscale-managed TLS certificates. Prepare that CA and stage only its
public certificate plus the leaf certificate/key; the root CA private key
never leaves the Mac:

```text
./prepare-user-endpoint-tls.sh create
./prepare-user-endpoint-tls.sh stage
```

The proxy exposes only Edge. It explicitly rejects operational and private
maintenance paths and never routes to Distribution, RGW, MariaDB, Keystone,
or a debug/metrics listener. The lifecycle validates certificate identity,
the complete HAProxy configuration, the OCI challenge realm, and exact file
ownership before an atomic install or removal. It preserves a one-time config
backup and owns only its bounded marker, certificate, backend CA, and Docker
registry CA paths:

```text
sudo ./bb00-system-haproxy.sh install
sudo ./bb00-system-haproxy.sh status
sudo ./bb00-system-haproxy.sh remove
```

The optional same-host HA evidence uses one additional Edge and Distribution
process on guest ports 18888 and 18889. These ports remain on the libvirt
management network and are never host listeners. Start or remove only those
exact replicas with:

```text
sudo ./guest-replicas.sh start
sudo ./guest-replicas.sh status
sudo ./guest-replicas.sh stop
```

This proves shared-RGW and load-balancer continuity only; both replicas still
share one VM and failure domain.

Run the real-client and bounded primary-pair outage acceptance from the Mac:

```text
./mac-registry-acceptance.sh
```

The orchestrator stages only two disposable application credentials through
mode-0600 temporary files, stops the primary Edge and Distribution pair, and
always restores the pair and removes the staging files on exit. The host-side
runner verifies the TLS name and token challenge, Docker, pinned Podman and
ORAS push/pull, project-B denial, and a failover push/pull. It retains only
secret-free, owner-readable evidence at
`/home/jh.byun/coffer-registry-acceptance-v2.json`.

After that v2 evidence exists, repeat the bounded process restart and
persistence check from the Mac:

```text
./mac-registry-lifecycle-acceptance.sh
```

It pulls the accepted Docker digest before and after restarting the primary
API/Edge/Distribution and same-host Edge/Distribution replica processes,
checks the closed client-network ports and private paths, scans runtime logs
for credential material, and removes every temporary identity and Docker
configuration on exit.

The externally terminated TLS path can be inspected separately:

```text
ssh -N \
  -L 18443:192.168.122.221:443 \
  -L 19999:192.168.122.221:9999 \
  -L 18788:192.168.122.221:8788 \
  bb00
```

Its URLs are `https://localhost:18443` for Horizon and
`https://localhost:19999` for Skyline. Because the certificate is issued for
`192.168.122.221`, a browser using `localhost` will report a hostname mismatch.

## User registry workflow

The selected public origin is one URL with three product surfaces:

```text
https://bb00.tail23b778.ts.net:18788/v1
https://bb00.tail23b778.ts.net:18788/auth/token
https://bb00.tail23b778.ts.net:18788/v2/
```

The Keystone catalog stores the `/v1` URL. Authenticated `GET /v1` explicitly
returns all three links. Do not remove `/v1` from a catalog URL to guess the
OCI endpoint.

Install the Coffer wheel with its client extra into an OpenStackClient
environment. The resulting commands are:

```text
openstack registry endpoint show
openstack registry repository create demo
openstack registry repository list
openstack registry repository show <repository-id>
openstack registry quota show
openstack registry login --client docker
```

`registry login` requires `OS_APPLICATION_CREDENTIAL_ID` or the corresponding
option and reads the application credential secret only from a hidden prompt
or stdin. It does not accept a human/admin password and never places the
secret in argv or an environment variable. The OCI image name is:

```text
bb00.tail23b778.ts.net:18788/p/<project-id>/<repository-name>:<tag>
```

For `curl`, Podman, or ORAS use the owner CA at
`~/Library/Application Support/Coffer/preview-tls/registry-ca.crt`. The host
HAProxy lifecycle installs the same public CA only into Docker's exact
`certs.d/bb00.tail23b778.ts.net:18788` trust directory for the bounded live
acceptance and removes it with the proxy.

Retrieve only project A's disposable login material into the owner's terminal:

```text
ssh -J bb00 ubuntu@192.168.122.204 \
  "sudo jq -r '.project_a | \"Domain: Default\nProject: \(.project_name)\nUser: \(.username)\nPassword: \(.user_password)\"' /root/coffer-ui-preview-identities.json"
```

The login and application credentials expire or are removed with the preview;
they are never stored in this repository or printed by the deployment
harness. Both dashboards expose **Project → Registry → Repositories** for
project A. The retained proof repository is `preview-proof`.

This preview proves one functional browser, control, token, OCI, and same-host
replica integration. It does not clear the independent Distribution,
Ceph/KMS, dependency, scanner, signing, publication, multi-failure-domain HA,
backup, upgrade, or production-promotion gates.
