# B1 / Map 12 Verified Map-Scene Alignment

Current status: B1 / Map 12 geometry alignment is globally verified from the
seven manually picked `anchor_role=alignment` anchors in the committed
manifest, and the first residual-backed robot-consumption proof now passes.
The official residual artifact reports `selected_transform_type=rigid_2d`,
mean residual `0.352908 m`, p90 `0.491765 m`, and max `0.502064 m`.
`output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json`
applies two Map12 navigation-memory points as B1 scene robot poses and captures
same-pose FPV/Chase evidence. Room/object label projection is still separate
and needs additional `anchor_role=semantic` room-interior anchors with reviewed
`navigation_area_id` / `asset_partition_id` values.
Agent-visible runtime-prior consumption now preserves B1
`digital_twin_capabilities` plus `capability_summary` through
`RealWorldCleanupContract` and the live MCP/runtime map payload. The same
surface names render/observation readiness for same-pose FPV/Chase/topdown
evidence and keeps `B1_floor2_slow` explicitly blocked as the default visual
route until same-frame, same-pose render proof exists.

Blocker fingerprint:

- blocker_kind: `b1_map12_isaac_same_pose_camera_proof`
- root_cause_classification: passed for preview-grade kinematic pose-driven
  Isaac robot-view proof
- last_decision_delta: geometry alignment and the first robot-consumption proof
  are no longer blockers, and the explicit runtime-prior consumer chain now
  exposes B1 navigation/render capability status to agent-visible MCP/runtime
  map context while preserving blocked room/object/manipulation status.

Last proven evidence:

- `output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json`
  is the current cropped B1 Gaussian top-down packet. It records
  `crop_max_z=1.8`, `geometry_status=rendered_gaussian_scene_topdown`, explicit
  camera height/FOV, and ray-plane `scene_xyz` mapping. The old
  `output/b1-map12/runtime-delete-smoke/review_labels_topdown.png` source-map
  frame image was deleted locally because it was a misleading intermediate, not
  current alignment evidence.
- Automatic and bbox-derived alignment probes were retired because they were
  easy to confuse with accepted evidence. The current alignment path is manual
  Map12/scene anchors, residual fitting, and recorded-camera projection only.
- `docs/status/active/b1-map12-scene-correspondences-draft.json` snapshots the
  seven operator-picked manual draft anchors from the ignored `tmp/` export so
  the local probe is reproducible. The anchors now explicitly declare
  `anchor_role=alignment`; they intentionally remain `review_status=proposed`
  until promotion, and their blank room/area ids are expected for geometry-only
  alignment.
- `python -m roboclaws.maps.b1_manual_draft_promotion --draft docs/status/active/b1-map12-scene-correspondences-draft.json --output output/b1-map12/manual-draft-alignment/b1-map12-scene-correspondences.verification-only.json`
  explicitly creates a verification-only accepted manifest for the manual
  fallback. It uses `anchor_role=alignment` geometry anchors only; do not commit
  it as the final accepted asset.
- `roboclaws.maps.b1_semantic_anchor_suggestions` now consumes an
  explicit `--room-projection` artifact, not the retired Map12 candidate label
  boxes. With the current committed geometry-only correspondence manifest,
  semantic projection is still blocked, so this suggestion path is a follow-up
  after accepted semantic anchors exist.
- `python -m roboclaws.maps.b1_alignment --correspondences output/b1-map12/manual-draft-alignment/b1-map12-scene-correspondences.verification-only.json --map-bundle vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot --output-dir output/b1-map12/manual-draft-alignment`
  writes `global_alignment_status=verified`, `selected_transform_type=rigid_2d`,
  and residual evidence with mean `0.352908 m`, p90 `0.491765 m`, and max
  `0.502064 m`.
- `python -m roboclaws.maps.b1_semantic_review_promotion --review-packet docs/status/active/b1-map12-alignment-accepted-review-packet.json --output assets/maps/b1-map12-scene-correspondences.json --check`
  validates seven human-accepted geometry anchors without writing the committed
  asset.
- `python scripts/maps/check_b1_map12_semantic_review_packet_fit.py --review-packet docs/status/active/b1-map12-alignment-accepted-review-packet.json --map-bundle vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot --output-dir output/b1-map12/alignment-accepted-fit-check`
  writes a non-mutating fit check with `global_alignment_status=verified` and
  no validation errors.
