---
plan_scope: vlm-direct-sidecar-and-openclaw-status-cleanup
status: IMPLEMENTED
created: 2026-06-12
last_reviewed: 2026-06-12
execution_mode: implemented-with-openclaw-local-validation-required
source:
  - user request to finish cleanup after AI2-THOR/direct-VLM retirement
  - intuitive-reduce-entropy audit on current launch, visual-grounding, and OpenClaw surfaces
  - user clarification to widen the audit before deleting code
  - intuitive-preflight contract for the formal cleanup pass
related_context:
  - docs/plans/refactor-retire-ai2thor-vlm-direct.md
  - docs/plans/2026-06-11-household-map-launch-open-ended-contracts.md
  - docs/adr/0136-use-base-navigation-map-and-first-class-household-launch-contracts.md
  - docs/adr/0138-use-detector-only-visual-grounding-sidecar.md
---

# VLM Direct Sidecar And OpenClaw Status Cleanup

## Current Finding

Implemented 2026-06-12: the repo has removed the old `agent_engine=vlm-policy`
and AI2-THOR direct VLM demo stack from the public launch catalog, and the
visual-grounding sidecar now uses a detector-only active contract. Hosted VLM
refiner/direct-producer routes are retired from active code, command examples,
tests, and benchmark promotion logic. OpenClaw remains guarded and
validation-required until an off-work-network Gateway proof runs.

2026-06-12 clarification: this document started as a pre-implementation
contract, then became the closeout record for the formal cleanup pass. The
audit biased toward finding the largest current surface area first, because the
previous retirement pass removed only part of the old VLM/direct shape.

2026-06-12 grill-batch decisions:

- Keep the visual-grounding HTTP sidecar, but make the active current contract
  detector-only.
- Remove VLM `refiner` and `direct_producer` active routes. Keep `proposer`
  request metadata temporarily, but define it as detector/adapter metadata only.
  A later refactor may rename it to `adapter` or `producer` if the contract
  expands again.
- Replace the old hosted-VLM ADR with a short detector-only ADR. ADR-0133 is
  archived as superseded context; ADR-0138 is the current decision.
- Preserve Gemini as parked historical knowledge, not active runtime code.
- Keep OpenClaw code and private recipes, but mark current OpenClaw routes as
  validation-required until off-work-network proof runs.
- Remove `script-runner` from the public `agent_engine` surface. Planner-proof
  should use `direct-runner` or private harness recipes instead of a
  user-facing script engine.
- Include ADR surface cleanup in this formal cleanup. The current ADR root
  should retain only decisions that still constrain implementation; historical
  or superseded records belong under `docs/adr/archive/**`.

Current non-VLM camera labelers that should remain:

- `sim-projected-labels`
- `fake-http`
- `contract-fake`
- `grounding-dino`
- `yoloe`
- `yolo-world`
- `omdet-turbo`

Current VLM or hosted vision-language routes that should be removed from active
code/docs/tests unless a future plan explicitly reintroduces them:

- camera labelers:
  - `grounding-dino+mimo-v2.5`
  - `yoloe+mimo-v2.5`
  - `grounding-dino+qwen3-vl`
  - `mimo-v2.5-direct`
  - `qwen3-vl-direct`
- sidecar adapter/provider slots:
  - `mimo-v2.5`
  - `qwen3-vl`
  - `xiaomi/mimo-v2.5`
  - `vertex_ai/gemini-3.1-flash-lite-preview`
  - `vertex_ai/gemini-3-flash-preview`
  - `tongyi/qwen3-vl-flash`
  - `tongyi/qwen3-vl-plus`
  - `siliconflow/Qwen/Qwen3-VL-8B-Instruct`
- benchmark promotion concepts:
  - `proposer_plus_refiner`
  - `direct_vlm`
  - `best_direct_vlm_pipeline_id`
  - `max_direct_vlm_pipelines`

OpenClaw is different. Keep OpenClaw code and private recipes, but mark the
route as validation-required/degraded until it is tested off the work network
with the current household-world contract.

MiMo, Gemini, Qwen, and other image-capable models are different again when they
are used as coding-agent/provider profiles. Do not remove text or multimodal
provider registry support for Codex, Claude Code, OpenAI Agents SDK, or
OpenClaw just because visual-grounding direct/refiner routes are being retired.
The target here is VLM-as-camera-labeler/direct-producer/refiner logic, not the
general model provider layer.

## 2026-06-12 Wide Entropy Scan

