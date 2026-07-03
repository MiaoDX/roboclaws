# MolmoSpaces Settings Matrix

This is the operator-facing map for MolmoSpaces cleanup demo settings. Use it
to choose the right run shape before making project-status claims.

## Canonical Status Demo

For the current project-status artifact, prefer:

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=world-public-labels seed=7 scenario_setup=relocate-cleanup-related-objects relocation_count=5
```

That public command resolves to the current MolmoSpaces/RBY1M cleanup shape:

```text
contract=realworld_cleanup_v1
public_backend=mujoco
implementation_backend=molmospaces_subprocess
perception_mode=visible_object_detections
include_robot=true
record_robot_views=true
robot_name=rby1m
static_fixture_projection_mode=room_only
primitive_provenance=api_semantic
```

It produces a real MolmoSpaces/RBY1M cleanup report with Agent View, Private
Evaluation, Score, Semantic Substeps, and Robot View Timeline. The timeline
contains FPV, chase, map, and verification images when the backend can capture
robot views.

Current robot-view render defaults are intentionally conservative:
FPV/chase/verify/snapshot images render at `540 x 360`, while map images render
through a separate `620 x 420` report path. Do not raise the cleanup or RAW_FPV
default resolution casually: visual-grounding corpora, bbox coordinates,
latency, and image-token cost all depend on the frame size. Use the dedicated
renderer comparison path for visual A/B checks before changing defaults.

Do not use the synthetic dogfood kit as the main status artifact. It is useful
for fast contract checks, but it has no robot camera timeline.

## Main Axes

| Axis | Values | Meaning | Status Claim |
|------|--------|---------|--------------|
| Contract | `realworld_cleanup_v1` | ADR-0003 public/private-safe surface. No `scene_objects`, no target list. | Target contract for demos. |
| Backend | `api_semantic_synthetic` | Fast in-process semantic state mutation. | CI/smoke shape, not real visual proof. |
| Backend | `molmospaces_subprocess` | Real upstream MolmoSpaces/MuJoCo scene. | Required for real visual evidence. |
| Perception | `visible_object_detections` | Agent gets robot-local observed handles, categories, boxes, and support estimates. | Current best cleanup-success mode. |
| Perception | `raw_fpv_only` | Agent gets FPV observation artifact, no structured detections before declaration. | Camera evidence contract plus Model-Declared Observation cleanup path for image-capable agents. |
| Perception | `camera_model_policy` | Raw FPV observation first, then camera-derived candidates become observed handles. | Internal producer mode behind `evidence_lane=camera-grounded-labels`, using the shared Model-Declared Observation schema. |
| Visuals | `--include-robot --record-robot-views` | Capture RBY1M robot-view timeline. | Required for FPV/chase/map/verification report. |
| Visuals | omitted | No robot-view timeline. | Fast smoke only. |
| Map bundle | `assets/maps/molmospaces/<scene_source>/<scene_index>` | Selected prebuilt Nav2-shaped static map bundle for the exact scene. | Default for non-smoke Molmo lanes. Missing bundles fail before cleanup startup. |
| Map bundle | `map_bundle=<path-or-assets-id>` | Operator override for a prepared environment bundle. | Fails before cleanup startup if missing or invalid. |
| Static fixture projection artifact | `room_only` | Public room-level static fixture projection in map/report artifacts. | Current default artifact shape; not an active MCP tool. |
| Static fixture projection artifact | `exact_fixtures` | Easier exact static fixture projection. | Historical/debug artifact only. |
| Provenance | `api_semantic` | Cleanup tools mutate simulator semantic state. | Current normal cleanup loop. |
| Provenance | `planner_backed` | Cleanup subphase has matching RBY1M/CuRobo proof. | Future strict manipulation target. |

## Scene Sampler Defaults

The operator console uses the source-aware MolmoSpaces sampler for its default
household scene rail. The visible first-slice UI set is intentionally small and
is selected by a deterministic seeded-random policy that prefers distinct public
room counts within each source. The current UI set is
`molmospaces/val_0`, `molmospaces/procthor-10k-val/11`,
`molmospaces/procthor-10k-val/15`,
`molmospaces/procthor-objaverse-val/0`,
`molmospaces/procthor-objaverse-val/1`, and
`molmospaces/procthor-objaverse-val/10`. `molmospaces/val_0` is the legacy
alias for `scene_source=procthor-10k-val`, scene index `0`. Existing launch
aliases such as `molmospaces/val_1`, `val_3`, `val_4`, `val_7`, and `val_9`
remain explicitly launchable as `procthor-10k-val` aliases, but they are hidden
from the default console scene rail unless admitted by the sampler.

The eval stress projection is broader than the UI projection. It currently
admits six prepared `procthor-10k-val` samples
(`0`, `10`, `11`, `12`, `13`, `15`) and ten prepared
`procthor-objaverse-val` samples (`0`, `1`, `4`, `5`, `7`, `10`, `11`, `12`,
`13`, `14`). `procthor-10k-val` remains partial until more rows clear scanner
gates. `ithor` and `holodeck-objaverse-val` are rejected exhausted under the
current public-room/actionability gates, not waiting on an implicit download
step. `ithor` candidate evidence for indices `1..12` and
`holodeck-objaverse-val` candidate evidence for indices `0..19` fail with
`fewer_than_three_public_navigation_areas`, so they should not be scanned again
without new human curation or an intentional gate change.

After any scene-catalog or map-bundle change, run:

```bash
.venv/bin/python scripts/operator_console/check_scene_catalog_sync.py
```

If it fails, it prints the exact scene-sampler fixture or preview asset that is
out of sync. The guard intentionally does not rewrite unrelated household eval
suites such as cleanup, map-build consumer, or open-ended goals; those move only
when their own sample contracts change.

The readiness exporter also writes
`scene_sampler_candidate_profile.json`, a metadata-first worklist for all four
scene groups. This profile does not admit scenes and does not download assets;
it separates the current evidence (`ithor` `1..12` and
`holodeck-objaverse-val` `0..19` rejected) from the next lightweight curation
step. For rejected-exhausted sources it recommends a small seeded source-scoped
set of unprofiled candidate world ids to inspect before any manual download or
scanner product-smoke run.

`procthor-10k-val` means the `val` split of the `procthor-10k` scene family; it
does not mean that Roboclaws has ten thousand validation scenes ready. Sampler
admission requires reviewable preview artifacts, at least three public
rooms/navigation areas, waypoint coverage, and source or prepared-manifest room
category provenance. Heuristic room-label parsing and room-count fallbacks may
seed review candidates, but they do not satisfy sampler admission.

## Semantic Contract Profile

`household_world` is the task-neutral MCP contract profile for household
world evidence. Cleanup skills compose it with `household_manipulation` and
`household_episode` when they need tools such as `navigate_to_object`,
`pick`, `place`, and `done`; the user's instruction, for example "clean the
room", remains a Task Prompt that the agent plans over those capabilities.

The profile is public-agent metadata only. It must not expose generated mess
sets, acceptable destinations, private manifests, hidden target lists,
`is_misplaced`, private scoring truth, or full simulator inventory oracles.
Demo recipes such as
`just run::surface surface=household-world preset=cleanup ...` choose a run
shape; they are not whole-task MCP tools.

## Model-Declared Camera Bridge

The Model-Declared Observation bridge lets a camera inference producer turn
public FPV evidence into public `observed_*` handles without exposing private
scoring truth. It applies to both camera evidence lanes:

| Evidence lane | Producer | Declaration timing |
|---------|----------|--------------------|
| `camera-raw-fpv` | Main cleanup agent reasoning over FPV image blocks. | Inline only: call `navigate_to_visual_candidate` when acting on a candidate. |
| `camera-grounded-labels` | Separate camera inference producer, detector, or deterministic harness producer selected by `camera_labeler`. | Producer registration: call `declare_visual_candidates` after an observation. |

`camera-raw-fpv` deliberately has no separate pre-registration strategy in normal
agent runs. That keeps the live image-agent loop close to the operator's mental
model: observe a raw camera frame, choose one plausible cleanup object, navigate
to it, then pick and place it. Explicit registration remains useful for
`camera-grounded-labels`, where perception and cleanup selection are separate roles.
In minimal-map `camera-raw-fpv`, omit `target_fixture_id`; use the
`candidate_fixture_id` and `recommended_tool` returned by
`navigate_to_visual_candidate`.

The declaration evidence should include source observation id, category, target
fixture id, evidence note, image region, producer metadata, grounding status,
and recovery hints. Unresolved declarations may appear in reports but should be
blocked from `pick`.

## Camera Labeler Axis

`evidence_lane=camera-grounded-labels` describes the input contract.
`camera_labeler` is the public producer axis. It is translated at the runner or
server boundary into the internal Visual Grounding Service pipeline id recorded
as report provenance.

| Camera labeler | Meaning | Implementation Status |
|----------|---------|-----------------------|
| `grounding-dino` | Deterministic simulator-state labels projected through camera visibility into reviewable camera candidates. | Current control producer. |
| `grounding-dino` | Contract-test HTTP service that returns deterministic public candidates. | First implementation phase. |
| `grounding-dino` | Bbox-first open-vocabulary proposer over RAW_FPV images. | Conservative first proposer target. |
| `yoloe` | YOLO-family promptable/open-vocabulary proposer over RAW_FPV images. | Proposer speed/latency comparison target. |
| `yolo-world` | YOLO-World open-vocabulary proposer over RAW_FPV images. | YOLO-family comparison target. |
| `omdet-turbo` | Transformers OmDet-Turbo open-vocabulary proposer over RAW_FPV images. | First-wave non-YOLO comparison target; current supported checkpoint is `omlab/omdet-turbo-swin-tiny-hf`. |

Hosted multimodal refiner and direct-producer labelers are retired from the
active camera-labeler axis. ADR-0138 keeps the HTTP sidecar boundary
detector-only; old hosted-model results are historical/parked evidence only.

Recommended command shape for current pipeline comparison:

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=yoloe
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=yolo-world
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=omdet-turbo
```