- `python -m roboclaws.maps.b1_semantic_review_promotion --review-packet docs/status/active/b1-map12-alignment-accepted-review-packet.json --output assets/maps/b1-map12-scene-correspondences.json`
  writes the committed correspondence manifest with seven accepted
  `anchor_role=alignment` anchors and blank semantic ids.
- `python -m roboclaws.maps.b1_alignment --correspondences assets/maps/b1-map12-scene-correspondences.json --map-bundle vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot --output-dir output/b1-map12/alignment`
  writes the official residual artifact with `status=global_verified`,
  `global_alignment_status=verified`, `selected_transform_type=rigid_2d`, seven
  matched anchors, mean residual `0.352908 m`, p90 `0.491765 m`, and max
  residual `0.502064 m`. Preview overlays are under
  `output/b1-map12/alignment/previews/`.
- `python -m roboclaws.maps.b1_map12_label_tool --map-bundle vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot --output-dir output/b1-map12/label-tool`
  writes `output/b1-map12/label-tool/label_tool.html` and
  `label_tool_packet.json`. The HTML editor starts from the current
  `semantics.json` if present, or an empty vendor-map packet otherwise. It no
  longer seeds the retired Map12 candidate room boxes.
- `python -m roboclaws.maps.b1_map12_correspondence_review --correspondences assets/maps/b1-map12-scene-correspondences.json --map-bundle vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot --scene-topdown-render output/b1-map12/scene-gaussian-topdown/scene_gaussian_topdown.json --output-dir output/b1-map12/correspondence-review`
  writes `output/b1-map12/correspondence-review/correspondence_review.html`
  and `correspondence_review_packet.json` with
  `review_status=review_pending`, `accepted_anchor_count=0`, validation
  passed, and the next action to produce at least six accepted anchors with
  explicit map and metric scene picks. The right panel is the rendered B1
  Gaussian scene top-down; missing, malformed, or label-inventory scene packets
  fail the command instead of degrading silently. The picker uses browser-ready
  `output/b1-map12/correspondence-review/map12_source_map.png` while preserving
  the vendor `occupancy.pgm` as `source_map.source_image` and using
  `nav2.yaml` origin/resolution for `map_xy` conversion.
- `python -m roboclaws.operator_console.scene_preview_cli --world b1-map12 --output-dir output/b1-map12/static-preview-proof`
  writes static B1 preview metadata with only `map` and `topdown` views; no
  `views.fpv`, no `views.chase`, and no corresponding camera preview files are
  published before residual-backed Isaac runtime camera evidence exists.
- `.venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_readiness --b1-root data/robot-data-lab/scene-engine/data/2rd_floor_seperated --map12-root vendors/agibot_sdk/artifacts/maps/robot_map_12 --alignment-artifact output/b1-map12/manual-draft-alignment/alignment_residuals.json --output output/b1-map12/manual-draft-alignment/readiness_with_alignment.json`
  passes validation with `map12_overlay_status=verified`,
  `map12_to_b1_usd_transform_status=verified`, and
  `robot_navigation_supported=false`.
- `roboclaws.backends.isaaclab.b1_waypoint_pose_requests` writes
  `b1_map12_waypoint_pose_requests_v1` artifacts for on-demand Map12 waypoint
  ids or `map_xy/yaw` points. Globally verified residual alignment and
  explicitly verified local-area transforms produce ready B1 pose rows;
  unverified, malformed, missing-area, or unknown-area requests produce
  blocked rows instead of fallback output.
- `roboclaws.backends.isaaclab.b1_navigation_smoke` requires at
  least two distinct applied B1 scene poses before setting
  `robot_navigation_supported=true`; duplicate-pose camera rows stay blocked.
- `.venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_readiness --b1-root data/robot-data-lab/scene-engine/data/2rd_floor_seperated --map12-root vendors/agibot_sdk/artifacts/maps/robot_map_12 --alignment-artifact output/b1-map12/alignment/alignment_residuals.json --output output/b1-map12/alignment/readiness_with_alignment.json`
  passes validation with `map12_overlay_status=verified`,
  `map12_to_b1_usd_transform_status=verified`, and
  `robot_navigation_supported=false` before runtime smoke evidence is attached.
