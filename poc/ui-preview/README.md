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
LAN or wildcard addresses, and passes the already terminated Kolla TLS streams
through without copying a private key onto the shared host:

```text
https://100.123.168.66:18443  Horizon
https://100.123.168.66:19999  Skyline
```

The backend preview certificate was issued for `192.168.122.221`, so a browser
using the `bb00` address requires a one-time certificate-warning bypass. The
proxy routes only these two dashboards to the preview external VIP. It does
not expose Keystone, MariaDB, the Coffer data plane, or a backend container
port. The lifecycle validates the complete HAProxy configuration before an
atomic install or removal, preserves a one-time backup, and owns only its
bounded marker block:

```text
sudo ./bb00-system-haproxy.sh install
sudo ./bb00-system-haproxy.sh status
sudo ./bb00-system-haproxy.sh remove
```

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

Retrieve only project A's disposable login material into the owner's terminal:

```text
ssh -J bb00 ubuntu@192.168.122.204 \
  "sudo jq -r '.project_a | \"Domain: Default\nProject: \(.project_name)\nUser: \(.username)\nPassword: \(.user_password)\"' /root/coffer-ui-preview-identities.json"
```

The login and application credentials expire or are removed with the preview;
they are never stored in this repository or printed by the deployment
harness. Both dashboards expose **Project → Registry → Repositories** for
project A. The retained proof repository is `preview-proof`.

This preview proves a functional browser integration only. It does not clear
the independent Distribution, Ceph/KMS, dependency, scanner, signing,
publication, HA, backup, upgrade, or production-promotion gates.
