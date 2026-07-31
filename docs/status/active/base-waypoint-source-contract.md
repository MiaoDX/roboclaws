# Base Waypoint Source Contract

Source plan: `docs/plans/2026-06-19-base-waypoint-source-contract.md`

Latest user intent: approved implementation via `$intuitive-flow`.

Current slice: implemented and verified.

Last proven evidence:

- Bundle-backed runtime preserves canonical artifact waypoint ids/source/pose/
  room fields and strips private `fixture_ids`.
- Product runtime without a selected map bundle fails loudly unless an internal
  test/offline synthetic opt-in is passed.
- `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=map-build agent_engine=direct-runner evidence_lane=world-public-labels seed=7 scenario_setup=baseline robot_views=off`
  passed and produced
  `output/household/household-world/map-build/direct-world-public-labels/0619_2235/seed-7/run_result.json`
  with `base_navigation_map.source=map_artifact_inspection_waypoints`,
  14/14 source/runtime waypoints, and 14/14 visited waypoints.
- All 16 committed `assets/maps/molmospaces/*/*` bundles passed
  `python -m roboclaws.maps.bundle`.

Known adjacent non-blockers:

- Cleanup relocated-object product run exercised the same waypoint projection
  and visited 14/14 artifact waypoints, but exited 1 on cleanup semantic
  placement score.
- Camera-grounded map-build exercised the projection, but exited 1 because the
  local Grounding-DINO sidecar was not reachable.

No-touch scope:

- `docs/plans/refactor-python-quality-backend-entropy*.md`
- `scripts/molmo_cleanup/summarize_live_run.py`
- `tests/unit/molmo_cleanup/test_summarize_live_run.py`
- `docs/status/active/2026-06-18-sdk-storage-targets.md`

Stop condition:

- canonical bundle waypoints are projected with artifact ids preserved;
- product runtime without a bundle fails loudly;
- offline/synthetic no-bundle generation remains explicit;
- focused tests and bundle checks run, with product-run proof run or blocked
  local-validation reason recorded.

Stop condition status: satisfied.
