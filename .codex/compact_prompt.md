Create a compact continuation brief for the next agent turn.

Preserve only durable, actionable state:

1. Current objective and explicit done criteria.
2. Current user requirements and applicable `AGENTS.md` constraints.
3. Active execution plan path and exact task status.
4. Decisions, reasons, and important rejected alternatives.
5. Current branch, modified files, and relevant commits.
6. Commands, tests, and checks already run, including outcomes.
7. Failed approaches, blockers, and unresolved risks.
8. The next three concrete actions; make the first action name a file, command, or decision.

Discard raw logs, repetition, obsolete hypotheses, and conversational filler. Never infer or claim unverified completion. Never include secrets or credential material.

On continuation, first re-read `AGENTS.md`, `.codex/state/HANDOFF.md`, the active execution plan, and `.codex/state/precompact-snapshot.md` if present. Then inspect Git state before acting.
