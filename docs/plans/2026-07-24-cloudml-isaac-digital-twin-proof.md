**Status:** Preflight draft ready for approval
**Created:** 2026-07-24
**Last reviewed:** 2026-07-24
**Current implementation contract:** Add a dedicated CloudML Isaac Lab capability and image,
then prove the existing `world=b1-map12 backend=isaaclab` route on one r49 worker through
ordered, stop-gated runtime, navigation, and MapBuild stages.
**Related ADRs:** ADR-0136 and ADR-0140; no new ADR unless implementation changes the public
world/backend contract or the durable CloudML placement policy.
**Supersedes / Superseded by:** Extends the CloudML execution plan and the completed local
B1/Isaac proof; it does not supersede either one.

## Plan Ledger

- Plan status: PROPOSED
- Session scope: cloudml-isaac-digital-twin-proof
- Parent plans:
  `docs/plans/2026-06-18-cloudml-juicefs-eval.md` and
  `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`
- Child plans: none
- Last updated: 2026-07-24
- Current slice: planning-loop and whole-plan preflight complete.
- Next action: approve the preflight contract, then execute the ordered phases through
  `$intuitive-flow`.
- Blocked on: no planning blocker. NVIDIA image acquisition or runtime execution requires explicit
  EULA authorization. Registry publication and each paid r49 submission require a separately
  scoped cost approval.
- Do not touch from this session: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware,
  physical movement, provider selection, eval scoring policy, or unrelated CloudML hybrid work.

## Preflight Contract

Preflight status: DRAFT

Task source: user request plus this planning-loop-reviewed plan.

Canonical source: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Route: durable `$intuitive-flow`; the root session owns phase ordering, approval gates, integration,
and final success/blocker judgment.

Goal: make the existing B1 / Map 12 Isaac Lab MapBuild route reproducible on CloudML r49 through a
pinned image, portable assets, explicit capability placement, and three separately accepted live
stages without changing ordinary MuJoCo baselines.

Scope:

- Freeze the accepted local Isaac/DINO runtime, commands, checker flags, portable asset closure,
  target resource budget, and per-stage cost envelope.
- Add one dedicated Isaac image identity and `cloudml-r49-isaac` capability while retaining the
  existing CPU MuJoCo and r49 DINO pools.
- Extend the existing content-addressed CloudML staging and worker boundary for Isaac inputs,
  runtime readiness, provenance, and run-owned outputs.
- Add three independent opt-in rows for generic runtime, B1 navigation, and the camera-grounded
  Grounding DINO MapBuild proof; accept each task before generating or submitting the next.
- Prove the frozen public B1 route on one non-preemptible r49 worker at a time and collect reports
  compatible with the strict accepted local gates.
- Keep repeatability/default promotion optional and separately approved after the first Stage C
  success.

Non-goals: no MolmoSpaces+Isaac restoration, digital-twin cleanup, CPU-only Isaac benchmark,
physical Agibot work, provider-backed agent run, public launch-axis change, new storage service,
transparent retry, routine-baseline inclusion, or preemptible/default promotion in the first proof.

Entity budget: reuse=Eval Harness row/catalog/plan lifecycle, current CloudML adapter and content
store, JuiceFS, run-owned output collection, existing Isaac/DINO commands and strict checkers;
remove/merge=keep one CloudML adapter, one content store, and existing-schema per-stage archives,
with no cross-task DAG or all-at-once executable profile; new=one pinned Isaac image identity, one
Isaac capability/pool, three opt-in row IDs, acceptance receipts, and the smallest portable asset
packaging helper required by the existing manifest boundary; expansion triggers=another GPU class
or Isaac version, typed manifest schema, provider credentials, distributed/multi-GPU execution,
sidecar/service boundary, public route change, cleanup enablement, or default/preemptible promotion
requires re-approval.

