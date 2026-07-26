# Skyline Console integration baseline

## Scope

This document fixes the supported source and runtime seams for the first
Coffer Skyline Console surface. It covers repository list, create, detail, and
current-project quota only. It does not claim a deployed Console, service
catalog, Keystone session, or browser result.

## Pinned 2026.1 sources

| Component | Branch | Revision | Relevant packaging |
|---|---|---|---|
| Skyline Console | `stable/2026.1` | `c9000cb1be332a213009793598f17a80ce59671e` | Branch tarball installed as the `skyline-console` Python package |
| Skyline API Server | `stable/2026.1` | `1902699cbf1b01f4d8d4c65a43a21b06a3a5e077` | Supplies login/profile/policy and Nginx generation |
| Kolla | `stable/2026.1` | `686c6d13dc1c31092b22c6c481e16a7329e935ea` | Builds `skyline-console` from the OpenStack branch tarball |
| Kolla-Ansible | `stable/2026.1` | `cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc` | Renders Skyline service mapping and runtime configuration |

The Console revision describes itself as `8.0.0-14-gc9000cb1`. Its upstream
Zuul lint and unit jobs use Node.js 16. The source package declares Node.js
`>=10.22.0` and Yarn `>=1.22.4`; the local exact verification baseline is
Node.js 16.16.0 and Yarn 1.22.22. The input lock digests are:

- `package.json`:
  `5c87dbbfd205422952a98a9978520f28697db160911ad0eb06e7f688315ed100`
- `yarn.lock`:
  `735ee34180d46f06bf73ac94fe6be2df3ef12ad31db2af62a98946a2429869eb`

These pins make the overlay reviewable. A different Console revision must
fail verification until its integration seams and generated patch are
requalified.

## Extension and packaging decision

Skyline Console has no supported external dashboard/plugin loader analogous to
Horizon's enabled-file mechanism. First-party services are registered in the
source tree:

- `src/client/client/constants.js`
- `src/client/<service>/index.js`
- `src/client/index.js`
- `src/stores/<service>/`
- `src/pages/<service>/App.jsx`
- `src/pages/<service>/routes/`
- `src/pages/basic/routes/index.js`
- `src/layouts/menu.jsx`
- `src/locales/*.json`

The accepted integration form is therefore a source overlay pinned to the
exact Console revision. Coffer owns the added source files and a small exact
revision patch for central registries, menu, and locale files. Verification
applies the overlay to a clean disposable checkout, runs the upstream
localization generator, focused tests, lint, and production build, and checks
that the installed Python package contains the resulting static bundle.

This is preferable to:

- pretending Skyline can load an independent runtime plugin;
- embedding a second React application under an unrelated path;
- maintaining an unconstrained full Skyline fork;
- patching built/minified assets after the supported source build.

Kolla must build the resulting source revision or source archive into a custom
`skyline-console` image. The stock Kolla image consumes the upstream branch
tarball directly, so merely mounting JavaScript into a running container is
not a supported or immutable deployment contract.

## Service discovery and version routing

The control service remains registered in Keystone as:

```text
service type: oci-registry
catalog endpoint: https://<coffer-api>/v1
```

Skyline API Server does not return raw catalog URLs to the browser.
`get_endpoints()` maps catalog service types through
`openstack.service_mapping` and returns same-origin paths:

```text
oci-registry: coffer
    ↓
profile.endpoints.coffer = /api/openstack/<region>/coffer
```

The generated Nginx configuration creates that location from the real catalog
endpoint. Its endpoint parser removes a terminal `v1` path before producing
`proxy_pass`, matching its behavior for Barbican and other versioned
services. The Console must therefore add:

```javascript
endpointVersionMap.coffer = 'v1';
cofferBase = () => getOpenstackEndpoint('coffer');
```

The resulting browser request is same-origin:

```text
/api/openstack/<region>/coffer/v1/repositories
```

No Coffer URL is compiled into the Console. Absence of
`profile.endpoints.coffer` hides the Registry menu and leaves the route
unreachable through normal navigation.

## Authentication and request boundary

Skyline's supported browser request layer is
`src/client/client/request.js`. Its Axios interceptor:

- reads the current `keystone_token` maintained by the Skyline login/profile
  flow;
