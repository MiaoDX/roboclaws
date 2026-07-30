# Aggressive Architecture Migration

**Status:** Authorized; Waves 0-3 complete, Wave 4 planner slice active
**Created:** 2026-07-30
**Execution unit:** This entire plan, delivered in bounded waves and slices
**Supersedes:** the broad-module-splitting non-goal in
`docs/plans/2026-07-30-post-cleanup-saturation-refactors.md`
**Source review:** multi-agent oversized-module, ponytail, ultra engineering,
package-topology, test-topology, and reduce-entropy audits at
`53a40afee1647c40933a22b4feb4772bee2cd5b4`

## Planning Charter

Goal:

- delete completed investigation, rehearsal, diagnostic, and one-shot probe
  stacks that no longer serve a current product or maintainer workflow;
- assign each retained runtime, artifact, backend, report, eval, and operator
  concern to one package owner;
- eliminate package and module dependency cycles;
- split retained oversized modules by behavior and dependency direction so no
  active source module remains at or above 1,000 lines;
- reduce total repository code while preserving current product behavior and
  proof quality.

Non-goals:

- no public launch-axis, surface, preset, provider-profile, evidence-lane,
  camera-labeler, artifact-schema, or privacy-boundary redesign;
- no compatibility wrappers, old-module re-export facades, or silent fallback;
- no rewrite of operator-console UX, agent strategy, provider transport,
  simulator behavior, or physical-robot behavior;
- no deletion or rewriting of immutable historical outputs, accepted evidence,
  candidate receipts, ADRs, retrospectives, or completed execution logs;
- no publication of durable baselines/catalog artifacts, Omniverse EULA
  acceptance, paid-provider expansion, or real-robot motion.

Allowed execution actions:

- delete code, tests, current recipes, and current human-doc instructions only
  after tracked caller closure proves the surface is retired;
- move active script-owned product code into package owners and update every
  in-repo caller forward-only;
- introduce small contract/value-object modules and composition roots only
  when they remove an observed cycle or duplicate contract owner;
- split modules and tests along behavior owners without retaining old import
  paths.

User-review gates:

- stop before changing a public command or artifact schema;
- stop before abandoning repository reproducibility for a current B1 input;
- stop before deleting a surface with a current human-doc, Just, workflow,
  package, or external consumer that cannot be migrated inside this plan;
- stop before a material provider, hardware, cost, credential, or publication
  expansion.

Planning-loop stop condition:

- the plan has one dependency direction, an explicit deletion/retention
  ledger, bounded slices, measurable acceptance, wave-specific proof, and no
  unresolved product decision hidden as an implementation default.

## Baseline And Ratchet

The source scan covers `roboclaws/`, `scripts/`, and operator-console
JavaScript:

| Metric | Baseline | Campaign target |
| --- | ---: | ---: |
| Source files at least 500 LOC | 132 | at most 90; target 85 |
| Source files at least 800 LOC | 49 | at most 20 |
| Source files at least 1,000 LOC | 33 | 0 |
| Source LOC | 180,297 | at most 150,000 |
| Known module SCCs | 6 | 0 |
| Known package bidirectional edges | 5 | 0 |
| Active script entrypoint size | up to 2,192 LOC | at most 250 LOC |

The test scan covers 228 `test_*.py` files plus test support:

| Metric | Baseline | Campaign target |
| --- | ---: | ---: |
| Test LOC | 108,901 | at most 90,000 |
| Test files at least 1,000 LOC | 25 | 0 |
| Test files at least 800 LOC | 29 | 0 |
| Typical retained behavior test | unbounded | 350-650 LOC |

The evidence-backed campaign estimate is 45,000-52,000 net deleted lines across
source and tests. The stretch estimate is about 56,000 lines only when
conditional surface closure remains honest. Structural movement of
35,000-45,000 retained lines is expected but is not counted as simplification.

LOC and file size are ratchets and reported outcomes, not independent reasons
to delete or split cohesive behavior. Every baseline source file at or above
1,000 lines and every test over 700 lines must receive an explicit `DELETE`,
`MERGE`, `SPLIT`, or `PARK` disposition. A `PARK` requires a named cohesion
reason, owner, and follow-up trigger. No entrypoint, facade, orchestrator, or
active script subsystem may remain at or above 1,000 lines. Entry/facade
targets are at most 600 lines, cohesive leaf targets at most 700, and active CLI
entrypoints at most 250. A smaller file fails the plan if it preserves duplicate
ownership or an invalid dependency direction.

## Decision Ledger

### Delete

1. Retired robot-camera apple-to-apple and visual-parity investigation.
   Delete the exact source and test paths in the path ledger below. Mechanically
   move the terminal active capsule to shipped history without rewriting its
   evidence links; historical plans and output artifacts remain. Expected
   deletion: about 10,838 source and 6,519 test lines.
2. Offline RAW-FPV perception probe, corpus/private-label generator, source
   tests, and probe-only docs. This does not include the current
   `camera-raw-fpv` runtime lane, MCP/checker behavior, or product artifacts.
3. Private Agent SDK performance matrix and its dedicated test. Current SDK
   metrics, performance profile, status, and live-report behavior remain.
4. Retired CI rehearsal/Pages surface: `ci-rehearsal*` recipes, live cleanup
   matrix runner, Pages assembler, `ci_live_reports`, and dedicated tests.
5. Caller-free one-shot MolmoSpaces-to-Isaac material/light probe generators
   included in the retired parity ledger. Generic Isaac runtime smoke,
   readiness, and B1 navigation proof remain current and are preserved.
6. Standalone grasp-filter diagnostics. First move `PROBE_SCRIPT` and the
   subprocess helper still used by grasp-pose cache into a small
   `grasp_probe_runtime` owner, then delete initial-contact diagnostic facade,
   diagnostic reports, runner scripts, and dedicated tests.
7. No additional test file is an unconditional deletion target. Wave 0 may
   classify source-string, retired-import, private-helper, missing-module, and
   obsolete-flag tests as deletion candidates, but each candidate must be added
   to the exact path ledger and receive plan review before deletion. Assertions
   that directly prove routing, packaging, privacy, schema, or retired-surface
   absence remain preservation gates.

Each deletion slice owns one leaf-to-root surface and migrates or removes all
of its package, recipe, doc, and test callers atomically. Slices above eight
files require an explicit path manifest and rationale; file count never
justifies a temporarily broken tree or compatibility facade. Each slice starts
with an exact tracked/dynamic caller search and ends with import, focused-test,
and command-parse proof. A discovered current caller converts the target to a
migration task or triggers a stop; it is never bypassed with a compatibility
shim.

### Unconditional Deletion Path Ledger

