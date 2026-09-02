# Phase 4 Live Proof Receipt

- Timestamp: `2026-09-02T06:23:00Z` (`2026-09-02 14:23` Asia/Shanghai)
- RESULT_STATUS: `PASS`
- Pipeline: `grounding-dino`
- Adapter requirement: real
- Model: `IDEA-Research/grounding-dino-base`
- Product run: `output/state-first-context-manager/dino-map-build/0902_1423/seed-7/`

## Blocker Resolution

The earlier readiness failure was a loopback connection refusal because no
visual-grounding sidecar was listening on `127.0.0.1:18880`. It was not a model,
GPU, dependency, or inference failure. Starting the existing real-router
sidecar with the repo's `.venv-visual-grounding` environment made the guarded
readiness command pass:

```bash
.venv-visual-grounding/bin/python \
  -m roboclaws.household.visual_grounding_sidecar.service \
  --pipeline real-router --adapter-mode real
.venv/bin/python \
  -m roboclaws.household.visual_grounding_sidecar.readiness \
  --pipeline grounding-dino
```

Readiness output:

```text
visual grounding readiness ok: pipeline=grounding-dino base_url=http://127.0.0.1:18880
```

## Product Proof

The existing public route completed without provider, lane, baseline, or
launch-axis substitution:

```bash
just run::surface \
  surface=household-world \
  world=molmospaces/procthor-10k-val/0 \
  backend=mujoco \
  preset=map-build \
  agent_engine=direct-runner \
  evidence_lane=camera-grounded-labels \
  camera_labeler=grounding-dino \
  seed=7 \
  scenario_setup=baseline \
  output_dir=output/state-first-context-manager/dino-map-build \
  scene_source=procthor-10k-val \
  scene_index=0 \
  map_bundle=assets/maps/molmospaces/procthor-10k-val/0
```

Observed result:

- `terminate_reason`: `map_build_baseline complete`
- 35 camera-grounded events and 35 raw FPV observations
- 238 detector candidates, zero failures, and 35 `ok` pipeline statuses
- `sidecar_status`: `available`
- `private_truth_included`: `false`
- Runtime Metric Map, trace, report, readiness, and robot-view artifacts written

Content digests:

| Artifact | SHA-256 |
|---|---|
| `run_result.json` | `7c44cb810338154bf27d50d4dc7084389ec6660ba9ad2b558b6b6adb3b30b1d1` |
| `trace.jsonl` | `7c42320df8d7a3e20102254f5e747e1d6d0a035ba50320c088529586af3deada` |
| `report.html` | `a0ec65eb54acb6b0ac7bbd9e41facabb630757abb7fbe8b97f5414e3cebfdecc` |
| `runtime_metric_map.json` | `fe2e12ae7b9267a061986496dcdf165c9c8534819bcfcb7f7d3ad50bad6fda7e` |
| `visual_grounding_readiness.json` | `3e2db29e15302efecb264f5c66fa29ca3edfd9c89e82666a9e377d50a4b300bf` |

## Automated Operator-Console Proof

The existing console was served on `http://127.0.0.1:8766/` because port 8765
was occupied by an unrelated process. Headless browser QA selected Build Map
and verified the existing route values (`openai-agents-sdk`,
`camera-grounded-labels`, `kimi-openai-chat`, `map-build`), the generated
command's `camera_labeler=grounding-dino`, provider/MCP readiness, disabled
movement controls, loaded previews, zero failed requests, and zero browser
console errors. Desktop and 390 px layouts had no horizontal overflow.

Screenshots:

| Artifact | SHA-256 |
|---|---|
| `output/state-first-context-manager/operator-console-proof.png` | `2ef33fc1bbd8026c103b49dd08dbf0b33c05629b25669423ad40081be612c0c4` |
| `output/state-first-context-manager/operator-console-proof-mobile.png` | `4d70db38c7fb4a2eb3a42a1f7e4da0b987469414421c501b9414a841ea9acc6f` |

This automated checkpoint covers route display, metadata, readiness, safety
state, assets, and responsive rendering. It does not claim a provider-backed
agent run or authorize physical robot movement.