- sends it as `X-Auth-Token` only while the Skyline expiry cookie is valid;
- adds a bounded `X-Openstack-Request-Id`;
- redirects an HTTP 401 response to the login flow.

The Coffer client must subclass the existing `BaseClient` and use this request
layer. Coffer source must not read local storage or cookies itself, add another
token store, put a token in a URL/body, persist credentials, or call a
deployment-specific host.

The upstream interceptor currently logs raw Axios failures. The Coffer
integration must not add further raw response logging or surface remote
payloads in notifications. Its store/action errors use fixed operation names;
the product API already owns the bounded 401/403/404/409/503 representations.
Removing the shared upstream log is outside this overlay's scope unless the
Skyline project accepts a general hardening change.

## Client and store contract

The source overlay adds a `CofferClient` with:

- base URL `cofferBase()`;
- repository collection, show, and create operations;
- a custom `quota()` read;
- no delete, update, data-plane, signer, maintenance, SQL, RGW, or secret
  operation.

The repository store preserves the public API envelopes:

```json
{
  "repositories": [],
  "next_marker": null
}
```

Forward paging is marker-based. The store binds the next request to the
server-provided `next_marker`; it never derives a cross-project marker from
untrusted URL state. The current project comes from the scoped token and is
not sent as an override.

Create sends exactly:

```json
{
  "name": "team/application",
  "immutable_tags": false
}
```

The action validates the same 255-character repository-name grammar as the
OpenAPI contract before sending. Detail accepts only the route UUID and
renders the bounded repository representation. Quota renders the current
project response without supporting mutations.

## Route, menu, and UI surface

The Project Console receives one top-level Registry menu, gated by the
`coffer` endpoint:

```text
Registry
└── Repositories
    └── Repository Detail
```

The list combines:

- the current quota usage/limit card;
- repository name linked to detail;
- immutable-tags state;
- size in bytes;
- created and updated timestamps;
- a Create Repository modal;
- forward pagination only.

The detail view shows ID, name, immutable-tags state, size, project ID, and
timestamps. No destructive action is present.

Console-side policy visibility is advisory. Skyline API Server's supported
policy manager has a fixed set of known OpenStack services and has no Coffer
policy manager. The first overlay therefore gates navigation on the scoped
catalog endpoint and relies on Coffer's authenticated `oslo.policy`
enforcement for reader/member/admin behavior. It must not misrepresent a
missing Skyline policy result as an authorization grant. Adding Coffer as a
first-class Skyline API Server policy provider is a future upstreamable
enhancement, not a prerequisite for API-enforced isolation.

All translation keys are generated through the upstream `yarn i18n` task for
English, Simplified Chinese, Korean, Turkish, and Russian. English keys are
the source text; non-English values may be filled independently without
blocking the deterministic source contract.

## Verification contract

The Coffer-owned verifier must fail closed unless:

1. the Console checkout is clean at the exact pinned revision;
2. `package.json` and `yarn.lock` match their pinned digests;
3. the central patch applies without offsets or fuzz;
4. every Coffer-owned added file is present after overlay application;
5. no hard-coded HTTP endpoint, credential, token storage, delete operation,
   or direct private backend appears in the Coffer source;
6. focused client/store/action tests pass;
7. upstream source lint passes without rewriting tracked files;
8. the localization generator is deterministic;
9. the production webpack build succeeds;
10. the Python package build includes the generated static assets.

Fixture data can prove local routing, rendering, validation, and failure
handling. It cannot prove Keystone catalog discovery, token forwarding,
Nginx proxying, Coffer API reachability, or browser behavior in a deployed
cloud. Those remain live Kolla acceptance evidence behind the Stage 6 release
gate.

## Kolla integration implications

The disabled-by-default companion role will eventually need:

- `enable_coffer_skyline: false` by default;
- `openstack.service_mapping` entry `oci-registry: coffer` when enabled;
- a custom immutable Skyline Console image containing the verified overlay;
- image digest input rather than mutable tag-only selection;
- Skyline API Server/Nginx regeneration and restart through the existing
  service lifecycle;
- reconfigure, disable, rollback, and residue checks;
- no Coffer token, credential, CA private key, SQL URL, RGW credential, or
  signer material in the browser image.

The Skyline Console image remains separate from the tenant OCI registry it
helps operate. Kolla must not depend on Coffer to pull the image required to
start Coffer or Skyline.
