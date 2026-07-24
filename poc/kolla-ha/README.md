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