Selected mode: repo entropy mode.

Why: the repo still has multiple live surfaces that imply hosted
VLM-refiner/direct-producer visual grounding is current, even though the desired
architecture is now detector sidecar plus coding-agent/Agent SDK/OpenClaw task
execution.

### Candidate 1: Active VLM camera-labeler values still resolve

Severity: P1

Entropy source: stale public surface and false confidence.

Materiality: launch validation, `just` recipe validation, and tests still treat
VLM refiner/direct camera labelers as supported. A future maintainer can follow
current command surfaces and revive a route that the product direction wants to
retire.

Affected paths:

- `roboclaws/household/profiles.py`
- `just/molmo.just`
- `just/agent.just`
- `tests/contract/dev_tools/test_task_agent_just_recipes.py`
- `tests/contract/visual_grounding/test_visual_grounding_service.py`
- `tests/contract/visual_grounding/test_visual_grounding_benchmark.py`

Evidence:

- `CAMERA_LABELERS` includes `grounding-dino+mimo-v2.5`,
  `yoloe+mimo-v2.5`, `grounding-dino+qwen3-vl`, `mimo-v2.5-direct`, and
  `qwen3-vl-direct`.
- `just/molmo.just` and `just/agent.just` whitelist the same values.
- Contract tests currently assert these values produce refiner/direct-producer
  stages instead of asserting rejection.

Suggested cleanup:

- Remove hosted VLM camera labeler aliases from current validation.
- Add negative coverage showing retired camera labelers are rejected.
- Preserve non-VLM labelers: `sim-projected-labels`, `fake-http`,
  `contract-fake`, `grounding-dino`, `yoloe`, `yolo-world`, `omdet-turbo`.

Owner skill: `$intuitive-refactor`.

Zen hint: one obvious camera-labeler set is better than parallel historical
choices that still run.

Pattern hint: no new pattern; direct deletion and negative tests are clearer.

### Candidate 2: Real sidecar still has hosted VLM provider logic

Severity: P1

Entropy source: stale adapter surface and paid-provider risk.

Materiality: `scripts/visual_grounding/adapters.py` still owns provider-prefixed
Gemini/MiMo/Qwen/SiliconFlow/Tongyi slots, hosted auth/env routing, OpenAI
chat-completions requests, direct-producer response generation, refiner
response generation, token/cost telemetry, and hosted error handling. This is
real behavior, not only old docs.

Affected paths:

- `scripts/visual_grounding/adapters.py`
- `scripts/visual_grounding/serve_visual_grounding_service.py`
- `tests/contract/visual_grounding/test_visual_grounding_service.py`

Evidence:

- Adapter catalog includes roles `refiner_or_direct_producer` and
  `direct_producer`.
- Hosted provider slots include `mimo-v2.5`, `qwen3-vl`,
  `xiaomi/mimo-v2.5`, `vertex_ai/gemini-*`, `tongyi/qwen3-vl-*`, and
  `siliconflow/Qwen/Qwen3-VL-8B-Instruct`.
- Real adapter code still calls hosted VLM JSON over chat-completions for both
  `refiner` and `direct_producer` tasks.

Suggested cleanup:

- Remove hosted visual-grounding provider specs and hosted VLM HTTP call path
  from this sidecar.
- Keep local detector proposer adapters: Grounding DINO, YOLOE, YOLO-World,
  and OmDet-Turbo.
- Keep generic HTTP sidecar client/server contract for detector outputs.

Owner skill: `$intuitive-refactor`.

Zen hint: explicit detector sidecar beats hidden provider branches in the same
adapter registry.

Pattern hint: strategy registry remains useful for detector adapters, but
hosted VLM strategies should be deleted rather than re-abstracted.

### Candidate 3: The request/benchmark contract remains refiner-shaped

Severity: P1

Entropy source: public contract drift.

Materiality: even after deleting hosted providers, the Visual Grounding Service
contract and benchmark harness still encode `proposer`/`refiner` as first-class
request concepts. If left unchanged, tests and future agents will keep treating
refiners as a current extension point.

Affected paths:

- `roboclaws/household/visual_grounding.py`
- `roboclaws/household/realworld_contract.py`
- `roboclaws/household/agibot_map_build_mcp_server.py`
- `scripts/visual_grounding/run_visual_grounding_benchmark.py`
- `scripts/visual_grounding/check_visual_grounding_benchmark_result.py`
- `scripts/visual_grounding/serve_fake_visual_grounding.py`
- `tests/unit/molmo_cleanup/test_visual_grounding.py`
- `tests/contract/visual_grounding/`