Context: must-read=this plan, `STATUS.md`, `ARCHITECTURE.md`,
`docs/agents/operating-runbook.md`, `docs/human/evaluation.md`,
`docs/plans/2026-06-18-cloudml-juicefs-eval.md`,
`docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`,
`skills/eval-harness/SKILL.md`, `skills/eval-harness/catalog/rows.json`,
`skills/eval-harness/scripts/eval_harness_cloudml.py`,
`roboclaws/evals/cloudml_task.py`, `roboclaws/evals/cloudml_content_store.py`,
`scripts/dev/run_cloudml_eval_worker.sh`, `just/harness.just`, and `just/molmo.just`;
useful=the accepted local B1 proof capsule and its exact artifacts, current CloudML CPU/GPU proof
reports, `Dockerfile.eval`, and focused tests named below; avoid-unless-needed=broad `output/` scans,
historical Isaac AOV/debug plans, shipped retrospectives, unrelated `.planning/` history, provider
incident logs, `TODOS.md`, and `THOUGHTS.md`.

Acceptance:

- SUCCESS: a pinned dedicated image and portable content-addressed inputs select only
  `cloudml-r49-isaac`; deterministic/dry-run gates pass; Stage A proves exact runtime identity and
  nonblank RTX rendering; Stage B proves staged B1 composition and navigation; Stage C proves 5/5
  waypoints, 25/25 DINO observations, 100 real robot-view images, Base and Runtime Metric Maps, and
  1.0 sweep coverage; every attempt has complete task/image/code/asset/host/runtime provenance;
  CPU MuJoCo, generic r49 DINO, and existing baseline profiles do not regress.
- BLOCKED_NEEDS_DECISION: stop before NVIDIA EULA acceptance; image publication; each bounded paid
  r49 envelope; any Isaac/DINO sidecar boundary; retry after failure; repeat Stage C; or any entity-
  budget expansion trigger. Approval of this DRAFT alone authorizes none of those external actions.
- BLOCKED_NEEDS_LOCAL_VALIDATION: image/offline smoke cannot run on a compatible local GPU/Docker
  runtime, or required Stage A/B/C CloudML evidence is unavailable due to capacity, registry,
  JuiceFS, disk/RAM, driver, runtime, assets, or an unapproved external gate. The implementation is
  not complete or merge-ready until Stage C passes.
- INTERMEDIATE_ONLY: Phase 0-2 code, deterministic tests, image build metadata, dry-run YAML, Stage
  A, or Stage B may be committed only as an explicitly reported checkpoint; none proves the cloud
  digital-twin product route.
- No regressions: ordinary MuJoCo remains CPU-eligible unless a row explicitly requires DINO/CUDA;
  current CPU and DINO image variables/pools, baseline profiles, launch axes, eval scoring, artifact
  privacy, and no-fallback semantics remain unchanged.

Verification:

- deterministic: `ruff check .`; `ruff format --check .`;
  `./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals`;
  `./scripts/dev/run_pytest_standalone.sh -q tests/unit/molmo_cleanup/test_isaac_lab_runtime_smoke_checker.py tests/contract/maps/test_b1_map12_verified_alignment.py tests/contract/dev_tools/test_isaac_runtime_preflight_just_recipe.py`.
- integration: run
  `just agent::eval recommend plan=docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md budget=focused`;
  generate each proposed `cloudml-isaac-runtime-smoke`, `cloudml-b1-map12-navigation-smoke`, and
  `cloudml-b1-map12-map-build-grounding-dino` row separately with
  `just agent::eval execute ... execution_target=cloudml cloudml_dry_run=true row_id=<stage-row>`;
  require deterministic YAML apart from attempt identity, pinned image/assets, no secret or
  workstation path, and a valid prior-stage acceptance receipt for B/C.
- product-run: exercise
  `just run::surface surface=household-world world=b1-map12 backend=isaaclab preset=map-build agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino`
  in the pinned image and require the frozen strict local checker contract before Stage C submit.
