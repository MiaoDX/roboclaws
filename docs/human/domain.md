# Roboclaws Domain Context

This file defines stable domain language. It is not project status. For current
focus, next action, and active source links, read [`STATUS.md`](../../STATUS.md).

Keep this file short. Historical phase vocabulary and shipped implementation
details belong in `.planning/`, `docs/adr/`, and `docs/retrospectives/`.

## Core Language

**Scenario Setup**:
A private pre-run world initialization choice that prepares the room before a
task starts. It can be `baseline` or a relocation setup, and it is independent
of task intent and evaluation policy.
_Avoid_: task intent, cleanup scenario, Agent View context

**Relocation Policy**:
A Scenario Setup mode that moves cleanup-related objects before the run starts.
The Cleanup Agent is not told the policy, object IDs, or before/after locations.
_Avoid_: public mess generator, cleanup worklist, private scoring truth

**Relocation Count**:
The operator-facing number of objects that a relocation setup may move.
_Avoid_: generated mess count, public target count

**Cleanup Agent**:
The robot or policy that perceives the messy scene and decides how to restore it.
_Avoid_: Placer

**Robot Run**:
One auditable execution episode with fixed prompt, surface axes, artifacts,
checker result, and report after terminal status.
_Avoid_: persistent background agent

**Operator Session**:
A durable operator interaction thread that can link multiple Robot Runs through
Steer, paused-handoff Resume, and terminal-parent Next Goal.
_Avoid_: single long-lived agent process, active-run goal queue

**Scorer**:
A private evaluator that compares the final scene state against acceptable
cleanup outcomes.
_Avoid_: Planner, oracle planner

**Private Scoring Truth**:
Hidden object-to-acceptable-destination rules used only by the Scorer.
_Avoid_: Public target map, planner hints

**Generated Mess Set**:
The hidden private/scorer-side set of movable objects displaced by relocation
for one cleanup evaluation run.
_Avoid_: Five curated targets

**Tidy-Plausible Outcome**:
A final object placement that a reasonable household cleanup could accept, even
when more than one destination is valid.
_Avoid_: Single correct target

**Disturbance Penalty**:
A soft scoring penalty for making an initially tidy object less tidy-plausible.
_Avoid_: False-positive failure

**Metric Map**:
A public map of rooms, walls, doors, driveable ways, and robot pose.
_Avoid_: Semantic object oracle

**Base Metric Map**:
The start-of-run agent-facing map context: occupancy/free-space geometry,
frame metadata, robot pose, public room-category hints when available, and
artifact-authored safe exploration or inspection candidates. In product
runtime, base inspection candidate ids and poses come from the map artifact
and are projected as-is except for runtime state such as `visited`. Runtime
observations and semantic enrichment belong in the Runtime Metric Map.
_Avoid_: rich fixture map, static object oracle, private target map

**Prebuilt Robot Map Bundle**:
A static operator-prepared map package containing navigation geometry, frame
metadata, fixture semantics, and inspection waypoints. For product runtime it
owns the base inspection waypoint source of truth; missing or malformed base
waypoints are a map artifact error, not permission for runtime fallback.
_Avoid_: Live SLAM result, hidden target map, runtime waypoint generator

**Source Map Frame**:
The robot, simulator, or imported map coordinate frame used by navigation and
map tools. Semantic polygons, anchors, and correspondence evidence must be
authored or transformed into this frame before reports render them.
_Avoid_: display-only image frame, beautified preview coordinates

**Display Frame**:
A report or UI coordinate frame derived from the Source Map Frame for human
inspection. The current map-parity slice explicitly omits rectified display
frames and renders raw/source map orientation.
_Avoid_: hidden map mutation, second semantic overlay

**Navigation Area**:
A public navigable or inspectable map zone. It may be an operator-authored
rectangle or generated area and is not necessarily a traced physical room
boundary.
_Avoid_: physical room outline, wall-truth polygon

**Room Boundary**:
A traced or derived polygon intended to match physical walls or room
partitions. Reports must not present Navigation Areas as Room Boundaries unless
the geometry source and alignment evidence support that claim.
_Avoid_: navigation-zone bounding box, review-only region

