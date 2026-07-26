# Coffer UI API contract baseline

- Date: 2026-07-26
- Scope: public project control API consumed by Horizon and Skyline Console
- Outcome: implementation baseline accepted for plan 0020

## Why this boundary comes first

Horizon and Skyline must represent the same Coffer authority. Neither UI may
derive repository ownership from an OCI path, query Coffer SQL, call the
private Distribution backend, or invent a deployment URL. The durable
integration point is the `oci-registry` endpoint in the current
project-scoped Keystone catalog plus a documented HTTP contract.

The Kolla companion role already registers public, internal, and admin
`oci-registry` endpoints ending in `/v1`. UI clients therefore resolve the
catalog endpoint and call version-relative paths such as `/repositories`; they
must not append a second `/v1`.

## Implemented source inventory

| Surface | Current behavior | Gap for UI |
|---|---|---|
| `POST /v1/repositories` | Project-scoped member/admin creates one repository; name and `immutable_tags` are validated; duplicate project/name returns 409 | No request ID contract or OpenAPI description |
| `GET /v1/repositories` | Project-scoped reader/member/admin receives all repositories ordered by name | Unbounded response and no continuation contract |
| `GET /v1/repositories/{repository_id}` | Project-scoped reader/member/admin receives one repository; cross-project IDs are indistinguishable from absence | No OpenAPI description |
| Quota store | `QuotaStore.usage(project_id)` returns limit, used, and reserved bytes or raises `QuotaNotConfigured` | No public project read endpoint |
| Identity | Keystone middleware supplies confirmed user/project/roles; `Identity` rejects unscoped, domain-scoped, system-scoped, or mismatched context | UI error mapping is implicit |
| Policy | Separate documented rules exist for repository create/list/get and registry pull/push/delete | No `quota:get` rule |
| Observability | HTTP metrics use bounded route labels for the three repository routes | New quota route must be added to the bounded label set |
| Request correlation | OCI token, maintenance token, and quota-admission paths emit `X-Openstack-Request-Id` | Ordinary repository control responses do not |

Repository representation is already stable enough for both UIs:

```json
{
  "id": "UUID",
  "project_id": "Keystone project UUID",
  "name": "team/application",
  "immutable_tags": false,
  "created_at": "2026-07-26T00:00:00Z"
}
```

There is deliberately no repository update or deletion method. Logical
repository deletion would need content/reference, quota, retention, and GC
semantics that are outside plan 0020.

## Accepted versioned contract

The source-controlled contract will be OpenAPI 3.1 JSON at
`api-ref/openapi.json`. JSON avoids introducing a runtime YAML parser, and a
focused test can load it using the Python standard library. The API service
does not generate or mutate the contract at startup.

The catalog service type remains the proposed `oci-registry`. Its endpoint is
versioned and ends in `/v1`. The OpenAPI server URL therefore also ends in
`/v1`, while documented paths are version-relative:

| Operation ID | Catalog-relative request | Policy | Success |
|---|---|---|---|
| `listRepositories` | `GET /repositories?limit=&marker=` | `repository:list` | 200 |
| `createRepository` | `POST /repositories` | `repository:create` | 201 |
| `getRepository` | `GET /repositories/{repository_id}` | `repository:get` | 200 |
| `getProjectQuota` | `GET /quota` | `quota:get` | 200 |

All operations require a confirmed project-scoped Keystone token. Reader,
member, and admin may read repositories and quota. Member and admin may create
a repository. A resource ID in another project returns the same 404 as an
unknown ID.

### Bounded repository listing

- `limit` is optional, defaults to 100, and accepts integers from 1 through
  1,000.
- `marker` is optional and must be the UUID of a repository visible in the
  current project.
- Ordering is deterministic by `(name, id)`.
- The response retains the existing `repositories` array and adds
  `next_marker`. It is the final returned repository ID only when another row
  exists, otherwise it is JSON `null`.
- A malformed limit/marker or a marker outside the project returns 400. The
  server never reveals whether that marker exists in another project.
- Pagination is a live ordered view, not a snapshot transaction. A concurrent
  create whose name sorts before an already consumed marker may appear only
  after the caller refreshes from the first page.

Example:

```json
{
  "repositories": [],
  "next_marker": null
}
```