`yolo-custom` is not an active pipeline. Without a planned cleanup-ontology
training set or supplied weights, it would only add dead configuration surface;
use `yoloe` or `yolo-world` for YOLO-family open-vocabulary probes.

For non-sim pipelines, Roboclaws should call an External Visual Grounding
Service behind `declare_visual_candidates`. The agent should not receive service
URLs, credentials, image filesystem paths, or model-host details. HTTP failures
must be recorded as pipeline failures; they must not silently fall back to
simulator labels unless `camera_labeler=grounding-dino` was selected.

`camera_labeler` is selected when launching the runner/server, not passed as a
cleanup MCP tool argument. The runner/server records the internal
`visual_grounding_pipeline_id` for service provenance. Agents should continue to call
`declare_visual_candidates(observation_id)` after `observe`; the server decides
whether empty candidate registration uses `sim` or the configured HTTP pipeline.
Explicit candidate declarations remain manual Model-Declared Observations and
should not trigger the external producer.

The first service request format should send JSON with base64 image bytes.
Shared filesystem image paths are allowed inside benchmark harness internals,
but not as the formal service contract. Use `VISUAL_GROUNDING_TIMEOUT_S`
defaulting to 20 seconds; inference timeouts should record pipeline failure
evidence rather than retrying. If `VISUAL_GROUNDING_API_KEY` is set, send it as
a bearer token and redact it from reports.

