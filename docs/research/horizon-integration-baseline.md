# Horizon integration baseline

- Date: 2026-07-26
- Target: Horizon 26.0.0
- Horizon revision: `e48473ce019c69eea261f2116bbeb161a660d3b6`
- Reference plugin: Designate Dashboard 22.0.0
- Reference revision: `650c95862360194e969831dc46f4834150311151`
- Outcome: out-of-tree Django plugin baseline accepted

## Source evidence

The official Horizon 26.0.0 tag requires Python 3.11 or newer and Django 4.2
or newer. Its plugin loader still accepts independently packaged enabled
files that add a panel group, panel, installed Django application, templates,
and optional policy configuration.

The official plugin tutorial recommends the same out-of-tree packaging model:
<https://docs.openstack.org/horizon/latest/contributor/tutorials/plugin.html>.
The current Designate Dashboard 22.0.0 release proves that an OpenStack service
dashboard can ship its own `enabled/`, `local_settings.d/`, API adapter, panel,
static resources, and tests without patching Horizon core.

Horizon's current `openstack_dashboard.api.base.url_for()` resolves a service
type from the authenticated user's region-aware catalog and honors
`OPENSTACK_ENDPOINT_TYPE` plus the configured secondary interface. Horizon's
placement adapter demonstrates token-authenticated `keystoneauth1` sessions
with the dashboard CA/no-verify settings. These are the integration seams
Coffer needs.

## Accepted package boundary

Coffer will add an independently installable Python distribution under
`ui/horizon/`:

```text
ui/horizon/
├── pyproject.toml
├── README.md
└── cofferdashboard/
    ├── api/
    ├── dashboards/project/registry/repositories/
    ├── enabled/
    ├── local_settings.d/
    ├── templates/
    └── tests/
```

- Distribution name: `coffer-horizon`
- Python package: `cofferdashboard`
- Supported baseline: `horizon>=26.0.0,<27.0.0`
- Dashboard: existing `project` dashboard
- Panel group: `registry`
- Panel: `repositories`
- Catalog permission: `openstack.services.oci-registry`

The package remains versioned with Coffer for now. A separate OpenDev
repository is governance/publication work and is not needed to prove the
operator-local plugin.

## API adapter

The server-side adapter will:

1. call `base.url_for(request, "oci-registry")`;
2. preserve the versioned catalog endpoint exactly, trimming only a final
   slash before appending `repositories` or `quota`;
3. use the current `request.user.token.id` through
   `keystoneauth1.token_endpoint.Token` and `keystoneauth1.session.Session`;
4. honor `OPENSTACK_SSL_NO_VERIFY` and `OPENSTACK_SSL_CACERT`;
5. send one generated bounded `X-Openstack-Request-Id`;
6. use finite connect/read timeouts;
7. validate each JSON envelope and required public field before constructing
   a UI resource; and
8. return no raw response, token, endpoint, exception body, or connection
   detail to a template or log.

There is no browser-side CORS call and no plugin-owned token storage. The
browser talks to Horizon; Horizon talks to Coffer.

The catalog endpoint already ends in `/v1`. The adapter must produce
`<catalog>/repositories`, not `<catalog>/v1/repositories`.

## User surface

The first Horizon surface is deliberately traditional server-rendered Django:

- repository table with name, immutable-tags state, and creation time;
- forward bounded pagination using Coffer's `marker`;
- quota card showing limit, used, reserved, and locally derived available
  bytes/percentage;
- modal repository creation with the exact lowercase/path regex and
  255-character limit;
- repository detail page showing only the five public representation fields;
  and
- fixed localized handling for authentication, forbidden, missing,
  conflict, and dependency-unavailable results.

It adds no delete/edit/tag/manifest/scanning/signing/lifecycle action.

The table follows the server's name ordering. Horizon can render the next page
from the final row UUID. Because Coffer v1 does not expose reverse pagination,
the plugin does not claim an API-backed Previous operation; browser history or
a fresh first-page load resets the view.

## Policy and catalog behavior

The panel is absent when the scoped catalog has no `oci-registry` service in
the selected region. The plugin ships a Horizon policy namespace
`oci-registry` whose read and create defaults mirror Coffer's accepted
oslo.policy rules:

- `repository:list/get` and `quota:get`: reader, member, or admin;
- `repository:create`: member or admin.

This improves action visibility but never becomes authorization. The Coffer
API remains authoritative and every 401/403 is handled safely.

The local policy file must be drift-tested against `src/coffer/policy.py`.

## Failure behavior

| Coffer/transport result | Horizon behavior |
|---|---|
| 400 | Keep the form open with a fixed validation failure |
| 401 | Let Horizon's established authentication/session handling run |
| 403 | Show a fixed insufficient-permission message |
| 404 repository | Redirect to the list with a fixed absent message |
| 404 quota | Render repositories and show quota as not configured |
| 409 | Keep create modal open with a fixed duplicate-name message |
| 503/network/invalid JSON | Show a fixed temporarily unavailable message |

No user-facing message interpolates a raw remote exception. Server logs may
record only the generated request ID and bounded result class, never the token,
endpoint query, repository response body, or adapter configuration.

## Verification baseline

The plugin is accepted locally only when:

- Python source compiles and packaging includes enabled settings, policy,
  templates, and translations/static inputs;
- adapter tests prove exact catalog discovery, `/v1` joining, token session,
  TLS settings, timeout, request ID, schema validation, and no secret exposure;
- Django/Horizon tests prove service-catalog hiding, table/quota rendering,
  create/detail success, fixed 400/401/403/404/409/503 handling, and no
  unsupported action;
- the policy mirror matches Coffer's registered rules;
- tests run against the exact Horizon 26.0.0 source revision above; and
- rendered fixture HTML is inspected before the milestone closes.

These checks prove source compatibility and local behavior. They do not prove
that a Kolla Horizon container has installed the wheel, discovered a live
catalog endpoint, or completed a real browser request. That evidence remains
after the Stage 6 deployment gate.

## Rejected alternatives

- **Patch Horizon core:** unnecessary because the supported plugin loader
  provides the required package boundary.
- **AngularJS plugin:** adds browser REST/CORS and legacy frontend complexity
  to a four-operation surface.
- **Direct browser-to-Coffer calls:** exposes a new CORS/token handling
  boundary and duplicates Horizon endpoint/interface selection.
- **OpenStackSDK resource before the service exists upstream:** would require
  a second project/release dependency and does not improve this narrow
  operator-local baseline.
- **Hard-coded Coffer URL in local settings:** bypasses region/interface
  catalog semantics and drifts from every other OpenStack service panel.
