# Kolla UI integration contract

Status: accepted local companion-role baseline

Baseline: Kolla-Ansible `stable/2026.1` at
`cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc`

## Result

Coffer does not install Python packages or replace static files inside running
Horizon or Skyline containers. Each UI is integrated through one separately
built immutable image:

| Surface | Custom artifact | Container transition |
|---|---|---|
| Horizon | `coffer-horizon` 0.1.0 wheel on Horizon 25.7.3 | existing `horizon` container only |
| Skyline | `skyline-console` `8.0.0+coffer.1` wheel at the pinned Console revision | existing `skyline_console` container only |

The main Kolla deployment remains responsible for both dashboards. The Coffer
companion playbook refuses to create a missing parent dashboard and never
changes `skyline_apiserver`.

## Immutable image contract

The build pipeline supplies a public JSON contract for each enabled surface.
It binds:

- schema and container contract version;
- surface and exact upstream project revision;
- wheel name, version, and SHA-256;
- custom image `@sha256:` reference;
- stock fallback image `@sha256:` reference.

`ui/images/write_contract.py` validates wheel metadata and emits the contract
atomically as mode 0640. The Kolla role rejects tags, missing or linked
contracts, wrong revisions, wrong package versions, unexpected fields,
different inventory image values, equal custom/fallback images, and absent
parent dashboard containers.

The contract has no token, password, certificate, private key, endpoint, or
catalog data.

## Lifecycle

```text
disabled + no marker
        |
        | enable and reconfigure
        v
validate contract -> write recovery marker -> swap to custom digest
        ^                                      |
        |           repeated reconfigure       |
        +--------------------------------------+
                                               |
                          disable and reconfigure
                                               v
                 swap to recorded fallback digest
                                               |
                              remove marker after success
                                               v
                                disabled + zero residue
```

Writing the marker before enable preserves the fallback after an interrupted
custom-image transition. During disable, the marker remains until the fallback
container reconciliation succeeds. A retry therefore converges without
guessing the previous image.

`pull` selects only the active Horizon or Skyline Console image. `stop` owns
only Coffer service containers and does not stop either dashboard. Operators
disable both UI integrations through `reconfigure` before retiring their
custom images.

## Operator variables

Both surfaces default to disabled:

```yaml
coffer_enable_horizon_dashboard: false
coffer_enable_skyline_console: false
```

An enabled Horizon integration requires:

```yaml
coffer_enable_horizon_dashboard: true
coffer_horizon_image_full: registry.example/coffer-horizon@sha256:<digest>
coffer_horizon_fallback_image_full: registry.example/horizon@sha256:<digest>
coffer_horizon_image_contract_file: /etc/kolla/config/coffer/ui/horizon-image.json
```

Skyline uses the parallel `coffer_skyline_console_*` variables and
`skyline-image.json`. The literal `<digest>` values above are documentation
placeholders; the role accepts only 64 lowercase hexadecimal characters.

The Coffer wrapper must run after the ordinary Kolla Horizon/Skyline deploy.
Enable, reconfigure, upgrade, pull, and fallback use the pinned Kolla service
definitions and filter them to exactly one dashboard container.

## Evidence and boundary

The isolated companion-role harness passes 108 checks. It proves:

- default `enable_coffer=false` leaves existing dashboards untouched;
- missing, mutable, mismatched, or unowned image inputs fail closed;
- deploy swaps only the two selected UI containers;
- repeated enabled and disabled reconfigure runs are idempotent;
- disable restores both exact fallback digests;
- final Coffer stop leaves stock dashboards running and no recovery marker;
- generated secret values never enter Ansible output or event state.

Five focused image-contract tests also pass, including real wheel metadata,
atomic/idempotent contract output, and exact Horizon runtime registration
files. Contracts generated from the current Horizon and Skyline wheels pass.

This is local Ansible, package, and fixture evidence. No custom image has yet
been built, scanned, signed, pushed, pulled from a real registry, or deployed
to a Kolla cloud. Live catalog, Keystone session, browser, rolling replica, and
rollback evidence remains gated by plan 0019.
