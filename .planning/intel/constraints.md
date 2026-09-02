# Constraints

No standalone SPEC documents were included. Constraints extracted from the PRD:

- **context-budget**: Pre-call contract is `estimated_input + expected_output + safety_reserve <= context_hard_limit_tokens`; soft limit is proactive watermark and hard overflow fails closed. `source: docs/plans/2026-09-01-state-first-context-manager.md`
- **data-boundary**: Do not place private scoring truth, credentials, raw prompts, or full tool payloads in model context or telemetry. `source: docs/plans/2026-09-01-state-first-context-manager.md`
- **artifact-integrity**: Keep append-only run events and immutable, complete MCP/DINO/report artifacts; do not create a second event ledger; preserve content-addressability. `source: docs/plans/2026-09-01-state-first-context-manager.md`
- **runtime-ownership**: Keep OpenAI Agents SDK loop and MCP contracts; do not migrate to another full agent runtime or add launch axes/profile picker. `source: docs/plans/2026-09-01-state-first-context-manager.md`
- **failure-safety**: Never silently raise limits, fall back to `baseline`, or replay the same over-limit transcript; missing/corrupt checkpoints fail closed. `source: docs/plans/2026-09-01-state-first-context-manager.md`

