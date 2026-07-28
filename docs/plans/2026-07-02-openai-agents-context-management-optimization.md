**Status:** Implemented
**Created:** 2026-07-02
**Last reviewed:** 2026-07-02
**Current implementation contract:** Implemented and verified. Research inputs and implementation choices are intentionally separated.
**Research source:** `docs/research/09-agent-context-management-research.md`
**Related plans:** `docs/plans/live-agent-runtime-sdk-spike.md`, `docs/plans/live-agent-runtime-sdk-perf-followups.md`
**Related ADRs:** `docs/adr/0126-bridge-camera-evidence-to-cleanup-handles-with-model-declared-observations.md`, `docs/adr/0132-keep-cleanup-memory-skill-first-and-remove-promoted-composite.md`, `docs/adr/0139-use-household-open-task-surface-with-presets.md`, `docs/adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md`

Final active state: `docs/status/active/openai-agents-context-management-optimization.md`

Final product proof:
`output/household/household-world/map-build/openai-agents-live-camera-grounded-labels/0702_2014/seed-7`

# OpenAI Agents Context Management Optimization

## Goal

Make the OpenAI Agents SDK live route context-managed by default while keeping
`baseline` as an explicit comparison profile only.

The target shape is simple:

```text
baseline
  unmanaged, explicit-only A/B and failure-reproduction profile

context_managed_v1
  default product/operator-console profile with source-level output reduction,
  deterministic model-input compaction, compact continuation, budget guards,
  and hard-limit fail-fast classification
```

## Research Inputs

These are research conclusions, not implementation decisions by themselves.
They come from `docs/research/09-agent-context-management-research.md`.

1. Context management should be layered:

   ```text
   source-level tool output shaping
     -> deterministic model-input pruning/summarization
     -> explicit token budgets and hard-limit gates
     -> optional provider-native compaction for conversation/reasoning residue
     -> complete trace/artifact source of truth outside the model context
   ```

2. Source-level reduction comes first. If a tool emits avoidable repeated or
   stale payloads, fix the model-visible tool contract before relying on a
   generic compactor.

3. Complete robot evidence must remain outside model context. MCP traces,
   reports, image artifacts, `runtime_metric_map.json`, `agent_view.json`, and
   `run_result.json` are the review/checker source of truth.

4. Deterministic compaction is preferred for robot state because it is
   reviewable, testable, and can carry public ids, hashes, byte counts, and
   explicit retention policy.

5. Provider-native compaction is compatible only as an additive layer after
   route-specific proof. It must not own Roboclaws robot state, Runtime Metric
   Map state, checker evidence, or failure classification.

6. Prompt caching is not context control. It may improve latency/cost for
   stable prefixes, but cached tokens still occupy context.

## Current Implementation Facts

These are repo facts as of 2026-07-02.

- `scripts/molmo_cleanup/openai_agents_perf_profile.py` still defaults to
  `baseline` when no profile is selected.
- The resolver still accepts several overlapping profile ids:
  `gpt_compact_v1`, `mimo_compact_v1`, `raw_fpv_budgeted_v1`, and `custom`.
- Both live SDK runner families use this resolver:
  - MolmoSpaces household cleanup/open-ended/map-build through
    `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py`.
  - Agibot map-build through
    `scripts/molmo_cleanup/run_live_openai_agents_agibot_map_build.py`.
- Existing context features are mostly present but split across opt-in knobs:
  compact continuation, context soft/hard limits, model-input compaction,
  raw-FPV image memory, camera-grounded history compaction, and the
  camera-grounded composite tool.
- `camera-grounded-labels` currently has a known model-history growth pattern:
  repeated `observe` tool output plus repeated `declare_visual_candidates` tool
  output. The private `observe_camera_grounded_candidates` tool already exists
  and preserves underlying trace events.
- The prompt rerender path is cleanup-biased today. `render_map_build_prompt`
  still tells camera-grounded MapBuild runs to use
  `observe -> declare_visual_candidates`, so the exact failure class that
  motivated this plan can remain even if cleanup prompts are managed.