| Surface | Exact implementation paths | Caller/doc/test disposition |
| --- | --- | --- |
| Robot-camera parity runners | `scripts/molmo_cleanup/run_robot_camera_apple2apple_comparison.py`; `scripts/molmo_cleanup/summarize_robot_camera_visual_parity.py` | No current Just/package caller; delete after leaf modules. Archive `docs/status/active/mujoco-isaac-camera-visual-parity.md`; preserve historical plans/output. |
| Robot-camera parity leaves | `scripts/molmo_cleanup/robot_camera_apple2apple_camera_contract.py`; `robot_camera_apple2apple_capture_quality.py`; `robot_camera_apple2apple_image_metrics.py`; `robot_camera_apple2apple_materials.py`; `robot_camera_apple2apple_native_render.py`; `robot_camera_apple2apple_object_gate.py`; `robot_camera_apple2apple_object_parity.py`; `robot_camera_apple2apple_report.py`; `robot_camera_apple2apple_rgb_evidence.py`; `robot_camera_apple2apple_visual_state.py`; `robot_camera_visual_parity_gates.py`; `robot_camera_visual_parity_payloads.py`; `robot_camera_visual_parity_report.py`; `make_robot_camera_rgb_gain_profile.py` | Delete leaf-to-root. Paths are relative to `scripts/molmo_cleanup/`. |
| Parity-only USD probes | `scripts/isaac_lab_cleanup/make_molmospaces_material_response_probe_usd.py`; `scripts/isaac_lab_cleanup/make_molmospaces_light_shadow_probe_usd.py` | Delete with their dedicated tests; do not delete generic Isaac runtime smoke. |
| Robot-camera parity tests | `tests/unit/molmo_cleanup/test_robot_camera_apple2apple_comparison.py`; `test_robot_camera_visual_parity_summary.py`; `test_robot_camera_visual_parity_summary_sources.py`; `test_robot_camera_rgb_gain_profile.py`; `test_robot_camera_prior_probe_sources.py`; `test_molmospaces_material_response_probe_usd.py`; `test_molmospaces_light_shadow_probe_usd.py` | Delete with owners. Paths after the first are relative to `tests/unit/molmo_cleanup/`. |
| Offline RAW-FPV probe | `scripts/molmo_cleanup/run_raw_fpv_perception_probe.py`; `raw_fpv_perception_scoring.py`; `generate_raw_fpv_private_labels.py`; `generate_raw_fpv_sweep_corpus.py` | Remove retired probe/corpus instructions from current human docs. `raw_fpv_perception_scoring.py` is a mechanically discovered leaf with only the retiring probe as caller. Archive terminal `raw-fpv-live-strategy-stabilization` capsule; retain runtime lane, canonical corpora/evidence, checker, MCP, and privacy contracts. |
| Offline RAW-FPV tests | `tests/unit/molmo_cleanup/test_raw_fpv_perception_probe.py`; `test_raw_fpv_perception_probe_sources.py` | Delete only probe-specific tests; retain current lane tests. |
| Private SDK matrix | `scripts/molmo_cleanup/run_agent_sdk_perf_matrix.py`; `tests/unit/molmo_cleanup/test_agent_sdk_perf_matrix.py` | Remove current maintainer instructions; preserve historical spike evidence and current SDK metrics/profile tests. |
| CI rehearsal/Pages | `roboclaws/household/ci_live_reports.py`; `scripts/molmo_cleanup/run_ci_live_cleanup_matrix.py`; `assemble_ci_live_pages.py`; `prewarm_molmospaces_ci_assets.py` | Delete `ci-rehearsal` and `ci-rehearsal-all` recipes together. `prewarm_molmospaces_ci_assets.py` is part of this surface, not an overlooked surviving caller. |
| CI rehearsal tests | `tests/unit/molmo_cleanup/test_ci_live_reports.py`; `test_ci_live_workflow_entries.py` | Delete with recipes and package owner; current `.github/workflows/ci.yml` remains lint/mock only. |
| Grasp diagnostics | `roboclaws/household/grasp_filter_diagnostics.py`; `grasp_initial_contact_diagnostics.py`; `scripts/molmo_cleanup/run_molmospaces_grasp_filter_diagnostics.py`; `run_molmospaces_grasp_initial_contact_diagnostics.py` | First move cache-required probe path/subprocess behavior to a small household-owned runtime helper. Retain `grasp_pose_policy_cache.py`, cache-generation CLI, and cache tests. |
| Grasp diagnostic tests | `tests/unit/molmo_cleanup/test_grasp_filter_diagnostics.py`; `test_molmo_grasp_initial_contact_diagnostics.py` | Delete after retained cache tests prove the extracted runtime helper. |
| Grasp diagnostic report split | `roboclaws/household/report.py`; `roboclaws/household/report_sections_grasp_diagnostics.py` | Remove only `render_grasp_filter_diagnostics_report`, `render_grasp_initial_contact_diagnostics_report`, and their filter/initial-contact section functions. Preserve cache generation, pose-policy cache, planner-feasibility, and shared report behavior; split the mixed section module before deleting diagnostic leaves. |

Wave 0 must expand each row with static callers, dynamic/recipe callers,
current docs, package data/artifact readers, replacement owner, deterministic
proof, product/local proof, and stop gate. That expansion may discover a
missing caller, but it may not add a deletion target without plan review.

### Reduce To A Small Retained Owner

1. Scene-camera comparison: retain the complete public Just parameter grammar,
   including `seed`, `generated_mess_count`, `output_dir`, `scene_source`,
   `scene_index`, `scene_usd_path`, `render_width`, `render_height`, and
   `lighting_profile`, plus their current runtime behavior. Fixed fixtures are
   verification inputs, not a replacement for parameterized execution. Retain
   `comparison_manifest.json` with schema
   `molmospaces_isaac_scene_camera_comparison_v1` and
   `camera_control_request.json` with their Wave 0 field/type/meaning fixtures.
   Delete HTML, hydration, lighting/color triage, replay, or source-artifact
   owners only where field-level fixture comparison proves every retained field
   keeps its name, type, and meaning. A required removal, rename, retype, or
   semantic repurpose triggers artifact-schema review and retention of the
   minimum current producer.
2. B1 Map 12 authoring: retain current base-map build, augmentation,
   alignment/navigation inputs, readiness, and provenance required by the
   product route. Migrate the full current reproducibility chain into a
   package-owned B1 backend CLI rather than leaving a script subsystem. B1
   label, overlay, correspondence, projection, promotion, and review tooling is
   `PARK` for deletion until that CLI can rebuild and verify accepted inputs;
   digest/provenance alone is not proof of reproducibility.
