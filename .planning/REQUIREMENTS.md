# Requirements: State-First Context Manager

## v1 Requirements

### REQ-state-and-checkpoint-schema: Typed state and checkpoint projection

Define a dependency-light typed task snapshot and checkpoint projection from
successful MCP/tool events, with explicit revision/provenance and
stale-observation semantics. Persist checkpoints atomically at meaningful
tool/action boundaries and context-budget interruption while reusing existing
run-artifact/completion conventions. Keep task/intent, pose/waypoint, observed
handles with freshness/provenance, action outcomes, safety gates, completion,
and evidence references/digests; exclude private scoring truth, credentials,
raw prompts, and full payloads from model input.

### REQ-pre-call-context-assembler: Pre-call context reconstruction

Rebuild each model input from the latest checkpoint, bounded recent raw
overlap, subgoal-scoped evidence, fixed system contract, and expected-output
reserve. Use proactive soft-limit watermarking and fail closed after optional
retrieval and older overlap eviction.

### REQ-resume-and-failure-semantics: Resumable overflow and failure handling

Make provider context-budget overflow resumable only when a valid checkpoint
exists and no terminal completion exists. Resume the next SDK invocation from
reconstructed state with bounded continuation and existing success artifacts;
missing or corrupt checkpoints fail closed with actionable status.

### REQ-route-proof-and-rollout: Cross-route proof and rollout

Validate the shared context contract across cleanup, MapBuild, and no-preset
open-ended household SDK paths, including camera-grounded/DINO inputs,
operator-console use, and Agibot resolver metadata without adding launch axes.
Preserve explicit unmanaged `baseline` comparison and content-addressed
traces, reports, and DINO artifacts.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-state-and-checkpoint-schema | Phase 1 | Complete |
| REQ-pre-call-context-assembler | Phase 2 | Pending |
| REQ-resume-and-failure-semantics | Phase 3 | Pending |
| REQ-route-proof-and-rollout | Phase 4 | Pending |

Coverage: 4/4 v1 requirements mapped exactly once.
