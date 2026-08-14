---
name: scene-gaussian-map-alignment
description: Align scene Gaussian/splat, USD/mesh, and robot map assets into an honest digital-twin evidence workflow. Use when a new Gaussian scene arrives, when B1/Map12-style assets need to be connected, when map anchors are being projected into a 3D scene, or when an agent must decide whether an alignment is candidate, verified, runtime-proven, or planner-backed.
---

# Scene Gaussian Map Alignment

Use this when a bundle combines a 3D Gaussian/splat/PLY/USD/OBJ scene, a robot
map such as Nav2 YAML plus occupancy PGM, semantic anchors from
`navigation_memory.json`, or an Isaac/operator-console report that must label
evidence honestly.

## Boundary

Keep stable, repeatable work in scripts. The skill owns the judgment that changes
from scene to scene:

- Stable scripts parse headers, bounds, map metadata, semantic-memory JSON,
  transforms, smoke artifacts, images, and HTML reports.
- The skill decides the evidence tier, asks for missing assets, chooses which
  anchors are credible, names blockers, and prevents overclaiming.
- Do not hide scene-specific assumptions in a script default. If an assumption
  will vary with the next Gaussian scene, write it in the skill/report as an
  explicit decision.

## Evidence Tiers

Use these labels consistently:

- `blocked`: geometry, map files, semantic anchors, or coordinate evidence are
  missing.
- `candidate`: bbox fit, scale/translate, manual placement, or another heuristic
  alignment exists.
- `verified`: named physical/semantic anchors match across map and scene with
  residuals recorded.
- `runtime_proven`: Isaac or robot-view smoke renders/navigates through
  candidate waypoints and writes view evidence.
- `planner_backed`: a real planner/Nav2-equivalent path proof exists.

Never skip tiers in wording. A runtime smoke can prove that rendered robot views
exist at candidate poses; it does not by itself prove Nav2 planner parity.

## Workflow

1. Inventory every asset before aligning: Gaussian/splat/PLY files and whether
   they are rendered or only inspected, USD/OBJ/mesh world bounds, Nav2 YAML,
   occupancy grid, semantic memory, map-bundle context, anchor ids, and any
   segmentation/object manifest/correspondence/calibration evidence.

2. Run the deterministic tools that apply to the available assets:

   ```bash
   python -m roboclaws.household.agibot_map_bundle \
     --source-map-dir <map-root> \
     --context-json <context-json> \
     --output-dir assets/maps/<bundle-name>

   .venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_readiness \
     --b1-root <scene-root> \
     --map12-root <map-root> \
     --output output/<run>/readiness.json

   .venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_navigation_smoke \
     --b1-root <scene-root> \
     --map12-root <map-root> \
     --output-dir output/<run> \
     --accept-nvidia-eula

   .venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_readiness \
     --b1-root <scene-root> \
     --map12-root <map-root> \
     --navigation-artifact output/<run>/navigation_smoke.json \
     --require-navigation-success \
     --output output/<run>/readiness_with_navigation.json

   python -m roboclaws.backends.isaaclab.b1_navigation_report \
     --run-dir output/<run>
   ```

3. Classify what the run actually proved: bbox fit is `candidate`; matched
   anchors with residuals are `verified`; rendered robot views at candidate
   poses are `runtime_proven`; planner path evidence is `planner_backed`.

4. Summarize the evidence without changing the artifacts:

   ```bash
   python skills/scene-gaussian-map-alignment/scripts/summarize_alignment_evidence.py \
     --readiness-artifact output/<run>/readiness_with_navigation.json \
     --navigation-artifact output/<run>/navigation_smoke.json \
     --output output/<run>/alignment_evidence_summary.json
   ```

5. Write the lightweight alignment manifest. This is the fusion contract for
   future runs; it is not a fused USD/Gaussian scene:

   ```bash
   python skills/scene-gaussian-map-alignment/scripts/summarize_alignment_evidence.py \
     manifest \
     --readiness-artifact output/<run>/readiness_with_navigation.json \
     --navigation-artifact output/<run>/navigation_smoke.json \
     --evidence-summary output/<run>/alignment_evidence_summary.json \
     --map-bundle assets/maps/<bundle-name> \
     --output output/<run>/alignment_manifest.json
   ```

6. Report the open blockers and next promotion step. Prefer one precise blocker
   over broad language like "alignment done".

## Honest Labels

- Do not claim Gaussian fusion unless the renderer consumed the Gaussian/splat
  asset; header/bounds inspection is only inventory evidence.
- Do not claim `semantic_anchors_are_usd_truth=true` without segmentation,
  object manifest, or anchor correspondences that bind map anchors to USD/scene
  objects.
- Do not claim manipulation support without object/receptacle binding plus a
  pick/place proof.
- A "verify image" is a rendered camera view from a candidate pose. It helps
  inspect gross placement and visibility, but it is not ground-truth alignment,
  semantic binding, or planner proof.
- If Map 12 semantics are used only as navigation-memory anchors, call them
  `robot_map_12_navigation_memory_overlay` or an equivalent overlay source, not
  USD truth.

## Output

When handing off results, include:

- alignment tier and transform source;
- whether Gaussian assets were rendered or only inspected;
- semantic source and semantic/USD binding status;
- navigation evidence status and whether it is planner-backed;
- artifact paths such as `readiness.json`, `navigation_smoke.json`,
  `readiness_with_navigation.json`, `alignment_evidence_summary.json`,
  `alignment_manifest.json`, `report.html`, and any map bundle;
- the exact next step needed to promote the evidence tier.

## Acceptance

After changing this skill, related scripts, or map/Isaac report contracts, run:

```bash
./scripts/dev/run_pytest_standalone.sh \
  tests/contract/maps/test_b1_map12_digital_twin_readiness.py \
  tests/contract/maps/test_b1_map12_navigation_report.py \
  tests/contract/maps/test_agibot_map_bundle_export.py \
  tests/contract/skills/test_scene_gaussian_map_alignment_skill.py \
  tests/contract/skills/test_skill_manifests.py \
  -q
```
