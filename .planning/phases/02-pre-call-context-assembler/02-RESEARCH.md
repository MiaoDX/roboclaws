# Phase 2: Pre-Call Context Assembler - Research

**Researched:** 2026-09-02
**Domain:** OpenAI Agents SDK model-input filtering, deterministic context budgeting, checkpoint-backed state reconstruction
**Confidence:** HIGH (repository evidence; provider token estimation remains MEDIUM)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Keep `openai-agents-sdk` and current MCP/runtime ownership; add a local,
  dependency-light typed snapshot/checkpoint seam.
- D-02: Project from the existing append-only trace/artifact ledger; do not add a
  second event ledger or expose private evaluation truth.
- D-03: Checkpoints are atomic, privacy-bounded artifacts and retain explicit
  revision/provenance plus stale-observation semantics.

### Scope
Define and test the authoritative task snapshot, project successful MCP/tool
events into it, and persist checkpoints at meaningful action/tool boundaries and
context-budget interruption. Existing traces, reports, DINO files, and
`run_result.json` semantics remain unchanged.

### Non-goals
No pre-call assembler, continuation/resume policy, provider-native compaction,
new launch axes, public MCP contract, or real-robot authorization.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| REQ-pre-call-context-assembler | Reconstruct bounded model input before provider calls with reserves, ordered eviction, and fail-closed residual overflow | Existing compaction hook, budget guard, profile limits, snapshot/checkpoint APIs, and focused tests identified below |
</phase_requirements>

## Summary

The current call path is `openai_agents_run_config.py` installing `_model_input_compaction_filter`; that filter invokes `_raise_budget_failure_before_model_call` before any item compaction. `_compact_model_input_items` performs item-level transformations (history windows, metric-map summaries, camera-grounded and raw-FPV policies) and emits metrics, but cannot reconstruct from authoritative state. Phase 2 should place a deterministic assembler at this hook: load the latest checkpoint snapshot, select subgoal evidence, retain a bounded recent raw overlap, reserve expected output plus safety margin, then apply ordered optional eviction before the hard-limit check.

Phase 1 provides `TaskSnapshot`, `Checkpoint`, `atomic_write_checkpoint`, and privacy filtering in `roboclaws/agents/task_state.py`; projection is in `openai_agents_event_projection.py`. The assembler must consume these read-only artifacts and must not create another ledger or alter complete trace/report payloads. Residual overflow should emit the existing `provider_context_budget_exceeded` failure/checkpoint path once, with no retry of the identical input.

**Primary recommendation:** Add a dependency-light pure assembler/budget helper owned by `roboclaws/agents/drivers`, call it from `_model_input_compaction_filter` before the existing compactor, and prove policy with synthetic-growth unit tests.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Snapshot-backed context reconstruction | API / Backend | Database / Storage (run artifacts) | Runtime owns model-facing policy; checkpoint JSON is durable input state |
| Token budget estimation and reserves | API / Backend | — | Provider call admission is runtime policy |
| Optional/raw overlap eviction | API / Backend | — | Must preserve action-critical typed state |
| Existing item-level compaction | API / Backend | — | Compatibility implementation detail at SDK model-input boundary |

## Standard Stack

### Core

| Component | Version | Purpose | Evidence |
|---|---|---|---|
| Python stdlib `dataclasses`, `json`, `pathlib` | repo runtime | Typed snapshot serialization and deterministic assembly | `[VERIFIED: codebase]` `roboclaws/agents/task_state.py` |
| OpenAI Agents SDK model-input filter contract | installed optional runtime | Pre-call interception | `[VERIFIED: codebase]` `openai_agents_compaction.py`, `openai_agents_run_config.py` |

No external packages are required for this phase; package legitimacy audit is not applicable.

## Architecture Patterns

### Pre-call pipeline

`ModelInputData(input, instructions)` -> load latest `Checkpoint` -> build fixed contract + public snapshot + subgoal evidence + bounded raw overlap -> estimate input tokens -> reserve output/safety -> evict optional retrieval, then oldest overlap -> admit call or write checkpoint and raise fail-closed budget error.

### Preserve existing compaction

Run `_compact_model_input_items` only after reconstruction and budget shaping. Keep its existing privacy summaries and complete artifact semantics; do not make it the source of truth. Use stable JSON sizing/hash helpers already imported by the module.

### Configuration

Profiles already expose `context_soft_limit_tokens` (proactive watermark) and `context_hard_limit_tokens` (terminal guard) through `openai_agents_perf_profile.py` and run config. Add reserve/overlap settings in the local context policy shape only if needed; do not add launch axes or provider-native compaction.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Durable state | Second event database/ledger | Existing trace/artifact ledger plus `Checkpoint` | Locked D-02 and preserves complete evidence |
| Snapshot serialization | Ad-hoc dicts in assembler | `TaskSnapshot.from_json/to_dict` | Enforces privacy and schema |
| Atomic persistence | Direct overwrite | `atomic_write_checkpoint` | Existing fsync + replace semantics |
| Item transformations | New duplicate compactor | `_compact_model_input_items` | Existing tested policies and metrics |