Keep model-heavy grounding code in sidecar service dependencies, not in the core
cleanup runtime. The repo may host the sidecar service code and fake pipeline,
but real Grounding DINO, YOLOE, YOLO-World, and OmDet probes should be explicit
local/dev setup steps. Do not implicitly download model weights in normal
cleanup, benchmark, or CI recipes. Treat YOLOE/YOLO-family adapters as optional
probes until licensing and redistribution boundaries are reviewed.

The first implementation slice covers fake HTTP plumbing, shared client
injection, report/checker metadata, and direct/MCP-smoke evidence. Full real
proposer benchmarking remains a later hard gate. The configurable sidecar has
an explicit `--adapter-mode real` path for proposer probes, but operators must
install model dependencies and weights deliberately in the sidecar environment
before using it. OpenAI Agents SDK live runs are useful best-effort confidence
checks for that slice, but direct and MCP-smoke fake HTTP runs are the hard
gates.

Hosted multimodal routes are not active visual-grounding sidecar dependencies.
Reintroduce any hosted refiner or direct-producer route only through a fresh
plan with a bounded offline/on-demand labeling use case; do not make those
providers part of normal cleanup, benchmark, or CI recipes.

Before promoting a real pipeline to the end-to-end cleanup matrix, run a
perception-isolated visual-grounding benchmark over fixed RAW_FPV observations.
Benchmark command shape:

```bash
just agent::harness molmo-visual-grounding-benchmark pipeline=grounding-dino
just agent::harness molmo-visual-grounding-benchmark pipeline=grounding-dino,yoloe,omdet-turbo
just agent::harness molmo-visual-grounding-benchmark \
  matrix=harness/visual_grounding/first_wave_gpu_sidecar_matrix.json \
  corpus=harness/visual_grounding/local_raw_fpv_corpus.json \
  base_url=http://127.0.0.1:18880 \
  timeout_s=60
just agent::harness molmo-visual-grounding-benchmark pipeline=grounding-dino
just agent::harness molmo-visual-grounding-benchmark pipeline=yoloe
just agent::harness molmo-visual-grounding-benchmark pipeline=omdet-turbo
```

