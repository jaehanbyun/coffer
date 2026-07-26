# UI rendered fixture evidence

Status: visually inspected local fixture evidence

Date: 2026-07-26

## Scope

The static fixture uses the accepted bounded surface for both UIs:

- current-project repository list;
- repository create action;
- immutable-tag state;
- used, reserved, and limit quota values;
- explicit fixture-only warning and behavioral boundary.

Both pages render the same three deterministic repositories and quota values.
No token, endpoint, credential, external asset, remote script, API call, or
live cloud is present.

## Browser checks

The in-app browser rendered the pages from a loopback-only Python static
server. Temporary viewport overrides were reset and the server was stopped
after inspection.

| Surface | Viewport | Document width | Table viewport / table | Result |
|---|---:|---:|---:|---|
| Horizon | 1440 × 900 | 1440 | 1150 / 1150 | no page or table overflow |
| Horizon | 375 × 812 | 375 | 345 / 726 | table-only horizontal scroll |
| Skyline | 1440 × 900 | 1440 | 1128 / 1128 | no page or table overflow |
| Skyline | 375 × 812 | 375 | 345 / 722 | table-only horizontal scroll |

For all four renders:

- the warning banner remains visible;
- `Repositories`, quota values, and three rows remain present;
- the create action remains usable in the visual hierarchy;
- narrow buttons fill the available content width;
- navigation collapses to Registry/Repositories without clipping the page;
- browser warning/error logs are empty.

## Screenshots

### Horizon desktop

![Horizon desktop fixture](../fixtures/ui/screenshots/horizon-desktop.jpg)

### Horizon narrow

![Horizon narrow fixture](../fixtures/ui/screenshots/horizon-narrow.jpg)

### Skyline desktop

![Skyline desktop fixture](../fixtures/ui/screenshots/skyline-desktop.jpg)

### Skyline narrow

![Skyline narrow fixture](../fixtures/ui/screenshots/skyline-narrow.jpg)

## Interpretation boundary

This evidence proves the intended information hierarchy and responsive
fixture layout only. The Horizon Django and Skyline React behavior is proved
by their pinned source tests and package builds. Neither form of local
evidence proves a Kolla image, scoped Keystone catalog, live API, tenant
isolation, TLS path, browser token flow, HA rollout, or production cloud.
