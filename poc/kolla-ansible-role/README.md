# Kolla-Ansible role contract harness

This isolated harness validates Coffer's operator-local companion role against
the exact Kolla-Ansible `stable/2026.1` commit recorded in
`ansible/KOLLA_ANSIBLE_COMMIT`. It does not deploy OpenStack, contact Keystone,
pull images, or start real containers. Contract-only Ansible modules record
safe lifecycle events without retaining module arguments or secret values.

The harness covers:

- disabled-mode no-op and every required lifecycle action;
- action-first wrapper ordering and refusal of destructive unrelated actions;
- HAProxy single-external-frontend rendering and verified backend TLS;
- proposed Keystone `oci-registry` service and three endpoint interfaces;
- database creation followed by repeat-safe one-shot bootstrap;
- bootstrap-before-process ordering and bootstrap-failure rollout blocking;
- secret source permissions and per-process recipient boundaries;
- idempotent reconfigure, pull, and stop;
- negative missing/unsafe secret, plaintext RGW, disabled backend TLS, occupied
  port, and direct-registry-bypass prechecks;
- exact removal of generated keys, certificates, state, and rendered configs.

## Prerequisites

- the repository's `.venv` with the Coffer package and test dependencies;
- an ignored `work/kolla-ansible-stage3` checkout at the recorded commit;
- that checkout's `.venv` with its runtime and lint requirements installed.

Run:

```console
make -C poc/kolla-ansible-role verify
```

For an installed Kolla-Ansible environment, invoke the companion playbook
through the action-first wrapper:

```console
ansible/kolla-ansible-coffer prechecks -i /path/to/inventory
ansible/kolla-ansible-coffer deploy -i /path/to/inventory
```

The wrapper accepts only `prechecks`, `deploy`, `reconfigure`, `pull`,
`upgrade`, `stop`, `validate-config`, `check`, and `genconfig`. Destructive
or unrelated Kolla commands are deliberately not forwarded.

The script creates only `poc/kolla-ansible-role/work`, uses loopback ports
`61313` and `18787` for bounded readiness/collision checks, and removes the
work directory in a `finally` block. The macOS-only address filter and fake
container modules live inside this harness and are never added to the product
role or operator wrapper.

## Isolated Linux validation target

`provision-validation-vm.sh` is intended to run only on the approved `bb00`
libvirt host. It creates the exact `coffer-kolla-stage3` domain with 8 vCPUs,
24 GiB RAM, a 120 GiB overlay in the existing `coffer-rgw` pool, static
`192.168.122.201` addressing on the default NAT network, and autostart
disabled. It does not reserve DHCP state or touch host ports, HAProxy, Harbor,
or any existing domain.

The `destroy` action removes only that exact domain and its three named volumes
(the copied base, writable overlay, and cloud-init seed).
It is used after bounded Linux contract evidence so the validation target
leaves no VM or storage residue.

With the guest reachable, `verify_remote.py` runs the lifecycle from the local
controller while using upstream Kolla's Linux address filter on the guest.
Connection details are required as environment variables and are written only
to the ignored, disposable fixture inventory:

```console
COFFER_STAGE3_JUMP_HOST=user@jump-host \
COFFER_STAGE3_GUEST_HOST=guest-address \
COFFER_STAGE3_KNOWN_HOSTS=/path/to/temporary-known-hosts \
make -C poc/kolla-ansible-role verify-remote
```

The remote run removes `/tmp/coffer-stage3-contract` even after failure. It
does not install packages, start real containers, bind guest ports 80/443, or
exercise the Stage 4 tenant OCI path.