That benchmark should compare candidate recall, false positives, duplicate
rate, category-family accuracy, bbox/overlay quality, destination-hint quality,
actionability proxy rate, structured-output parse failures, latency, and cost
without running the full cleanup loop.
Cost and memory fields are explicit telemetry slots: they show reported totals
when a sidecar stage provides token/cost or memory metadata, and otherwise say
that the service did not report that data.
The benchmark result also emits a capped end-to-end probe recommendation:
always include the `sim` control, then at most one detector-only proposer
pipeline. Treat fake-contract recommendations as artifact-shape evidence only
until real detector sidecar provenance is present for every selected non-sim
pipeline; a mixed fake/real recommendation still requires real reruns before
being used as a full cleanup probe.
The benchmark checker treats zero candidates as a valid poor-recall result when
`--require-success` is used; add `--require-candidates` only for deterministic
fake smoke tests that are expected to emit at least one candidate.

Keep the benchmark working set under `harness/visual_grounding/`. The initial
git-tracked smoke corpus is synthetic and validates artifact shape only; larger
image corpora and generated outputs should remain local or published artifacts.
Private labels in that harness are scoring data only and must not be returned
to the agent or grounding service.

To build a path-backed corpus from a stored cleanup run with RAW_FPV artifacts:

```bash
.venv/bin/python scripts/visual_grounding/build_visual_grounding_corpus_from_cleanup_run.py \
  output/molmo/<run>/seed-7 \
  --output harness/visual_grounding/local_raw_fpv_corpus.json
```

That single-run builder is automated, but it is intentionally narrow: it
exports one cleanup run's RAW_FPV observations. Use it for stable fixtures and
apple-to-apple reruns, not as the only evidence for model-family ranking.

For a more representative local benchmark corpus, generate a multi-run,
image-deduped sample from stored run artifacts:

```bash
.venv/bin/python scripts/visual_grounding/build_representative_visual_grounding_corpus.py \
  output \
  --output output/visual-grounding-corpora/representative-raw-fpv/representative_raw_fpv_corpus.json \
  --name representative-raw-fpv \
  --max-observations 96 \
  --min-raw-fpv 5
```

The representative builder scans for `run_result.json` files with RAW_FPV
artifacts and private evaluation, drops exact duplicate image hashes by
default, stratifies by room/category labels, and records source/dedupe
statistics in `sampling`. Keep its output under ignored `output/` unless a
specific published artifact is needed.

For model selection, prefer a fresh bbox-labeled MolmoSpaces corpus generated
from multiple scene indices:

```bash
.venv/bin/python scripts/visual_grounding/build_molmospaces_visual_grounding_bbox_corpus.py \
  --output output/visual-grounding-corpora/molmospaces-bbox-10x10/corpus.json \
  --name molmospaces-bbox-10x10 \
  --scene-source procthor-10k-val \
  --scene-indices 0-9 \
  --targets-per-scene 10 \
  --frame-classes target_focused_fpv
```

That builder actively creates MolmoSpaces scenes, focuses the robot FPV camera
on generated cleanup targets, and writes MuJoCo segmentation bbox truth as
private benchmark labels. Public requests still contain only the image, category
hints, static fixture projection, and non-target capture provenance. Use `--scene-indices 0
--targets-per-scene 2` for a cheap local smoke before a 10x10 run.

That builder copies the referenced RAW_FPV images next to the generated corpus
and derives room-level private category-presence labels from the run's private
evaluation. When MolmoSpaces mess-placement diagnostics are available, the
builder assigns each private label to the public room containing the initial
mess receptacle fixture, then falls back to the legacy object-id room suffix
only when that fixture provenance is unavailable. Those labels are benchmark
scoring data only; they are not included in service requests, predictions JSONL,
MCP responses, or Agent View payloads.

For real proposer probes, install optional sidecar dependencies and weights
explicitly into the dedicated sidecar environment. Product
`camera_labeler=grounding-dino` runs auto-start the local real-router sidecar
when the default `VISUAL_GROUNDING_BASE_URL` is not already reachable. The
sidecar defaults to DINO base recall (`IDEA-Research/grounding-dino-base`,
`box_threshold=0.25`, `text_threshold=0.20`, device and dtype `auto`).

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.venv-visual-grounding" \
  uv sync --project sidecars/visual-grounding --extra cuda --extra yoloe --extra omdet

