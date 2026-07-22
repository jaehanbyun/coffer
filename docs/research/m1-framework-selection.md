# M1 Python Framework and Process-Model Selection

- Date: 2026-07-21
- Scope: Coffer control API and future registry token realm
- Outcome: Falcon WSGI with Gunicorn native-thread workers selected
- Decision: accepted ADR 0007

## Executive Result

Coffer will use Falcon 4.3.1 in WSGI mode and expose a server-neutral WSGI application. The reference process model is Gunicorn 26.0.0 with pre-fork `gthread` workers, no application preload, and bounded native threads. Coffer will not use Eventlet, `oslo_service.wsgi.Server`, or an ASGI bridge in the initial control plane.

This is the smallest stack that preserves the native `keystonemiddleware.auth_token` boundary and the synchronous OpenStack libraries selected for the PoC. A local compatibility spike passed on Python 3.11.14, 3.12.2, and 3.13.14 before the repository API seam was created.

## Supported Runtime and Pinned Inputs

The [OpenStack 2026.2 tested runtime](https://governance.openstack.org/tc/reference/runtimes/2026.2.html) requires Python 3.11 or newer, uses Python 3.12 as the Ubuntu 24.04 default, and requires projects to test through Python 3.13. Coffer therefore declares `requires-python >=3.11` and tests 3.11, 3.12, and 3.13.

The spike used the versions in the OpenStack requirements repository at commit `1244391f2eb1a5b626c84ea9623d631ce5820ff7`:

| Component | Pin | Role |
|---|---:|---|
| Falcon | 4.3.1 | WSGI routing and JSON API |
| Gunicorn | 26.0.0 | Reference external WSGI process manager |
| keystonemiddleware | 13.0.0 | Keystone token validation and identity normalization |
| keystoneauth1 | 5.15.0 | Synchronous Keystone client/session contract |
| oslo.config | 10.5.0 | Service configuration |
| oslo.context | 6.5.0 | Request/database transaction context |
| oslo.log | 8.3.0 | OpenStack-compatible logging |
| oslo.policy | 6.0.0 | Project-role policy enforcement |
| oslo.db | 18.1.0 | Database engine and transaction facade |
| SQLAlchemy | 2.0.51 | Repository persistence model |
| WebOb | 1.8.10 | WSGI request/response dependency of Keystone middleware |

The [global requirements](https://opendev.org/openstack/requirements/src/commit/1244391f2eb1a5b626c84ea9623d631ce5820ff7/global-requirements.txt) and [upper constraints](https://opendev.org/openstack/requirements/src/commit/1244391f2eb1a5b626c84ea9623d631ce5820ff7/upper-constraints.txt) establish a current OpenStack-compatible set, not permanent Coffer upper bounds. `uv.lock` preserves the PoC result; each dependency update still requires the focused matrix.

## Candidate Comparison

| Candidate | Keystone fit | Unneeded surface | Process implication | Result |
|---|---|---|---|---|
| Falcon 4.3.1 WSGI | Direct WSGI composition with `auth_token`; request environment remains accessible | Small API-first core with no runtime dependencies of its own | Portable across Gunicorn, uWSGI, and mod_wsgi | Selected |
| Flask 3.1.3 | Direct WSGI composition | Templates, sessions, static files, CLI, signals, and app-context machinery are not needed | Same external WSGI requirement | Valid fallback, not selected |
| Pecan 1.8.0 | Direct WSGI/WebOb composition and historic OpenStack familiarity | Controller dispatch, templates, scaffolding, commands, and context-local model add no greenfield value | Same external WSGI requirement | Viable, not selected |
| Falcon ASGI plus Hypercorn | Requires preserving or bridging the WSGI Keystone boundary | Adds HTTP/2, WebSocket, event-loop, and protocol dependencies | Blocking Keystone and database work still runs in threads | Deferred |

Falcon explicitly separates [`falcon.App` for WSGI and `falcon.asgi.App` for ASGI](https://falcon.readthedocs.io/en/4.3.1/api/app.html). The current [Keystone middleware architecture](https://docs.openstack.org/keystonemiddleware/latest/middlewarearchitecture.html) is WSGI. An ASGI-first service would therefore add an adapter at the authentication boundary without converting `keystoneauth1`, Requests, or normal `oslo.db` work to native async I/O.

## Compatibility Spike

The ignored spike under `work/m1-framework-spike/` wrapped a Falcon WSGI route with `keystonemiddleware.auth_token.AuthProtocol`, using the upstream `AuthTokenFixture`. Six checks passed on each supported Python version:

1. A project-scoped token reached Falcon with confirmed project UUID, user ID, roles, and `keystone.token_info`.
2. Two identically named projects in different domains remained distinct by immutable project UUID.
3. An invalid token was rejected with 401 by the middleware.
4. A valid unscoped token was rejected with 403 by the application.
5. Client-supplied `X-Project-Id` and `X-Roles` values were replaced by validated middleware identity.
6. `oslo.config`, `oslo.log`, `oslo.policy`, and an `oslo.db` SQLite transaction ran together in the same synchronous process.

| Python | Result |
|---:|---|
| 3.11.14 | 6 passed; WebOb emitted the expected Python 3.11 `cgi` deprecation warning |
| 3.12.2 | 6 passed; WebOb emitted the expected Python 3.12 `cgi` deprecation warning |
| 3.13.14 | 6 passed; the constrained `legacy-cgi` dependency satisfied WebOb |

Falcon's test client initially failed while introspecting the WebOb `wsgify` descriptor on `AuthProtocol` to distinguish WSGI from ASGI. A two-argument `(environ, start_response)` test adapter made the existing WSGI contract explicit. This is a test-client introspection limitation; the middleware itself is a standard WSGI callable.

The durable repository seam then added create/get/list behavior using the same middleware, project UUID ownership, `oslo.policy`, and `oslo.db`. Its focused API suite verifies reader/member policy, per-project duplicate names, neutral cross-project lookup, invalid/unscoped tokens, and spoofed identity headers.

## Process Model

OpenStack is actively removing Eventlet. The [TC removal goal](https://governance.openstack.org/tc/goals/selected/remove-eventlet.html) targets deprecation in 2027.1 and removal in 2027.2. The [`oslo.service` 2026.1 release notes](https://docs.openstack.org/releasenotes/oslo.service/2026.1.html) state that its embedded Eventlet WSGI server does not work with the threading backend and direct services to standard WSGI servers such as uWSGI or Gunicorn.

Coffer's reference shape is:

```text
edge TLS/load balancer -> Gunicorn pre-fork workers -> bounded native threads
                                             |-> keystonemiddleware / Keystone
                                             |-> oslo.policy
                                             `-> oslo.db / SQL database
```

Initial deployment guidance is two workers and two to four threads per worker, `worker_class = gthread`, and `preload_app = false`. These are safe starting values, not performance claims. Final concurrency must be bounded by Keystone, HTTP, memcache, and database pool capacity and measured under the PoC workload.

Gunicorn is the reference rather than the application contract. Operators may use uWSGI or mod_wsgi if they preserve native threads, lazy per-worker initialization, graceful draining, and the same WSGI middleware order. The [Nova WSGI deployment model](https://docs.openstack.org/nova/latest/admin/wsgi.html) likewise exports WSGI applications for standard servers.

## Security and Operational Boundaries

- Keep `delay_auth_decision = false` for the control API. The application still explicitly requires project scope because token validity alone does not imply a project-scoped tenant operation.
- Do not place the future Basic-auth application-credential token realm behind the control API's rejecting `auth_token` pipeline. M2 must use a separate route pipeline or application entry point.
- Configure finite Keystone HTTP timeouts. Blocking forever can consume every `gthread` slot.
- Use a fresh `oslo.context` and database transaction/session per request; never share SQLAlchemy sessions between threads.
- Retain `preload_app = false` so live database engines, Keystone sessions, and key state are created after fork.
- Replace the middleware's test-only in-process token cache with configured memcache before multi-worker or multi-replica acceptance.
- Trust proxy forwarding headers only when the edge proxy strips or overwrites client-supplied values.
- An in-memory SQLite database is only a unit-test/smoke default. Multi-process and real M1 acceptance require one shared supported SQL database.
- The fixture initially proved only the middleware contract. The Mac/DevStack lab now proves real Keystone project/domain/system token behavior, incoming service-token enforcement, a two-second in-process revoke-cache bound, outage 503, application-credential lifecycle, and cross-domain duplicate-name isolation. Shared memcache/SQL and multi-worker consistency remain real deployment gates.

## Rejected Alternatives

- **`oslo_service.wsgi.Server` or Eventlet workers:** deprecated path that conflicts with OpenStack's threading migration.
- **Gevent workers:** reintroduce monkey-patching and blocking-driver compatibility risk without a demonstrated requirement.
- **ASGI bridge:** preserves the blocking WSGI/Keystone/database core inside thread pools and adds an authentication adapter.
- **Embedded Falcon, Flask, or Waitress development server:** lacks the required multiprocess supervision and production lifecycle controls.
- **uWSGI as the only baseline:** supported by existing OpenStack deployment patterns, but its upstream repository describes maintenance mode; keep it as an operator-compatible alternative instead.

## Next Gate

Framework selection is closed by accepted ADR 0007, and the Mac/DevStack lab has now passed the durable repository API and separate token-realm boundaries against real Keystone. The remaining process-model gate is shared SQL/memcache and multi-worker consistency in the later deployment environment.