- The raw-FPV budget guard is currently scoped to `camera-raw-fpv`. The latest
  failure was `camera-grounded-labels`, so label lanes still need lane-neutral
  observe/context budget protection.
- Operator-console MolmoSpaces SDK routes inherit the current default profile
  and therefore can accidentally run unmanaged `baseline`.

## Implementation Choices

These choices are the Roboclaws plan. They are separate from the research
survey above.

### Architecture And ADR Boundaries

`agent_sdk_perf_profile` is an OpenAI Agents SDK runtime profile, not a new
public launch axis. Public launch grammar remains `surface`, `world`, `backend`,
`intent` or `preset`, `agent_engine`, `provider_profile`, `evidence_lane`, and
`camera_labeler`. The runtime profile may be selected explicitly by CLI,
environment, or metadata for comparison, but product and operator-console routes
should not expose a normal profile picker.

The camera-grounded composite tool is compatible with ADR-0132 only under the
perception/source-output boundary:

- acceptable: collapse the model-visible `observe -> declare_visual_candidates`
  pair into one SDK-private observe+label tool result for
  `camera-grounded-labels`;
- required: preserve the underlying `observe` and `declare_visual_candidates`
  trace/report events and public evidence;
- forbidden: hide cleanup action selection, task memory, destination choice,
  private scoring truth, or a promoted cleanup macro behind the composite tool.

This plan does not need a new ADR for the first implementation because the
selected work is execution-shaped: resolve runtime profile defaults, migrate old
profile ids, rerender prompts, and add guards/tests. Create or update an ADR only
if a later slice promotes `agent_sdk_perf_profile` into a durable public command
surface, enables provider-native compaction as an accepted architecture layer, or
changes MCP/tool contracts beyond the SDK-private perception bridge already
covered by ADR-0126 and ADR-0132.

### Profile Contract

- Keep exactly two accepted profile ids:
  - `context_managed_v1`
  - `baseline`
- Default profile resolution to `context_managed_v1`.
- Keep `baseline` passable only through explicit CLI, environment, or metadata.
- Reject removed ids loudly:
  - `gpt_compact_v1`
  - `mimo_compact_v1`
  - `raw_fpv_budgeted_v1`
  - `custom`
- Do not add compatibility aliases. Migrate in-repo callers, docs, and tests.
- Keep direct field overrides for experiments where they already exist, but do
  not represent them as a public `custom` profile.

### Managed Profile Defaults

`context_managed_v1` should resolve to one profile id with provider/lane-aware
payload fields:

```text
agent_sdk_perf_profile:
  schema: agent_sdk_perf_profile_v1
  profile_id: context_managed_v1
  context_policy:
    source_level_tool_output_reduction: true
    deterministic_model_input_compaction: true
    provider_native_compaction:
      mode: off
  continuation_mode: state_summary_only
  context_soft_limit_tokens: provider-aware
  context_hard_limit_tokens: provider-aware
  model_input_compaction:
    enabled: true
    modes:
      - public_tool_result_summary_v1
      - repeated_metric_map_delta_v1
      - camera_grounded_history_v1
      - raw_fpv_image_memory_v1 when lane/provider supports image input
  camera_grounded_composite_tools:
    enabled: true
    applies_to: camera-grounded-labels
  max_observe_per_waypoint: 1
  raw_fpv_candidate_budget: lane-specific
  raw_fpv_repeated_failure_limit: lane-specific
  done_retry_budget: bounded
```

Provider-aware ceilings stay inside this payload. They must not create separate
public profile ids. A smaller effective-window provider gets lower soft/hard
defaults than a larger one, and hard-limit classification remains Roboclaws
owned.

`context_policy` is telemetry/configuration inside the resolved runtime profile.
It is not an agent-facing capability profile, MCP profile, or eval-harness
baseline group.

### Route And Intent Scope

`context_managed_v1` applies to every OpenAI Agents SDK live route unless the
caller explicitly selects `baseline`:

- MolmoSpaces cleanup;
- MolmoSpaces open-ended household tasks;
- MolmoSpaces MapBuild;
- Agibot MapBuild.