**Scene Partition**:
A digital-twin asset partition such as a USD, Gaussian, or scene-engine room
folder. It can provide semantic labels or candidate correspondence evidence,
but it is not map-frame geometry without an explicit correspondence manifest or
verified transform.
_Avoid_: map polygon, physical room truth

**Correspondence Anchor**:
A human/operator-reviewed physical or semantic landmark that exists in both a
Source Map Frame and a Scene Partition or scene frame, with explicit coordinates
or evidence in both frames. It can verify map-scene alignment after residuals
are computed, but it is not object-level USD truth by itself.
_Avoid_: bbox seed, model guess, unreviewed visual match, object/receptacle binding

**Polygon Geometry Source**:
The provenance for a map polygon, such as
`operator_authored_navigation_zone`, `traced_occupancy_room_boundary`,
`scene_engine_partition`, `runtime_observation`, or `generated_candidate`.
_Avoid_: unlabeled overlay, inferred room truth

**Alignment Status**:
The confidence tier for cross-frame or cross-environment spatial evidence:
`native`, `candidate`, `verified`, `runtime_proven`, `planner_backed`, or
`blocked`. Candidate overlays may support review but must not be promoted to
room geometry or planner-safe evidence without proof.
_Avoid_: implicit trust, list-order correspondence, display polish as proof

**Runtime Metric Map**:
A public run artifact that enriches the Metric Map with observed-object priors,
public semantic anchors, map-update candidates, and provenance without mutating
the source navigation map.
_Avoid_: Private target map, source map rewrite

**Runtime Map Prior Snapshot**:
The canonical downstream runtime-map prior artifact. Online
`surface=household-world preset=map-build` Runtime Metric Map output and
offline Agibot `navigation_memory.json` conversion both produce this shape:
source map reference, runtime map payload, public anchors, materialized
inspection waypoints, materialized fixture or receptacle candidates,
actionability status, and evidence.
_Avoid_: Agibot-only cleanup input, private scoring artifact

**Public Semantic Anchor**:
A public semantic place, fixture, room area, landmark, or observed prior with
provenance and actionability status. Static fixtures and receptacles may become
tool-consumable targets; movable-object priors remain `needs_confirm` until
current-run evidence observes them again.
_Avoid_: global object inventory, scorer target

**Inspection Waypoint**:
A public Metric Map pose where the Cleanup Agent can observe part of a room or
navigation area during a cleanup sweep. Base inspection waypoints are authored
or generated by the map artifact pipeline and keep their artifact ids in
runtime. Target-specific inspection candidates created after current-run
observations are runtime candidates, not replacements for the base waypoint set.
_Avoid_: Hidden object viewpoint, runtime-renamed base waypoint

**Relative Pose Navigation**:
A bounded navigation action that moves or turns the robot in the robot-local
frame from its current pose, such as a short forward/backward nudge, lateral
nudge, or yaw turn. It is distinct from navigating to a public Metric Map
Inspection Waypoint.
_Avoid_: hidden waypoint, map mutation, unbounded teleop

**Room-Level Fixture Hint**:
A public hint that names a large fixed receptacle or fixture and the room where
it belongs, without giving an exact pose.
_Avoid_: Oracle fixture map

**Observed Object Handle**:
A stable object identifier exposed to the Cleanup Agent only after the object
appears in robot-local perception.
_Avoid_: Pre-run object id

**Support Estimate**:
A robot-local perception estimate of what fixture or surface an observed object
is on or near.
_Avoid_: Ground-truth object location

**Agent View**:
The exact public information and perception data available to the Cleanup Agent
during the run.
_Avoid_: Full report context

**Private Evaluation**:
The post-run report section that explains scoring using hidden mess and
acceptable-destination data.
_Avoid_: Agent input

**Cleanup Artifact Report**:
The shared HTML review artifact for MolmoSpaces cleanup demos, backed by one
report renderer and one semantic timeline model.
_Avoid_: Per-demo report clone

**Semantic Cleanup Subphase**:
A report-facing label for one step in the object cleanup loop:
`nav`, `pick`, `nav`, optional `open`, then `place`.
_Avoid_: Raw tool log as visual flow