- `python -m roboclaws.backends.isaaclab.b1_waypoint_pose_requests --alignment-artifact output/b1-map12/alignment/alignment_residuals.json --points output/b1-map12/navigation-smoke/map12_points.json --output output/b1-map12/navigation-smoke/waypoint_pose_requests.json`
  successfully converts two accepted alignment-corner anchors into
  residual-backed B1 scene poses, but the subsequent smoke run under
  `output/b1-map12/navigation-smoke/navigation_smoke.json` remains blocked
  because both FPV images have too little visual detail. This confirms corner
  alignment anchors are valid geometry evidence but poor camera-smoke points.
- `python -m roboclaws.backends.isaaclab.b1_waypoint_pose_requests --alignment-artifact output/b1-map12/alignment/alignment_residuals.json --points output/b1-map12/navigation-smoke/residual-overlay/map12_points.json --output output/b1-map12/navigation-smoke/residual-overlay/waypoint_pose_requests.json`
  converts the `plastic_bottle_table_1` and `long_table` Map12 navigation-memory
  candidate points into ready residual-backed B1 scene pose requests with no
  blocked rows.
- `.venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_navigation_smoke --readiness-artifact output/b1-map12/alignment/readiness_with_alignment.json --waypoint-pose-requests output/b1-map12/navigation-smoke/residual-overlay/waypoint_pose_requests.json --output-dir output/b1-map12/navigation-smoke/residual-overlay --accept-nvidia-eula`
  passes. The resulting
  `output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json`
  reports `robot_navigation_supported=true`,
  `robot_navigation_provenance=isaac_b1_map12_navigation_smoke`,
  `navigation_provenance=kinematic_pose_driven`, two applied waypoints, and
  same-pose FPV/Chase/Map/Verify images for each waypoint.
- `.venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_readiness --b1-root data/robot-data-lab/scene-engine/data/2rd_floor_seperated --map12-root vendors/agibot_sdk/artifacts/maps/robot_map_12 --alignment-artifact output/b1-map12/alignment/alignment_residuals.json --navigation-artifact output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json --require-navigation-success --output output/b1-map12/navigation-smoke/residual-overlay/readiness_with_navigation.json`
  passes and promotes the readiness artifact to
  `robot_navigation_supported=true` from the real navigation-smoke artifact.
- `python -m roboclaws.operator_console.scene_preview_cli --world b1-map12 --b1-camera-artifact output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json --output-dir output/b1-map12/operator-preview-residual-overlay`
  succeeds and writes `b1-map12-preview.json`, `b1-map12-fpv.png`,
  `b1-map12-chase.png`, `b1-map12-map.png`, and `b1-map12-topdown.png`. The FPV
  and Chase metadata share `waypoint_id=b1_aligned_long_table`, reference
  `output/b1-map12/alignment/alignment_residuals.json`, use
  `alignment_transform_source=reviewed_correspondence_fit`, and record
  `isaac_runtime_*` provenance.
- `python -m roboclaws.backends.isaaclab.b1_navigation_report --run-dir output/b1-map12/navigation-smoke/residual-overlay --readiness-artifact output/b1-map12/alignment/readiness_with_alignment.json --navigation-artifact output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json --waypoint-pose-requests output/b1-map12/navigation-smoke/residual-overlay/waypoint_pose_requests.json --output output/b1-map12/navigation-smoke/residual-overlay/report.html`
  passes and writes the reviewable navigation report.
- `python -m roboclaws.backends.isaaclab.b1_navigation_proof --stamp residual-overlay-default-harness --output-dir output/b1-map12/navigation-smoke-harness`
  is the canonical package-owned maintainer replay. It consumes the
  default residual-backed readiness candidate waypoints without an explicit
  `waypoint_pose_requests` override and writes non-empty `navigation_smoke.json`,
  `readiness_with_navigation.json`, `report.html`, and
  `operator-preview/b1-map12-preview.json` under
  `output/b1-map12/navigation-smoke-harness/residual-overlay-default-harness/`.
  The smoke artifact applies `b1_aligned_plastic_bottle_table_1` and
  `b1_aligned_long_table`; the preview metadata uses the same waypoint for
  FPV/Chase, references `output/b1-map12/alignment/alignment_residuals.json`,
  and records `alignment_transform_source=reviewed_correspondence_fit`.
  An explicit
  `waypoint_pose_requests=output/b1-map12/navigation-smoke/residual-overlay/waypoint_pose_requests.json`
  replay also passes under `residual-overlay-harness-4`.
  The earlier interrupted
  `output/b1-map12/navigation-smoke-harness/residual-overlay-harness/` directory
  is a partial run with zero-byte JSON files and is not evidence.