Some managed fields are route-specific in effect. For example, incomplete-turn
continuation does not apply to a one-turn runner in the same way it applies to
the MolmoSpaces cleanup runner. The resolver should still return one
`context_managed_v1` payload, and each runner should apply the fields it
actually owns while preserving the same profile identity and telemetry shape.

### Provider-Native Compaction

Do not enable provider-native compaction in the first implementation.

Represent it as an explicit future field only:

```text
provider_native_compaction:
  mode: off | responses_server_compaction_v1
  threshold_tokens
  provider_capability
  proof_artifact
```

Turning it on later requires provider-specific proof that complete artifacts
remain present, hard-limit checks still fire before provider rejection, context
metrics remain attributable, and no private truth or credentials become
model-visible.

### Camera-Grounded Labels

For `camera-grounded-labels`, `context_managed_v1` should use the composite
tool by default:

```text
observe_camera_grounded_candidates
```

This is a model-context optimization, not a hidden task macro. The server must
continue to preserve the underlying `observe` and `declare_visual_candidates`
trace/report events.

The prompt/profile path should stop asking the model to use the old
`observe -> declare_visual_candidates` cadence when the composite tool is
enabled.

For `preset=map-build`, this requires a map-build-specific prompt path. It is
not enough to rerender cleanup prompts. The camera-grounded MapBuild prompt must
tell the model to call `observe_camera_grounded_candidates` after navigating to
each public inspection waypoint when the composite tool is enabled, while still
preserving the MapBuild rule that no cleanup/manipulation tools are allowed.

### Model-Input Compaction

Use the existing `RunConfig.call_model_input_filter` path as the deterministic
compaction hook.

Managed defaults should:

- keep complete artifacts outside model context;
- keep the first full `metric_map` model-visible and summarize repeated maps;
- retain recent actionable camera-grounded outputs and summarize older ones;
- keep only the latest full raw-FPV frame model-visible when image memory is
  enabled, summarizing older frames by public observation id, byte count, hash,
  and policy;
- write aggregate compaction metrics without persisting raw prompts, model
  text, full tool payload bodies, image payloads, credentials, or private truth.

Broad compaction remains guarded by tests because earlier I/N/AB evidence
showed that token reduction alone can regress behavior.

### Continuation And Hard Limits

`context_managed_v1` uses `state_summary_only` continuation by default.

Soft limit:

- switch to compact continuation state before replaying any broad prompt;
- never replay full raw-FPV or camera-grounded observation history.

Hard limit:

- fail fast with `provider_context_budget_exceeded` or
  `provider_context_failure`;
- do not silently retry with `baseline`;
- do not silently raise the budget;
- preserve provider/model/context metrics needed to explain the failure.

### Budget Guards

Generalize the current budget guard shape beyond raw-FPV:

- lane-neutral max observe per waypoint;
- lane-neutral context budget terminal checks;
- lane-specific raw-FPV candidate budget;
- lane-specific raw-FPV repeated candidate failure fingerprints.

The prior UI failure was `camera-grounded-labels`, so the managed profile must
protect label-lane MapBuild loops, not only `camera-raw-fpv`.

## Phased Execution Plan

### Phase 1: Profile Resolver Contract

Change `openai_agents_perf_profile.py` so:

- default resolves to `context_managed_v1`;
- explicit `baseline` resolves unchanged as unmanaged comparison behavior;
- removed profile ids fail with actionable errors;
- direct field overrides still work against the selected profile;
- resolved payload includes `context_policy` with
  `provider_native_compaction.mode=off`.

Update CLI help text to name only `context_managed_v1` and `baseline`.

### Phase 2: Managed Defaults

Implement `context_managed_v1` defaults:

- provider-aware soft/hard context limits;
- `state_summary_only` continuation;
- bounded continuations and done retry;
- model-input compaction enabled;
- repeated map delta compaction enabled;
- camera-grounded history compaction enabled;
- camera-grounded composite tool enabled for `camera-grounded-labels`;
- camera-grounded MapBuild prompt rendering that uses the composite cadence
  when the managed profile enables it;
- raw-FPV image memory and candidate budgets enabled only for raw-FPV-capable
  lanes/providers.

Keep `baseline` as the existing unmanaged behavior.

