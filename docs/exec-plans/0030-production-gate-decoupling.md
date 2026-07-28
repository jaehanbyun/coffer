---
title: "Production gate decoupling and ledger v2"
status: active
updated: 2026-07-28
owner: primary-agent
---

# Objective

Replace the over-coupled Stage 6 promotion decision with an additive,
fail-closed ledger v2 that judges the Registry core, a selected storage
backend, the RGW and Barbican SSE-KMS capability, Horizon, Skyline, and
Referrers independently. Preserve the existing ledger v1 byte and CLI
contracts, admit only source-bound qualified dependency lineages, and produce
machine-readable evidence that can truthfully distinguish a core production
candidate from optional or deployment-specific profiles.

## Done Criteria

- [ ] The current coupling between security-critical core gates and optional
      storage, KMS, UI, and Referrers capability gates is recorded with exact
      code and evidence ownership.
- [ ] ADR 0018 is accepted and defines the fixed ledger v2 scopes, status
      semantics, core candidate rule, deployment-profile rule, and the
      relationship to ADRs 0001, 0003, and 0006.
- [ ] The accepted dependency policy admits only three exact lineage classes:
      signed official upstream release, approved vendor backport, and
      Coffer-maintained minimal patch release.
- [ ] Each admitted lineage is bound to immutable source and artifact
      provenance, reproducible build inputs, SBOM and vulnerability evidence,
      support dates, upstream submission, replacement, and retirement rules.
- [ ] Vendor and Coffer lineages receive the same runtime, protocol, security,
      architecture, and teardown qualification as upstream inputs plus their
      additional maintenance obligations. No waiver or caller-supplied pass
      status exists.
- [ ] `coffer.production-promotion-ledger/v2` independently reports Registry
      core, storage backend, RGW and Barbican KMS, Horizon, Skyline, and
      Referrers status and evidence.
- [ ] Top-level `production_candidate` is exactly the Registry core decision.
      An optional profile cannot make it true or false, and a deployable
      combination still requires the core plus its selected storage and
      integration profiles.
- [ ] Missing evidence is `pending`, explicit negative evidence is `blocked`,
      and `qualified` requires every fixed required gate in that scope to be
      passed by a source-bound verifier.
- [ ] Existing v1 release, ledger, and specialist evidence is remapped
      conservatively. Blocked and pending states never become passed; a v1
      passed result remains pending until its original specialist payload is
      revalidated for the v2 scope.
- [ ] Ledger v1 code, schema, CLI, Make targets, and output path remain
      compatible. Ledger v2 uses a distinct implementation and output.
- [ ] General v2-to-v1 projection is refused. Rollback is limited to replaying
      the exact original v1 bytes whose digest is bound by the migration
      record, with no vendor or Coffer patch lineage and no semantic drift.
- [ ] Synthetic lineage and scope fixtures cover every accepted and rejected
      policy branch but are explicitly ineligible as production evidence.
- [ ] Focused verifier, migration, compatibility, CLI, owner-only file,
      source-drift, downgrade, and rollback tests pass.
- [ ] The full promotion harness, complete Python regression, compilation,
      formatting, documentation, secret scan, and diff checks pass.
- [ ] The live current evidence produces a mode-0600 ledger v2 whose Registry
      core and every profile remain non-qualified unless actual evidence says
      otherwise.
- [ ] The plan, ADR, runbook, release boundary, and `HANDOFF.md` accurately
      record the final core candidate and per-profile state.
- [ ] Changes are preserved in reviewable atomic commits and pushed only
      through the verified `jaehanbyun` GitHub account.

## Non-goals

- Qualifying the currently vulnerable Distribution v3.1.1 release.
- Treating the Ceph Tentacle v20.2.2 zero-byte SSE-KMS failure as a generic
  storage-backend success.
- Treating local fixtures, retained preview VMs, UI builds, or prior Stage 5
  acceptance as production evidence.
- Creating a dependency patch, credential, key, certificate, image release,
  production deployment, or destructive remote fixture during this package.
- Selecting every future storage driver. Ledger v2 defines a typed backend
  profile and requires driver-specific qualification.
- Replacing the v1 specialist harnesses in place. Existing contracts remain
  available while v2-native scope evidence is introduced additively.

## Context and Evidence

- `poc/production-promotion/readiness.py` reduces Distribution, Ceph, and
  `oslo.messaging` to one minimum release status.
- `poc/production-promotion/artifacts.py` requires core, Horizon, and Skyline
  artifacts for both architectures before emitting one artifact result.
- `poc/production-promotion/ledger.py` then places RGW/KMS and every later
  specialist into one ten-gate serial transaction.
- The current owner-only ledger v1 reports zero passed, one blocked, nine
  pending, and `production_candidate=false`.
- The Distribution blocker is a Registry-core security and protocol input.
  The Ceph encrypted zero-byte move is specific to the RGW and Barbican
  SSE-KMS capability. The `oslo.messaging` CVE is a Horizon and Skyline parent
  dependency blocker. Native or fallback Referrers is an advertised
  capability and lifecycle decision, not an unconditional Registry-core
  requirement.
- ADR 0006 already allows a separately reviewed VEX and permits optional
  capabilities to remain disabled when Coffer neither advertises nor depends
  on them. Its upstream-only implementation and global Referrers/RGW coupling
  require a narrower superseding decision rather than a weaker security bar.