Evidence:

- `VisualGroundingClientConfig` has `proposer_id`, `proposer_model_id`,
  `refiner_id`, and `refiner_model_id`.
- `visual_grounding_request(...)` accepts both `proposer` and `refiner`.
- `realworld_contract.py` passes both blocks into every camera-grounding
  request.
- Benchmark promotion still selects `best_proposer_plus_refiner_pipeline_id`
  and `best_direct_vlm_pipeline_id`.
- The checker requires `max_direct_vlm_pipelines == 1`, making old direct-VLM
  promotion a passing condition.

Suggested cleanup:

- Decide the new detector-only request shape before implementation:
  - minimum cleanup: remove `refiner` and direct-producer promotion while
    keeping a `proposer` block for detector runtime/model parameters; or
  - stronger cleanup: rename `proposer` to `producer` / `adapter` so the
    current contract no longer preserves the old proposer/refiner taxonomy.
- Update fake service behavior so contract-fake cannot silently validate
  retired direct/refiner semantics.
- Simplify benchmark promotion to `sim` plus proposer-only detector candidates.

Owner skill: `$intuitive-refactor` with architecture review.

Zen hint: current contract vocabulary should say what the system now does.

Pattern hint: a small pipeline/adapter data table is enough; a multi-stage
pipeline abstraction is now too broad for the current scope.

### Candidate 4: Current human docs still recommend or explain retired routes

Severity: P1

Entropy source: human source-of-truth drift.

Materiality: the human docs still describe hosted VLM refiner/direct-producer
routes as current comparison targets, including runnable commands. This is the
highest-risk rediscovery path for future humans and agents.

Affected paths:

- `docs/human/molmospaces-settings.md`
- `docs/human/molmospaces-visual-grounding-results.md`
- `docs/human/molmospaces-cleanup-mode-architecture.md`
- `just/README.md`
- `docs/human/agent-task-command-taxonomy.md`
- `ARCHITECTURE.md`
- `docs/adr/archive/superseded/0133-use-http-visual-grounding-service-for-real-camera-labels.md`
- `docs/adr/0138-use-detector-only-visual-grounding-sidecar.md`

Evidence:

- `molmospaces-settings.md` lists hosted VLM camera labelers and commands such
  as `camera_labeler=grounding-dino+mimo-v2.5`.
- `just/README.md` includes benchmark examples for
  `yoloe+mimo-v2.5`, `grounding-dino+mimo-v2.5`, and `qwen3-vl-direct`.
- `molmospaces-cleanup-mode-architecture.md` names proposer-plus-refiner and
  optional direct VLM routes as planned values.
- ADR-0133 still says Qwen3-VL/MiMo can be compared as refiners and optional
  direct producers under the HTTP service.

Suggested cleanup:

- Keep current docs detector-first: DINO/YOLOE/YOLO-World/OmDet plus fake/sim.
- Move hosted/direct VLM information to a short retired/historical subsection,
  not current command examples.
- ADR-0133 is archived as superseded historical context. ADR-0138 is the
  current short decision: keep the HTTP sidecar boundary, retire hosted VLM
  refiner/direct-producer routes from the active visual-grounding contract.

Owner skill: `$intuitive-doc` plus `$intuitive-refactor` for code references.

Zen hint: current docs should be a small truth surface, not a memory of every
experiment.

Pattern hint: no pattern; doc-tier separation is clearer.

### Candidate 5: Gemini needs a parked memory, not active code

Severity: P2

Entropy source: recurring rediscovery risk.

Materiality: Gemini produced strong historical image/video/data-labeling
intuition and the direct `Grounding DINO + Gemini 3 Flash` cleanup row improved
exact matches from 3/10 to 8/10 on the 2026-05-26 matrix. If all current routes
are deleted with no note, future maintainers may forget why Gemini is worth
revisiting later.

Affected paths:

- `docs/human/molmospaces-visual-grounding-results.md`
- `docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md`
- optional later backlog surface such as `TODOS.md`

Evidence:

- Gemini direct-producer did not beat DINO proposer-only in the RAW_FPV
  benchmark, but Gemini as a refiner improved one direct cleanup run
  materially.
- Current DINO base-recall later reached the same scene-0 cleanup quality
  without hosted VLM, so Gemini is not a current dependency.

Suggested cleanup:

- Preserve a compact retired evidence note:
  - Gemini direct-producer: not current, weaker than DINO on available
    benchmark.
  - Gemini refiner: historically promising for quality, too slow/token-heavy
    for the current lean architecture.
  - Future reintroduction condition: only after the core architecture is stable,
    with a fresh explicit plan and a small on-demand/offline labeling use case.
- Do not keep active Gemini sidecar provider code solely for memory.

Owner skill: `$intuitive-doc`.

Zen hint: parked knowledge is better than live accidental surface area.

Pattern hint: no pattern; a short parked note is enough.

### Candidate 6: `script-runner` and `openclaw-gateway` are still public engine axes

Severity: P1 for status drift; P2 for implementation cleanup.

Entropy source: launch-axis ambiguity.

Materiality: `ARCHITECTURE.md`, `just/README.md`, `agent_engines.py`, and
launch error messages still expose `script-runner` and `openclaw-gateway` as
public engines. The user intent is to keep OpenClaw code but mark it as
validation-required, while script-style routes may no longer be part of the
current architecture.

Affected paths:

- `roboclaws/launch/agent_engines.py`
- `roboclaws/launch/catalog.py`
- `just/agent.just`
- `just/README.md`
- `docs/human/agent-task-command-taxonomy.md`
- `docs/human/openclaw/*.md`
- `roboclaws/agents/provider_registry.py`
- `tests/contract/dev_tools/test_task_agent_just_recipes.py`

Evidence:

- Before cleanup, `AGENT_ENGINE_SPECS` included `script-runner`.
- Before cleanup, launch error text expected
  `codex-cli|claude-code|openai-agents-sdk|direct-runner|openclaw-gateway|script-runner`.
- Current decision: `script-runner` is removed from public agent-engine specs,
  planner-proof intent/task dispatch support, docs, and launch error hints.
- OpenClaw provider route status is `experimental`, not clearly
  validation-required.

Suggested cleanup:

- Keep `script-runner` removed from public `agent_engine` specs.
- Current evidence: `script-runner` is a provider-less dispatch alias for
  `driver=script`. It is not used by `household-world`; it is currently allowed
  on `planner-proof` and lowers to planner-proof bundle runner paths with
  `mode=dry-run|execute-rerun`.
- Keep any required script execution as private `harness::*` plumbing for
  planner-proof.
- Keep OpenClaw code and private recipes, but expose status as
  validation-required/degraded in docs and route metadata if the current status
  vocabulary supports it.
- Keep work-network guard unchanged; do not claim OpenClaw is healthy until an
  off-work-network Gateway proof runs.

Owner skill: `$intuitive-refactor` plus `$intuitive-doc`.

Zen hint: public launch axes should be stable current choices, not every
internal runner.

Pattern hint: no pattern; route metadata/status should be explicit.

### Candidate 7: Current vs historical plan/ADR surfaces need a boundary

Severity: P2

Entropy source: workflow/documentation drift.

Materiality: older plans and ADRs legitimately record VLM/direct/refiner
experiments. Deleting all mentions would erase useful evidence, but leaving
current human docs and accepted ADRs unmarked makes future agents treat old
experiments as active design.

Affected paths:

- `docs/adr/archive/superseded/0133-use-http-visual-grounding-service-for-real-camera-labels.md`
- `docs/adr/0138-use-detector-only-visual-grounding-sidecar.md`
- `docs/plans/molmospaces-http-visual-grounding-service.md`
- `docs/plans/2026-06-11-adaptive-target-inspection.md`
- `docs/retrospectives/molmospaces-http-visual-grounding-service.md`
- `docs/human/molmospaces-visual-grounding-results.md`

Suggested cleanup:

- Mark older VLM/refiner/direct planning evidence as historical or superseded
  by this cleanup plan.
- Do not deep-edit `.planning/**`, retrospectives, or `output/**` just to purge
  old words.
- Add one short current pointer from the relevant human doc to this cleanup
  plan once implementation is approved.

Owner skill: `$intuitive-doc`.

Zen hint: history should remain history; current truth should be unmistakable.

Pattern hint: no pattern; status labels and doc-tiering are enough.

## Explicit Non-Targets From The Wide Scan

Do not remove these in the VLM-sidecar cleanup:

- MiMo / Kimi / MiniMax / Codex provider registry entries used by coding agents.
- `XM_LLM_*`, `MIMO_TP_KEY`, `KIMI_API_KEY`, `MM_*`, or provider redaction logic
  outside visual-grounding sidecar routes.