### Phase 3: Budget Guard Generalization

Generalize budget classification so label lanes get protection too:

- preserve existing raw-FPV terminal reasons;
- add lane-neutral observe/context budget classification;
- ensure hard-limit failure can happen before another continuation or broad
  observation loop.

### Phase 4: Operator-Console And Launch Surfaces

Make product/operator-console SDK routes inherit the managed default.

Acceptance here is not that the UI exposes a new profile dropdown. It should
not. Normal UI routes should be managed by default; `baseline` remains an
explicit CLI/env/metadata path for comparison.

Also migrate in-repo live/eval callers that can pass
`--agent-sdk-perf-profile` or `ROBOCLAWS_OPENAI_AGENTS_PERF_PROFILE`. Historical
status packets and old artifact manifests may keep old profile names as
evidence history, but runnable commands, active tests, and current docs should
not require removed profile ids.

### Phase 5: Cleanup Tests And Docs

Update tests, docs, and in-repo examples:

- replace old managed ids with `context_managed_v1`;
- keep historical artifact mentions only where they describe past evidence;
- add rejection tests for removed ids;
- add tests proving default product/operator-console paths no longer select
  unmanaged baseline.

## Acceptance Criteria

SUCCESS requires all of:

- default OpenAI Agents SDK profile resolves to `context_managed_v1`;
- explicit `baseline` resolves and preserves unmanaged behavior;
- removed profile ids fail loudly without aliases;
- `context_managed_v1` enables deterministic model-input compaction and compact
  continuation by default;
- `camera-grounded-labels` managed runs enable
  `observe_camera_grounded_candidates` and rerender stale two-step prompts;
- MolmoSpaces MapBuild `camera-grounded-labels` managed prompts use the
  composite observe+label cadence and do not keep instructing the old
  `observe -> declare_visual_candidates` pair;
- Agibot MapBuild uses the same resolver contract and does not retain old
  profile ids as accepted managed profiles;
- raw-FPV budgets remain lane-specific inside `context_managed_v1`;
- label lanes have lane-neutral observe/context budget protection;
- operator-console MolmoSpaces SDK routes do not accidentally launch unmanaged
  `baseline`;
- no complete trace/report/runtime-map/image artifacts are removed to save
  model tokens.

No regressions:

- `baseline` remains available for explicit A/B comparison;
- provider route compatibility and model validation still fail loudly;
- existing `done` / `run_result.json` success boundary remains unchanged;
- private truth, credentials, raw prompts, model text, and full tool payloads
  are not persisted in new profile or compaction telemetry.

## Verification

Recommended deterministic gates:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/agents/test_live_runtime.py \
  tests/unit/agents/test_household_cleanup_prompts.py \
  tests/unit/agents/test_openai_agents_model_input_config.py \
  tests/unit/agents/test_openai_agents_budget_sources.py \
  tests/unit/operator_console/test_routes.py \
  tests/unit/operator_console/test_launcher.py

.venv/bin/ruff check \
  scripts/molmo_cleanup/openai_agents_perf_profile.py \
  scripts/molmo_cleanup/openai_agents_budget.py \
  scripts/molmo_cleanup/run_live_openai_agents_cleanup.py \
  roboclaws/agents/drivers/openai_agents_model_input.py \
  roboclaws/agents/prompts/household_cleanup.py \
  roboclaws/operator_console/routes.py \
  tests/unit/agents/test_live_runtime.py \
  tests/unit/agents/test_household_cleanup_prompts.py \
  tests/unit/agents/test_openai_agents_model_input_config.py \
  tests/unit/agents/test_openai_agents_budget_sources.py \
  tests/unit/operator_console/test_routes.py \
  tests/unit/operator_console/test_launcher.py