- local-live-manual: after separate approvals, run the offline image RTX/DINO smoke, then CloudML
  Stage A, collect/check its receipt, Stage B, collect/check its receipt, and Stage C on
  non-preemptible queue `11759` r49 tasks; inspect nonblank image/report artifacts and measured
  resource/cost provenance. These gates are intentionally unavailable during preflight because no
  EULA, publication, or paid-task authorization has been granted.
- optional: with separate approval, repeat Stage C on a fresh host before maintained-product or
  preemptible promotion; a Stage A repeat proves runtime portability only.

Execution: main=root supervisor implementing Phase 0-2 first, preserving the shared dirty worktree,
running deterministic/dry-run gates, and stopping at every approval or live-proof boundary;
worker=none; worker-goal=none.

To execute: `/goal execute docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md with intuitive-flow`

Optional tracking: none.

Approval: `LGTM`, `approve`, or `go ahead` approves this implementation contract only; EULA,
publication, paid r49 tasks, retries, sidecar expansion, and repeat/promotion remain separate gates.

# CloudML Isaac Digital-Twin Proof

## Outcome

Make the already-supported B1 / Map 12 digital twin reproducible on CloudML without changing its
product meaning:

```text
frozen B1/Map12 case + pinned code + pinned Isaac image + content-addressed assets
  -> simulator:isaaclab + renderer:rtx capability match
  -> queue 11759 r49 worker
  -> generic Isaac runtime smoke
  -> B1 / Map 12 navigation smoke
  -> direct-runner MapBuild product proof
  -> collected CloudML artifacts with local-proof-compatible checkers
```

The public route remains:

```text
surface=household-world
world=b1-map12
backend=isaaclab
preset=map-build
agent_engine=direct-runner
evidence_lane=camera-grounded-labels
camera_labeler=grounding-dino
```

CloudML is an execution target for that route, not a new world, backend, preset, agent engine, or
digital-twin product surface.

## Why This Work Exists

The local hardware proof is strong but not portable. On 2026-07-24, the repo proved real Isaac
headless RTX rendering and a strict B1 MapBuild run on a local RTX 3090, including 5/5 public
waypoints, 25/25 Grounding DINO observations, 100 robot-view images, and 1.0 sweep coverage.
CloudML currently cannot reproduce that claim because:

- the eval placement model has no `simulator:isaaclab` or `renderer:rtx` capability;
- `cloudml-r49` assumes the MuJoCo/Grounding DINO image and worker bootstrap;
- `Dockerfile.eval` has CPU and CUDA/DINO variants but no Isaac Sim/Lab runtime;
- the B1 scene, Map 12 bundle, robot USD, and alignment inputs are not a frozen CloudML asset set;
- no CloudML artifact records the Isaac runtime/image/driver/GPU provenance.

Demand gate: pass. Reusing the generic CUDA image would create false confidence because CUDA and
Grounding DINO readiness do not prove Isaac Sim imports or RTX rendering. A separate capability
and image identity are justified; a new public product route is not.

## Current Evidence And Constraints

- Canonical digital twin: `world=b1-map12`, `backend=isaaclab`.
- MolmoSpaces household scenes remain `backend=mujoco`; MolmoSpaces+Isaac stays retired.
- Local runtime metadata: Isaac Sim `6.0.0.0`, Isaac Lab `0.54.3`, Torch `2.7.0+cu128`.
- Local renderer proof: `isaac_lab_headless_rtx` on an RTX 3090.
- Candidate CloudML resource: queue `11759` (`robot-dev-common`), one
  `cloudml.ng1r49-8-8.13-107` worker with RTX 4090-class GPU.
- Initial runs must be non-preemptible so infrastructure compatibility failures are not confused
  with scheduler eviction. Preemptible execution is a later cost optimization.