### Read-only project quota

`GET /quota` uses only the authenticated project ID and returns:

```json
{
  "quota": {
    "project_id": "Keystone project UUID",
    "limit_bytes": 10737418240,
    "used_bytes": 1048576,
    "reserved_bytes": 0
  }
}
```

The UI may derive available bytes and percentages, but those derived values
are not duplicated in the authority response. Missing project quota returns
404 with a fixed `Quota not configured` title. It does not create a default,
raise a limit, expose another project, or become an admin quota API.

### Errors and request correlation

The stable client decision boundary is HTTP status:

| Status | Meaning for the UI |
|---|---|
| 400 | Malformed repository document or pagination input |
| 401 | Missing, expired, or invalid Keystone authentication |
| 403 | Valid identity lacks project scope or required role |
| 404 | Repository is absent from the current project, or project quota is not configured |
| 409 | Repository name already exists in the current project |
| 503 | A required control dependency is unavailable |

Falcon resource errors retain the JSON `title` and optional `description`
shape. UI code must not branch on translated English descriptions. Every
request that reaches the Falcon control application receives one
`X-Openstack-Request-Id` response header. A syntactically valid incoming
`X-Openstack-Request-Id` may be preserved; otherwise Coffer generates
`req-<UUID>`. Keystone middleware may reject an invalid token before Falcon,
so its outer 401 response remains middleware-owned.

Unexpected database errors must not expose connection strings, SQL,
credentials, project names, or exception text. The final dependency-unavailable
mapping is added only if focused tests can preserve existing readiness and
startup behavior; otherwise it remains a deployment-error boundary and the
UI handles generic 5xx as unavailable.

## OpenAPI drift checks

`tests/test_openapi_contract.py` will fail unless:

1. every public `/v1` Falcon control route has the documented path/method;
2. every documented operation references the exact registered oslo.policy
   rule and role expectation;
3. repository and quota schemas require the implemented fields and types;
4. every operation declares Keystone bearer authentication, standard status
   classes, and `X-Openstack-Request-Id`;
5. no maintenance, metrics, health, OCI token, `/v2/`, SQL, RGW, or private
   backend route is accidentally included in the project control document;
6. examples contain no real identity, endpoint, credential, token, registry
   content, or secret.

The first drift test is structural and deterministic. Full OpenAPI semantic
validation may be added as a development dependency only if it is pinned and
does not enter the production API image.

## UI consumption rules

- Resolve `oci-registry` from the current project-scoped catalog.
- Prefer the public interface in user-facing deployments; allow the
  deployer's normal interface/region selection rather than embedding a URL.
- Join catalog-relative paths without discarding an existing `/v1` prefix.
- Forward the current scoped token only through Horizon's server-side service
  adapter or Skyline's established authenticated client boundary.
- Never place a token in a URL, local storage owned by the plugin, logs,
  rendered HTML, test snapshots, exception details, or evidence.
- Treat 401 as session/authentication handling, 403 as unavailable action, 404
  as current-project absence/configuration, 409 as a create conflict, and all
  5xx/network failures as dependency unavailable.

## Framework evidence

- Horizon's current official plugin tutorial recommends an independently
  packaged enabled file, panel, service adapter, views/templates, and tests:
  <https://docs.openstack.org/horizon/latest/contributor/tutorials/plugin.html>.
- Horizon dashboard construction and registration are documented at
  <https://docs.openstack.org/horizon/latest/contributor/tutorials/dashboard.html>.
- Skyline Console's official development guide describes resource clients,
  stores, page containers, routes, menus, and locales:
  <https://docs.openstack.org/skyline-console/latest/development/index.html>.
- Skyline's current source/package boundary still needs an exact revision pin
  before deciding whether Coffer ships a source overlay or maintained fork.

## Implementation order

1. Add bounded repository paging to `RepositoryStore` and the collection
   resource.
2. Add `QuotaResource`, `quota:get`, quota route metrics, and a shared request
   ID middleware.
3. Add `api-ref/openapi.json` and structural/runtime contract tests.
4. Run focused API, quota, observability, middleware, and full repository
   regressions.
5. Update plan 0020 and `HANDOFF.md`, then publish the API baseline as one
   atomic milestone.