.venv/bin/ruff format --check \
  scripts/molmo_cleanup/openai_agents_perf_profile.py \
  scripts/molmo_cleanup/openai_agents_budget.py \
  scripts/molmo_cleanup/run_live_openai_agents_cleanup.py \
  roboclaws/agents/drivers/openai_agents_model_input.py \
  roboclaws/agents/prompts/household_cleanup.py \
  roboclaws/operator_console/routes.py \
  tests/unit/agents/test_live_runtime.py \
  tests/unit/agents/test_household_cleanup_prompts.py \
  tests/unit/agents/test_openai_agents_model_input_config.py \
  tests/unit/agents/test_openai_agents_budget_sources.py \
  tests/unit/operator_console/test_routes.py \
  tests/unit/operator_console/test_launcher.py
```

Required product/local-live proof after code changes:

```bash
just dev::network-status

just run::surface \
  surface=household-world \
  world=molmospaces/val_0 \
  backend=mujoco \
  preset=map-build \
  agent_engine=openai-agents-sdk \
  provider_profile=codex-router-responses \
  evidence_lane=camera-grounded-labels \
  camera_labeler=grounding-dino \
  scenario_setup=baseline \
  seed=7
```

If live/provider proof cannot run, record the concrete blocker from guarded
preflight/status output. Do not claim the behavior fully complete with only
unit tests when launch/runtime behavior changed.

If Agibot map-build runner behavior changes, add either a focused mocked
runner test or a concrete hardware/GDK blocker. Do not require physical Agibot
hardware for this MolmoSpaces context-management plan unless the code change
touches Agibot backend execution semantics beyond profile resolution and
metadata propagation.

## Stop Gates

Stop for review if:

- enabling provider-native compaction is required to pass tests or live proof;
- a managed default would remove complete MCP traces/reports/images/runtime-map
  artifacts;
- a provider requires a different public profile id;
- `baseline` would need to remain default for product/operator-console routes;
- hard-limit handling can only be implemented by silently falling back or
  raising budgets.

## Entropy Review Result

Selected mode: plan entropy mode.

Why: the target is a concrete implementation plan, and the risk is unclear
scope, stale profile surfaces, and proof gaps before execution.

Discovery intensity: saturation scan.

Selected candidates:

1. P0: MapBuild prompt path must be first-class.

   Demand gate: pass. The failing run was MapBuild, but the draft plan mostly
   described cleanup prompt rerendering. Without an explicit MapBuild prompt
   requirement, implementation could make cleanup managed while leaving
   MapBuild camera-grounded runs on the old double-history cadence.

   Resolution: add route/intent scope, map-build prompt requirements,
   acceptance, and prompt tests.

2. P1: Agibot map-build runner shares the resolver.

   Demand gate: pass. Removing old profile ids and changing the default affects
   both MolmoSpaces and Agibot SDK runners. The plan must prevent an
   implementation from updating only the cleanup runner.

   Resolution: add Agibot runner to scope and acceptance, with mocked proof or
   hardware-blocker evidence instead of mandatory physical proof.

3. P1: In-repo caller migration must distinguish runnable callers from
   historical evidence.

   Demand gate: pass. Search shows old profile names in tests, active runners,
   and historical status packets. The plan needs to preserve historical truth
   while removing old ids from runnable commands and active tests.

   Resolution: add migration guidance for live/eval callers and historical
   artifact carve-out.

4. P2: Verification needed prompt tests, not only runtime/profile tests.

   Demand gate: pass. The double-history issue can survive if prompt rendering
   is not checked directly.

   Resolution: add `test_household_cleanup_prompts.py` and prompt source files
   to deterministic gates.

Parked observations:

- Provider-native compaction remains off. No further planning is needed until a
  provider-specific proof is proposed.
- Exact provider-aware token ceilings are implementation defaults as long as
  hard-limit fail-fast and profile telemetry are preserved.

## Grill Batch Result

Decision-impact audit result: no more user discussion is needed before
preflight/execution.

Assumptions verified from docs/code:

- `ARCHITECTURE.md` keeps public launch axes small and treats provider/model
  routing separately from runtime strategy.
- ADR-0132 rejects promoted cleanup composites, but permits this plan's boundary
  when the composite is SDK-private perception output shaping and trace
  preserving.
- ADR-0126 already accepts model-declared observations as the public bridge from
  camera evidence to cleanup handles.
- ADR-0139 keeps MapBuild as a `surface=household-world preset=map-build`
  route, so MapBuild prompt rendering must be included directly instead of
  inheriting cleanup-only prompt fixes.
- ADR-0145 says baseline/profile groups should be purposeful and shrinkable,
  which supports removing old overlapping profile ids and keeping `baseline`
  explicit-only.

Resolved boundaries:

- `agent_sdk_perf_profile` remains SDK runtime configuration, not a public launch
  axis, capability profile, or eval-harness profile.
- `context_managed_v1` is the default product/operator-console runtime profile;
  `baseline` is explicit-only comparison and failure-reproduction behavior.
- `observe_camera_grounded_candidates` is a perception source-level reduction for
  model context, not a cleanup macro. It must not choose cleanup targets,
  destinations, task completion, or private scoring behavior.
- Provider-native compaction remains off. Enabling it later is contract-shaped
  enough to require separate proof and likely ADR review.

Remaining items are implementation defaults, not grill questions:

- exact provider-aware soft/hard token ceilings;
- exact aggregate telemetry field names, as long as private prompts, model text,
  full tool payloads, image payloads, credentials, and private truth are not
  persisted;
- whether Agibot proof is a mocked runner test or a concrete hardware/GDK
  blocker when only profile resolution/metadata propagation changes.

## Preflight Contract

Preflight status: DRAFT
Task source: user prompt plus `docs/research/09-agent-context-management-research.md`
Canonical source: `docs/plans/2026-07-02-openai-agents-context-management-optimization.md`
Route: durable `$intuitive-flow`
Goal: Implement the two-profile OpenAI Agents SDK context-management contract with `context_managed_v1` as the default and `baseline` explicit-only.

Scope:

- Profile resolver, CLI help, runtime metadata, budget guards, operator-console launch defaults, and focused tests/docs.

Non-goals:

- No provider-native compaction enablement.
- No new public profile ids.
- No compatibility aliases for removed profile ids.
- No hidden cleanup macro or private-truth shortcut.
- No broad provider/model bake-off.

Entity budget:

- reuse=`openai_agents_perf_profile.py`, `openai_agents_model_input.py`, `openai_agents_budget.py`, existing composite tool, existing operator-console route catalog;
- remove/merge=old profile ids into `context_managed_v1`;
- new=no new runtime module expected;
- expansion triggers=provider-native compaction, new public profile id, new artifact contract, or UI-exposed profile picker.

Context:

- must-read=`docs/research/09-agent-context-management-research.md`, this plan, `scripts/molmo_cleanup/openai_agents_perf_profile.py`, `scripts/molmo_cleanup/openai_agents_budget.py`, `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py`, `roboclaws/agents/drivers/openai_agents_model_input.py`, `roboclaws/operator_console/routes.py`;
- useful=`docs/plans/live-agent-runtime-sdk-perf-followups.md`, `docs/status/active/live-agent-runtime-sdk-spike.md`;
- avoid-unless-needed=historical output artifacts and broad provider matrices.

Acceptance:

- SUCCESS: acceptance criteria above plus deterministic gates and required product/local-live proof or explicit blocker evidence.
- BLOCKED_NEEDS_DECISION: none currently.
- BLOCKED_NEEDS_LOCAL_VALIDATION: required live/provider proof unavailable after code changes.
- INTERMEDIATE_ONLY: none unless explicitly approved.
- No regressions: `baseline` explicit-only A/B still works, complete artifacts remain intact, success still requires MCP `done` / `run_result.json`.

Verification:

- deterministic=pytest and ruff gates listed above;
- integration=operator-console route/launcher tests and profile/budget tests;
- product-run=MapBuild `camera-grounded-labels` command listed above;
- local-live-manual=provider/network/MuJoCo availability via `just dev::network-status`, provider readiness, and run artifacts;
- optional=repeat with `evidence_lane=world-public-labels` for lower-cost sanity if provider capacity allows.

Execution:

- main=root session supervises and judges final complete/blocked status;
- worker=none by default;
- worker-goal=none.

To execute:

```text
/goal execute docs/plans/2026-07-02-openai-agents-context-management-optimization.md with intuitive-flow
```

Approval: LGTM/approve/go ahead approves; edits request revision.