- CI live report matrix entries using MiMo as a coding-agent model.
- `camera-raw-fpv` as an evidence lane or ablation route, unless maintainers
  explicitly decide raw-FPV visual reasoning is also outside current scope.
- Vendored upstream MolmoSpaces Gemini references under `vendors/`.
- Historical `.planning/**`, `docs/retrospectives/**`, `docs/status/active/**`,
  and `output/**` evidence solely because they mention VLM.

## Zoom-Out Map

```text
household-world cleanup/map-build/open-ended
  -> evidence_lane=camera-grounded-labels
       -> camera_labeler
            keep: sim/fake/detector proposer labelers
            remove: hosted VLM refiner/direct producer labelers
       -> Visual Grounding Service
            keep: HTTP sidecar contract, fake/contract fake, local detector adapters
            remove: hosted VLM provider config, request call path, direct/refiner promotion

agent engines
  keep: codex-cli, claude-code, openai-agents-sdk, direct-runner
  review/remove public axis: script-runner, unless planner-proof still needs it
  keep but mark validation-required: openclaw-gateway
```

## Preflight Contract

Preflight status: APPROVED_AND_EXECUTED

Task source: mixed user prompt, reduce-entropy audit, grill-batch decisions, and
preflight review.

Canonical source: `docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md`.

Route: durable `$intuitive-flow`, with `$intuitive-refactor` discipline for the
code deletion / stale-surface cleanup slice and `$intuitive-doc` discipline for
human/source-of-truth updates.

Goal: remove active hosted VLM refiner/direct-producer visual-grounding routes,
while preserving detector labelers, generic coding-agent provider routing, and
OpenClaw code marked validation-required.

Scope:

- Remove hosted VLM camera labelers/providers/refiner/direct-producer semantics
  from current code, command validation, benchmark promotion, tests, and active
  docs.
- Keep detector/fake/sim labelers:
  `sim-projected-labels`, `fake-http`, `contract-fake`, `grounding-dino`,
  `yoloe`, `yolo-world`, and `omdet-turbo`.
- Keep the visual-grounding HTTP sidecar, but make the active contract
  detector-only.
- Keep `proposer` temporarily as detector-only adapter metadata; remove
  `refiner`, `direct_producer`, `proposer_plus_refiner`, and `direct_vlm`
  active concepts.
- Preserve a compact Gemini parked note: Gemini remains historically strong for
  image/video understanding and data labeling, but is not current runtime code.
- Keep OpenClaw code and private recipes, but mark OpenClaw routes
  validation-required until off-work-network Gateway proof exists.
- Keep `script-runner` removed from the public `agent_engine` surface; planner
  proof should use `direct-runner` or private harness recipes.
- Clean ADR/current-doc surfaces so ADR-0138 owns detector-only sidecar status
  and ADR-0133 / old VLM records live only as archived or historical evidence.

Non-goals:

- Do not remove Grounding DINO, YOLOE, YOLO-World, OmDet-Turbo, fake HTTP, or
  contract fake camera labelers.
- Do not remove the visual-grounding HTTP sidecar itself.
- Do not delete historical `.planning/**`, retrospectives, old output
  artifacts, or old benchmark evidence solely because they mention VLM.
- Do not delete generic text/model provider routing used by Codex, Claude Code,
  OpenAI Agents SDK, OpenClaw text routes, model matrix docs, or coding-agent
  cleanup.
- Do not delete OpenClaw code, bootstrap scripts, or private `just openclaw::*`
  recipes in this slice.
- Do not perform live OpenClaw validation on the work network.
- Do not promote OpenAI Agents SDK or OpenClaw to default/public-stable status.
- Do not erase Gemini historical evidence; reduce it to parked/historical
  knowledge instead of active runtime surface.

Context:

must-read=`README.md`, `ARCHITECTURE.md`, `STATUS.md`, `AGENTS.md`,
`CLAUDE.md`, this plan, `docs/plans/refactor-retire-ai2thor-vlm-direct.md`,
`docs/plans/2026-06-11-household-map-launch-open-ended-contracts.md`,
`roboclaws/household/profiles.py`, `roboclaws/household/visual_grounding.py`,
`scripts/visual_grounding/adapters.py`,
`scripts/visual_grounding/run_visual_grounding_benchmark.py`,
`scripts/visual_grounding/check_visual_grounding_benchmark_result.py`,
`tests/contract/visual_grounding/`, `just/README.md`, `just/agent.just`,
`just/molmo.just`, `just/harness.just`, `roboclaws/launch/agent_engines.py`,
`roboclaws/launch/intents.py`, `roboclaws/launch/catalog.py`,
`docs/human/molmospaces-settings.md`,
`docs/human/molmospaces-visual-grounding-results.md`,
`docs/human/model-route-verdicts.yaml`, and `docs/human/model-matrix.md`.

