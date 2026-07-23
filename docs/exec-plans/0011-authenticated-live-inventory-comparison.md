---
title: "Authenticated live inventory comparison contract"
status: complete
updated: 2026-07-23
owner: primary-agent
depends_on: docs/exec-plans/0010-post-import-ledger-comparison.md
---

# Objective

Define and prove a bounded, read-only comparison between one exact imported
`coffer.inventory/v1` baseline and authenticated live Distribution manifest
presence. The vertical slice must first prove the complete SQL ledger through
plan 0010, resolve exact repository ID/project/name authority without extending
the artifact, close the database snapshot, and then require an injected
authenticated probe for every digest. It must not choose or provision a
production cross-project service identity, accept credentials on a command line,
mutate SQL or registry state, enable admission, or declare cutover readiness.

## Done Criteria

- [x] The comparison reuses the canonical artifact/hash parser and plan 0010's
  exact ledger check, and resolves canonical repository names from the same
  read-only SQL snapshot without adding mutable names to the signed inventory.
- [x] Every inventory manifest receives an authenticated digest HEAD; only one
  exact matching `Docker-Content-Digest` on 200 counts as present. Exact 404 is
  absent, while 401/403/other status, malformed or duplicate digest headers,
  timeout, TLS, and transport failures are indeterminate.
- [x] Missing authentication fails before network access. The comparison issues
  no SQL/HTTP mutation and emits only fixed aggregate counts and one fixed
  refusal class without project, repository, manifest/descriptor digest, origin,
  token, credential, header, URL, or SQL detail.
- [x] Focused concurrent-change and authenticated HTTP fixture tests prove the
  bounded snapshot/network boundary and secret-safe behavior. A disposable
  unmodified Distribution proof is added only if it can remain isolated and use
  synthetic credentials without changing the accepted production identity
  model.
- [x] An ADR candidate and operator documentation record that exact live presence
  is evidence only. Writer exclusion, backup/restore, production credential
  delivery, authorization, representative scale, rollback, and admission
  cutover remain separate gates.

## Non-goals

- Creating a Keystone user, application credential, service role, registry JWT,
  secret file, private CA, or privileged cross-project production identity.
- Connecting to production SQL, Distribution, RGW, Keystone, or Barbican, or
  using any retained lab credential or tenant data.
- Holding a database transaction open during network I/O, locking registry
  writers, repairing mismatches, changing quota rows, enabling admission,
  deleting content, or running GC.
- Proving blob/reference completeness beyond the signed inventory's manifest
  roots, all-replica consistency, load-balancer behavior, or a continuous
  writer-exclusion interval.
- Selecting Kolla/Helm/systemd packaging, Galera policy, HA topology, or
  production audit/retention policy.

## Context and Evidence

- Plan 0010 proves exact marker/authority/ledger equality in one read-only
  SQLite/PostgreSQL/MariaDB snapshot, but deliberately does not contact live
  Distribution.
- `coffer.inventory/v1` omits repository names so mutable routing data does not
  enter the durable content artifact. The control schema retains the exact
  repository UUID, project UUID, and canonical suffix needed for a live path.
- `HTTPDistributionManifestProbe` already implements canonical digest HEAD,
  exact 200-header/404/indeterminate semantics, TLS support, bounded timeout, and
  optional header injection. `build_reconciler()` currently supplies no
  credential, and the operator runbook records production authenticated probe
  delivery as unresolved.
- A verified inventory may span Keystone projects. One ordinary application
  credential is project-bound, so silently granting it cross-project registry
  pull would introduce a new privileged service boundary outside accepted ADRs.
- SQL equality and live HTTP presence occur at different instants. Even when
  both pass, only independent writer exclusion across the full interval can make
  them a coherent cutover observation.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Verify SQL and resolve repository routes in one read-only snapshot, then close SQL before HTTP | Keeps authority consistent with the ledger without holding database resources across slow network I/O | Put names in inventory; resolve each name in separate transactions; hold SQL open through probes | 2026-07-23 |
| Require an injected authenticated probe and fail before network when it is absent | Proves the comparison core without inventing a production credential model or permitting anonymous fallback | Anonymous HEAD; CLI token argument; embedded static service secret | 2026-07-23 |
| Reuse exact reconciliation HEAD semantics | Existing behavior is bounded, tested, and conservative for 200/404/indeterminate outcomes | GET bodies; tag lookup; trust status 200 without exact digest header | 2026-07-23 |
| Keep the result `verified`, never `ready` or `cutover-approved` | Two bounded observations cannot prove writer exclusion, all replicas, rollback, or authorization | Emit a cutover token; enable admission automatically | 2026-07-23 |

## Tasks

- [x] Extract a reusable same-snapshot ledger comparison and exact repository-route result without changing import or schema state.
- [x] Implement the injected-auth live comparison core with focused secret-safe and no-mutation tests.
- [x] Prove authenticated HTTP behavior in an isolated fixture and decide whether a pinned Distribution rerun adds evidence beyond the existing probe contract.
- [x] Record the production identity alternatives as an ADR candidate, update operator documentation, run the complete matrix, inspect the diff, and prepare atomic publication.

## Progress Log

### 2026-07-23 — Work package activated

- Completed: Published plan 0010 at `d0580cc`, mapped the live-presence gap, and
  bounded this package to an injected authenticated read-only comparison core.
- Evidence: The existing probe accepts protected headers but the runner builds it
  without credentials; the inventory omits repository names; control SQL owns
  exact names; a multi-project inventory cannot use one ordinary project-bound
  application credential as an implicit global reader.
