# Codex Long-Horizon Workflow

## Memory Architecture

Coffer uses four layers with deliberately different responsibilities:

1. `AGENTS.md` contains stable repository rules and recovery behavior.
2. The active `docs/exec-plans/*.md` file contains the current work package, decisions, progress, and acceptance evidence.
3. `.codex/state/HANDOFF.md` is the concise cross-session continuation point.
4. `.codex/state/precompact-snapshot.md` and Codex local memories are auxiliary recall. The hook-generated snapshot is ignored by Git and contains only mechanical repository state.

The first three layers are authoritative. Do not place secrets in any layer.

## Model and Reasoning Policy

| Work type | Model | Reasoning | Why |
|---|---|---|---|
| Main implementation and integration | `gpt-5.6-sol` | `high` | Strong agentic coding with enough depth for multi-step work |
| Architecture, security, migration, or difficult planning | `gpt-5.6-sol` | `xhigh` in Plan mode | More search and trade-off analysis before changing the system |
| Independent read-heavy scans or routine checks | `gpt-5.6-terra` | `medium` | Faster and more economical when ultimate reasoning depth is unnecessary |
| Exceptional, eval-proven hard problems | `gpt-5.6-sol` | `max` or supported `ultra` mode | Use selectively; latency and cost are materially higher |

The project config deliberately uses `high` for normal work and `xhigh` for Plan mode. Start there and change it only after observing failures or evaluating task quality; reasoning effort is not a substitute for clear done criteria and durable state.

## Starting or Resuming a Work Session

1. Read `AGENTS.md` and `.codex/state/HANDOFF.md`.
2. Open the active execution plan named in the handoff.
3. Inspect `git status --short` and recent commits.
4. Verify that the plan's exact next action matches the repository.
5. Work through one small, testable milestone at a time.

If no active plan exists for multi-stage work, copy `docs/exec-plans/TEMPLATE.md` to a numbered plan and fill in objective, done criteria, non-goals, evidence, and the first task.

## Before and After Compaction

Before invoking `/compact`, stop at an atomic boundary and update the active plan and `HANDOFF.md`. The `PreCompact` hook then records Git state in `.codex/state/precompact-snapshot.md`; it intentionally does not parse the transcript or invent semantic state.

After compaction, re-read those files and reconcile them with Git before acting. If they disagree, the repository and the source-of-truth order in `AGENTS.md` win.

Codex loads project configuration only for trusted repositories, and project hooks require separate review and trust. Review `.codex/config.toml`, `.codex/hooks.json`, and the Python script; trust the repository when Codex prompts, then use `/hooks` to trust the hook. Restart or open a new task after project configuration changes if the current session does not reload them.

## Local Memories

This repository enables experimental Codex memories as a convenience. They can improve recall between sessions but are generated asynchronously and may be disabled when external context is present. Required instructions and decisions therefore remain in checked-in files. Use `/memories` to inspect or manage them when available.

## Completion Checklist

- Done criteria are demonstrably satisfied.
- Relevant focused checks passed, or skipped checks are explicitly explained.
- The final diff contains no unrelated changes or secrets.
- Decisions and evidence are recorded in the active plan.
- `HANDOFF.md` states the final status and any remaining risks or next action.