3. Live performance/status: remove retired Codex CLI and Claude Code extractor
   and formatting branches. Preserve current OpenAI Agents SDK telemetry and a
   package-owned `molmo::status` command with a CLI entrypoint below 250 lines.
4. Planner manipulation diagnostics: retain planner feasibility readiness,
   cache preflight, canonical proof request/result, and current product proof.
   Delete one-shot diagnostic samplers/reports only after their product-grade
   invariant is owned by the retained feasibility/proof path.

### Preserve

- `just molmo::apple2apple-grid`, the current Runtime Map Prior matrix;
- current `camera-raw-fpv` agent/runtime/checker/MCP contracts;
- `direct-runner` and `openai-agents-sdk` behavior;
- current B1 Map 12 build, augment, readiness, alignment, navigation, and
  product inputs until a package-owned equivalent passes the same proofs;
- Base Metric Map, Runtime Metric Map, Runtime Map Prior Snapshot, Agent View,
  run-result, report, eval, privacy, and provenance schemas;
- planner feasibility readiness/cache and truthful blocked-capability behavior;
- current public Just grammar and operator-console safety/lifecycle behavior.

## Target Architecture

Imports point downward:

```text
CLI / operator console / eval entrypoints
                    |
                    v
          launch.executor typed dispatch
             |                    |
             v                    v
 household/direct runtime     agents SDK lifecycle
             |                    |
             +----------+---------+
                        v
              backend adapters
                        |
                        v
          household / maps / worlds owners
                        |
                        v
       narrow cycle-breaking value/contracts
```

Rules:

- `roboclaws.launch.executor` continues to own typed dispatch and child-process
  lifecycle. `agents.household_live_runner` continues to own the SDK live
  lifecycle; both are split in place rather than hidden behind a generic
  application framework.
- Narrow contract/value modules are introduced only at the owner named by a
  proven cycle and only when they have named consumers. There is no mandatory
  repository-wide `contracts` or `application` package.
- `operator_console`, `reports`, and `evals` may consume launch/runtime services
  or canonical artifacts; product runtime does not import their UI, rendering,
  or grading layers.
- `scripts` contains only thin argparse/wiring/exit-code adapters and never
  owns a long-running product subsystem.
- direct/MCP artifact assembly first converges in the existing household
  run-artifact owner. Report renderers and eval graders consume the canonical
  schema-preserving dictionary; a new `HouseholdRunResult` value type is
  permitted only if two named consumers still need it after convergence.
- worlds own scene catalog/sampling; launch owns typed selection and execution,
  not world-specific scanning.
- no old-module aliases, re-export facades, duplicate dataclasses, string copies
  of typed state, or hidden subprocess paths survive migration.

The migration must remove these known cycles:

1. household manipulation/proof six-module SCC;
2. `evals.long_horizon <-> evals.long_horizon_grader`;
3. `evals.cli <-> evals.runner`;
4. `operator_console.launcher <-> operator_console.readiness`;
5. `operator_console.interactions <-> operator_console.state`.

It must also remove the package bidirectional edges `agents <-> household`,
`household <-> launch`, `agents <-> launch`, and
`agents <-> operator_console`.

The package-edge guard encodes these concrete corrections:

- move provider-profile values used by household/launch out of the agents
  implementation owner into a narrow shared profile contract;
- move goal/environment metadata imported by household out of launch
  orchestration into their domain/value owner;
- keep `launch -> agents` and `launch -> household` dispatch edges, while
  removing the corresponding reverse imports;
- move operator-message consumption out of console UI modules so agents do not
  import `operator_console`;
- keep report timing projection out of agents runtime and keep evaluation/open
  artifact projection out of launch orchestration where those reverse edges
  create cycles.

Wave 0 records an explicit allowed package-edge matrix. No implementation wave
may weaken it to make a move pass.

## Execution Plan

Every slice changes one ownership seam, migrates its complete named caller set,
and ends in a green commit. Slices above eight files record why caller-atomic
migration requires the larger manifest. Delete-only and structural split work
do not share a slice.

### Wave 0: Freeze Evidence And Add Architecture Guards

1. Record the exact source/test LOC and oversized-file baseline in the Python
   quality baseline owner and give every oversized file a provisional
   disposition.
2. Generate an AST import graph for `roboclaws`; record the exact six SCCs,
   five bidirectional package edges, and an explicit allowed package-edge
   matrix.
3. Add forbidden-edge checks for package imports/execution of `scripts`, core
   product imports of eval/report/console UI, and the reverse edges this plan
   removes. Activate each guard with its owning migration slice so Wave 0 does
   not assert a knowingly red baseline.
4. Expand the unconditional deletion ledger with static imports, subprocess
   paths, Just/workflow callers, current docs, tests, package data/artifact
   readers, replacement owner, proof, and stop gate.
5. Record current public command traces and canonical artifact/privacy/schema
   fixtures for `apple2apple-grid`, RAW-FPV, B1, direct runner, SDK mock/live,
   operator sessions, reports, and evals.
6. Correct baseline documentation drift where `ARCHITECTURE.md` names a missing
   `roboclaws/household/direct_episode.py`; the current owner is
   `household_world_episode.py`.

Stop if dynamic entrypoints or an untracked external consumer make a deletion
target ambiguous. Wave 0 does not change runtime behavior.

#### Wave 0 Evidence: Size Baseline

`scripts/dev/python_quality_baseline.json` is the machine-readable owner. It
counts physical UTF-8 lines in Python files under `roboclaws/` and
`scripts/` as source and under `tests/` as tests. Reproduction is
`python scripts/dev/check_python_quality_ratchet.py --write-baseline`; read-only
verification is the same command without `--write-baseline`.

| Scope | Python files | LOC | >=500 | >=800 | >=1000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Source | 414 | 180,297 | 132 | 49 | 33 |
| Tests | 237 | 108,901 | 51 | 29 | 25 |

All 78 files over the 800-line ratchet carry a stored provisional disposition,
owner, and trigger: 68 `SPLIT`, 4 `DELETE`, 2 `MERGE`, and 4 `PARK`. The parked
rows are B1 authoring tools owned by Wave 5 and reopen only after package-owned
rebuild, digest, provenance, readiness, and product parity. These are
provisional migration classifications, not deletion authorization.

#### Wave 0 Evidence: Import Graph And Guards

`scripts/dev/check_architecture_import_graph.py` parses imports with `ast`,
resolves relative imports, computes Tarjan SCCs, aggregates package edges, and
ratchets known-red policies so removals pass while new cycles, package edges,
script dependencies, or inversions fail. Current SCCs are:

1. `evals.cli`, `evals.runner`;
2. `evals.long_horizon`, `evals.long_horizon_grader`;
3. `household.backend`, `manipulation_provenance`,
   `planner_observed_binding`, `planner_primitive_executor`,
   `planner_probe_primitive_executor`, `planner_proof_attachment`;