- The local preflight currently uses 80 GiB as a lower-bound warning, not as a proven CloudML
  capacity requirement. Phase 0 must calculate target-task scratch and memory budgets from the
  image/runtime, compressed and expanded assets, shader/cache data, outputs, and safety margin.
- Current B1 asset sizes are approximately 11 GiB for
  `2rd_floor_seperated`, 2.5 GiB for `B1_floor2_slow`, under 1 MiB for Map 12, and under 1 MiB
  for the generated robot USD. Do not upload all B1 data for the generic smoke.
- NVIDIA EULA acceptance must be explicit in the image/runtime contract and recorded as a boolean,
  never inferred from GPU selection.
- Collected Stage A provenance must report exact, non-`unknown` Isaac Sim, Isaac Lab, Torch, and
  CUDA versions; an image tag or build declaration alone is insufficient.

## Scope

### 1. Dedicated Isaac Image Contract

- Add one reproducible Isaac image path, separate from the current CPU and CUDA/DINO eval images.
- Pin the base image, Isaac Sim, Isaac Lab source revision/package, Python, CUDA/Torch, and repo
  dependency lock inputs.
- Prefer an NVIDIA/Isaac-supported base or the repo-local Isaac Lab Docker source over installing
  the full runtime at task startup.
- Build/import smoke must prove `torch.cuda.is_available()`, Isaac imports, expected versions,
  RTX headless startup, and a nonblank generated-scene render.
- Publish the immutable digest only after the local/container smoke passes.
- Use a distinct environment variable such as `ROBOCLAWS_CLOUDML_ISAAC_IMAGE_URL`; do not overload
  `ROBOCLAWS_CLOUDML_GPU_IMAGE_URL` and hide runtime identity.

### 2. Explicit CloudML Capability And Placement

- Add a dedicated worker pool such as `cloudml-r49-isaac` with at least `gpu`,
  `simulator:isaaclab`, `renderer:rtx`, `python-env`, and `artifact-storage`.
- Keep `cloudml-r49` as the MuJoCo/Grounding DINO route.
- Select the Isaac pool only for rows that explicitly require `simulator:isaaclab`; GPU alone is
  insufficient.
- Reuse queue `11759` and the existing r49 resource shape for the first proof.
- Fail with `no_eligible_worker_pool` or an Isaac-specific readiness error when the image,
  capability, GPU, disk, EULA, or assets are missing. No MuJoCo or local fallback is allowed.
- Keep the first three proof stages as explicit attempts with separate task IDs and artifact roots.

### 3. Frozen Isaac Asset Set

- Extend the existing content-addressed CloudML input boundary rather than adding another storage
  service.
- Create separate asset groups so the generic runtime smoke uses only generated/control assets,
  while B1 stages add the scene, Map 12, robot USD inputs, alignment artifact, Base Metric Map,
  waypoint requests, and required metadata.
- Preserve relative USD references or rewrite them deterministically during asset preparation;
  the worker must not depend on workstation absolute paths.
- Freeze the transitive USD, robot URDF/mesh, alignment, and map dependency closure actually
  consumed by the proof. Reject absolute workstation paths in manifests, text metadata, and
  composed USD dependencies; do not archive both complete B1 roots when a smaller verified closure
  is sufficient.
- Record per-file or per-archive hashes, total bytes, source provenance, and the exact staged path
  consumed by each stage.
- Probe JuiceFS content-addressed objects before upload and reuse matching immutable inputs.
- Do not stage provider secrets for the generic or direct-runner proof.
- Prefer one existing-schema immutable asset archive per separately invoked stage. Add a typed
  asset-manifest schema only if Phase 0 proves the current content-store identity cannot represent
  the required closure and provenance.

### 4. Isaac-Aware Worker Bootstrap And Provenance

- Split GPU readiness by worker capability: DINO validation remains in the current r49 branch;
  Isaac validation checks the dedicated runtime, GPU/driver, disk, EULA, renderer, and staged
  inputs.
