# Coffer Agent Guide

## Mission

Coffer is the confirmed project codename for an OpenStack-native OCI Registry service. The descriptive service name is `OCI Registry service`; the proposed, not-yet-official Keystone service type is `oci-registry`; and the user-facing CLI noun is `registry`. The project is currently in architecture review and proof-of-concept planning. Treat product and architecture choices as provisional unless they are recorded in an accepted execution plan or ADR.

Current architectural hypothesis:

- OCI Distribution-compatible data plane
- Keystone-integrated identity and project isolation
- OpenStack-friendly object storage, with Ceph RGW/S3 as the leading candidate
- A separate control plane only where upstream registry components do not satisfy OpenStack requirements

## Sources of Truth

When information conflicts, use this order:

1. The user's current request
2. This `AGENTS.md`
3. The active file in `docs/exec-plans/`
4. `.codex/state/HANDOFF.md`
5. `.codex/state/precompact-snapshot.md`
6. Generated local memories or conversation summaries

Required project instructions and decisions must live in checked-in files. Local memories and generated snapshots are supporting recall, not authoritative state.

## Session Start and Recovery

Before making material changes:

1. Read this file.
2. Read `.codex/state/HANDOFF.md`.
3. Read the active execution plan, if one is named in the handoff.
4. Inspect `git status --short` and recent commits.
5. Reconcile the requested work with the repository state before continuing.

After context compaction, do not rely on the compacted summary alone. Repeat the recovery sequence above and verify the next action against the actual files and Git state.

## Long-Horizon Work Protocol

- For work spanning multiple milestones, create an execution plan from `docs/exec-plans/TEMPLATE.md` before implementation.
- Keep exactly one next concrete action in the active plan. It should name the first file, command, or decision to address.
- Work in small, verifiable milestones. Update the active plan and handoff after every material milestone or decision.
- Record architectural decisions with their reasons and rejected alternatives. Do not silently reverse an accepted decision.
- Before manual compaction or when the context window is becoming crowded, finish or safely stop the current atomic action, then update the active plan and handoff.
- The handoff must state: objective, completed work, decisions and reasons, changed files, verification results, failures, blockers, and the exact next action.
- At completion, run the most relevant focused checks, inspect the diff, and update the handoff. Do not claim completion for unverified work.

## Autonomy and Safety

Proceed autonomously with safe local inspection, scoped edits, builds, and tests that are clearly part of the requested work.

Ask before:

- destructive or difficult-to-recover operations;
- production deployment or external publication;
- pushing commits, opening issues or pull requests, or sending messages;
- handling credentials or changing security boundaries;
- making an architectural choice that materially expands or changes the requested scope.

Never store credentials, tokens, private keys, kubeconfigs, or sensitive transcript content in plans, handoffs, snapshots, or memories. Preserve unrelated user changes.

## Multi-Agent Work

Use subagents only when the initiating request explicitly authorizes them. Delegate independent read-heavy research, test, or review tasks; keep one primary writer for overlapping files. Ask workers for concise findings and evidence, not raw logs. The primary agent owns integration, decisions, verification, and the durable handoff.

## Engineering Defaults

- Prefer the simplest sufficient vertical slice over speculative abstractions.
- Keep edits surgical and tests proportional to risk.
- Reuse mature OCI registry components before building a new data plane.
- Treat product names, APIs, storage choices, and service boundaries as hypotheses until documented and validated.
- Keep raw exploration and command logs out of the main context; preserve only evidence, decisions, and actionable outcomes.
