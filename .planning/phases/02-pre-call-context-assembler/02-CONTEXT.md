# Phase 2: Pre-Call Context Assembler - Context

**Gathered:** 2026-09-02
**Status:** Ready for planning
**Source:** PRD Express Path (`docs/plans/2026-09-01-state-first-context-manager.md`)

<domain>
## Phase Boundary

Rebuild every managed OpenAI Agents SDK model input before provider dispatch from
the latest Phase 1 checkpoint, action-critical canonical snapshot state,
subgoal-scoped evidence, and a bounded recent raw overlap. Apply the proactive
soft watermark and prove the complete pre-call budget equation before retaining
the assembled payload. Residual overflow writes one checkpoint and fails closed;
resume/continuation behavior belongs to Phase 3.

</domain>

<decisions>
## Locked Decisions

- Reconstruction runs before the existing hard-limit guard and before the
  provider call. The prior transcript and item-level compaction are not the
  authoritative state source.
- Every decision uses `estimated_input + expected_output + safety_reserve <=
  context_hard_limit_tokens`. Expected-output reserve is provider/lane specific;
  estimation remains conservative rather than claiming exact token accounting.
- Crossing the soft watermark proactively triggers reconstruction even when the
  previous observed input remains below the hard limit.
- Eviction is deterministic: optional targeted retrieval first, then oldest raw
  overlap. Fixed system instructions and action-critical snapshot fields are
  never eviction candidates.
- If required content plus reserves still exceeds the hard limit, persist the
  Phase 1 checkpoint once, emit actionable budget evidence, fail closed, and do
  not retry the identical payload.
- Preserve existing traces, reports, DINO artifacts, and public MCP/launch
  contracts. Do not enable provider-native compaction or add a second ledger.

## Agent's Discretion

- The exact dependency-light token estimator and conservative multiplier.
- The focused assembler module name and internal result/value types.
- Raw-overlap and optional-retrieval caps, provided eviction remains ordered and
  the reserve equation is observable in tests and budget events.

</decisions>

<implementation>
## Owned Implementation Surface

- `roboclaws/agents/drivers/openai_agents_compaction.py`: invoke reconstruction
  before the legacy guard/provider dispatch and retain legacy item compaction
  only as a subordinate implementation detail.
- `roboclaws/agents/drivers/openai_agents_budget.py` and existing profile/config
  owners: calculate/validate input, output, safety, soft-watermark, and hard-limit
  values without changing public launch axes.
- One focused module under `roboclaws/agents/drivers/` only if it gives the
  assembler a coherent dependency-light owner.
- Reuse the Phase 1 snapshot/checkpoint reader and atomic writer. Do not modify
  its schema unless a concrete Phase 2 requirement cannot be represented; any
  public or durable schema change is a stop gate.

## Focused Test Surface

- Existing focused compaction/filter tests, or a new
  `tests/unit/agents/test_openai_agents_context_assembler.py` when separation is
  clearer.
- `tests/unit/agents/test_openai_agents_budget_sources.py` for reserve arithmetic,
  conservative estimation, and residual overflow evidence.
- Tests must cover: reconstruction at the soft watermark before the hard guard;
  provider/lane expected-output plus safety reserves; optional retrieval then
  oldest-overlap eviction; action-critical snapshot retention; synthetic growth
  below the hard limit; and residual overflow checkpointing once without
  identical-payload retry.

</implementation>

<scope>
## Non-Goals And Stop Gates

- No Phase 3 continuation/resume policy or lifecycle classification.
- No Phase 4 route-wide live/eval rollout proof.
- No public MCP/tool/launch contract, privacy boundary, safety policy, provider
  infrastructure, or externally consumed artifact-schema change. Stop for user
  review if any becomes necessary.
- No changes to Phase 1 artifacts or shipped history.

</scope>

<canonical_refs>
## Canonical References

- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/phases/01-state-and-checkpoint-schema/01-CONTEXT.md`
- `docs/plans/2026-09-01-state-first-context-manager.md`
- `docs/adr/0126-bridge-camera-evidence-to-cleanup-handles-with-model-declared-observations.md`
- `docs/adr/0132-keep-cleanup-memory-skill-first-and-remove-promoted-composite.md`
- `roboclaws/agents/drivers/openai_agents_compaction.py`
- `roboclaws/agents/drivers/openai_agents_budget.py`

</canonical_refs>