useful=`docs/plans/refactor-mimo-v25-migration.md`,
`docs/plans/visual-grounding-gpu-sidecar-benchmark.md`,
`docs/plans/molmospaces-http-visual-grounding-service.md`,
`docs/retrospectives/molmospaces-http-visual-grounding-service.md`,
`docs/human/openclaw/local.md`, `docs/human/openclaw/gateway-internals.md`,
`just/openclaw.just`, and `scripts/openclaw/openclaw-bootstrap.sh`.

avoid-unless-needed=`.planning/**`, `output/**`, `.tmp/**`, and old generated
reports.

Acceptance:

- SUCCESS:
  - current code no longer exposes hosted VLM refiner/direct producer
    `camera_labeler` values;
  - visual-grounding adapter catalog no longer lists hosted VLM providers or
    `refiner_or_direct_producer` / `direct_producer` roles;
  - benchmark promotion output no longer contains `best_direct_vlm_pipeline_id`,
    `max_direct_vlm_pipelines`, or proposer-plus-refiner slots;
  - current human docs and `just/README.md` no longer recommend hosted VLM
    refiner/direct producer routes as active choices;
  - current ADR root is slim and does not keep superseded VLM/AI2-THOR records
    as active architecture decisions;
  - OpenClaw remains available only as guarded validation-required route, with
    docs explaining work-network validation has not been done recently;
  - public household and planner-proof routes still resolve.
- BLOCKED_NEEDS_DECISION:
  - maintainers want to preserve any VLM refiner/direct route as active
    benchmark code rather than historical evidence;
  - OpenClaw route status needs a product label not representable by current
    metadata.
- BLOCKED_NEEDS_LOCAL_VALIDATION:
  - OpenClaw validation cannot be closed on the work network; any claim that
    OpenClaw is healthy requires off-work-network Docker/Gateway proof.
- INTERMEDIATE_ONLY:
  - acceptable only if the VLM code deletion lands but OpenClaw validation
    status updates are parked for a follow-up.
- No regressions:
  - `camera_labeler=grounding-dino|yoloe|yolo-world|omdet-turbo|fake-http|contract-fake`
    remain valid for `evidence_lane=camera-grounded-labels`;
  - `camera_labeler=sim-projected-labels` remains the deterministic control;
  - `camera-raw-fpv`, `world-oracle-labels`, and `world-public-labels` lanes
    remain unchanged;
  - Codex, Claude Code, OpenAI Agents SDK, direct-runner, MuJoCo, Isaac Lab,
    Agibot GDK, and planner-proof current routes remain resolvable.
  - `agent_engine=script-runner` remains rejected by the public launch catalog.

Verification:

- deterministic:

```bash
.venv/bin/ruff check \
  roboclaws/household/profiles.py \
  scripts/visual_grounding/adapters.py \
  scripts/visual_grounding/run_visual_grounding_benchmark.py \
  scripts/visual_grounding/check_visual_grounding_benchmark_result.py \
  roboclaws/launch/agent_engines.py \
  roboclaws/launch/intents.py

.venv/bin/ruff format --check \
  roboclaws/household/profiles.py \
  scripts/visual_grounding/adapters.py \
  scripts/visual_grounding/run_visual_grounding_benchmark.py \
  scripts/visual_grounding/check_visual_grounding_benchmark_result.py \
  roboclaws/launch/agent_engines.py \
  roboclaws/launch/intents.py
```

- focused tests:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/contract/visual_grounding \
  tests/contract/dev_tools/test_task_agent_just_recipes.py \
  tests/contract/dev_tools/test_code_just_recipes.py \
  tests/contract/mcp/test_semantic_profiles.py \
  tests/unit/operator_console
```

- integration:

```bash
ROBOCLAWS_JUST_TRACE=1 just run::surface \
  surface=household-world world=molmospaces/val_0 backend=mujoco \
  intent=cleanup agent_engine=direct-runner \
  evidence_lane=camera-grounded-labels camera_labeler=grounding-dino

