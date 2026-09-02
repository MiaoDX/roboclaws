**Status:** Active
**Created:** 2026-09-01
**Last reviewed:** 2026-09-02
**Current implementation contract:** Delta to the implemented 2026-07-02 context-management contract. This plan adds a Roboclaws-specific state-first context assembler and checkpoint/resume boundary; it does not reopen the already accepted profile/default migration.
**Research source:** `.planning/research/context-management/report.md`
**Related plan:** `docs/plans/2026-07-02-openai-agents-context-management-optimization.md`
**Related ADRs:** `docs/adr/0126-bridge-camera-evidence-to-cleanup-handles-with-model-declared-observations.md`, `docs/adr/0132-keep-cleanup-memory-skill-first-and-remove-promoted-composite.md`

# State-First Context Manager

## Plan Ledger

- **Decision:** Keep `openai-agents-sdk` and the current MCP/runtime ownership. Implement the domain context manager locally; expose storage/retrieval behind a replaceable adapter seam.
- **Research conclusion:** Community systems converge on durable state/checkpoints plus proactively reconstructed model context. They do not require Roboclaws to adopt a full agent framework.
- **Delta boundary:** The July plan's profile, prompt, item compaction, and provider-native-compaction decisions remain shipped/current. This plan covers the missing canonical task snapshot, pre-call budget reconstruction, and resumable checkpoint semantics.
- **No new ADR yet:** This is execution-shaped. Create an ADR only if the snapshot becomes a durable public/MCP contract, changes private-data boundaries, or provider-native compaction is accepted.
- **Open decision gate:** None for this plan. Typed snapshot fields and adapter implementation are local defaults; public contract changes are an explicit stop gate.
- **Implementation:** Phases 1-3 are complete. Phase 4 local proof is recorded in `.planning/phases/04-route-proof-and-rollout/04-VALIDATION.md` and `04-LIVE-PROOF.md`; its focused eval gate remains partial.
- **Residual eval findings:** One missing historical fixture and one existing unmanaged direct-runner behavior failure remain out of scope; no durable baseline was published.

## Goal

Prevent context growth from reaching provider hard limits by rebuilding each model input from authoritative run state, a bounded recent raw overlap, and targeted evidence. Preserve complete MCP/DINO/report artifacts and make context-budget interruption resumable from a checkpoint.

## Non-goals

- Do not migrate to LangGraph, LlamaIndex, AutoGen, Letta, Google ADK, or another complete agent runtime.
- Do not replace the OpenAI Agents SDK loop or MCP tool contracts.
- Do not put private scoring truth, credentials, raw prompts, or full tool payloads into model context or telemetry.
- Do not silently raise hard limits, fall back to `baseline`, or replay the same over-limit transcript.
- Do not enable provider-native compaction in this slice.
- Do not treat this plan as a new provider/model bake-off or a real-robot movement authorization.

## Current Evidence And Failure

The current filter performs item-level compaction, but the budget guard executes before `_compact_model_input_items`. The configured 64k soft limit is not a canonical reconstruction trigger; 96k is the fail-closed hard limit. MiMo runs observed approximately 97-98k input tokens. The existing July plan is therefore implemented for profile plumbing, but its broader research target is not complete.

## Target Contract

```text
append-only run events + immutable artifacts
        -> typed task snapshot/checkpoint
        -> pre-call budget estimator
        -> context assembler:
             fixed system contract
             canonical snapshot
             current subgoal evidence
             bounded recent raw overlap
             expected-output reserve
```

The snapshot is authoritative for current task state, not a summary of the prompt. At minimum it records task/intent, current robot pose and waypoint, observed object handles and freshness/provenance, navigation/pick/place outcomes, safety gates, completion status, evidence references/digests, and a monotonic revision. Full raw event bodies remain in existing artifact storage.

## Phased Execution

### Phase 1: State And Checkpoint Schema

Owner modules: new focused modules under `roboclaws/agents/` or the existing household lifecycle owner, plus schema tests.