- CloudML generation and worker entry default to EULA not accepted. Both must reject a missing or
  false approval receipt; local recipe defaults must not leak into the formal cloud path.
- Run Isaac with the dedicated runtime Python rather than installing it into the normal `.venv/`.
- Capture task ID, queue, cluster, host, GPU, driver, CUDA, image digest, Isaac Sim/Lab versions,
  renderer mode, startup time, peak GPU memory, stage duration, and output hashes.
- Preserve the current run-owned output mount and collector envelope.
- Keep CloudML transport/bootstrap thin; invoke existing Isaac scripts and product commands instead
  of copying task strategy into the adapter.

### 5. Ordered Live Proof Ladder

Each stage is a new explicit CloudML task and starts only after the previous stage is accepted.
Implement A/B/C as three separately invoked opt-in row executions. Do not use row `depends_on` for
this ladder because the current harness deliberately packs dependency-connected rows into one
task, and do not expose an executable profile that submits all three concurrently. Collection of
each stage writes an acceptance receipt containing the stage ID, task ID, checker result, artifact
root, and artifact hashes; receipt verification is a local control-plane precondition for
generating or submitting the next stage.

#### Stage A: Generic Runtime Smoke

Run the existing strict Isaac runtime smoke against its generated scene. Require:

- exact pinned, non-`unknown` runtime versions and visible RTX 4090-class GPU;
- renderer mode `isaac_lab_headless_rtx`;
- loaded USD stage and selected public bindings;
- four robot-view images plus the runtime smoke image;
- all required images nonblank and checker pass;
- collected state, logs, GPU samples, timing, and image hashes.

Stop after Stage A on import, driver, shader/cache, disk, renderer, blank-image, output-mount, or
collector failure. Do not upload the full B1 asset set to debug a generic runtime failure.

#### Stage B: B1 / Map 12 Navigation Smoke

Stage only the B1 navigation asset group and run the existing readiness and navigation smoke.
Require:

- asset and alignment readiness with no missing referenced files;
- robot USD readiness;
- successful real Isaac render of the selected B1 scene;
- all requested navigation poses accepted by the existing strict checker;
- nonblank robot-view/report/preview artifacts;
- collected navigation and readiness artifacts with immutable input provenance.

Stop after Stage B if the B1 USD cannot compose from the staged root, camera evidence is blank,
alignment/readiness fails, or navigation does not pass. Do not continue to a product agent run.

#### Stage C: Direct-Runner MapBuild Product Proof

Run the frozen public route with `agent_engine=direct-runner`,
`evidence_lane=camera-grounded-labels`, and `camera_labeler=grounding-dino`. Require parity with the
accepted local product proof:

- 5/5 public waypoints visited;
- 25/25 expected Grounding DINO observations;
- 100 robot-view images and non-placeholder provenance;
- Base Metric Map and Runtime Metric Map artifacts;
- 1.0 sweep coverage;
- strict B1 robot-consumption, waypoint-honesty, map-build, and Base Metric Map gates;
- full CloudML task/image/asset/runtime provenance in the collected report.

Grounding DINO may run in the same dedicated Isaac image only if its pinned model and CUDA
sidecar pass the existing readiness contract. Phase 0 must resolve and offline-prove that packaging
choice before image implementation. Otherwise keep Stage C blocked for explicit review of a
two-process/sidecar boundary; do not silently omit observations or substitute public labels.

### 6. Eval Harness And Documentation Integration

- Add the smallest row/case representation needed to select the three Isaac proof stages without
  turning the normal baseline profiles into an expensive default.
- Keep `baseline-core`, `baseline-live-default`, and ordinary MuJoCo refresh behavior unchanged.
- Give the Isaac proof an explicit opt-in profile or row set until repeatability and cost are known.
- Teach dry-run, status, retry, collect, and reports about the Isaac pool and immutable inputs.
- Document the default placement matrix: CPU MuJoCo on queue 8151, DINO MuJoCo on r49, and Isaac
  digital twin on the dedicated r49 Isaac capability.