ROBOCLAWS_JUST_TRACE=1 just run::surface \
  surface=household-world world=molmospaces/val_0 backend=mujoco \
  intent=cleanup agent_engine=direct-runner \
  evidence_lane=camera-grounded-labels camera_labeler=mimo-v2.5-direct

ROBOCLAWS_JUST_TRACE=1 just run::surface \
  surface=planner-proof world=planner-proof/default backend=mujoco \
  intent=planner-proof agent_engine=direct-runner mode=dry-run
```

The first trace should succeed, the second should fail with an unsupported
camera labeler, and the planner-proof route should still resolve through the
accepted current engine shape.

Also trace that `agent_engine=script-runner` is rejected by the public launch
catalog.

- product-run:

```bash
just agent::harness molmo-visual-grounding-benchmark pipeline=grounding-dino
```

Run with a real sidecar only when local dependencies and model weights are
available. Contract-fake/fake-http smoke may be used for CI-safe shape checks.

- local-live-manual:

```bash
just dev::network-status
```

If the result is `network: work`, do not run OpenClaw Gateway. Off the work
network, a separate validation issue or follow-up plan should run:

```bash
just run::surface \
  surface=household-world world=molmospaces/val_0 backend=mujoco \
  intent=cleanup agent_engine=openclaw-gateway \
  provider_profile=<supported-profile> evidence_lane=world-oracle-labels
```

- optional:

```bash
just agent::harness agent-validation recommend \
  plan=docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md \
  budget=focused
just agent::harness agent-validation execute \
  plan=docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md \
  budget=focused