.venv-visual-grounding/bin/python - <<'PY'
import torch, transformers, ultralytics
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("transformers", transformers.__version__)
print("ultralytics", ultralytics.__version__)
PY

.venv-visual-grounding/bin/python scripts/visual_grounding/serve_visual_grounding_service.py \
  --pipeline real-router --adapter-mode real

VISUAL_GROUNDING_YOLOE_MODEL_ID=yoloe-11s-seg.pt \
  .venv-visual-grounding/bin/python scripts/visual_grounding/serve_visual_grounding_service.py \
    --pipeline real-router --adapter-mode real

VISUAL_GROUNDING_OMDET_MODEL_ID=omlab/omdet-turbo-swin-tiny-hf \
  .venv-visual-grounding/bin/python scripts/visual_grounding/serve_visual_grounding_service.py \
    --pipeline real-router --adapter-mode real
```

The sidecar project intentionally does not change the core Roboclaws `.venv/`.
Use a local PyTorch CUDA index or mirror when needed; keep that machine-local
and out of committed project metadata.

The `camera-grounded-labels` product route runs a fail-fast readiness check
against the configured sidecar before starting the simulator or agent. A
contract-only `--pipeline grounding-dino` service that returns
`adapter_unavailable` is blocked up front; it should not be used as evidence for
cleanup or map-build behavior. Set
`ROBOCLAWS_AUTOSTART_VISUAL_GROUNDING_SIDECAR=0` to disable local auto-start.
Each product run records `visual_grounding_readiness.json` in its artifact
directory with the resolved stage status and model id.

To exercise only the HTTP contract without real model dependencies, start the
configurable service in its default mode. It should return explicit unavailable
evidence instead of fake candidates:

```bash
.venv/bin/python scripts/visual_grounding/serve_visual_grounding_service.py --pipeline grounding-dino
```

Current default: DINO base recall (`IDEA-Research/grounding-dino-base`,
`box_threshold=0.25`, `text_threshold=0.20`). The older tiny-recall result came
from category-presence scoring on historical frames; the bbox-aware 2026-05-27
benchmark ranked base-recall first. Current OmDet support uses Transformers'
built-in `OmDetTurboProcessor` and `OmDetTurboForObjectDetection`; the
previously listed base checkpoint is not a valid public model id, so the
first-wave matrix sweeps the tiny checkpoint with threshold variants instead.

The active sidecar contract is detector-only. Hosted refiner and direct-producer
probes that previously used chat-completions endpoints are parked historical
routes, not current setup steps. Generic model provider keys may still be used
by supported SDK live-agent routes; they are not visual-grounding camera labelers.

List the sidecar adapter slots without starting the server:

```bash
.venv/bin/python scripts/visual_grounding/serve_visual_grounding_service.py --list-adapters
```

The adapter catalog includes a redacted `runtime` readiness block for each
adapter. For local proposer adapters it reports importable dependencies such as
`torch`, `transformers`, and `ultralytics`; model weights remain unverified
until a real adapter run loads them.

Real proposer pipeline ids such as `grounding-dino` and `yoloe` report visible
`adapter_unavailable`, `missing_dependency`, or adapter-error failures unless
the service is started with `--adapter-mode real` with installed sidecar
dependencies and model weights. Legacy hosted refiner/direct-producer ids are
not active adapter slots. The
adapter catalog names the optional sidecar extra and current redacted runtime
readiness for each target adapter.

For real-robot deployment, extend the same benchmark with a fixed head-camera
seed set and edge latency measurements before selecting a proposer. Route
perception is a later extension: candidates discovered during navigation should
carry `discovered_during=navigation`, use short-term tracking before becoming
stable handles, and never block navigation primitives.

Intermediate proposals, rejected proposals, and overlays are diagnostic
evidence. Benchmark reports may show them in detail; normal cleanup reports
should show accepted candidates, pipeline summary, failure evidence, and overlay
links. They must not become MCP response fields or Agent View cleanup
candidates. For live `camera-grounded-labels` agents, prompts should only
instruct the agent to call `declare_visual_candidates` after `observe`; they should not
mention service URLs, credentials, image paths, or model-host details.

For the first live `camera-raw-fpv` agent gate, prefer semantic acceptability over
the exact hidden restoration score: require enough preferred/acceptable
placements, full sweep coverage, declaration-driven actions, and no structured
label leakage. Keep the exact private scorer in the report as diagnostic
evidence and use it for stricter regression/debug runs when exact target
agreement is the point of the test.

## Entrypoint Support

Not every entrypoint exposes every contract mode yet. Treat the matrix below as
the current source of truth before claiming a run supports a setting.

| Entrypoint | Visible Detections | Raw FPV Only | Camera Labels | Notes |
|------------|--------------------|--------------|---------------------|-------|
| `python -m roboclaws.household.household_world_episode` | yes | yes | yes | Deterministic household-world demo and checker path. The example path is only a thin wrapper. |
| `scripts/molmo_cleanup/run_molmo_realworld_agent_mcp_smoke.py` | yes | yes | yes | Dogfood/smoke wrapper used by several just recipes; uses model-declared simulated producers where camera-label declarations are exercised. |
| `python -m roboclaws.cli.agent_server household-world` | yes | yes | yes | Direct live-agent server CLI exposes raw-FPV declaration tools and supports the `camera_model_policy` declaration path. |
| `RealWorldCleanupContract` / `realworld_mcp_server` internals | yes | yes | yes | Internals use `declare_visual_candidates` and `navigate_to_visual_candidate` for camera evidence to handle registration. |

## Command Taxonomy

Use the public launch catalog for operator-facing runs:

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=<engine> evidence_lane=<lane>
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=map-build agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco agent_engine=openai-agents-sdk provider_profile=codex-router-responses prompt="find something useful to drink"
```