- Record successful proof in human docs only after Stage C passes; before that, report the exact
  failed or blocked stage.

## Non-Goals

- No MolmoSpaces+Isaac route, compatibility alias, or hidden backend fallback.
- No digital-twin cleanup enablement or cleanup product-readiness claim.
- No Agibot physical probe, robot connection, or movement.
- No OpenAI Agents SDK or provider call in the first CloudML proof.
- No CPU-only Isaac benchmark; RTX rendering is a required capability, not an optimization toggle.
- No full provider/task/evidence-lane Cartesian matrix.
- No scheduler-transparent retry. Every retry is a new explicit attempt.
- No default inclusion in routine baselines until cost and repeatability are measured.
- No image build or package download during a formal CloudML evidence task.

## Entity Budget

- Reuse: CloudML plan/shard lifecycle, JuiceFS content-addressed inputs, run-owned outputs,
  collectors/reports, existing Isaac preflight/smoke/navigation/product commands, and strict
  checkers.
- Add: one Isaac image identity, one Isaac worker capability/pool, existing-schema per-stage asset
  archives, acceptance receipts, and opt-in eval rows/profile.
- Avoid: a second CloudML adapter, a new storage backend, duplicated Isaac task scripts, a new
  public launch axis, or a generic plugin framework.
- Expansion triggers requiring review: another GPU class, more than one Isaac version, provider
  credentials, distributed/multi-GPU Isaac, a sidecar service boundary, or cleanup enablement.

## Implementation Phases

### Phase 0: Reconcile Runtime And Frozen Case

- Select and record the exact Isaac Sim/Lab/Torch/CUDA versions and Isaac Lab source revision from
  the accepted local proof.
- Define the generated-smoke and B1 asset groups, enumerate referenced USD dependencies, and
  measure the minimal portable closure and archive sizes.
- Decide whether the pinned Isaac image can host the existing DINO sidecar and model offline. Stop
  for sidecar-boundary review before image implementation if it cannot.
- Freeze Stage A/B/C commands, checker flags, expected artifacts, and timeouts.
- Measure or obtain the target r49 CPU, RAM, scratch-disk, driver, and GPU contract. Calculate
  compressed-plus-expanded asset, image/runtime, shader/cache, and output headroom rather than
  inheriting the local 80 GiB threshold.
- Produce per-stage timeout, maximum GPU-hour, registry-byte, asset-byte, and storage estimates
  before any image push or CloudML submit.

Exit: deterministic manifests and commands can be reviewed without local absolute paths.

### Phase 1: Image And Offline Proof

- Obtain explicit NVIDIA EULA authorization before acquiring/building an image or running a smoke
  that requires acceptance. This does not authorize registry publication or a paid cloud task.
- Implement the dedicated image and build helper.
- Prove imports, versions, CUDA, RTX headless rendering, and nonblank generated output locally in
  the image with network disabled after build.
- Pin and record the resulting registry digest.

Exit: immutable image digest plus offline smoke artifacts. Stop if the supported image cannot run
on the target CloudML driver contract.

### Phase 2: Placement, Staging, And Dry Run

- Add capability matching, resource/image mapping, Isaac bootstrap, asset groups, and provenance.
- Add three independent opt-in stage rows, acceptance receipts, and next-stage receipt validation;
  do not express the stop gates with `depends_on`.
- Add unit/contract tests for pool selection, missing capability/image/EULA/assets, deterministic
  YAML, no fallback, retry identity, and redaction.
- Generate and inspect all three CloudML dry-run tasks without submission.

Exit: deterministic tests pass and the reviewed YAML references only pinned code, image, assets,
commands, and run-owned output paths.

### Phase 3: Cost-Gated CloudML Proof