- `python -m roboclaws.maps.b1_semantic_projection --correspondences assets/maps/b1-map12-scene-correspondences.json --room-semantics assets/maps/b1-map12-room-semantics.json --output output/b1-map12/semantic-projection/semantic_projection.json`
  currently exits non-zero with `accepted semantic anchors are required before
  projecting room labels`. This is the correct gate for the current committed
  manifest: seven accepted `anchor_role=alignment` anchors prove geometry, but
  room label projection is blocked until accepted `anchor_role=semantic`
  anchors are promoted into the correspondence manifest. The projection script
  also keeps object projection blocked; it does not infer object labels from
  room anchors.
- `roboclaws.backends.isaaclab.b1_navigation_report` can include
  `waypoint_pose_requests.json` and renders ready/blocked conversion decisions
  in the HTML report. The current accepted navigation-smoke proof includes
  local Isaac same-pose camera evidence.
- `python scripts/maps/compile_b1_map12_runtime_bundle.py --map-bundle vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot --scene-root data/robot-data-lab/scene-engine/data/2rd_floor_seperated --room-semantics assets/maps/b1-map12-room-semantics.json --alignment-artifact output/b1-map12/alignment/alignment_residuals.json --navigation-artifact output/b1-map12/navigation-smoke/residual-overlay/navigation_smoke.json --output-dir output/b1-map12/digital-twin-runtime-proof-check`
  compiles a valid runtime Nav2 bundle with
  `digital_twin_capabilities.robot_consumption_proof.status=robot_navigation_verified`,
  `robot_navigation_supported=true`, and source-frame
  `spatial_contract.alignment_status=verified`. The compiler does not
  auto-discover `output/` artifacts: callers must pass explicit verified
  alignment/navigation artifact paths, and missing or mismatched artifacts fail
  loudly.
- The compiler also writes `b1_robot_consumption_manifest.json` inside the
  compiled bundle. This is a thin downstream-consumer summary of the already
  verified proofs: robot navigation readiness, room semantic projection status,
  object semantic status, manipulation status, required bundle files, and the
  no-autodiscovery policy.
- `scripts/maps/compile_b1_map12_runtime_bundle.py` also accepts explicit
  `--semantic-projection-artifact` /
  `b1_semantic_projection_artifact=...` inputs. When a strict projection
  artifact exists, the generated `semantics.json` carries
  `digital_twin_capabilities.room_semantic_projection_proof` and promotes room
  semantic labeling to verified. With the current proposed-only semantic review
  packet, this remains blocked; the compiler does not auto-discover projection
  output and does not infer object labels from room anchors.
- `roboclaws.maps.runtime_prior_conversion.runtime_prior_snapshot_from_nav2_cleanup_bundle`
  and `python -m roboclaws.maps.runtime_prior_conversion nav2-cleanup-bundle`
  can convert a compiled B1 Nav2 cleanup bundle into the canonical
  `runtime_map_prior_snapshot_v1` contract. This gives downstream robot
  consumers the same prior shape for compiled B1 bundles that simulator
  map-build output and Agibot `navigation_memory.json` already use.
- The B1 product route now exports that canonical prior next to the compiled
  bundle as `runtime_map_prior_snapshot.json`, plus the compact
  `runtime_map_prior_targets.json` materialized-target summary, and copies the
  B1 robot-consumption manifest to the run root. These are visible run
  artifacts only; they do not auto-feed generated `output/` artifacts back into
  the default route.
- `runtime_map_prior_targets.json` now carries the same
  `digital_twin_capabilities` plus a compact `capability_summary`, so consumers
  of the materialized-target summary can see verified B1 navigation status and
  blocked room/object/manipulation capability status without parsing the full
  snapshot.
- `RealWorldCleanupContract` now preserves B1 `digital_twin_capabilities` from
  an explicitly supplied raw `runtime_metric_map_v1` prior or
  `runtime_map_prior_snapshot_v1` wrapper into the agent-visible
  `runtime_metric_map`. Focused contract/MCP tests prove the
  `metric_map -> navigate_to_waypoint -> observe` path can still see
  `robot_navigation_supported=true`, render/observation readiness, blocked
  `B1_floor2_slow` default visual-route status, and blocked
  room/object/manipulation/planner/physical-robot status.
- The operator console artifact list now exposes these wrapper-level files, so
  a B1 console run can show both the canonical prior and the robot-consumption
  manifest even when the live attempt evidence lives in a nested timestamp/seed
  directory.