4. `household.household_runtime_contract`,
   `household.realworld_contract_init`;
5. `operator_console.interactions`, `operator_console.state`;
6. `operator_console.launcher`, `operator_console.readiness`.

The authoritative scan found six SCCs, not the five asserted during planning.
The additional runtime cycle is the function-local import at
`realworld_contract_init.py:223` back to `household_runtime_contract.py`, whose
top-level import of `realworld_contract_init` closes the cycle. It also found
five bidirectional package pairs: `agents <-> household`, `agents <-> launch`,
`agents <-> operator_console`, `household <-> launch`, and
`household <-> operator_console`. The fifth is real: `household_mcp_server`
imports console interactions while console routes/runtime modules import
household. Wave 1 must own both newly frozen edges; guards are not filtered to
preserve the earlier counts.

The explicit current allowed package-edge matrix is:

| Package | Allowed current targets (removals allowed; additions fail) |
| --- | --- |
| `agents` | `core`, `household`, `launch`, `operator_console`, `reports` |
| `cli` | `household`, `launch`, `maps` |
| `core` | none |
| `devtools` | none |
| `evals` | `agents`, `core`, `household`, `launch`, `maps`, `operator_console` |
| `household` | `agents`, `core`, `launch`, `maps`, `mcp`, `operator_console` |
| `launch` | `agents`, `core`, `household` |
| `maps` | `core` |
| `mcp` | none |
| `operator_console` | `agents`, `core`, `household`, `launch`, `maps` |
| `reports` | `core`, `household` |
| package root | none |

Known-red policy rows are active ratchets, not waived checks. Package import or
execution of scripts has two frozen violations and is owned by Wave 5; core
product inversions into eval/report/operator UI have three and are owned by
Waves 1-2; planned reverse package edges have 25 module pairs and are owned by
Waves 1-2. Exact pairs are emitted by the checker. Each policy permits deletion
of a known violation but rejects a new violation, so Wave 0 is green without
weakening a future removal gate.

#### Wave 0 Evidence: Unconditional Deletion Consumer Ledger

Current-code searches covered Python imports and literal paths, subprocess and
dynamic loading, `just/`, workflows, current human/agent docs, tests, package
data, and artifact readers. Historical plans, retrospectives, and outputs are
preservation evidence rather than current callers. No unknown external or
untracked dynamic consumer was found.

| Surface | Static callers | Dynamic / recipe callers | Current docs | Tests | Package data / artifact readers | Replacement owner | Deterministic proof | Product / local proof | Stop gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Robot-camera parity runners | parity leaf modules only | none | none | four runner/summary tests | historical output readers only | none; retired Wave 3 surface | exact-reference absence plus focused retained scene-camera tests | neighboring `apple2apple-grid` dry-run | any current recipe/package consumer |
| Robot-camera parity leaves | runner/summary within same surface | gain-profile helper called by runner | none | parity comparison/summary/profile/probe suite | preserve historical parity outputs | none; leaf-to-root Wave 3 deletion | path manifest, import absence, retained image/geometry contracts | scene-camera and grid command parse | retained scene-camera field depends on a leaf |
| Parity-only USD probes | parity runner only | runner subprocess path | none | two dedicated USD probe tests | generated probe USD is disposable; historical output preserved | none | exact path absence and generic Isaac smoke contracts | guarded Isaac availability only; no EULA acceptance | generic runtime smoke depends on probe |
| Robot-camera parity tests | none | none | none | exact seven-row test ledger | fixture inputs used by retained tests stay | retained scene-camera/grid test owners | collection and retained contract suite | grid dry-run | test proves a retained schema/route |
| Offline RAW-FPV probe | private-label/corpus tools within surface | corpus imports label generator; no Just/workflow caller | none | two probe-specific tests | canonical RAW-FPV corpora/evidence retained | current camera-raw-fpv runtime/MCP/checker owners | privacy, MCP, checker, and lane contracts | direct-runner camera-raw-fpv grammar/proof | private label reaches public artifact or current caller appears |
| Offline RAW-FPV tests | none | dynamic module loading of probe under test | none | exact two-row ledger | retained lane fixtures remain | retained RAW-FPV contract tests | retained lane/privacy tests collect and pass | camera-raw-fpv deterministic product proof | assertion covers current lane rather than probe |
| Private SDK matrix | shared live-performance readers only | no Just/workflow caller | none | dedicated matrix test | historical speedup fixtures retained | `agents` SDK metrics/profile plus `reports.live_performance` | SDK mock/profile/live-performance fixtures | guarded SDK live proof in later runtime wave | current maintainer command or external consumer appears |
| CI rehearsal/Pages | `ci_live_reports` and rehearsal scripts only | `ci-rehearsal*` Just recipes call matrix runner | none | CI report/workflow tests | historical Pages/report outputs retained | normal lint/mock CI and current report owners | workflow/recipe absence plus normal CI contracts | no provider launch in deletion slice | current workflow or published Pages consumer appears |
| CI rehearsal tests | none | dynamic loading of matrix/pages scripts under test | none | exact two-row ledger | test fixtures disposable; historical output retained | current CI recipe contracts | collect normal CI and verify recipes | lint/mock CI only | assertion proves maintained workflow |
| Grasp diagnostics | diagnostic owners call cache generation/feasibility | two diagnostic CLIs; no current Just/workflow recipe | none | two diagnostic test files | diagnostic JSON/report leaves disposable | new small household grasp-probe runtime for cache-required subprocess path | retained cache generation/cache tests plus exact import absence | planner feasibility/cache preflight | cache generation still imports a deleted diagnostic owner |
| Grasp diagnostic tests | direct diagnostic/report imports | CLI dynamic loading under test | none | exact two-row ledger | cache fixtures retained | retained cache and feasibility tests | focused cache/preflight suite | planner proof deterministic fixture | test proves retained cache semantics |
| Grasp diagnostic report split | `report.py` imports section functions | report rendering dispatch | none | report and diagnostic tests | current cleanup reports retained field-for-field | retained household report owner | report fixture comparison and diagnostic-name absence | deterministic report rerender | any non-diagnostic report field changes |

#### Wave 0 Evidence: Public Contract Trace And Fixture Index

Wave 0 reuses immutable deterministic evidence rather than copying schemas into
a second fixture vocabulary:

| Surface | Current trace / fixture owner | Frozen contract proof |
| --- | --- | --- |
| `apple2apple-grid` | `tests/unit/molmo_cleanup/test_apple2apple_test_grid.py` and Just recipe contract tests | dry-run grammar, Runtime Map Prior matrix, no provider |
| RAW-FPV | `tests/fixtures/agent_sdk_speedup_foundation/raw_fpv_*`, RAW-FPV MCP/recovery tests | public/private boundary, event/trace/live-status shape |
| B1 | `tests/fixtures/agibot_robot_map_12_context.completed.json` and `tests/contract/maps/test_b1_map12_*` | build, readiness, alignment, navigation, digest/provenance inputs |
| Direct runner | household runtime/run-artifact contract fixtures and checker run-result source tests | run-result, Agent View, map and privacy schemas |
| SDK mock/live | `tests/fixtures/agent_sdk_speedup_foundation/*` plus SDK profile/live-performance tests | OpenAI event, timing, status, trace, and run-result schemas; no provider launched in Wave 0 |
| Operator sessions | `tests/unit/operator_console/test_operator_session_followup.py` and state/launcher tests | steer, resume, next-goal, redaction and lifecycle transitions |
| Reports | `tests/contract/reports/test_molmo_cleanup_report.py` and artifact-report tests | deterministic rerender and retained artifact fields |
| Evals | eval CLI/runner/report tests and `tests/support/eval_runtime_map.py` | suite, trial, availability, grading and Runtime Map projection schemas |

Wave 0 ran only deterministic reads/tests. It did not launch providers, accept
the Omniverse EULA, publish a baseline/catalog, or move a robot.

### Wave 1: Migrate Minimal Contract And Result Ownership Atomically

Break one proven cycle at a time at its narrowest existing owner:

1. Manipulation SCC: move provenance constants and request/result/backend
   Protocol values plus their complete caller set to
   `household/manipulation_contract.py`; planners and backends depend on it,
   while the backend contract does not import planners.
2. Long-horizon SCC: move the pure spec/value layer and all consumers to
   `evals/long_horizon_contract.py`; grader depends on the contract and runner
   depends on the grader.
3. Eval CLI/runner SCC: remove runner's CLI back-import and migrate the full
   caller set so only CLI imports runner.
4. Console launcher/readiness SCC: move the shared error/value to a small
   console-owned contract; readiness does not import launcher.
5. Console interactions/state SCC: move operator-message artifact reading to a
   state-owned or narrow artifact reader, preserving `interactions -> state`
   direction.
6. Merge common direct/MCP run-artifact assembly and validation plus every
   direct/MCP/report/checker consumer in that seam into the existing
   `realworld_run_artifacts` owner. Keep thin direct/MCP adapters and the current
   dictionary schema; do not introduce a result dataclass unless two named
   consumers still require it.
7. Remove reverse package imports with their complete callers using the Wave 0
   edge matrix while retaining `launch.executor` typed dispatch and SDK live
   lifecycle ownership. Each cycle/edge slice is green and complete before the
   next begins.

Do not add generic repository-wide contracts, runtime services, dependency
injection, or application/container frameworks. Each new leaf must remove a
named cycle or duplicate contract interpretation.

### Wave 2: Prove Canonical Parity And Lock Dependency Direction

1. Verify that every Wave 1 owner has no old-path, reverse-edge, or unmigrated
   caller and that reports/graders consume canonical fields rather than
   reconstructing private projections.
2. Compare before/after direct and MCP artifact, privacy, provenance, and report
   fixtures field-for-field.
3. Prove SDK operator-message consumption no longer depends on console UI while
   steer/resume/next-goal behavior remains unchanged.
4. Activate all six SCC and five bidirectional-edge guards. No known cycle or
   forbidden reverse edge may remain after this wave.

No old import path remains as a facade. Stop if parity requires a public schema,
command, provider, or operator-lifecycle behavior change.

### Wave 3: Delete Completed Investigation And Rehearsal Stacks

Execute only the unconditional path ledger:

1. Retire robot-camera parity leaf-to-root in bounded path-manifest slices.
2. Retire CI rehearsal/Pages, including its prewarm caller and Just recipes.
3. Retire offline RAW-FPV probe/private-label/corpus tooling while retaining and
   proving the current runtime lane.
4. Retire the private Agent SDK perf matrix while retaining current metrics and
   profile behavior.
5. Extract grasp cache runtime dependencies, then retire diagnostic owners.

Each slice requires exact absence searches, import proof, focused tests, and
`--help` or Just dry-run proof for neighboring retained commands. At wave end,
run unit/contract suites plus named preservation gates.

### Wave 4: Collapse Conditional Workbenches Without Contract Changes

1. Preserve `just molmo::scene-camera-comparison`, its full parameterized
   render-only semantics, `comparison_manifest.json` field contract, and
   `camera_control_request.json`. Consolidate geometry/pose/image behavior under
   one owner; use fixed fixtures for verification and delete
   HTML/hydration/replay/lighting or redundant source-loader layers only after
   field-level parity proof.
2. Do not execute the current scene-camera default path if it implicitly accepts
   the Omniverse EULA. Verification uses deterministic fixtures and an explicit
   guarded availability/preflight result until an operator has separately
   accepted the EULA.
3. Reduce planner manipulation workbenches to retained feasibility, cache, and
   proof owners after moving any product-grade invariant into those owners.
4. Preserve generic Isaac runtime smoke. It may be split or moved in Wave 5,
   but it is not classified as a disposable workbench.
5. Keep B1 authoring deletion parked. Wave 5 migrates the reproducibility chain;
   a later deletion proposal must prove rebuild equivalence, not only digest
   identity.

Stop if scene-camera geometry/pose behavior or schema changes, or if planner
feasibility/cache/product proof becomes weaker.

### Wave 5: Move Product Subsystems Out Of Scripts

1. Move the active MolmoSpaces subprocess worker and its runtime dependencies
   into `roboclaws/backends/molmospaces/`; leave a module CLI at
   `python -m roboclaws.backends.molmospaces.worker`.
2. Move the active Isaac Lab worker and generic runtime-smoke implementation
   into `roboclaws/backends/isaaclab/`, keeping Isaac packages outside the
   normal `.venv` and preserving standalone launch behavior.
3. Migrate current B1 base-map build, augmentation, semantic projection,
   alignment/promotion, readiness, and navigation reproducibility into a
   package-owned B1 CLI. Keep review/authoring inputs until the package CLI can
   rebuild accepted assets and compare provenance/digests.
4. Split backend workers into protocol/dispatch, state,
   navigation/actions, capture/perception, and initialization owners.
5. Move the current cleanup checker from `scripts` into existing package
   owners: structural invariants under household validation and benchmark-only
   scoring under eval graders. Leave only a thin CLI.
6. Update Just, launch, operator-console, eval, report-rerun, and test callers
   forward-only; delete every replaced script owner in the completed slice.