- Present the measured registry/storage bytes, per-stage timeout, maximum GPU-hours, and current
  capacity before approval. An approval must explicitly name image publication and either Stage A
  only or a bounded A/B/C ladder; it never covers automatic retries or the later repeat run.
- Submit Stage A; collect and accept it before Stage B asset upload/submit.
- Submit and accept Stage B before Stage C.
- Submit Stage C and render the final comparison/report packet.

Exit: Stage C acceptance passes, or the plan remains active with one precise failed-stage blocker
and its artifacts.

### Phase 4: Optional Repeatability And Promotion

- Keep the first accepted Stage C as completion of this CloudML proof; routine/default promotion is
  not implicit in that success.
- With separate paid approval, repeat a selected stage on a fresh r49 host/task and compare startup,
  render, task, GPU memory/utilization, and output hashes.
- A fresh-host Stage A repeat proves only image/driver portability. Preemptible or maintained
  product placement requires a second accepted Stage C on a fresh host.
- Update current docs and plan ledger with measured cost and only the policy supported by the
  repeated stage.

Exit: repeatability evidence supports the narrowly stated policy, or the route stays
explicit/non-preemptible. This phase is not required for the first-proof success condition.

## Acceptance

SUCCESS requires all of the following:

1. Isaac rows require `simulator:isaaclab` and cannot match CPU or generic DINO pools.
2. The dedicated image is immutable, version-pinned, locally/offline proven, and selected only by
   the Isaac pool.
3. CloudML dry-run tasks are deterministic and contain no secret values or workstation absolute
   paths.
4. Stage A passes on a real r49 worker with RTX rendering and nonblank images.
5. Stage B passes B1 asset/readiness/navigation and image gates from staged immutable inputs.
6. Stage C matches the current strict local B1 MapBuild acceptance contract.
7. Every attempt records task, image, code, asset, host, GPU/runtime, timing, and artifact identity.
8. Failure at any stage blocks later paid stages with an actionable artifact, without fallback.
9. Ordinary CPU MuJoCo and r49 DINO placement and existing baseline profiles do not regress.
10. The first-proof profile remains opt-in and non-preemptible after Stage C success. Any later
    preemptible or maintained-product promotion is supported by a separately approved second
    Stage C on a fresh host.

INTERMEDIATE_ONLY:

- image build/import success without real RTX rendering;
- deterministic tests and CloudML dry-run;
- Stage A or Stage B without Stage C;
- a product run that weakens local checker flags or omits required B1 evidence.

BLOCKED_NEEDS_DECISION:

- NVIDIA EULA acceptance before image/runtime use;
- registry publication and the explicitly bounded non-preemptible r49 cost envelope;
- adding provider credentials or a new sidecar/service boundary;
- promoting the opt-in Isaac profile into a routine baseline;
- enabling preemptible execution before repeatability evidence.

BLOCKED_NEEDS_EXTERNAL_STATE:

- no eligible r49 capacity, registry access, JuiceFS access, sufficient task disk, compatible
  driver, or reachable immutable assets;
- the approved NVIDIA/Isaac package source cannot be materialized into the pinned image.

## Verification

Planning/dry-run recommendation:

```bash
just agent::eval recommend \
  plan=docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md \
  budget=focused
```

Deterministic implementation gates:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/molmo_cleanup/test_isaac_lab_runtime_smoke_checker.py \
  tests/contract/maps/test_b1_map12_verified_alignment.py \
  tests/contract/dev_tools/test_isaac_runtime_preflight_just_recipe.py