Use `agent::run` and lower `molmo::*` recipes only for maintainer debugging or
historical report reproduction:

```bash
just agent::run household-world <agent-engine-or-private-driver> <evidence-lane> task_intent=cleanup
```

| Axis | Values | Meaning |
|------|--------|---------|
| Driver | `direct` | Deterministic Python cleanup loop; no MCP server and no live LLM agent. |
| Driver | `mcp-smoke` | Deterministic script through ADR-0003 MCP tools; drives the same tool-call path but does not launch Codex or Claude. |
| Driver | `openai-agents-live` | Private implementation driver for `agent_engine=openai-agents-sdk`. |
| Preset | `smoke` | Synthetic contract sanity; world labels; semantic report. |
| Evidence lane | `world-public-labels` | MolmoSpaces/RBY1M report; agent receives structured detections without destination/tool oracle hints or pre-confirmed navigation permission. |
| Evidence lane | `camera-raw-fpv` | MolmoSpaces/RBY1M report; agent receives raw camera artifacts and no structured labels. |
| Evidence lane | `camera-grounded-labels` | MolmoSpaces/RBY1M report; agent receives camera-derived structured candidates produced by `camera_labeler`. |

Guarded smoke/live drivers are validation-required maintainer routes. Keep
them out of normal operator runbooks until their separate proof is green.

`verify::*` remains the confidence-gate namespace: it runs focused tests and then
delegates scenario execution to `harness::*`. `harness::*` remains the
lower-level implementation-rig namespace, useful when debugging a specific
script or checker. The `molmo::*` report recipes below are convenience wrappers
over the private household cleanup implementation runner; they are not a
separate public cleanup dispatcher.
All cleanup profiles require a selected prebuilt Base Metric Map bundle; the
facade resolves `map_bundle=auto` to
`assets/maps/molmospaces/<scene_source>/<scene_index>`, and `map_bundle=...`
accepts either a path or an environment id under `assets/maps`. Generate a scene
bundle with
`scripts/maps/generate_molmospaces_scene_bundles.py --scene <source>/<index> --force`
before launching a new scene; `map_bundle=none` is not a valid simulator path.

Convenience report recipes:

| Command | Expands To | Use It For |
|---------|------------|------------|
| `just molmo::quick-check` | `mcp-smoke smoke` | Cheap contract check; accepts `driver=` and `profile=` overrides. |
| `just molmo::review-report` | `direct world-public-labels` | Canonical human review/status report. |
| `just molmo::mcp-smoke-report` | `mcp-smoke world-public-labels` | Real visual MCP smoke without a live external agent. |
| `just molmo::camera-raw-report` | `direct camera-raw-fpv` | Camera-only observation evidence; not cleanup-success proof. |

The `driver=` and `profile=` tokens above are
private implementation-runner vocabulary. Prefer `agent_engine=...`,
`provider_profile=...`, and `evidence_lane=...` in new docs, plans, and user
runbooks.

