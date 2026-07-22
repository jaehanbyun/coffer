# ADR 0007: Use Falcon WSGI and Gunicorn Native Threads

- Status: accepted
- Date: 2026-07-21
- Decision owners: Coffer maintainers
- Related plan: `docs/exec-plans/0002-thin-vertical-poc.md`
- Evidence: `docs/research/m1-framework-selection.md`

## Context

Coffer needs a small JSON control API and registry token realm while retaining `keystonemiddleware`, `keystoneauth1`, and the selected Oslo libraries. Keystone token middleware is WSGI, and the current HTTP and database paths are synchronous. Selecting an ASGI-first framework would therefore introduce an adapter at a security boundary without removing blocking work.

OpenStack is also removing Eventlet. A new service should not adopt `oslo_service.wsgi.Server`, Eventlet/Gevent workers, or monkey-patching as a default process model.

## Decision

Use Falcon in WSGI mode for Coffer HTTP APIs. Export a server-neutral WSGI application and use Gunicorn with bounded native `gthread` workers as the reference process manager.

The initial operational baseline is:

- Python 3.11 through 3.13;
- Gunicorn with multiple worker processes and two to four native threads per worker as a starting point;
- `preload_app = false` so live clients, database engines, and key state are created after fork;
- an external TLS/load-balancing proxy and a private application listener;
- explicit Keystone, database, and request timeouts;
- no `oslo.service` dependency in the web process.

Keep the WSGI entry point portable. uWSGI or mod_wsgi may be supported where operators already standardize on them, provided they preserve the same middleware order, native-thread model, post-fork initialization, and graceful shutdown behavior.

Compose the Keystone-token control API and the future Basic-auth registry token realm separately. The control API uses rejecting `keystonemiddleware.auth_token`; that middleware must not preempt the application-credential exchange endpoint.

## Rationale

- Falcon is the smallest current OpenStack-constrained API framework in the evaluated set and directly exposes the WSGI environment populated by Keystone middleware.
- The constrained stack passed the identity and Oslo compatibility spike on Python 3.11, 3.12, and 3.13.
- Gunicorn provides pre-fork fault isolation, bounded native threads for blocking Keystone/database calls, and graceful process supervision without monkey-patching.
- A standard WSGI application retains operator choice and matches current OpenStack migration guidance.

## Rejected Alternatives

- **Flask:** technically compatible, but its template, session, static-file, CLI, signal, and application-context surface is unnecessary for this API.
- **Pecan:** technically compatible and familiar in OpenStack, but its controller/scaffolding/template model has no greenfield advantage over Falcon.
- **ASGI-first Falcon, FastAPI, or Starlette:** would bridge the WSGI authentication layer and synchronous dependencies through thread pools without a demonstrated async workload.
- **`oslo_service.wsgi.Server` or Eventlet:** follows a deprecated path targeted for removal from OpenStack.
- **Gevent workers:** add monkey-patching and database/client compatibility risk.
- **uWSGI-only baseline:** remains an operator option, but binding a new service exclusively to a maintenance-mode server is unnecessary.

## Consequences

- Coffer must maintain the WSGI middleware ordering as a security invariant.
- Thread counts and database/HTTP pools require coordinated bounds and load-test evidence.
- The service needs a shared SQL database and shared token cache before multi-worker acceptance; in-memory SQLite/cache defaults remain test-only.
- ASGI may be reconsidered only if a concrete workload requires long-lived high-concurrency I/O and the Keystone/database path has native async equivalents.
- Changing framework or process model requires a superseding ADR and the same supported-Python, identity, policy, and database compatibility matrix.
