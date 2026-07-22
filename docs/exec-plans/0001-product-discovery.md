---
title: "OpenStack-native OCI Registry product discovery and MVP architecture baseline"
status: completed
updated: 2026-07-21
owner: primary-agent
---

# Objective

Define an evidence-backed product boundary and MVP architecture baseline for Coffer, an OpenStack-native private OCI registry. The result must distinguish what should be composed from mature upstream software from what Coffer must add, and end with a thin vertical proof-of-concept plan rather than a broad product implementation.

## Done Criteria

- [x] Map the relevant capabilities of AWS ECR, Azure Container Registry, and Google Artifact Registry to Coffer MVP, later phases, and explicit non-goals.
- [x] Verify existing OpenStack projects, historical or active proposals, OCI Distribution, Keystone, Glance, Swift, and Ceph RGW reuse constraints using primary sources.
- [x] Record proposed ADRs for build-vs-compose, service boundaries, authentication, project isolation, storage, HA, and the initial security posture.
- [x] Define one thin vertical PoC with observable acceptance criteria and concrete verification commands in a follow-up execution plan.
- [x] Update `HANDOFF.md` with decisions, evidence, risks, changed files, validation, and the exact next action.

## Non-goals

- Implementing a production registry, a new OCI blob/manifest data plane, or a complete OpenStack service in this work package.
- Matching every ECR, ACR, or Artifact Registry feature in the MVP.
- Seeking OpenStack governance approval, publishing a specification, or opening external issues without user approval.
- Finalizing the global product name or API stability contract.
- Solving image build, signing authority, runtime admission control, billing, or cross-region replication in the first PoC.

## Context and Evidence

- Repository rules: `AGENTS.md`
- Long-horizon harness: `prompts/long-horizon-harness.md`
- Initial architectural hypothesis: OCI Distribution-compatible data plane, Keystone project isolation, and OpenStack-friendly object storage.
- Research policy: prefer current primary documentation, specifications, governance records, and upstream repositories; label inference and uncertainty.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Run three read-only Ultra research tracks while the primary agent owns all repository writes | The investigation divides into independent evidence domains and the user explicitly requested Ultra parallel execution | Sequential broad research; parallel write-heavy agents | 2026-07-21 |
| Compose an unmodified CNCF Distribution v3 data plane with a separate Coffer token/control plane | It offers the narrowest standard integration surface and maps directly to external Bearer-token authorization | Build/fork Distribution; use Harbor as a component; use Quay as a component | 2026-07-21 |
| Authenticate finite Keystone application credentials at a stateless broker and issue approximately five-minute Distribution JWTs | Preserves standard clients and project/role authority while keeping Keystone credentials and calls out of the blob data path | Direct Keystone bearer; human passwords; htpasswd; non-expiring refresh tokens; an MVP Coffer credential store | 2026-07-21 |
| Use one private regional Ceph RGW bucket through Distribution's S3 driver | Shortest upstream-supported path in common OpenStack storage deployments | Custom Swift driver; per-project registry/bucket fleets; direct client RGW access | 2026-07-21 |
| Limit MVP to a private project-scoped single-region OCI service with bounded soft quotas | Focuses evidence on OpenStack-specific integration instead of hyperscaler feature parity | Universal artifact repository; public registry; bundled build system; global active-active | 2026-07-21 |
| Name the project `coffer`, the service `OCI Registry service`, and propose `oci-registry` as its service type | Separates a globally usable project identity from descriptive user documentation and machine-readable API semantics | Keep the initial Korean working name; use one name for project/service/type; use `artifact-registry` or `container-registry` | 2026-07-21 |

## Tasks

- [x] Research OpenStack project landscape, current discussions, and reuse boundaries.
- [x] Research OCI Distribution data-plane composition and upstream registry choices.
- [x] Research Keystone tenancy/authentication plus storage, HA, and security constraints.
- [x] Map hyperscaler registry capabilities and derive the MVP boundary.
- [x] Synthesize the product brief and architecture baseline.
- [x] Record ADR candidates and their rejected alternatives.
- [x] Define the thin vertical PoC execution plan; validate it against research findings before closing this work package.
- [x] Update the durable handoff and run documentation consistency checks.