For live SDK reports, repo-local `.env` keys are honored the same way as the
direct navigation demos. Normal users configure keys only; command shape
controls behavior.

```bash
XM_LLM_BASE_URL=https://api.llm.mioffice.cn/v1
XM_LLM_API_KEY=...
KIMI_API_KEY=...
```

SDK repo workflows default to `codex-router-responses` and require
`CODEX_BASE_URL` plus `CODEX_API_KEY` (`gpt-5.5`, Responses API). They do not
fall back to `mimo-mify-responses` when `XM_LLM_API_KEY` is present. To use
`mimo-mify-responses`, set `ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses`
explicitly; that profile uses `XM_LLM_API_KEY`, `xiaomi/mimo-v2.5`, Responses
API, and web search disabled. Retired `codex-cli` and `claude-code` engines are
not current public live-agent recipes. Guarded maintainer routes stay outside
normal hosted/current run guidance until their validation proof is green.

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=openai-agents-sdk provider_profile=codex-router-responses evidence_lane=world-public-labels seed=7 scenario_setup=relocate-cleanup-related-objects relocation_count=5
```

Probe a live SDK run without attaching:

```bash
just molmo::status
just molmo::status output/household/household-world/open-ended/openai-agents-live-world-public-labels/seed-7
```

The status probe reports elapsed time, MCP tool progress, and
`run_result.json` / `report.html` readiness. Interactive/operator MolmoSpaces
visual cleanup remains single-instance by default because each visual run owns a
MuJoCo-backed MolmoSpaces backend. If the requested MCP port is busy, the
launcher fails instead of silently starting another simulator on a different
port.

Eval-harness runs may select multiple visual cleanup rows:

```bash
just agent::eval execute \
  plan=docs/plans/2026-06-15-eval-harness-skill-entrypoint.md