Stop if package code still imports or executes a script path, B1 rebuild parity
is incomplete, direct/MCP artifacts differ, or a checker invariant lacks a
unique product-validation versus eval-grading owner.

### Wave 6: Split Retained Oversized Owners And Tests

Split behavior, not line ranges, in this order:

1. `operator_console/static/app.js`: native ES modules for app state, workflow
   model/view, launch, background tasks, run session, manual control, visual
   workspace, and HTTP/DOM helpers. Preserve UI behavior; `app.js` becomes a
   180-250 line composition entrypoint.
2. `operator_console/runtime_inventory.py`: inventory sources, task model,
   blocker policy, and host probes.
3. OpenAI live runtime: run configuration, retry model, provider racing, event
   log, history, image memory, grounded history, compaction, and event
   projection. Preserve provider and cost behavior.
4. Household runtime: navigation, perception, manipulation, completion, state,
   runtime-map targets/lifecycle, MCP adapter, episode adapter, and Agibot
   adapter.
5. World sampling: move scene catalog/sampling/scanner/validation to
   `worlds/molmospaces`; launch consumes an immutable `WorldSpec`.
6. Reports: first remove diagnostic sections and duplicate reconstruction in
   the existing household report owner. Move to `reports/household` only if a
   remaining dependency inversion requires it; split composer, semantic
   sections, tables, document, and styles by behavior.
7. Eval pipeline: suite loading, trial execution, live execution, grading, and
   aggregation; CLI only imports runner.
8. Planner proof request/feasibility and runtime-prior snapshot/lifecycle
   clusters along request, selection, validation, execution, and artifact
   ownership.

9. Split retained tests only where the new behavior owners make the boundary
   clearer: live runtime, backend, checker, household contract, report, eval,
   B1, scene sampler, and planner proof.
10. Add only genuinely shared builders under `tests/support`: household artifact
   fixtures, Isaac stage/prim/camera fakes, B1 proof writers, and eval runtime-map
   builders.
11. Parameterize repeated policy accept/reject matrices and malformed-source
   cases after keeping one domain-facing failure proof per consumer.
12. Replace JavaScript source-string/layout assertions with browser behavior
   tests for the same operator workflows.
13. Update `tests/conftest.py`, Just focused recipes, quality baselines, active
   docs, and current runbooks to the new node IDs. Historical logs stay intact.

No old module may remain as a re-export facade. All in-repo imports, tests,
docs, and recipes move in the same slice. A split fails if it introduces more
state copies, factories, adapters, Protocols, or registries than it removes.

Every retained test must prove caller-visible behavior, an artifact/schema
contract, a domain failure mode, an architecture/packaging invariant, or a real
regression. Pure layout, private-call, and redundant static-string tests do not
meet the value gate; routing, privacy, packaging, and retired-surface guards
remain when they are the direct proof of the contract.

### Wave 7: Telemetry, Status, And Final Cleanup

1. Delete retired-engine extraction and comparison branches from live
   performance reporting while preserving historical fixture readability where
   still required.
2. Reduce current Molmo status to a package-owned SDK status CLI below 250
   lines and migrate its documented command.
3. Remove empty packages, stale exports, dead dependencies, obsolete quality
   exceptions, and migration-only helpers proven unused after Waves 1-6.
4. Give every remaining oversized source/test file its final disposition and
   regenerate import, LOC, dependency, command, and artifact-contract metrics.
5. Update `ARCHITECTURE.md`, relevant human docs, `STATUS.md`, and the plan
   ledger to the implemented owners and final measurements.

## Verification Matrix

### Per Slice

- exact caller/import/subprocess/env/recipe/doc searches;
- touched-file Ruff and format checks;
- focused unit/contract tests;
- import and CLI/Just dry-run proof;
- `git diff --check` and no compatibility wrapper or stale old-owner path.

### Per Wave

- Wave 0: deterministic import graph, allowed-edge matrix, exact caller ledger,
  and public command/artifact/privacy fixture capture;
- Wave 1: focused SCC owners, direct/MCP artifact assembly, launch executor,
  SDK lifecycle, and console/eval contract tests;
- Wave 2: zero SCCs/forbidden edges, direct/MCP field-level result equivalence,
  report rerender, SDK mock, MCP contracts, and session
  steer/resume/next-goal tests;
- Wave 3: retained RAW-FPV, SDK metrics/profile, `apple2apple-grid`, B1
  readiness, neighboring command contracts, and exact retired-reference
  absence searches;
- Wave 4: fixed-fixture scene-camera contract under unchanged command/schema,
  planner feasibility/cache proof, and guarded Isaac availability evidence;
- Wave 5: Molmo and Isaac worker contracts, B1 build/augment/alignment/readiness/
  navigation reproducibility, checker/result schema, public launch executor,
  and zero package-to-script dependency;
- Wave 6: operator-console browser/host-runtime smoke, eval suites, direct
  household episodes, SDK mock/live proof, artifact/privacy contracts,
  collection identity, unit/contract/slow partitions, and focused Just recipes;
- Wave 7: historical performance fixtures, current SDK status/live proof,
  architecture/size/dependency ratchets, and final product proofs.

Named preservation gates:

- `apple2apple-grid`: `just molmo::apple2apple-grid mode=dry-run` plus its
  focused recipe/grid contracts;
- RAW-FPV: public direct-runner `camera-raw-fpv` product grammar/proof,
  MCP/checker contracts, and privacy assertion that excludes private labels;
- B1: build, augment, readiness, alignment, navigation, and before/after
  digest/provenance comparison under guarded availability, with no real motion;
- direct/SDK: canonical result/schema/privacy equivalence, direct map-build and
  cleanup product proofs, SDK mock, and the required guarded provider proof;
- scene-camera: unchanged Just grammar, existing result schema, deterministic
  geometry/pose fixtures, and explicit no-EULA-acceptance behavior.
- generic Isaac runtime smoke: `just harness::isaac-runtime-smoke` command
  contract,
  `tests/contract/dev_tools/test_isaac_runtime_preflight_just_recipe.py`,
  `tests/unit/molmo_cleanup/test_isaac_lab_runtime_smoke_checker.py`, and guarded
  availability evidence; do not execute a path that accepts the EULA unless an
  operator has accepted it separately.

### Final Deterministic Gates

```bash
uv sync --extra dev
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh --collect-only -q
./scripts/dev/run_pytest_standalone.sh -m "unit and not slow and not local" -q
./scripts/dev/run_pytest_standalone.sh -m "contract and not slow and not local" -q
./scripts/dev/run_pytest_standalone.sh -m slow -q
./scripts/dev/run_pytest_standalone.sh -q
```