## Progress Log

### 2026-07-21 — Work package started

- Completed: Restored repository context and fixed the work package scope, done criteria, non-goals, and research tracks.
- Evidence: `AGENTS.md`, `.codex/state/HANDOFF.md`, and the reusable harness were read before edits; Git has no commits and contains only the initial untracked harness files.
- Changed files: `docs/exec-plans/0001-product-discovery.md`
- Next exact action: Spawn the three read-only Ultra research tracks and begin official-source cloud-registry capability mapping.

### 2026-07-21 — Hyperscaler expectations mapped

- Completed: Compared current ECR, ACR, and Artifact Registry capabilities and separated Coffer MVP, deferred features, and explicit non-goals.
- Evidence: Official AWS, Microsoft, and Google product documentation linked from `docs/product-discovery.md`.
- Changed files: `docs/product-discovery.md`, `docs/exec-plans/0001-product-discovery.md`, `.codex/state/HANDOFF.md`
- Next exact action: Collect and reconcile the three Ultra research reports, beginning with the OpenStack landscape findings.

### 2026-07-21 — Architecture integration skeleton drafted

- Completed: Drafted the target component boundaries, token exchange/data flow, resource model, HA/security baseline, technology candidates, and PoC evidence risks without treating unresolved research as accepted decisions.
- Evidence: Product principles and standard OCI/Keystone composition hypothesis; external details remain subject to the active research tracks.
- Changed files: `docs/architecture/mvp-baseline.md`, `docs/exec-plans/0001-product-discovery.md`
- Next exact action: Reconcile the draft against the three Ultra reports and replace unsupported assumptions with cited decisions or explicit open questions.

### 2026-07-21 — Thin vertical PoC bounded

- Completed: Defined a real-Keystone, real-Ceph-RGW acceptance path with an unmodified OCI client, cross-project denial, offline JWT validation, persistence, audit, and secret-hygiene checks.
- Evidence: `docs/exec-plans/0002-thin-vertical-poc.md`; final technical assumptions remain subject to the upstream research reports.
- Changed files: `docs/exec-plans/0002-thin-vertical-poc.md`, `docs/exec-plans/0001-product-discovery.md`
- Next exact action: Reconcile all draft boundaries and PoC assumptions with the three Ultra reports.

### 2026-07-21 — OCI data-plane track reconciled

- Completed: Verified the upstream token flow, stop-the-world GC constraint, best-effort notification behavior, and S3 storage boundary; recorded the build-vs-compose ADR candidate.
- Evidence: `docs/adrs/0001-compose-cnc-distribution.md` and its primary upstream links.
- Changed files: ADR 0001, product discovery, architecture baseline, and this plan.
- Next exact action: Reconcile the OpenStack landscape report, then identity/storage/security findings.

### 2026-07-21 — OpenStack landscape reconciled

- Completed: Verified the absence of a current first-class registry service/type in the researched official catalogs, distinguished the active OpenStack-Helm registry chart from a cloud service, and bounded Glance, Zun, Magnum, Kolla, Ironic, Keystone, and Swift reuse.
- Evidence: `docs/research/openstack-registry-landscape.md` and its primary OpenStack links.
- Changed files: OpenStack landscape research, product discovery, architecture baseline, and this plan.
- Next exact action: Reconcile the identity/storage/security report and finalize the remaining ADR candidates.

### 2026-07-21 — Identity, storage, and security track reconciled

- Completed: Defined the Keystone application-credential-to-Distribution-JWT flow, standard project-role mapping, UUID namespace, RGW S3 topology, bounded soft quota, encryption/secret boundary, HA shape, threat mitigations, and expanded PoC gates.
- Evidence: `docs/adrs/0002-keystone-application-credential-token-broker.md`, `docs/adrs/0003-rgw-s3-single-region-storage.md`, and their official source links.
- Changed files: ADRs 0002/0003, architecture baseline, product boundary, PoC plan, this plan, and handoff.
- Next exact action: Run cross-document, source-link, Markdown/Mermaid, secret-pattern, and Git consistency checks; resolve every actionable mismatch.