- B1 / Isaac product checks now use a B1-specific
  `--require-b1-robot-consumption-proof` gate. That gate reads the run-local
  copied `map_bundle/semantics.json` and requires
  `digital_twin_capabilities.robot_consumption_proof.status=robot_navigation_verified`;
  it also requires run-root `b1_robot_consumption_manifest.json` to agree with
  the proof's navigation/artifact fields and no-autodiscovery policy;
  it does not reuse the older RBY1M real-robot readiness gate.
- The B1 route fails before launch when that gate is active but
  `b1_alignment_artifact` or `b1_navigation_artifact` is missing. This keeps
  proof inputs explicit and avoids silently relying on generated `output/`
  artifacts.
- The operator console now mirrors that contract: B1 / Map 12 route metadata
  lists `b1_alignment_artifact` and `b1_navigation_artifact` as required
  overrides, readiness blocks without readable JSON paths, and launch passes the
  supplied explicit paths through unchanged.
- `roboclaws.maps.b1_semantic_review_promotion` now implements the
  strict promotion gate from a human-edited review packet to the committed
  correspondence manifest. Proposed-only rows, missing `anchor_role`, fewer
  than six human-accepted anchors, bbox/seed coordinate sources, and
  auto-accepted suggestions are rejected before writing output. Accepted
  `alignment` anchors may keep blank semantic ids; accepted `semantic` anchors
  require real ids and reject synthetic `manual_draft_*` values. `--check`
  validates the same gate without writing the committed asset, and write mode
  strips review-only suggestion metadata from promoted anchors.
- The same semantic suggestion command now writes
  `output/b1-map12/manual-draft-anchor-semantic-review.html`, a read-only
  operator table showing each proposed anchor, candidate semantic ids, and
  nearest candidate distances.
- `scripts/maps/check_b1_map12_semantic_review_packet_fit.py` can validate a
  human-edited packet and run the residual fitter against a promoted preview
  manifest under `output/` without writing `assets/maps/b1-map12-scene-correspondences.json`.
- Operator-console B1 FPV/Chase promotion rejects generic `robot_view_steps`
  unless they include a camera-control contract proving the FPV source is a
  robot-mounted or head-camera-equivalent runtime view and not scene-probe/bbox
  evidence. B1 navigation-smoke waypoint evidence remains valid as the
  pose-driven camera artifact path.
- B1 FPV/Chase promotion also rejects artifacts without waypoint ids or with
  mixed FPV/Chase view labels, so accepted preview metadata stays tied to one
  same-waypoint evidence row.
- B1 `--skip-existing` preview reuse now requires the cached camera metadata to
  keep the matching camera artifact path, same waypoint id, residual alignment
  artifact, and `reviewed_correspondence_fit` transform source. Incomplete
  stale camera metadata is rewritten to static map/topdown preview and stale
  FPV/Chase files are removed.
- `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_b1_scene_gaussian_topdown.py tests/contract/maps/test_b1_map12_verified_alignment.py tests/contract/maps/test_b1_map12_label_tool.py tests/contract/maps/test_robot_map12_consistency.py tests/unit/operator_console/test_render_scene_previews.py tests/unit/operator_console/test_static_assets.py -q`
  passes.
- `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_b1_map12_verified_alignment.py tests/contract/maps/test_b1_map12_digital_twin_readiness.py tests/contract/maps/test_b1_map12_navigation_report.py tests/unit/operator_console/test_render_scene_previews.py -q`
  passes for the pose-request and report-audit contract.
- `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_runtime_map_prior_snapshot.py tests/contract/maps/test_b1_map12_runtime_bundle.py -q`
  passes for compiled B1 bundle -> canonical Runtime Map Prior Snapshot
  conversion and B1 runtime-bundle proof gates.
- `ruff check roboclaws/maps/b1_semantic_review_promotion.py roboclaws/maps/b1_semantic_anchor_suggestions.py tests/contract/maps/test_b1_map12_verified_alignment.py`,
  `ruff format --check roboclaws/maps/b1_semantic_review_promotion.py roboclaws/maps/b1_semantic_anchor_suggestions.py tests/contract/maps/test_b1_map12_verified_alignment.py`,
  and `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_b1_map12_verified_alignment.py -q`
  pass for the strict promotion gate, `--check` mode, and read-only semantic
  review report.