Then run `just agent::eval recommend|execute` for the actual diff and budget.
Canonical direct-runner map-build and cleanup product proofs are required.
Runtime, console, provider, eval, artifact-selection, or backend-facing waves
also require the relevant guarded live/preflight/availability proof under repo
policy. A blocked Isaac proof must record the concrete EULA/readiness blocker;
the migration does not accept the EULA. Real-robot movement remains excluded.

## Failure Modes And Stop Gates

- A deleted surface has a current caller: stop that slice, classify the caller,
  and migrate it only if it is inside the preserved product shape.
- A structural move changes a public command, schema, privacy boundary, cost,
  provider behavior, or physical capability claim: stop for user review.
- A new abstraction lacks two named consumers or does not remove a proven
  dependency problem: delete it and keep the behavior with its concrete owner.
- A split only redistributes lines or leaves the old owner as a facade: reject
  the split.
- B1 package CLI cannot rebuild and verify current inputs, digest/provenance,
  readiness, and product commands: retain the complete required authoring path
  and keep its deletion parked.
- Scene-camera reduction loses geometry/pose regression detection: retain the
  minimum failing contract leaf and stop diagnostic deletion at that boundary.
- Product code still imports or executes `scripts`: Wave 5 cannot complete.
- Any known SCC or package bidirectional edge remains: Wave 2 cannot complete.
- Full deterministic or required live/preflight proof fails: repair within the
  current wave or report a concrete blocker; do not advance on partial proof.

## Acceptance

SUCCESS requires all waves to be complete and the structural ratchets to pass:

- every baseline oversized file has a final `DELETE`, `MERGE`, `SPLIT`, or
  justified `PARK` disposition; no retained entrypoint/facade/orchestrator or
  active script subsystem is at least 1,000 lines;
- net deletion, source/test LOC, and `>=500`/`>=800`/`>=1000` counts are
  reported against baseline, with the 45,000-52,000 deletion and
  150,000/90,000 source/test ceilings treated as campaign targets rather than
  behavior-overriding gates;
- zero known module SCCs, zero package bidirectional edges, no package-to-script
  dependency, and no product-to-console/eval/report inversion;
- all migrated active script entrypoints are at most 250 lines and no package
  imports or executes a script path;
- current launch grammar, direct/SDK product behavior, operator safety,
  artifact/privacy/provenance contracts, eval availability, B1 readiness, and
  planner feasibility remain proven;
- required deterministic and scoped live/preflight gates pass. If a required
  simulator/provider/hardware proof is unavailable, record the concrete
  repo-policy blocker and finish as `BLOCKED_NEEDS_LOCAL_VALIDATION`, not
  `SUCCESS`.

BLOCKED_NEEDS_DECISION applies when a current external/public consumer,
artifact-schema change, B1 reproducibility choice, public workflow removal, or
material live/hardware/cost expansion is required.

BLOCKED_NEEDS_LOCAL_VALIDATION applies when a required simulator, provider, or
hardware proof cannot run for a demonstrated environment reason.

## Rollback And Commit Discipline

- one green commit per bounded slice, using `type: description`;
- record a per-slice manifest of changed owners, migrated callers, schema
  fixtures, proof, and reverse dependencies;
- stage only task-owned paths and preserve concurrent work;
- use forward fixes during an active slice; revert a completed bad slice only
  after the manifest proves no later slice depends on its new owner, otherwise
  revert dependent slices in reverse order;
- never mix deletion, package movement, schema change, and UI behavior change
  in one commit;
- update this plan ledger after each completed wave, and update `STATUS.md` only
  when repo-level focus, next action, or blocker changes.

## Plan Ledger

- Current status: ACTIVE.
- Current wave: Wave 3, unconditional investigation/rehearsal deletion stacks.
- Completed waves: Wave 0 froze exact size/disposition and import-graph
  baselines, expanded the deletion consumer ledger and public fixture index,
  corrected the planned topology from five/four to six/five, and wired both
  removal-friendly ratchets into `verify::static`.
- Wave 1 completed slices: manipulation values and request/result/backend
  types moved to `household/manipulation_contract.py`; 39 package, script, and
  test callers migrated without facades; the six-module SCC is absent from the
  refreshed graph baseline. Focused behavior proof passed, with the four
  unrelated loopback-only visual-grounding tests unavailable in the worker
  socket sandbox.
- Wave 1 completed slices: long-horizon specs and pure values moved to
  `evals/long_horizon_contract.py`; runtime behavior remains in
  `long_horizon.py`, the grader depends on the contract, and the runner depends
  directly on grader/contract. The SCC is absent from the refreshed baseline;
  177 focused eval tests and static gates pass.
- Wave 1 completed slices: the eval runner no longer imports CLI or exposes a
  duplicate module entrypoint; `evals.cli -> evals.runner` is the only product
  direction. The SCC is absent, CLI grammar/exit behavior is unchanged, and
  245 focused tests plus root CLI/source contracts pass.
- Wave 1 completed slices: `ConsoleLaunchError` moved to
  `operator_console/launch_contract.py`; readiness no longer imports launcher
  and the SCC is absent. The full operator-console suite passes, and a root
  host-runtime smoke served `/`, `/api/routes`, and `/api/runtime/tasks` with
  valid responses before clean operator shutdown.
- Wave 1 completed slices: operator-message JSONL reading and its normalized
  summary moved to `operator_console/operator_message_artifacts.py`;
  `operator_console/state.py` consumes that artifact owner and no longer
  imports interactions, so the SCC is absent. The full operator-console suite,
  root host HTTP inventory smoke, and static/architecture gates pass.
- Wave 1 completed slices: `realworld_contract_init.py` now receives its
  initialization values and helper callables explicitly from
  `household_runtime_contract.py` instead of importing that owner back. The
  final module SCC is absent; 123 runtime/MCP contract tests and all static
  ratchets pass without increasing frozen quality debt.
- Wave 1 completed slices: shared direct/MCP artifact paths, goal/completion
  status, public observation projections, evidence metadata, runtime-prior
  summaries, robot-view metadata, metadata merging, and JSON writing now have
  one interpretation in `realworld_run_artifacts.py`. The MCP adapter retains
  its distinct timing/diagnostic/server behavior; downstream producer,
  checker, report, privacy/schema, and static gates pass with 29 net lines
  removed and no dictionary-schema change.
- Wave 1 completed slices: immutable provider/model catalog specs, constants,
  lookup, normalization, capabilities, and route payloads moved to
  `core/provider_catalog.py`; agent readiness, environment/runtime settings,
  retired-engine policy, and CLI remain in `agents/provider_registry.py`.
  Every moved-symbol caller uses the core owner directly, the old surface is
  absent, `agents <-> household` is removed, and bidirectional pairs decrease
  from five to four. Provider payload/readiness/CLI parity, full root
  operator-console tests, and static ratchets pass.