- The complete mapping and source references are recorded in
  `docs/research/production-ledger-v2-coupling.md`.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Keep ledger v1 immutable and add v2 in separate modules and files | Changing `ledger.py` changes its source hash and would invalidate retained v1 evidence; an additive path gives deterministic rollback | In-place schema switch; dual-write to one path | 2026-07-28 |
| Make Registry core the sole owner of top-level `production_candidate` | Optional UI, KMS, and Referrers availability must not redefine the security status of the core service | One global minimum; caller-selected aggregate | 2026-07-28 |
| Require selected storage and integration profiles separately for a deployable combination | A registry cannot operate without storage, but core software qualification and backend qualification have different evidence and lifecycle owners | Pretend core alone is deployable; force every backend and UI into core | 2026-07-28 |
| Migrate v1 evidence monotonically and negative-first | The current v1 result can prove a blocker or missing evidence, but its combined digests cannot prove independent v2 scopes | Infer profile passes from v1 gate names or plan history | 2026-07-28 |
| Permit official, vendor-backport, and Coffer-minimal-patch lineages only under one security threshold and increasing maintenance obligations | Waiting only for upstream can unnecessarily block unrelated capability profiles, while private untracked forks are unacceptable | Upstream-only forever; arbitrary fork; date-based waiver | 2026-07-28 |
| Keep native, fallback-tag, and disabled Referrers dispositions explicit | Each has different client concurrency, GC, deletion, signing, and advertisement consequences | Treat fallback as native; make Referrers an unconditional core gate | 2026-07-28 |

## Tasks

- [x] Recover the harness, handoff, active Stage 6 plan, ledger v1, relevant
      ADRs, specialist evidence, current Git state, and live retained outputs.
- [x] Run independent read-only policy, evidence-mapping, and compatibility
      reviews and reconcile their findings.
- [x] Fix the ledger v2 scope and migration baseline in this plan and the
      coupling research note.
- [ ] Implement the dependency-lineage policy and fixtures, then prove all
      official, vendor, Coffer-patch, VEX, support, upstream-submission, and
      retirement branches fail closed.
- [ ] Implement source-bound independent scope evidence for Registry core,
      storage backend, RGW and Barbican KMS, Horizon, Skyline, and Referrers.
- [ ] Implement ledger v2, final-result validation, CLI enforcement, and
      deterministic current-evidence output.
- [ ] Implement v1 import, compatibility validation, exact-byte replay, and
      lossy downgrade refusal.
- [ ] Integrate v2 Make targets, the production runbook, release boundary,
      ADR acceptance, and current evidence remap.
- [ ] Run focused, promotion, full repository, documentation, security, and
      residue verification.
- [ ] Inspect the final diff, update this plan and `HANDOFF.md`, then commit
      and push atomic milestones under the verified account.

## Progress Log

### 2026-07-28 — Existing policy and evidence recovered

- Completed: Read the long-horizon harness, project instructions, current
  handoff, Stage 6 plan, ledger v1 implementation, release aggregator,
  combined artifact verifier, related ADRs, current retained v1 output, and
  recent Git history. Three independent read-only reviews covered provider
  lineage policy, v1-to-v2 evidence mapping, and compatibility/rollback.
- Evidence: All reviews identify the same three primary coupling points:
  global minimum release readiness, combined core/UI artifact qualification,
  and the serial RGW/KMS prerequisite inherited by core operations.
- Current disposition: No existing passed state is imported. The current v1
  result remains zero passed, one blocked, nine pending, and
  `production_candidate=false`.
- Changed files: This plan, the coupling research note, ADR 0018 draft, and
  `HANDOFF.md`.
- Next exact action: Add
  `poc/production-promotion/input_lineage.py` and
  `tests/test_production_promotion_input_lineage.py`, beginning with exact
  schema and common immutable provenance validation before any class-specific
  admission rule.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Recovery source order | Harness, `AGENTS.md`, `HANDOFF.md`, plan 0019, Git status/log | passed |
| Current ledger v1 state | Owner-only retained JSON inspection | passed; 0 passed, 1 blocked, 9 pending, candidate false |
| Independent policy review | Read-only Ultra agent | passed; strict three-lineage policy and Referrers split |
| Independent evidence review | Read-only Max agent | passed; negative-only current remap |
| Independent compatibility review | Read-only Max agent | passed; additive v2 and exact-v1 replay boundary |
| Plan/document checks | pending | pending |

## Failures, Blockers, and Risks

- The first three parallel agent turns were interrupted by a transient response
  stream failure. Their bounded read-only retries completed; no file or
  external state changed.
- Existing v1 specialist result schemas include transitive optional-profile
  prerequisites. They may be retained as stronger legacy evidence, but no v2
  pass may be inferred from their gate name or digest alone.
- A generic profile result would become self-attestation if it accepted a
  caller-supplied status or free-form check set. The v2 verifier must own exact
  per-scope checks, source hashes, provider bindings, non-synthetic adapter
  rules, and the derived status.
- The current release and live specialist evidence cannot make any v2 scope
  qualified. This is an expected honest result, not a blocker to implementing
  and verifying ledger v2.

## Handoff

- Current state: Recovery and design baseline are complete. Ledger v1 and its
  output path remain untouched. ADR 0018 is a draft until implementation and
  security regression confirm the decision.
- Exact next action: Implement the common immutable lineage manifest validator
  before adding official, vendor, and Coffer-specific branches.
- First file or command:
  `poc/production-promotion/input_lineage.py`
- Questions requiring user input: None.