- Changed files: Added this plan and activated it in README and `HANDOFF.md`.
- Next exact action: Add a focused test that obtains exact repository routes and
  ledger equality from one SQL snapshot, beginning in
  `tests/test_live_inventory_verification.py`.

### 2026-07-23 — Same-snapshot routes and authenticated core complete

- Completed: Extended the plan 0010 read-only snapshot result with canonical
  repository routes, added an injected authenticated live comparison core, and
  reused the exact Distribution reconciliation HEAD semantics without claims or
  ledger mutation.
- Evidence: 48 focused import/SQL/live tests pass. New coverage proves zero DML,
  a concurrent rename remains outside the route snapshot, noncanonical names
  fail closed, authentication prepares before any probe, every manifest is
  visited, exact present aggregation, malformed provider results fail closed,
  fixed absence/indeterminate/exception refusal, aggregate-only output,
  Bearer-protected HTTP success, and wrong-token 401 refusal without token or
  content identifiers.
- Decision: A fresh unmodified Distribution fixture is deferred because no
  production provider is accepted; it would add only another static synthetic
  token. Existing M2 already proves Coffer JWT validation by unmodified
  Distribution, and the reconciliation fixture proves exact digest HEAD.
- Changed files: `src/coffer/quota_import_verification.py`,
  `src/coffer/live_inventory_verification.py`,
  `tests/test_live_inventory_verification.py`, and this plan.
- Next exact action: Record the provider boundary and alternatives in proposed
  ADR 0013, then update architecture and operator documents.

### 2026-07-23 — Production identity boundary documented

- Completed: Added proposed ADR 0013 and updated README, architecture, and both
  inventory/quota operator boundaries. The ADR requires authenticated probe
  preparation and anonymous fail-closed behavior but deliberately does not
  select or provision a production provider.
- Evidence: Current official Keystone documentation confirms application
  credentials delegate roles on their creation project. Current Distribution
  token/scope documentation confirms subject/audience-bound repository actions
  and requested-versus-authorized intersection.
- Changed files: `docs/adrs/0013-require-explicit-authentication-for-live-comparison.md`,
  README, architecture, both runbooks, this plan, and `HANDOFF.md`.
- Next exact action: Run the shared-SQL harness to prove route resolution on
  PostgreSQL/MariaDB, then run the complete regression matrix.

### 2026-07-23 — Work package complete and ready for atomic publication

- Completed: Proved the extended exact snapshot query on both supported shared
  SQL engines and completed the cross-version, language, fixture, documentation,
  and secret-safety regression matrix. No production provider, identity,
  credential, live endpoint, admission rule, or mutable operator path was added.
- Evidence: PostgreSQL 17.10 and MariaDB 11.4.12 each passed exact inventory
  import verification and all prior migration/concurrency checks, then cleanup
  reported zero containers, volumes, networks, and generated credentials. Python
  3.11.14, 3.12.2, and 3.13.14 each pass 199 tests; 3.11/3.12 emit only WebOb's
  known `cgi` deprecation warning. Lock, compilation, Alembic head `0004`, four
  installed CLI helps, Go format/test/vet, 58 Bash/ShellCheck files, six Compose
  models, 54 Make dry-runs, 56 Markdown files, 32 local links, 99 external links,
  project-owned Gitleaks, private-key/JWT scans, and diff checks pass. Podman is
  stopped.
- Verification correction: The first Make dry-run command used zsh command
  substitution and treated newline-separated targets as one word; an explicit
  Bash rerun passed all 54 targets. A whole-directory Gitleaks attempt included
  ignored disposable environments and reported known non-project artifacts; the
  exact 216 tracked and publishable untracked files pass, and the staged diff is
  checked separately before commit.
- Next exact action: Stage only the plan 0011 file set, run cached-diff and staged
  Gitleaks checks, commit once as `feat: compare authenticated live inventory`,
  verify the GitHub account, and atomically push from remote head `d0580cc`.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Published plan 0010 recovery | clean local/remote `main` at `d0580cc`; inventory/ledger/probe call graph | passed |
| Same-snapshot route resolution | focused SQLite exact/authority/concurrent-change tests | passed |
| Authenticated HTTP comparison | existing exact probe matrix plus injected-auth protected HTTP fixture | passed |
| Shared SQL | PostgreSQL 17.10 and MariaDB 11.4.12 import/comparison harness | passed; zero residue and Podman stopped |
| Complete regression | Python 3.11–3.13, docs, language/static checks, diff, secret scans | passed: 199 tests per version and all structural/safety checks |

## Failures, Blockers, and Risks

- One normal Keystone application credential is project-bound and cannot be
  assumed to authorize every project in a baseline. Production promotion needs
  an accepted per-project exchange, narrowly privileged maintenance identity, or
  another operator-owned mechanism; this package does not choose one silently.
- Resolving names and closing SQL before HTTP avoids a long transaction but
  creates an unavoidable observation gap. Writer exclusion is therefore a
  required external gate, not a property of this comparator.
- Existing reconciliation is allowed to mutate ledger state after observations.
  The new comparator may reuse only its probe semantics, never its claim or
  reconciliation mutation path.

## Handoff

- Current state: Same-snapshot route resolution, the injected-auth comparison
  core, focused HTTP evidence, proposed ADR 0013, shared-SQL evidence, and the
  complete regression matrix are finished and ready for atomic publication.
- Exact next action: Stage the exact plan 0011 file set and run staged secret and
  cached-diff checks before the single commit.
- First command: `git status --short`.
- Questions requiring user input: none for injected synthetic/disposable auth;
  a production cross-project identity, credentials, live data, maintenance, and
  admission cutover require separate authorization and an accepted ADR.