```

Execution: main=supervise the decision boundary, prevent accidental removal of
non-VLM detector labelers or coding-agent provider routes, and update this plan
if a route proves still current; worker=optional focused worker for the
visual-grounding code/tests lane; worker-goal=remove active hosted VLM
refiner/direct-producer support from visual-grounding code/tests while
preserving proposer-only labelers.

To execute:

```text
/goal execute docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md with intuitive-flow
```

Approval: `LGTM`, `approve`, `go ahead`, or equivalent approves this contract;
edits request revision.

## Implementation Evidence

Status: IMPLEMENTED with OpenClaw local validation still required.

Implemented 2026-06-12:

- removed hosted VLM visual-grounding camera labelers from active
  `camera_labeler` validation;
- removed visual-grounding request/config `refiner` fields and active hosted VLM
  provider/refiner/direct-producer sidecar code;
- kept detector/fake/sim labelers:
  `sim-projected-labels`, `fake-http`, `contract-fake`, `grounding-dino`,
  `yoloe`, `yolo-world`, and `omdet-turbo`;
- simplified benchmark promotion to `sim` plus one detector-only proposer
  pipeline and updated the checker to reject retired promotion slots;
- updated contract tests with negative coverage for retired refiner/direct
  routes;
- updated current human docs and `just/README.md` to recommend detector-only
  routes and keep Gemini/MiMo/Qwen evidence historical/parked;
- marked `openclaw-gateway` metadata and local docs as `validation-required`;
- preserved generic MiMo/Kimi/Codex/OpenAI/OpenClaw provider routing outside
  visual grounding.

Verification run:

```bash
.venv/bin/python -m py_compile scripts/visual_grounding/adapters.py scripts/visual_grounding/run_visual_grounding_benchmark.py scripts/visual_grounding/check_visual_grounding_benchmark_result.py scripts/visual_grounding/serve_fake_visual_grounding.py roboclaws/household/visual_grounding.py roboclaws/household/realworld_contract.py roboclaws/launch/agent_engines.py roboclaws/operator_console/routes.py tests/contract/visual_grounding/test_visual_grounding_service.py tests/contract/visual_grounding/test_visual_grounding_benchmark.py tests/unit/operator_console/test_routes.py
.venv/bin/ruff check roboclaws/household/profiles.py roboclaws/household/visual_grounding.py roboclaws/household/realworld_contract.py scripts/visual_grounding/adapters.py scripts/visual_grounding/run_visual_grounding_benchmark.py scripts/visual_grounding/check_visual_grounding_benchmark_result.py scripts/visual_grounding/serve_fake_visual_grounding.py roboclaws/launch/agent_engines.py roboclaws/operator_console/routes.py tests/contract/visual_grounding/test_visual_grounding_service.py tests/contract/visual_grounding/test_visual_grounding_benchmark.py tests/unit/operator_console/test_routes.py
.venv/bin/ruff format --check roboclaws/household/profiles.py roboclaws/household/visual_grounding.py roboclaws/household/realworld_contract.py scripts/visual_grounding/adapters.py scripts/visual_grounding/run_visual_grounding_benchmark.py scripts/visual_grounding/check_visual_grounding_benchmark_result.py scripts/visual_grounding/serve_fake_visual_grounding.py roboclaws/launch/agent_engines.py roboclaws/operator_console/routes.py tests/contract/visual_grounding/test_visual_grounding_service.py tests/contract/visual_grounding/test_visual_grounding_benchmark.py tests/unit/operator_console/test_routes.py
./scripts/dev/run_pytest_standalone.sh -q tests/contract/visual_grounding tests/unit/molmo_cleanup/test_visual_grounding.py tests/contract/molmo_cleanup/test_molmo_realworld_contract.py tests/unit/operator_console/test_routes.py tests/contract/dev_tools/test_task_agent_just_recipes.py tests/contract/dev_tools/test_code_just_recipes.py tests/contract/mcp/test_semantic_profiles.py
ROBOCLAWS_JUST_TRACE=1 just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco intent=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
ROBOCLAWS_JUST_TRACE=1 just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco intent=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=mimo-v2.5-direct
ROBOCLAWS_JUST_TRACE=1 just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=direct-runner mode=dry-run
ROBOCLAWS_JUST_TRACE=1 just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=script-runner mode=dry-run
just dev::network-status
.venv/bin/python scripts/visual_grounding/serve_visual_grounding_service.py --pipeline fake-http --host 127.0.0.1 --port 18880
just agent::harness molmo-visual-grounding-benchmark pipeline=fake-http base_url=http://127.0.0.1:18880 timeout_s=5
just agent::harness agent-validation recommend plan=docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md budget=focused
```

Results:

- static checks and focused tests passed;
- accepted `camera_labeler=grounding-dino` trace resolved;
- retired `camera_labeler=mimo-v2.5-direct` trace failed as unsupported;
- planner-proof resolved with `agent_engine=direct-runner`;
- `agent_engine=script-runner` failed as unsupported;
- fake visual-grounding benchmark passed when pointed at a running fake sidecar;
- `just dev::network-status` reported `network: work`, so OpenClaw Gateway
  validation was not run by policy;
- adaptive validation recommendation artifact:
  `output/agent-validation-matrix/20260612T131418Z/validation_matrix.html`.

Remaining parked gate:

- Run a separate off-work-network OpenClaw Gateway household cleanup proof before
  calling OpenClaw healthy or stable.

## Settled Defaults

- Clean all visual-grounding current-surface candidates in one implementation
  pass, and keep OpenClaw status as a final lightweight docs/metadata slice if
  needed.
- Keep `proposer` temporarily as detector-only metadata and remove `refiner` /
  `direct_producer` active routes. Rename to `adapter` or `producer` only in a
  later contract refactor if the sidecar expands again.
- `script-runner` is no longer a public `agent_engine`; use `direct-runner` or
  private harness recipes for planner-proof.
- Keep historical VLM results only as explicitly retired evidence, not in
  current recommendation tables.
- Keep a compact Gemini parked note in the current plan and either `TODOS.md`
  or a retired section of `molmospaces-visual-grounding-results.md`.
- Mark OpenClaw as `validation-required` or the closest existing status, and
  keep work-network guards unchanged.
- ADR root cleanup is included. Keep only current implementation-constraining
  ADRs in `docs/adr/`; historical and superseded ADRs live under
  `docs/adr/archive/**`.

## Suggested Implementation Order

0. Add negative tests for VLM camera labelers, adapter catalog absence, and
   benchmark promotion absence.
1. Remove VLM labeler aliases from `roboclaws/household/profiles.py` and just
   recipe validation.
2. Delete hosted VLM adapter/provider code from `scripts/visual_grounding/adapters.py`.
3. Remove request-contract `refiner` metadata and keep `proposer` as
   detector-only provenance unless a separate contract refactor is approved.
4. Simplify visual-grounding benchmark promotion and checker policy to
   proposer-only.
5. Update fake service and visual-grounding tests so contract-fake cannot keep
   retired direct/refiner semantics alive.
6. Update docs and examples, including Gemini retired/parked wording and
   ADR-0138 pointers.
7. Mark OpenClaw status as validation-required and document the off-work-network
   validation gate.
8. Run focused verification and stale-token searches.