- `ruff check roboclaws/operator_console/scene_preview_cli.py tests/unit/operator_console/test_render_scene_previews.py`,
  `ruff format --check roboclaws/operator_console/scene_preview_cli.py tests/unit/operator_console/test_render_scene_previews.py`,
  `./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console/test_render_scene_previews.py -q`, and
  `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_b1_map12_verified_alignment.py tests/contract/maps/test_b1_map12_navigation_report.py tests/unit/operator_console/test_render_scene_previews.py -q`
  pass for the hardened B1 camera-preview provenance gate.
- `ruff check roboclaws/backends/isaaclab/b1_navigation_smoke.py tests/contract/maps/test_b1_map12_verified_alignment.py`,
  `ruff format --check roboclaws/backends/isaaclab/b1_navigation_smoke.py tests/contract/maps/test_b1_map12_verified_alignment.py`,
  `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_b1_map12_verified_alignment.py -q`, and
  `./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_b1_map12_verified_alignment.py tests/contract/maps/test_b1_map12_digital_twin_readiness.py tests/contract/maps/test_b1_map12_navigation_report.py -q`
  pass for the distinct-applied-pose navigation smoke gate.

Next hypothesis: the same residual-backed point path is sufficient for
operator-selected Map12 `map_xy/yaw` points inside verified global coverage, as
long as the points are useful interior navigation/viewpoints rather than
alignment-corner anchors.

P0 consumer-chain status:

- Closed: B1 `digital_twin_capabilities` / `capability_summary` from an
  explicitly supplied `runtime_map_prior` reaches the agent-visible
  MCP/runtime map context.
- Closed: render/observation readiness is named in that capability surface for
  same-pose Gaussian/digital-twin FPV, Chase, and topdown evidence.
- Closed: focused tests prove the existing MCP path sees the B1 status through
  `metric_map -> navigate_to_waypoint -> observe`.
- Closed with explicit blocked status: `B1_floor2_slow/` is not selected as
  the default visual/render route because no same-frame, same-pose render proof
  exists yet; the capability surface reports
  `blocked_missing_verified_b1_floor2_slow_render_proof`.
- Still parked outside P0: human room-semantic anchor review, room semantic
  projection, object semantic projection, object/receptacle binding,
  manipulation, planner-backed navigation, physical robot support, and public
  absolute `map_xy/yaw` MCP navigation.

Next command/artifact:

```bash
/goal execute docs/plans/2026-06-17-b1-map12-two-map-alignment-blocker.md with intuitive-flow
```

Stop condition: P0 consumer-chain implementation is closed. Do not claim
room/area labels, object labels, manipulation, planner-backed navigation,
physical robot support, or public absolute `map_xy/yaw` navigation until
separate follow-up proof artifacts exist.

No-touch scope: no generated `output/**` commits, no fallback/autodiscovery, no
room/object semantic promotion, no public surface or MCP contract change, no
object or receptacle USD binding, no manipulation or planner-backed navigation
claim, and no threshold relaxation without a plan update.

Parked work:

- Use `output/b1-map12/correspondence-review/correspondence_review.html` only if
  more geometry anchors are needed. The first seven accepted alignment anchors
  are already committed.
- Use `output/b1-map12/label-tool/label_tool.html` when the current
  axis-aligned candidate room boxes are too crude. Exported label drafts still
  need an explicit review/merge step before replacing committed map semantics
  or correspondence assets.

Post-implementation note for fresh context on 2026-06-18:

- Current goal remains: make the B1 / Map12 Gaussian asset consumable through
  the same robot-facing map-prior shape as simulator assets.
- Already proven: reviewed geometry alignment, residual-backed B1 scene pose
  application, same-pose Isaac FPV/Chase proof, explicit B1 proof artifacts in
  product/operator-console routes, B1 robot-consumption manifest, canonical
  runtime prior snapshot, compact prior targets with capability summary,
  agent-visible runtime-prior capability propagation, render/observation
  readiness naming, and B1-specific checker proof.
- Remaining non-P0 follow-ups are accepted room semantic anchors, strict room
  semantic projection, object semantic projection, object/receptacle binding,
  manipulation, planner-backed navigation, physical robot support, or a public
  MCP navigation tool.
- Strict no-touch constraints for resume: do not commit generated `output/**`;
  do not add fallback or output autodiscovery; do not treat
  `docs/status/active/b1-map12-semantic-anchor-review-packet.json` as accepted
  truth; do not infer room/object labels from the seven alignment anchors.
