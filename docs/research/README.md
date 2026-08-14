# Research Reports

This directory contains technical research documents that inform Roboclaws
project decisions. Reports are not all current guidance: some capture historical
AI2-THOR or game-era decisions that ADR-0137 and the household-world launch
contract have since superseded.

## Report Index

| # | Status | File | Topic | Key Conclusion |
|---|--------|------|-------|---------------|
| 01 | Historical; superseded by ADR-0148 | [openclaw-isaaclab-feasibility](01-openclaw-isaaclab-feasibility.md) | OpenClaw + Isaac Lab feasibility | Retained as historical research; OpenClaw is no longer a current runtime. |
| 02 | Superseded by ADR-0137 | [ai2thor-multiagent-foundations](02-ai2thor-multiagent-foundations.md) | AI2-THOR multi-agent API + OpenClaw integration | AI2-THOR findings remain historical; AI2-THOR is no longer a current public launch axis. |
| 03 | Partly superseded by household-world direction | [simulation-platforms-2026](03-simulation-platforms-2026.md) | 2026 simulation platform landscape | Platform survey remains useful context, but the active direction is MolmoSpaces/MuJoCo plus explicit backend gates. |
| 04 | Historical; superseded by ADR-0148 | [openclaw-robotics-ecosystem](04-openclaw-robotics-ecosystem.md) | OpenClaw robotics ecosystem mapping | Retained as historical ecosystem context; OpenClaw is retired. |
| 05 | Superseded by retired game/public-surface cleanup | [real-model-smoke-validation](05-real-model-smoke-validation.md) | Issue #50 local-dev validation | Territory/coverage findings are history, not current product strategy. |
| 06 | Current background | [visual-grounding-perception-producer](06-visual-grounding-perception-producer.md) | Edge visual-grounding perception producer | Separate producer service; fast proposer first, optional verifier only when measured quality requires it. |
| 07 | Current background | [agent-sdk-vs-frameworks-for-coding-loop](07-agent-sdk-vs-frameworks-for-coding-loop.md) | OpenAI Agents SDK vs. Claude Agent SDK vs. other frameworks, for the code-holds-the-loop MCP robot agent | Decisive axis is loop ownership, not provider compat; thin DIY loop on the MCP Python SDK (or PydanticAI) beats both vendor SDKs for this use case; OpenAI Agents SDK preferred of the two; resilience must be engineered regardless. |
| 08 | Current decision context | [agent-evaluation-harness-research](08-agent-evaluation-harness-research.md) | OpenAI, Anthropic, Cursor, eval frameworks, and agent benchmark patterns | Use public benchmarks for calibration, but build a repo-native versioned eval suite with samples, trials, trace/state graders, identity packets, `pass^k`, and failure replay. |
| 09 | Current decision context | [agent-context-management-research](09-agent-context-management-research.md) | Agent context management, tool-output reduction, provider compaction, and Roboclaws profile compatibility | Use layered context management: source-level tool output shaping, deterministic model-input compaction, explicit budgets/hard limits, optional provider-native compaction only as an additive compatibility layer, and complete trace/artifact state outside model context. |

## See Also

- [`docs/research-checkpoints/`](../research-checkpoints/) — Monthly ecosystem checkpoint snapshots (Chinese, internal decision-oriented). Complementary to single-topic reports here: research/ answers "should we do X?", checkpoints/ answer "what does the ecosystem look like now and do our prior judgments still hold?".

## Changelog

- **2026-04-13**: Initial version, 4 reports completed
- **2026-04-14**: Added report 05 documenting the issue #50 real-model smoke validation outcome
- **2026-04-28**: Added cross-link to new monthly checkpoint series at `docs/research-checkpoints/`
- **2026-05-25**: Added report 06 on the visual-grounding perception producer reference design
- **2026-06-09**: Added report 07 comparing the OpenAI Agents SDK, Claude Agent SDK, and other frameworks for the code-holds-the-loop MCP robot agent (decision context for replacing the Codex-CLI subprocess driver)
- **2026-06-14**: Added report 08 on agent evaluation harness best practices and Roboclaws eval-suite implications
- **2026-07-02**: Added report 09 on agent context management best practices and the `baseline` / `context_managed_v1` compatibility policy