- Define a dependency-light typed snapshot and checkpoint schema with explicit revision/provenance and stale-observation semantics.
- Project successful MCP/tool events into the snapshot without exposing private scoring truth.
- Persist checkpoint artifacts atomically at meaningful tool/action boundaries and at context-budget interruption.
- Reuse existing run artifact/completion conventions; do not create a second event ledger.

Acceptance: snapshot round-trips; required object/waypoint/pose/action/safety/evidence fields survive; private truth, credentials, raw prompt text, and full payloads are absent; complete existing traces/artifacts remain unchanged.

### Phase 2: Pre-Call Context Assembler

Owner modules: `roboclaws/agents/drivers/openai_agents_compaction.py`, budget helpers, and a focused assembler module if needed.

- Assemble from the latest checkpoint plus recent raw overlap and subgoal-scoped evidence.
- Use `estimated_input + expected_output + safety_reserve <= context_hard_limit_tokens` as the pre-call contract.
- Treat the soft limit as a proactive watermark. Trigger reconstruction before the hard guard, with provider/lane-specific output reserve.
- Evict optional retrieval first, then older raw overlap; never evict action-critical snapshot fields.
- Keep current item-level compaction as a compatibility implementation detail only where it is still useful; it must not be the source of truth.

Acceptance: deterministic tests prove reconstruction happens before hard-limit failure, output reserve is accounted for, input remains below the hard limit under synthetic growth, and residual overflow fails closed with a checkpoint rather than retrying the same payload.

### Phase 3: Resume And Failure Semantics

Owner modules: `household_live_lifecycle.py`, `household_live_continuation.py`, budget/failure projection, and focused lifecycle tests.

- On `provider_context_budget_exceeded`, write a checkpoint digest and classify the run as resumable only when the checkpoint is valid and no terminal completion exists.
- Start the next SDK invocation from reconstructed state, not the previous full model input.
- Preserve bounded continuation counts and existing `run_result.json`/`done` success semantics.
- Distinguish recoverable checkpointed context overflow from unrecoverable provider/context failure in artifacts and status.

Acceptance: mocked continuation resumes from snapshot; no duplicate over-limit payload is sent; missing/corrupt checkpoint fails closed with actionable status; terminal success still requires MCP `done` and `run_result.json`.

### Phase 4: Route Proof And Rollout

Owner modules: existing profile/run integration tests and product eval gates.

- Cover cleanup, MapBuild, and no-preset open-ended household SDK paths, including camera-grounded/DINO inputs.
- Verify operator-console and Agibot resolver metadata use the same context contract without adding a profile picker or new launch axis.
- Run deterministic tests and the focused eval recommendation/execution gates.
- Run the documented local camera-grounded product proof when provider/network/runtime readiness passes; otherwise record the guarded blocker output and stop.

Acceptance: existing `baseline` remains an explicit unmanaged comparison; managed runs stay within budget under synthetic and available local live workloads; complete traces/reports/DINO artifacts remain reviewable and content-addressable; no private data crosses telemetry or model input boundaries.

## Verification Commands

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
just agent::eval recommend plan=docs/plans/2026-09-01-state-first-context-manager.md budget=focused
just agent::eval execute plan=docs/plans/2026-09-01-state-first-context-manager.md budget=focused
```

Live proof is conditional on the existing network/provider/runtime gates. If unavailable, run the documented preflight/status command and retain the concrete blocker; do not substitute a provider bake-off.

## Stop Gates And Risks

- Stop for user review before changing any public MCP/tool/launch contract, private-data boundary, safety policy, provider infrastructure, or durable artifact schema consumed outside this runtime.
- Stop if the snapshot duplicates an existing canonical owner instead of projecting from it; prefer deleting the duplicate abstraction.
- Stop if behavior tests show that compaction loses action-critical state; retain more typed state or narrow the slice before implementation.
- Provider token estimation may be approximate. Keep a conservative reserve and prove the residual hard-limit path rather than claiming exact accounting.

## Current Status

The implementation is complete and its scoped deterministic, real Grounding
DINO MapBuild, and automated operator-console proofs pass. Phase 4 is not marked
complete because the focused eval packet retains one missing historical fixture
and one unmanaged direct-runner behavior failure. Addressing either requires
separate prioritization; neither belongs to the state-first implementation.