**Planner-Backed Manipulation Proof**:
Evidence that a MolmoSpaces robot manipulation planner policy actually executed
robot actions and changed robot state, separate from semantic state edits.
_Avoid_: planner class import, `api_semantic` success

**Planner-Backed Cleanup Primitive Gate**:
A per-cleanup-subphase evidence gate that checks whether the cleanup loop's own
`nav`, `pick`, `nav`, `open`, or `place` steps are planner-backed.
_Avoid_: report-only proof attachment

**RBY1M CuRobo Runtime Gate**:
Evidence that the target RBY1M/CuRobo runtime is ready for strict cleanup
primitive proof.
_Avoid_: standalone Franka proof as target cleanup readiness

**Planner Proof Request Manifest**:
Private cleanup artifact metadata that turns completed semantic substeps into
exact bound planner probe requests for local proof-bundle generation.
_Avoid_: Agent View planner aliases

**Planner Proof Bundle Runner Report**:
The visual report produced by the local proof-bundle runner to show probe
commands, proof artifacts, blockers, and optional cleanup rerun commands.
_Avoid_: treating command evidence as proof success

**Grasp-Feasibility Blocker**:
A proof-result classification for exact-scene requests that clear robot
placement but fail through post-placement grasp/candidate rejection.
_Avoid_: generic task-feasibility blocker

**Grasp Cache Evidence**:
Evidence about rigid grasp-cache availability, validity, generation, and
installation for exact planner objects.
_Avoid_: assuming object assets imply usable cached grasps

## Relationships

- **Scenario Setup** prepares the room before the **Cleanup Agent** starts.
- A **Cleanup Agent** must not receive the **Private Scoring Truth**, hidden
  relocated-object list, or target count.
- A **Scorer** may use the **Private Scoring Truth** only after the run ends.
- A **Cleanup Agent** may receive public map, fixture, and robot-local
  perception data.
- A **Prebuilt Robot Map Bundle** may back the public **Metric Map** and
  fixture semantics before runtime observations begin.
- A **Base Metric Map** is the current start-of-run projection of public
  map context for household tasks; **Runtime Metric Map** evidence enriches it
  without mutating the source map.
- Product runtime loads base **Inspection Waypoints** from a **Prebuilt Robot
  Map Bundle** or equivalent canonical map artifact. It may add visit state,
  but it must not silently synthesize, renumber, or fallback-generate the base
  waypoint set.
- **Relative Pose Navigation** starts from the current robot pose and does not
  create or replace **Inspection Waypoints**.
- Map overlays use the **Source Map Frame** as spatial truth; a **Display
  Frame** is a labeled derived view, not a replacement for navigation
  coordinates.
- A **Navigation Area** can carry room semantics, but it is not a **Room
  Boundary** unless its **Polygon Geometry Source** and **Alignment Status**
  support that stronger claim.
- A **Scene Partition** binds to map geometry through explicit correspondence,
  not list order.
- A **Correspondence Anchor** can promote map-scene alignment only after
  residuals are recorded and accepted; unreviewed suggestions and bbox seeds do
  not count as accepted anchors.
- A **Runtime Metric Map** may be wrapped as a **Runtime Map Prior Snapshot**
  for downstream cleanup or open household tasks.
- Offline Agibot `navigation_memory.json` conversion produces an
  **Runtime Map Prior Snapshot** at the map-artifact boundary; cleanup
  should consume the canonical snapshot, not a special Agibot-only branch.
- Small movable objects should be discovered through **Observed Object
  Handles**, not pre-run global object IDs.
- Prior movable objects in a **Runtime Map Prior Snapshot** are
  non-actionable until current-run evidence confirms them.
- Reports must separate **Agent View** from **Private Evaluation**.
- `api_semantic` cleanup artifacts can be useful evidence, but they must not
  satisfy **Planner-Backed Manipulation Proof**.
- The cleanup visual rhythm is `nav -> pick -> nav -> open? -> place`.
- **Planner-Backed Cleanup Primitive Gate** remains blocked until cleanup
  subphases have exact planner-backed primitive evidence.
