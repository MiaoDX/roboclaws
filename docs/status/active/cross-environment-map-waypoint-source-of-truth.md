# Cross-Environment Map Waypoint Source Of Truth

Source plan:
`docs/plans/2026-06-20-cross-environment-map-waypoint-source-of-truth.md`

Latest user intent: approved implementation via `$intuitive-flow`.

Current slice: guardrails and active sampler bundle refresh complete; final
acceptance audit passed.

Completed:

- Added strict `validate_base_navigation_map_v1_bundle()` product gate.
- B1 base-map generation and Digital Twin sidecar generation now call the
  strict validator.
- Added shared area-based `BaseWaypointBuilder` and wired B1 / Map 12 through
  it.
- Split MolmoSpaces Base Navigation Map preparation away from
  `RealWorldCleanupContract` / Agent View projection.
- Regenerated `assets/maps/molmospaces/procthor-10k-val/0` as a fixture-free
  strict Base Navigation Map v1 bundle with 7 rooms, 7 base waypoints, and 0
  static landmarks.
- Regenerated the 16 active MolmoSpaces sampler bundles as fixture-free strict
  Base Navigation Map v1 bundles; generation manifest validation reported
  `ok=true` for every target and `static_landmark_count=0`.
- Removed product Agent View snapshot fallback; product snapshots now require
  a selected source bundle.
- Runtime product map selection validates strict Base Navigation Map v1 and
  consumes artifact-authored base waypoints.
- Product checkers and product snapshot copy paths now validate strict Base
  Navigation Map v1 by default. Rich Agent View bundle export/checking is an
  explicit legacy opt-in path.
- Updated product checkers for canonical area-inspection waypoint ids and
  semantic-success evidence.

Last proof:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/contract/maps/test_nav2_map_bundle_contract.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_contract.py \
  tests/contract/molmo_cleanup/test_molmospaces_realworld_cleanup.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py \
  tests/contract/dev_tools/test_task_agent_just_recipes.py

ruff check \
  roboclaws/household \
  roboclaws/maps \
  scripts/maps \
  scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
  scripts/molmo_cleanup/realworld_base_navigation_map_checker.py \
  tests/contract/maps \
  tests/contract/molmo_cleanup/test_molmospaces_realworld_cleanup.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py \
  tests/contract/dev_tools/test_task_agent_just_recipes.py

.venv/bin/python scripts/maps/generate_molmospaces_scene_bundles.py \
  --active-sampler-scenes \
  --force \
  --json

for d in <16 active sampler bundle dirs>; do
  .venv/bin/python -m roboclaws.maps.bundle "$d" --json
done
```

Previous product proof:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/contract/maps/test_generate_molmospaces_scene_bundles.py \
  tests/contract/maps/test_nav2_map_bundle_contract.py \
  tests/contract/maps/test_runtime_map_prior_snapshot.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_contract.py \
  tests/contract/checkers/test_realworld_base_navigation_map_checker.py

ruff check \
  roboclaws/household \
  roboclaws/maps \
  scripts/maps \
  scripts/molmo_cleanup/check_molmo_realworld_cleanup_result.py \
  scripts/molmo_cleanup/realworld_base_navigation_map_checker.py \
  tests/contract/maps \
  tests/contract/checkers/test_realworld_base_navigation_map_checker.py \
  tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py

just run::surface \
  surface=household-world \
  world=molmospaces/procthor-10k-val/0 \
  backend=mujoco \
  preset=cleanup \
  agent_engine=direct-runner \
  evidence_lane=world-public-labels \
  seed=7 \
  scenario_setup=relocate-cleanup-related-objects \
  relocation_count=5
```

Product proof artifact:
`output/household/household-world/cleanup/direct-world-public-labels/0621_1719/seed-7/run_result.json`

Key proof facts:

- `nav2_map_bundle.source_bundle_root` is
  `assets/maps/molmospaces/procthor-10k-val/0`.
- `nav2_map_bundle.snapshot_complete` is `true`.
- Runtime observed object count is 5.
- Copied snapshot `semantics.json` has 7 rooms, 7 base waypoints, and 0
  `static_landmarks`; refreshed active sampler bundle manifests report 4-10
  rooms/base waypoints per scene and 0 `static_landmarks`.
- Runtime static map fixture count is 0.

No-touch scope:

- Existing unrelated refactor/python-quality files.
- Existing unrelated live runtime / JSON source / report changes.
- Existing untracked SDK storage active note.

Cleanup follow-up:

- Stale synthetic/no-bundle test helpers and legacy rich Agent View bundle
  surfaces are being removed. Product, smoke, and test helpers now select a
  strict Base Navigation Map bundle instead of authoring map context from Agent
  View.
