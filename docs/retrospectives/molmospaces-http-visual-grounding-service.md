# MolmoSpaces HTTP Visual Grounding Service

Owner/session: completed Codex thread
Started: 2026-05-25 20:24 Asia/Shanghai
State: complete

## Scope

Implement ADR-0133 and `docs/plans/molmospaces-http-visual-grounding-service.md`
through the direct `intuitive-flow` route. This file tracks standalone progress
only; the ADR and plan remain the source of truth.

## Source Of Truth

- ADR: `docs/adr/0133-use-http-visual-grounding-service-for-real-camera-labels.md`
- Plan: `docs/plans/molmospaces-http-visual-grounding-service.md`

## Latest Evidence

- Adapter readiness now reports Grounding DINO and YOLOE dependencies importable
  in this checkout, MiMo v2 Omni hosted config present as `bearer_configured`,
  and Qwen3-VL still missing hosted/local config. The sidecar catalog redacts
  credentials.
- Fake HTTP contract path-backed benchmark passed:
  `output/visual-grounding-benchmark/path-backed-contract-fake/`.
- Direct fake HTTP cleanup transport control passed:
  `output/molmo/direct-camera-labels-fake-http/0525_2252/seed-7/report.html`.
  It used `visual_grounding_pipeline_id=fake-http`, made 14
  `declare_visual_candidates` calls over the HTTP sidecar, produced 14
  candidates, reached sweep coverage `1.0`, and ended as `partial_success`.
- MCP smoke fake HTTP cleanup transport control passed:
  `output/molmo/mcp-camera-labels-fake-http/0525_2253/seed-7/report.html`.
  It used `visual_grounding_pipeline_id=fake-http`, made 14
  `declare_visual_candidates` calls through the MCP server path, produced 14
  candidates, reached sweep coverage `1.0`, and ended as `partial_success`.
- Real hosted MiMo direct-producer path-backed RAW_FPV benchmark passed:
  `output/visual-grounding-benchmark/path-backed-mimo-v2-omni-direct-0525_202437/`.
  It ran 28 observations with zero failures/timeouts, 71 candidates, 28
  overlays, token usage reported, recall `0.268293`, precision `0.15493`, and
  `auth_mode=bearer_configured`.
- Real Grounding DINO proposer path-backed benchmark passed:
  `output/visual-grounding-benchmark/path-backed-grounding-dino-real-0525/`.
  It ran 28 observations with zero failures/timeouts, 58 candidates, 28
  overlays, recall `0.219512`, precision `0.155172`, and average latency
  `4685.857ms`.
- Real YOLOE proposer path-backed benchmark passed:
  `output/visual-grounding-benchmark/path-backed-yoloe-real-0525/`. It ran 28
  observations with zero failures/timeouts, 16 candidates, 28 overlays, recall
  `0.04878`, precision `0.125`, and average latency `95.679ms`.
- Combined proposer comparison ranked Grounding DINO over YOLOE:
  `output/visual-grounding-benchmark/path-backed-proposer-real-comparison-0525/`
  with score `0.275042` versus `0.170579`.
- Grounding DINO plus MiMo v2 Omni refiner benchmark passed:
  `output/visual-grounding-benchmark/path-backed-grounding-dino-mimo-refiner-real-0525/`.
  It ran 28 observations with zero failures/timeouts, 37 candidates, 28
  overlays, recall `0.195122`, precision `0.216216`, average latency
  `31253.429ms`, and total reported tokens `109909`.
- Direct sim-control cleanup report passed:
  `output/molmo/direct-camera-labels-sim-baseline/0525_2206/seed-7/report.html`.
  It used `visual_grounding_pipeline_id=sim`, produced 13 candidates, placed 10
  observed handles, reached sweep coverage `1.0`, and advisory exact private
  matches were `8/10`.
- Direct best proposer-only cleanup report passed:
  `output/molmo/direct-camera-labels/0525_2132/seed-7/report.html`. It used
  `visual_grounding_pipeline_id=grounding-dino`, produced 20 candidates, placed
  4 observed handles, reached sweep coverage `1.0`, and advisory exact private
  matches were `3/10`.
- MCP smoke cleanup report for the best proposer-only lane passed:
  `output/molmo/mcp-camera-labels-grounding-dino/0525_2141/seed-7/report.html`.
  It used `visual_grounding_pipeline_id=grounding-dino`, made 14
  `declare_visual_candidates` calls, produced 20 candidates and 20 overlays,
  placed 4 observed handles, reached sweep coverage `1.0`, and advisory exact
  private matches were `3/10`.