- Wave 1 completed slices: generic structured JSONL issue parsing and the
  file-backed operator-message/resume queue protocol moved to
  `core/jsonl_sources.py` and `core/operator_messages.py`; the two old console
  owners were deleted without facades. Agents and household now consume core
  directly, removing `agents <-> operator_console` and
  `household <-> operator_console`; bidirectional pairs decrease from four to
  two. Full root operator-console, household MCP, SDK resume/handoff,
  session-live, and static ratchets pass.
- Wave 1 completed slices: agent-engine retirement policy, backend catalog,
  environment setup/provenance, goal contracts, task intent/surface specs,
  checker policy, open-ended artifact validation, and generated-mess threshold
  moved from launch/product owners to single core owners. All callers migrated
  directly and nine obsolete launch modules were deleted without facades;
  `agents -> launch` and `household -> launch` are absent, leaving zero module
  SCCs and zero bidirectional package pairs. Root launch, agent, operator,
  CLI/Just, MCP, artifact/privacy/schema, and static gates pass.
- Wave 2 completed: frozen direct/MCP artifact, privacy, provenance, report,
  eval, SDK, and operator lifecycle fixtures pass field-for-field. A proof pass
  exposed nine residual `agents -> household` edges and one
  `agents -> reports` inversion hidden by the zero-pair metric; pure RAW-FPV,
  scan-profile, task-intent, robot-view, timing/performance, and visual-slot
  contracts moved to core/agents owners, all callers migrated directly, and
  six old modules were deleted without facades. Both Wave 1-2 policy guards are
  now enforced green with zero violations; root parity/loopback and static
  suites pass, and oversized modules decrease from 76 to 75.
- Wave 3 completed slice: the robot-camera apple-to-apple/visual-parity stack,
  two parity-only USD probes, seven dedicated tests, and its terminal active
  capsule were deleted leaf-to-root. The 26-file slice removes 18,132 lines;
  exact current caller searches are empty, 105 retained scene-camera/grid/Isaac
  contracts pass, `apple2apple-grid` dry-run remains provider-free, and the
  guarded Isaac preflight stops before EULA acceptance. Architecture/static
  gates stay green and oversized modules decrease from 75 to 72.
- Wave 3 completed slice: the CI rehearsal/Pages package owner, three scripts,
  two dedicated tests, and both `ci-rehearsal*` recipes were deleted atomically.
  The seven-path slice removes 1,567 lines; exact current caller searches are
  empty, normal lint/mock CI and generic Pages reporting remain, focused
  workflow/report/Just contracts and the full mock gate pass, and no provider
  route was invoked.
- Wave 3 completed slice: the offline RAW-FPV probe, its mechanically
  discovered scoring leaf, private-label/corpus generators, two dedicated
  tests, and terminal active capsule were deleted together. The seven-path
  slice removes 5,989 lines; exact current-code searches are empty, 306
  retained RAW-FPV guidance/recovery/lane/privacy/checker/MCP tests pass, and
  direct-runner `camera-raw-fpv` grammar remains valid. The deterministic
  `molmo-realworld-raw-fpv` product gate passes after its stale harness recipe
  was repaired to provide the required Base Metric Map bundle. Static and
  architecture ratchets remain green and oversized modules decrease from 72
  to 70; no provider, publication, or physical-robot action occurred.
- Wave 3 completed slice: the private Agent SDK performance matrix and its
  dedicated test were deleted, and the active SDK-spike capsule now treats the
  retained manifest/fixtures as historical evidence rather than advertising a
  retired maintainer command. The two-path slice removes 2,126 lines; exact
  current caller and instruction searches are empty, and 197 retained SDK
  runtime, metrics-source, performance-profile, status, and live-performance
  tests pass without provider calls. Architecture/static ratchets remain green
  and oversized modules decrease from 70 to 68.
- Wave 3 completed slice: the grasp-pose cache's byte-identical 12,350-byte
  MolmoSpaces probe and subprocess wrapper moved to the focused
  `grasp_probe_runtime.py` owner, and cache reporting moved to
  `report_sections_grasp_generation.py`. The two standalone diagnostic owners,
  two CLIs, two dedicated tests, old mixed report-section path, and diagnostic
  report entrypoints were then removed without facades. Seven retired paths
  remove 2,226 lines while the two retained owners contain 587 lines; 87 cache,
  pose-policy, planner-feasibility, checker, report, and Just contracts pass.
  The architecture baseline improves to 247 modules and 734 edges with zero
  SCCs/pairs; oversized modules remain at 68. Wave 3 is complete.
- Planning-loop result: CONVERGED after two rounds. Round 1 entropy, docs-grill,
  and skeptic scouts found speculative layers, unsafe wave order, incomplete
  caller paths, proxy-metric gates, and preservation ambiguity. Round 2 verified
  those findings were closed and found only mechanical contradictions, now
  resolved in this artifact. No unresolved HIGH blocker or required product
  decision remains.
- Accepted scope: the user authorized implementation of this complete plan via
  `intuitive-flow` on 2026-07-30.
- Accepted planning defaults: preserve scene-camera command, parameter behavior,
  and schema; preserve full B1 reproducibility until a package CLI proves
  rebuild parity; preserve generic Isaac runtime smoke; keep launch executor and
  SDK lifecycle with their current durable owners.
- Rejected: generic repository-wide application/contracts frameworks, mandatory
  run-result dataclass, raw LOC as a behavior-overriding success gate, universal
  eight-file slice ceilings, wholesale report relocation without an observed
  inversion, and blanket test splitting/deletion by size or source shape.
- Parked: B1 authoring deletion beyond proven package-owned rebuild parity,
  publication, real-robot movement, EULA acceptance, public contract redesign,
  provider bakeoff, and unrelated feature work.
- Wave 4 completed slice: eight redundant scene-camera source/presentation
  owners were removed after fixed-fixture parity. Geometry, pose, image,
  lighting, replay, USDA, manifest, and camera-control-request behavior now has
  retained package owners, while `report.html` is a compact artifact index.
  The slice removes 2,667 lines and adds 385 (2,282 net); 103 focused contracts
  and the static gate pass. The graph improves to 239 modules / 711 edges with
  zero SCCs/pairs, and oversized modules remain at 68. The public recipe keeps
  all nine parameters and now requires explicit prior
  `OMNI_KIT_ACCEPT_EULA=YES`; guarded host preflight passes runtime/GPU/Isaac
  Lab checks and blocks only on unaccepted EULA, which this migration did not
  accept.
- Next action: finish Wave 4 by reducing planner manipulation diagnostic
  workbenches to the retained feasibility, cache, request, and proof owners
  without weakening product proof.