### 2026-07-21 — Work package completed

- Completed: Closed all discovery criteria, kept the four architecture decisions explicitly proposed pending maintainer review, and left the implementation PoC as the separate proposed plan `0002-thin-vertical-poc.md`.
- Evidence: All 43 external Markdown links returned HTTP 200; both Mermaid diagrams rendered with `mmdc` and were visually inspected; Markdown fences/local links and trailing whitespace passed; Gitleaks found no leaks; Codex TOML/JSON/Python hook checks and a representative pre-compaction hook run passed.
- Changed files: architecture status, this completed plan, and `.codex/state/HANDOFF.md`.
- Next exact action: Review and accept or amend ADR candidates 0001–0004, then start M0 of `docs/exec-plans/0002-thin-vertical-poc.md`.

### 2026-07-21 — Coffer naming accepted after completion

- Completed: Replaced the working name across durable project state and examples; standardized `coffer`, `OCI Registry service`, proposed `oci-registry`, CLI noun `registry`, and `COFFER_*`; recorded accepted ADR 0005; renamed the canonical local Git root to `/coffer` while retaining a temporary compatibility symlink for the active workspace.
- Evidence: OpenStack project/service naming and Keystone catalog guidance in ADR 0005; repository-wide residual-name scan; refreshed external-link, Mermaid, Markdown, Bash syntax, harness, hook, and Gitleaks checks.
- Changed files: `README.md`, `AGENTS.md`, durable handoff/workflow/prompt, discovery and architecture documents, research summary, plans, ADRs 0001–0004, and new ADR 0005.
- Next exact action: Review the still-proposed architecture ADRs 0001–0004, then start M0 of `docs/exec-plans/0002-thin-vertical-poc.md`.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Primary-source coverage | Extract Markdown URLs and run parallel redirected `curl` checks | passed: 43/43 returned HTTP 200 |
| Decision traceability | Cross-check product baseline, architecture, ADR candidates 0001–0004, and PoC plan | passed: decisions and deferred gates align |
| Scope control | Compare deliverables with done criteria and non-goals | passed: discovery completed; ADRs remain proposed; PoC implementation not started |
| Mermaid | Render both architecture blocks with `mmdc` using local Chrome and inspect the PNG output | passed: both rendered and were visually readable |
| Markdown | Check balanced fences, local link targets, and trailing whitespace across project Markdown | passed: 16 files checked |
| Harness | Parse TOML/JSON, compile the hook, run a representative `PreCompact` payload, and verify snapshot ignore | passed |
| Secret hygiene | `gitleaks dir . --redact --no-banner --exit-code 1` | passed: no leaks found |
| Repository consistency | Inspect source-of-truth terms and `git status --short` | passed with expected no-commit/untracked initial repository state |

## Failures, Blockers, and Risks

- The repository has no initial commit, so all pre-existing harness files appear untracked; preserve them and do not commit without authorization.
- The four ADRs are evidence-backed candidates, not accepted design records; maintainer review is the next decision gate.
- Final PoC acceptance requires a disposable real Keystone and Ceph RGW environment; local substitutes cannot close the integration criteria.

## Handoff

- Current state: Product discovery and the MVP architecture baseline are complete; four ADR candidates await maintainer review and no PoC implementation has started.
- Exact next action: Review and accept or amend ADR candidates 0001–0004, then begin M0 of `docs/exec-plans/0002-thin-vertical-poc.md`.
- First file or command: Read `docs/adrs/0001-compose-cnc-distribution.md`, then review ADRs 0002–0004 as one decision set.
- Questions requiring user input: accept or amend the four ADR candidates; identify a disposable Keystone/Ceph RGW environment before PoC M3.