- First direct Grounding DINO plus MiMo refiner cleanup attempt with the default
  20s client timeout produced useful failure evidence, not a pass:
  `output/molmo/direct-camera-labels-grounding-dino-mimo-refiner/0525_2145/seed-7/report.html`.
  It recorded 14 visible `timeout` pipeline failures, zero fabricated sim
  labels, zero candidates, and failed the cleanup checker.
- Direct best proposer-plus-refiner cleanup report passed after raising
  `VISUAL_GROUNDING_TIMEOUT_S=240`:
  `output/molmo/direct-camera-labels-grounding-dino-mimo-refiner-240s/0525_2153/seed-7/report.html`.
  It used `visual_grounding_pipeline_id=grounding-dino+mimo-v2-omni`, made 14
  `declare_visual_candidates` calls, ran 14 proposer stages and 14 refiner
  stages, produced 17 candidates and 17 overlays, placed 7 observed handles,
  reached sweep coverage `1.0`, advisory exact private matches were `5/10`, and
  reported MiMo token usage totaled `68080`.
- Local live Codex camera-labels cleanup report now passes the checker after
  the Agent View contract fix:
  `output/molmo/codex-camera-labels-grounding-dino/0525_2216/seed-7/report.html`.
  The run used the real `grounding-dino` pipeline, reached sweep coverage
  `1.0`, made 16 `declare_visual_candidates` calls, recorded 24 model-declared
  camera candidates, cleaned 4 public candidate chains, produced 3 exact private
  matches out of 10 generated mess objects, and ended as `partial_success`
  without falling back to simulated labels.
- The checker now accepts public main-cleanup-agent model-declared retry
  observations in camera-labels Agent View and validates expected external
  visual-grounding pipelines by membership in `visual_grounding_pipeline_ids`
  when a later manual retry is also present.
- Focused artifact scan over the new cleanup outputs found no raw bearer token,
  API-key, or provider URL strings. Reports preserve `auth_mode` such as
  `bearer_configured` only.

## Current Selection

- Best proposer-only pipeline for cleanup promotion: `grounding-dino`.
- Best proposer-plus-refiner pipeline for cleanup promotion:
  `grounding-dino+mimo-v2-omni`, but only with an explicit longer client
  timeout because the default 20s timeout is too short for the hosted refiner.
- Direct VLM lane: `mimo-v2-omni-direct` has benchmark evidence but no same-run
  end-to-end cleanup report yet.
- Qwen3-VL remains a designed optional lane; local or hosted config is not
  available in this checkout.

## Next Action

Commit or ship this scoped change separately when the broader dirty worktree is
ready.

## Completion Audit

All explicit ADR-0133 and plan hard gates are matched to evidence:

- Public profiles remain `world-labels`, `camera-raw`, and `camera-labels`;
  `visual_grounding` is a runner/server pipeline axis, not a new public MCP
  tool. Evidence: `just task::run molmo-cleanup ... camera-labels
  visual_grounding=...`, `roboclaws/molmo_cleanup/realworld_mcp_server.py`, and
  `roboclaws/molmo_cleanup/realworld_contract.py`.
- HTTP service boundary exists with provider-neutral request/response schema,
  JSON image bytes, optional bearer auth, timeout/failure handling, and redacted
  config metadata. Evidence: `roboclaws/molmo_cleanup/visual_grounding.py`,
  `scripts/visual_grounding/serve_visual_grounding_service.py`, and
  `tests/unit/molmo_cleanup/test_visual_grounding.py`.
- Direct, MCP smoke, and live Codex routes share the server-side integration
  through `declare_visual_candidates`; agents do not receive visual-grounding
  service URLs, credentials, image paths, or model-host details. Evidence:
  fake HTTP direct/MCP reports plus the local live Codex report above.
- `camera-labels visual_grounding=sim` remains the control baseline with
  `simulated_camera_model` pipeline provenance. Evidence:
  `output/molmo/direct-camera-labels-sim-baseline/0525_2206/seed-7/report.html`.
- Non-sim service failures are visible and do not fabricate simulator labels.
  Evidence: contract tests for HTTP failure/no fallback plus the default-timeout
  `grounding-dino+mimo-v2-omni` report with visible timeout failures and zero
  candidates.
- Reports/checkers preserve pipeline id, stage id, model id, status, latency,
  candidate count, unresolved count, duplicate rate, failure evidence, overlays,
  and Visual Grounding versus Destination Hint quality. Evidence:
  `scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py`,
  `roboclaws/molmo_cleanup/report.py`, checker/report tests, and the cleanup
  reports above.
