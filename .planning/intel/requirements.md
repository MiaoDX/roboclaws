# Requirements

## REQ-state-and-checkpoint-schema

- Source: `docs/plans/2026-09-01-state-first-context-manager.md`
- Description: Define a dependency-light typed task snapshot and checkpoint projection from successful MCP/tool events, with explicit revision/provenance and stale-observation semantics. Persist checkpoints atomically at meaningful tool/action boundaries and context-budget interruption while reusing existing run-artifact/completion conventions.
- Scope: task/intent, robot pose and waypoint, observed object handles with freshness/provenance, navigation/pick/place outcomes, safety gates, completion status, evidence references/digests, monotonic revision; private scoring truth, credentials, raw prompts, and full payloads remain excluded from model input.
- Acceptance criteria: Snapshot round-trips; required object/waypoint/pose/action/safety/evidence fields survive; excluded private/raw data is absent; complete existing traces/artifacts remain unchanged.

## REQ-pre-call-context-assembler

- Source: `docs/plans/2026-09-01-state-first-context-manager.md`
- Description: Rebuild each model input from the latest checkpoint, bounded recent raw overlap, subgoal-scoped evidence, fixed system contract, and expected-output reserve. Use proactive soft-limit watermarking and fail closed after optional retrieval and older overlap eviction.
- Scope: `roboclaws/agents/drivers/openai_agents_compaction.py`, budget helpers, and a focused assembler module if needed; current item-level compaction may remain only as an implementation detail.
- Acceptance criteria: Deterministic tests prove reconstruction before hard-limit failure, output reserve accounting, below-hard-limit synthetic growth, and residual overflow checkpointing without retrying the same payload.

## REQ-resume-and-failure-semantics

- Source: `docs/plans/2026-09-01-state-first-context-manager.md`
- Description: Make provider context-budget overflow resumable only when a valid checkpoint exists and no terminal completion exists. Resume the next SDK invocation from reconstructed state, preserving bounded continuation and existing success artifacts.
- Scope: household lifecycle/continuation and budget/failure projection; distinguish recoverable checkpointed overflow from unrecoverable provider/context failure.
- Acceptance criteria: Mocked continuation resumes from snapshot with no duplicate over-limit payload; missing/corrupt checkpoint fails closed with actionable status; terminal success still requires MCP `done` and `run_result.json`.

## REQ-route-proof-and-rollout

- Source: `docs/plans/2026-09-01-state-first-context-manager.md`
- Description: Validate the shared context contract across cleanup, MapBuild, and no-preset open-ended household SDK paths, including camera-grounded/DINO inputs, operator console, and Agibot resolver metadata without adding launch axes.
- Scope: Existing profile/run integration tests, product eval gates, and conditional local camera-grounded proof. `baseline` remains an explicit unmanaged comparison.
- Acceptance criteria: Managed runs stay within budget under synthetic and available local live workloads; complete traces/reports/DINO artifacts remain reviewable and content-addressable; no private data crosses telemetry or model-input boundaries; guarded blockers are recorded when live prerequisites are unavailable.