## Common Pitfalls

1. **Hard guard runs first:** Current ordering raises at hard usage before compaction; move reconstruction/admission before this check and retain hard guard as residual protection. `[VERIFIED: codebase]`
2. **Evicting state fields:** Snapshot fields (pose, waypoint, object freshness/provenance, action outcomes, safety, completion, evidence refs) are action-critical and must never be dropped. `[VERIFIED: PRD + task_state.py]`
3. **Reserve omission:** Input-only estimates can pass while output causes provider rejection; enforce `estimated_input + expected_output + safety_reserve <= hard`. `[VERIFIED: PRD]`
4. **Retrying identical overflow:** Residual overflow must checkpoint once and fail closed, not replay unchanged items. `[VERIFIED: PRD]`
5. **Private leakage:** Use `TaskSnapshot.to_dict`/public observation values and evidence digests only; never include raw prompts, credentials, private scoring truth, or full payloads. `[VERIFIED: task_state.py + PRD]`

## Code Examples

Existing hook shape (repository-verified):

```python
async def _filter(data):
    model_data = getattr(data, "model_data", None)
    original_items = getattr(model_data, "input", None)
    # Phase 2 inserts reconstruction/admission before the residual hard guard.
    return _model_input_data_like(model_data, input_items=items, instructions=instructions)
```

Existing checkpoint read/write primitives: `Checkpoint.from_json(...)`, `TaskSnapshot.to_dict()`, and `atomic_write_checkpoint(path, Checkpoint(snapshot))` in `roboclaws/agents/task_state.py`.

## Runtime State Inventory

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | Checkpoint JSON under each run directory; trace/artifact JSONL | Read existing files; no migration |
| Live service config | None identified for this local policy | None |
| OS-registered state | None | None |
| Secrets/env vars | Profile settings may come from env/config; no renamed keys | Preserve names; no migration |
| Build artifacts / installed packages | None relevant | None |

## Environment Availability

No external dependency is required beyond repository Python tooling. `.venv`/`uv` and standalone pytest are the documented paths; no provider or simulator is needed for deterministic phase tests.

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest (repo standalone wrapper) |
| Config file | repository test configuration/conftest |
| Quick run command | `./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents/test_openai_agents_input_window.py tests/unit/agents/test_live_runtime_budget.py` |
| Full suite command | `./scripts/dev/run_pytest_standalone.sh -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| REQ-pre-call-context-assembler | Soft watermark triggers reconstruction before hard failure | unit | focused new assembler test | Wave 0 |
| REQ-pre-call-context-assembler | Output + safety reserves admitted in decision | unit | focused budget test | Wave 0 |
| REQ-pre-call-context-assembler | Eviction ordering preserves snapshot | unit | focused eviction test | Wave 0 |
| REQ-pre-call-context-assembler | Synthetic growth stays bounded; residual overflow checkpoints once/no replay | unit/contract | focused filter/checkpoint test | Wave 0 |

Existing compaction and budget tests provide regression coverage; add focused tests beside `tests/unit/agents/` rather than broad integration fixtures.

## Security Domain

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | Existing runtime auth boundaries unchanged |
| V3 Session Management | no | Run checkpoint identity remains task-owned |
| V4 Access Control | yes | Preserve existing public/model boundary |
| V5 Input Validation | yes | Validate numeric limits and snapshot schema |
| V6 Cryptography | no | Use existing SHA-256 digest helper; do not add crypto |

## Sources

### Primary (HIGH confidence)
- `docs/plans/2026-09-01-state-first-context-manager.md` (Phase 2 contract and stop gates)
- `.planning/phases/01-state-and-checkpoint-schema/01-CONTEXT.md` (locked decisions)
- `roboclaws/agents/drivers/openai_agents_compaction.py`, `openai_agents_budget.py`, `task_state.py` (live implementation)
- `tests/unit/agents/test_openai_agents_input_window.py`, `test_live_runtime_budget.py` (existing proof seams)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Provider token estimator can remain conservative/approximate using existing usage metrics and JSON sizing | Summary/Architecture | Underestimation could still cause provider rejection; retain residual hard guard |

## Open Questions (RESOLVED)

1. Exact tokenization method and per-provider output reserve are intentionally
   local policy: use conservative JSON/character estimation with injectable
   provider/lane reserve values and retain the existing residual hard guard.
   This keeps tests deterministic without changing public launch axes.

## Metadata

**Confidence breakdown:** Standard stack HIGH (codebase); Architecture HIGH (PRD + live call path); Pitfalls HIGH except token estimation MEDIUM.
**Research date:** 2026-09-02
**Valid until:** 2026-10-02