```

The harness records relevant rows and reports local runtime blockers honestly.
Live SDK Molmo cleanup remains single-session by launcher policy; if one row is
active, later live rows are blocked rather than moved to a hidden port or
silently replaced by a cheaper substitute.

## Report Shapes

All Molmo cleanup demos should route through the shared cleanup report underlay
in `roboclaws/household/report.py`. Different settings only add or omit
sections.

| Shape | Required Settings | Expected Sections |
|-------|-------------------|-------------------|
| Synthetic cleanup smoke | `api_semantic_synthetic` | Summary, before/after, semantic substeps, score, advisory/private sections where available. No robot timeline. |
| Real visual cleanup | `molmospaces_subprocess`, `include_robot`, `record_robot_views` | Synthetic sections plus Robot View Timeline with FPV, top-down scene view, and verification. Base Metric Map preview and Runtime Metric Map evidence are rendered separately from scene imagery. |
| Raw FPV evidence | `perception_mode=raw_fpv_only`, robot views enabled | Raw FPV Observations plus visual timeline. No structured observed-object table before declaration. |
| Sanitized detector evidence | `evidence_lane=world-public-labels` | Structured detections with producer/source/actionability fields. Destination, tool selection, and navigation permission remain policy-required until source-FPV confirmation. |
| Model-declared camera cleanup | `camera-raw-fpv` or `camera-grounded-labels` with declaration evidence | Raw FPV Observations plus Model-Declared Observations and normal semantic cleanup sections. |
| Camera-label producer evidence | `evidence_lane=camera-grounded-labels` or `perception_mode=camera_model_policy` | Raw FPV observation evidence plus Model-Declared Observations with camera-labeler and internal visual-grounding pipeline provenance. |
| Planner proof attached | `--planner-proof-run-result ...` | Attached Planner Proof, Cleanup Primitive Gate, Planner Cleanup Bridge. |
| Proof bundle runner | proof-bundle runner script | Separate runner report with selected commands, proof results, blockers, grasp/task-feasibility evidence. |

## Recommended Recipes

Molmo operator recipes write runs under Shanghai-local timestamp folders:
`output/molmo/<recipe>/<MMDD_HHMM>/...`. Recipes place each seed below that
timestamp root, for example `output/molmo/review-report/0511_1628/seed-1/`.

Fast synthetic contract smoke:

```bash
just molmo::quick-check
```

Real visual status/review report:

```bash
just molmo::review-report
```

Render-only MuJoCo/Isaac scene camera comparison:

```bash
just molmo::scene-camera-comparison
```

The retired Genesis candidate lane is no longer runnable from this recipe. The
old Genesis reports remain historical renderer-parity evidence only.

This probe uses `roboclaws.camera_control.render_views` to drive MuJoCo and a
prepared Isaac USD with one external camera request. It
is for scene/camera review only: it does not run cleanup, pick/place, private
scoring, or pickup box annotation. The main lane now uses explicit canonical
`eye`/`target`/`up` poses in the MolmoSpaces scene frame for both backends.
Room-level views use MolmoSpaces room mesh world bounds, not MuJoCo mesh
`geom_size`, so the room camera starts from a real room scale. The report also
records camera-pose, camera-intrinsics, room-scale, lighting, color profile,
and USD-bounds residuals separately. MuJoCo canonical views convert the explicit
`eye`/`target` request into MuJoCo's free-camera azimuth/elevation convention
before rendering; the manifest records the backend pose used for the parity
check. The camera request also carries MuJoCo runtime render state separately
from legacy object-center positions, including articulated child joint names
and `qpos` values when MolmoSpaces exposes them. Isaac uses the
prepared USD's scene lights plus the configured soft fill profile and reports
both existing and added light counts. Target-vs-USD
diagnostics are bounds-aware: large receptacles may aim the camera above a
surface, so the report treats a target inside the USD XY footprint and within
the configured surface-aim height allowance separately from a true target/scene
frame mismatch. A passing camera-pose contract means the two backends accepted
the same render-camera API pose; material differences, renderer lighting, or
display color-management differences can still prevent full visual identity.

Real visual MCP smoke:

```bash
just molmo::mcp-smoke-report
```

Raw camera evidence:

```bash
just molmo::camera-raw-report
```

Live external-agent reports:

```bash
just molmo::codex-report
just molmo::claude-report
```

Guarded report recipes are maintainer-only validation routes; they are not part
of the normal current entrypoint set.
`claude-report` is blocked on the work network unless the repo-local `.env`
contains a supported MiMo or MiMo mify Anthropic key route. `codex-report`
may run on the work network with the repo-local `codex-router-responses` route configured in
`.env`, or with explicit `ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses` plus
`XM_LLM_API_KEY`. Run `just dev::network-status` first if you are unsure which
network you are on.

Planner proof-bundle dry run:

```bash
just harness::molmo-planner-proof-bundle-runner
```

Local strict proof/rerun attempt:

```bash
just harness::molmo-planner-proof-bundle-execute-rerun
```

## Current Boundaries

- A clean semantic cleanup run does not prove physical manipulation.
- `api_semantic` means the simulator state was updated through semantic tools.
- `raw_fpv_only` proves camera artifact plumbing and, for image-capable agents,
  the Model-Declared Observation cleanup path from FPV evidence to public
  handles.
- The `camera-raw-fpv` live success gate uses semantic acceptability because a tidy
  camera-derived placement can be correct for review while missing the generated
  exact target fixture.
- The 2026-06-08 scorer-only raw-FPV probe reached a scoreable 36-frame
  raw-only set covering all five generated targets, but CodexENV `gpt-5.5`
  still confirmed at most two unique coarse hidden targets. Keep pure
  `camera-raw-fpv` as a baseline/ablation lane and prefer
  `camera-grounded-labels` for the current live cleanup path. That conclusion is
  scoped to hidden-target recovery and live actionability; a clean-context
  RAW-FPV visual labeler is tracked separately as perception-only evidence.
- `camera_model_policy` remains internal metadata for deterministic simulated
  camera-label producer evidence under the shared Model-Declared Observation
  schema; it is not real pixel inference unless the producer is explicitly a
  detector route.
- The global planner cleanup bridge remains blocked until cleanup subphases are
  planner-backed for the required object/target bindings.
- Guarded maintainer viability and clean cleanup success are separate gates.

## Source Docs

- [ADR-0003](../adr/0003-separate-cleanup-agent-view-from-private-evaluation.md):
  public Agent View vs private evaluation.
- [ADR-0126](../adr/0126-bridge-camera-evidence-to-cleanup-handles-with-model-declared-observations.md):
  model-declared observations bridge camera evidence to cleanup handles.
- [ADR-0136](../adr/0136-use-base-metric-map-and-first-class-household-launch-contracts.md):
  current launch, map, intent, and evidence-lane contract.
- [ADR-0138](../adr/0138-use-detector-only-visual-grounding-sidecar.md):
  current detector-only visual-grounding sidecar boundary.
- [`domain.md`](domain.md): domain vocabulary and shipped-history notes.