```

Image and integration gates:

- Build the pinned Isaac image and run its post-build smoke with network disabled.
- Validate `nvidia-smi`, CUDA/Torch, Isaac imports, versions, disk, EULA state, and RTX renderer.
- Generate Stage A/B/C CloudML YAML twice and require byte-identical task inputs apart from run and
  task identity.
- Probe every JuiceFS digest before submit and verify collected output/archive hashes.
- Search YAML, logs, manifests, and reports for secret values and workstation absolute paths.

Live gates:

- Stage A generic Isaac runtime smoke on one non-preemptible r49 task.
- Stage B B1 / Map 12 navigation smoke on a new invocation after Stage A receipt acceptance.
- Stage C direct-runner, camera-grounded, Grounding DINO B1 MapBuild on a new invocation after
  Stage B receipt acceptance.
- Separately approved fresh-host Stage C repeat before preemptible or maintained-product promotion.

## Risks And Stop Gates

| Risk | Required response |
| --- | --- |
| Isaac image is very large or build is network-fragile | Build once, pin digest, prove offline; never install in evidence tasks. |
| CloudML driver is incompatible with pinned Isaac/CUDA | Stop at Phase 1/Stage A and record exact driver/runtime evidence. |
| Target CPU, RAM, or scratch disk is below the measured stage budget | Block before asset upload, extraction, or renderer startup. |
| B1 USD contains absolute or missing references | Fail asset preparation/readiness; do not patch paths ad hoc in the live task. |
| RTX 4090 VRAM is insufficient | Stop with peak-memory and renderer diagnostics; do not silently lower evidence requirements. |
| Stage C needs both Isaac and DINO dependencies | Resolve and offline-prove one pinned image in Phase 0/1 or return for explicit sidecar-boundary review before image publication. |
| Shader/cache startup dominates cost | Record separately; optimize only after the first correct proof. |
| Output differs from local proof | Classify runtime/platform versus behavioral difference before changing gates. |
| A task is preempted | Record an explicit failed/preempted attempt and resubmit only after review. |

## Expected Changed Surfaces

Exact filenames may narrow during preflight, but ownership should remain:

- CloudML placement and row requirements:
  `skills/eval-harness/scripts/eval_harness_cloudml.py`, catalog/row helpers, and focused tests.
- Image/build contract: a dedicated Isaac Dockerfile or a clearly separated build target plus
  `scripts/dev/` build/offline-smoke helpers.
- Worker/bootstrap and task envelope: `roboclaws/evals/cloudml_task.py`,
  `scripts/dev/run_cloudml_eval_worker.sh`, and tests.
- Content-addressed assets: existing `roboclaws/evals/cloudml_content_store.py` boundary and an
  Isaac-specific packaging helper; extend the manifest schema only if Phase 0 proves the current
  one-archive identity cannot represent the required closure and provenance.
- Existing Isaac commands/checkers: reuse; change only for portable path/runtime injection or
  missing provenance required by the cloud proof.
- Docs: `skills/eval-harness/SKILL.md`, `docs/human/evaluation.md`, and this plan after live proof.

## Recommended Execution Route

After approval of the preflight contract above, execute the whole plan through `$intuitive-flow`.
Execution starts at Phase 0 and stops at each applicable EULA, publication, paid-task, retry,
sidecar-expansion, or repeat-run boundary with the measured cost envelope.

## Planning-Loop Resolution

Round 1 used three independent, read-only scouts: plan entropy, documentation grill, and
hardware/cost skepticism. No second round was needed after the findings converged.

- Accepted/merged: explicit non-accepting EULA defaults and early authorization; exact runtime
  versions; portable asset closure; measured CPU/RAM/disk budget; separately invoked stage rows and
  acceptance receipts; unconditional DINO parity; Phase 0 DINO packaging decision; and evidence-
  scoped repeatability.
- Parked: alternate GPU classes/queues, typed asset schema expansion unless the current one-archive
  boundary proves insufficient, and default/preemptible promotion until a separately approved
  fresh-host Stage C repeat exists.
- Rejected: CPU-only Isaac comparison in this plan; it would test a different contract from the
  required RTX digital twin.
- Needs user review at execution time: NVIDIA EULA authorization; image publication and bounded
  paid-task envelope; any sidecar/service boundary; and any later repeat/promotion spend.
