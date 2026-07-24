# Kolla AIO Stage 4 harness

This directory owns the disposable Stage 4 x86_64 validation target and its
full Kolla-Ansible/Coffer acceptance flow. It never installs on the shared
libvirt host and does not reuse host HAProxy, Harbor, or unrelated domains.

`provision-validation-vm.sh` runs on the approved libvirt host as its existing
libvirt-group user. It creates only `coffer-kolla-aio-stage4`, with 8 vCPUs,
32 GiB RAM, a 180 GiB root overlay, two dedicated NICs, static management
address `192.168.122.202`, and autostart disabled. The Ubuntu 24.04 cloud image
is accepted only at the SHA-256 pinned in the script.

The `destroy` action removes only the exact Stage 4 domain and its seed, root,
and copied-base volumes. It does not change the default network or its DHCP
configuration.

## Execution order

Run the VM provisioner on the approved libvirt host:

```text
./provision-validation-vm.sh create
./provision-validation-vm.sh status
```

Inside the disposable AIO, use the pinned Kolla-Ansible source and
`globals.yml` for `bootstrap-servers`, `prechecks`, `pull`, and `deploy`.
Then copy this repository checkout into the guest and run the Coffer-specific
helpers in this order:

1. `guest-stage4-rgw-user.sh prepare` in the retained RGW lab.
2. `guest-stage4-create-bucket.py` and `guest-prepare-coffer.sh` in the AIO.
3. Companion-role precheck and deploy through `ansible/kolla-ansible-coffer`.
4. `guest-stage4-identities.py prepare` followed by
   `guest-stage4-tenant-acceptance.sh`.
5. `guest-stage4-restart-verify.sh`.
6. Two captured companion reconfigure runs followed by
   `guest-stage4-idempotency-verify.sh`.

Cleanup runs in reverse ownership order: identity helper `cleanup`, RGW helper
`cleanup`, companion `stop`, exact Coffer container removal, then the
provisioner's `destroy` action. Audit the exact domain, volumes, identity and
bucket names after removal. Do not use this harness against a retained or
production Kolla deployment.

`globals.yml` owns the Kolla AIO input and `coffer-globals.yml` owns only
non-secret companion-role inputs. Stage 4 generates the Coffer backend CA,
certificate, signing key, JWKS, database/service passwords, Distribution HTTP
secret, and disposable RGW credentials directly under
`/etc/kolla/config/coffer` in the AIO. Private material is never copied back to
the repository or printed as command output.

This target is a non-production AIO. Its external Kolla and Coffer origins,
Coffer process backends, and external RGW boundary all use verified TLS. Kolla
core-service backends and its internal VIP remain HTTP inside the disposable
single-node guest. This does not close multinode/HA, backup, upgrade, or
security-image promotion gates.
