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

Provisioning remains disabled until the Ubuntu image checksum is pinned and
the preflight proves all declared names, MAC addresses, networks, volumes, and
subnets are free while leaving at least 40 GiB host memory and 250 GiB storage
available after the complete six-guest budget.