- Perception-isolated benchmark harness and corpus path exist and can rank
  proposer-only, proposer-plus-refiner, and direct-producer pipelines. Evidence:
  `scripts/visual_grounding/`, `harness/visual_grounding/`, benchmark tests, and
  the DINO, YOLOE, DINO+MiMo, and MiMo direct benchmark artifacts above.
- Proposer comparison ranks Grounding DINO over YOLOE on identical frames and
  hints; end-to-end promotion is capped to sim, best proposer-only, best
  proposer-plus-refiner, and no required direct-VLM cleanup lane. Evidence:
  comparison and cleanup artifacts above.
- Core cleanup dependencies remain unchanged; real model dependencies are
  optional extras (`visual-grounding-dino`, `visual-grounding-yoloe`,
  `visual-grounding-qwen3vl`) and sidecar/local-dev gates. Evidence:
  `pyproject.toml` plus `uv sync --extra ...` verification.
- Credential hygiene passed: reports/artifacts preserve redacted auth modes
  such as `bearer_configured`, and focused scan found no bearer/API-key matches.

Deferred items are explicitly non-blocking or later-phase scope: fixed/custom
YOLO weights, Qwen3-VL execution, real Agibot Stage-0 frame measurement, and
continuous route perception.

## Verification

- `uv sync --extra dev --extra molmospaces --extra visual-grounding-dino --extra visual-grounding-yoloe`
  completed against the repo-local `.venv`.
- `.venv/bin/ruff check scripts/visual_grounding tests/contract/visual_grounding tests/unit/molmo_cleanup/test_visual_grounding.py`
  passed.
- `./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_visual_grounding.py tests/contract/visual_grounding -q`
  passed: 28 tests.
- `.venv/bin/python scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py output/molmo/codex-camera-labels-grounding-dino/0525_2216/seed-7/run_result.json --expect-backend molmospaces_subprocess --expect-policy codex_agent --expect-profile camera-labels --min-generated-mess-count 10 --require-agent-driven --require-robot-views --require-camera-model-policy --expect-visual-grounding-pipeline grounding-dino --allow-partial-cleanup --min-sweep-coverage 1.0`
  passed.
- `.venv/bin/ruff check scripts/visual_grounding scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py tests/contract/visual_grounding tests/unit/molmo_cleanup/test_visual_grounding.py tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py`
  passed.
- `./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_visual_grounding.py tests/contract/visual_grounding tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py -q`
  passed: 71 tests.
- `just task::run molmo-cleanup direct camera-labels visual_grounding=fake-http output_dir=output/molmo/direct-camera-labels-fake-http`
  passed against a local `fake-http` sidecar on `127.0.0.1:18880`.
- `just task::run molmo-cleanup mcp-smoke camera-labels visual_grounding=fake-http output_dir=output/molmo/mcp-camera-labels-fake-http`
  passed against the same local `fake-http` sidecar.
- `rg -n "Bearer |VISUAL_GROUNDING_API_KEY|sk-[A-Za-z0-9]" ...` over the
  visual-grounding benchmark and cleanup output directories found no matches.
- `git diff --check` passed.
- `STATUS.md` was checked after verification and left unchanged because this
  remains standalone concurrent work tracked in this file.

## Touched Areas

- `roboclaws/molmo_cleanup/visual_grounding.py`
- `roboclaws/molmo_cleanup/realworld_contract.py`
- `roboclaws/molmo_cleanup/realworld_mcp_server.py`
- `python -m roboclaws.household.household_world_episode`
- `examples/molmo_cleanup/molmo_realworld_cleanup_agent_server.py`
- `scripts/visual_grounding/`
- `scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py`
- `scripts/molmo_cleanup/run_molmo_realworld_agent_mcp_smoke.py`
- `docs/human/molmospaces-settings.md`
- `just/README.md`, `just/harness.just`, `just/molmo.just`, `just/agent.just`
- `tests/contract/visual_grounding/`
- `tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py`
- `tests/unit/molmo_cleanup/test_visual_grounding.py`

## Notes

- `127.0.0.1:18880` was cleared after the latest runs; no visual-grounding
  sidecar is intentionally left running.
- The capped end-to-end cleanup evidence now covers `sim`, best proposer-only,
  and best proposer-plus-refiner lanes. The direct VLM cleanup lane remains
  optional/open.
- Remaining promotion gate: completion audit against ADR-0133 plus the plan.
