---
name: household-world
description: Complete household-world goals through public household MCP tools.
metadata:
  openclaw:
    emoji: H
---

# Household World

Use only the `roboclaws__*` MCP tools exposed for the run. The GoalContract,
TaskIntentSpec, optional TaskPresetSpec, evidence lane, and required capability
profile decide the behavior. Task type does not create a separate runner or
skill.

This Skill is the canonical owner of generic search, sweep, manipulation,
completion, and recovery strategy. Run kickoff context supplies only the
operator goal, selected evidence lane, budgets, required artifacts, and episode
facts. The explicit operator goal and public safety, capability, and
required-tool responses are authoritative; other kickoff text does not replace
this strategy.

Do not call `scene_objects`, read private manifests, inspect scoring code,
infer generated mess truth, or use hidden destination tables. The report may
show Private Evaluation after a run, but that information is not agent input.

## Intent Routing

- No preset, `intent=open-ended`: the operator goal is authoritative. Inspect
  only as much as the goal needs, use public map/observation/target-query
  evidence, and call `roboclaws__done(reason)` when the goal is satisfied,
  blocked by a public capability response, or exhausted by the public search
  budget.
- `preset=cleanup`, `intent=cleanup`: run a full household cleanup sweep.
  Visit public inspection waypoints, clean public recommended candidates through
  trace-preserving manipulation tools, and call `done` only after waypoint
  coverage and public pending candidates are resolved.
- `preset=map-build`, `intent=map-build`: build Runtime Metric Map evidence.
  Visit public inspection waypoints and target-query recovery paths, but do not
  pick, place, place_inside, open_receptacle, close_receptacle, or clean any
  object.

## Shared Loop

1. Call `roboclaws__metric_map()` when map context is needed. Cleanup and
   map-build presets call it first.
2. Treat `metric_map.inspection_waypoints` as public coverage candidates, not
   private task hints. Use Base Metric Map waypoints, public room labels,
   Runtime Metric Map evidence, and `roboclaws__resolve_target_query()` for
   named places, stale labels, destinations, or open-ended search terms.
3. Navigate only through public waypoints or public target candidates with
   `roboclaws__navigate_to_waypoint()`, then observe with
   `roboclaws__observe()`. Use `roboclaws__adjust_camera()` only for bounded
   public recovery when target or observation evidence is incomplete.
4. Follow public recovery responses such as `required_tool`,
   `required_next_tool`, `blocked_capability`, `destination_options`,
   `target_actionability_status`, and actionability status. Do not invent
   fixture ids from stale map labels.
5. Keep all reasoning tied to public observations, target candidates, public
   semantic anchors, inspected viewpoints, and the returned public search
   budget.

Never return a final answer before calling `roboclaws__done(reason)`. When the
remaining turn or tool budget is low, call `done` with the public progress and
remaining risk instead of spending the closeout budget on optional observations.
If `done` returns a required recovery action, perform only that bounded recovery
before calling `done` again.

## Open-Ended Goals

Do not start a room-cleanup routine unless the operator explicitly asks for
cleanup. For information, search, or inspection goals, answer from public
observations and target-query evidence. A not-found answer is valid only after
public evidence shows the useful search space has been checked or exhausted.

For manipulation goals, act only on task-relevant observed handles or visual
candidates. If the backend blocks manipulation, report the blocker and call
`done` with the public evidence gathered so far. Do not require every
inspection waypoint to be visited unless the goal itself asks for a full-room
sweep or a preset selects that policy.

## Cleanup Preset

Build an exact checklist from `metric_map.inspection_waypoints`. For each
useful waypoint or current-room area, call
`roboclaws__navigate_to_waypoint(waypoint_id)`, then `roboclaws__observe()`.
Mark a waypoint complete only after an observe response at that waypoint id.
Before `done`, compare the checklist against observed waypoint ids and visit
any missing waypoint.

Prefer a local cleanup loop after each useful observation instead of a full
up-front survey. Clean plausible misplaced objects with only observed object
handles. The contract-derived `cleanup_worklist` in Agent View and `done`
recovery payloads are authoritative.

For each observed cleanup handle, run this public tool chain:

```text
navigate_to_object(object_id)
pick(object_id)
navigate_to_receptacle(candidate_fixture_id)
open_receptacle(candidate_fixture_id)      # only for fridge/refrigerator targets
place_inside(candidate_fixture_id)         # for fridge/refrigerator/shelf targets
close_receptacle(candidate_fixture_id)     # only after opening fridge-like targets
place(candidate_fixture_id)                # for normal surfaces instead of place_inside
```

Do not observe again after a successful placement unless a public tool response
requires fresh visual evidence. The default budget is one observation per
inspection waypoint; repeat an observation only for a returned bounded recovery
action, not to reconfirm a successful tool result.

Choose `place_inside` for fridge, refrigerator, shelf, bookshelf, bookcase, or
shelving targets. Choose `place` for table, sofa, bed, desk, sink, counter,
stand, hamper, and other surface-like fixtures. If any tool returns
`error_reason: semantic_order`, call its `required_tool` with the same public
object or fixture id, then retry the failed step once.

In `world-public-labels`, detections intentionally omit private destination
truth. Treat `destination_policy` as public category/fixture-affordance
guidance: resolve preferred categories with `resolve_target_query` and match
returned public anchors against Runtime Metric Map public semantic anchors or
other public fixture evidence.

In `camera-raw-fpv`, inspect raw FPV image evidence directly. Select at most
one fresh high-confidence cleanup object per source observation, then call
`roboclaws__navigate_to_visual_candidate(...)` only when you intend to act on a
visual candidate. Do not pre-register raw-FPV candidates with
`declare_visual_candidates`. If a compact continuation supplies a bounded
public revisit queue after `done` reports a grounded-chain deficit, finish any
heading blocker first, then inspect each listed waypoint at most once from the
specified fresh recovery view.

For a raw-FPV candidate, use the exact visible class when clear and a broader
cleanup category only when the class is uncertain. Ground with
`image_region={type:bbox,value:[x,y,width,height]}`; never send normalized or
bare coordinate fields. When a candidate touches an image edge, take the
bounded camera adjustment named by the public response and use only the fresh
reviewable bbox. Never retry the same source-observation/category/region tuple.
Omit `source_fixture_id` when Base Metric Map context is sufficient, and omit
unknown `target_fixture_id` values rather than sending empty, null-like text.

In `camera-grounded-labels`, use `roboclaws__declare_visual_candidates()` to
register producer-labelled candidates before cleanup selection.

After the local cleanup loop, call `done` as the authoritative closeout probe.
Only close out after every public inspection waypoint has an observe response
and every public recommended candidate is resolved. If `done` returns
`pending_cleanup_candidates`, clean exactly those listed handles using their
`candidate_fixture_id` or `destination_options`, then call `done` again.
Follow a top-level `required_tool` or
`completion.blockers[*].required_tool`; if destination evidence is incomplete,
continue the waypoint sweep rather than inventing fixture ids. Skip candidates
reported as `already_handled` and avoid repeating work in the same stale area.

## Map-Build Preset

Use the same public map, observation, camera, and target-query tools, but do not
run cleanup actions. Map-build waypoints are coverage candidates, not one-shot
observations. When a target query, visual candidate, anchor, or waypoint
observation is incomplete, use bounded public camera recovery when budget
remains. If a target candidate is `visible_only`, `needs_observe`, or
references a generated target-inspection candidate, convert it only through the
public waypoint returned by `metric_map`, `resolve_target_query`, or tool
recovery, then observe from that waypoint before calling it actionable.

A not-found map-build answer must cite the public search budget, inspected
viewpoints, and any camera adjustment attempts. Call `done` only after the
selected map-build coverage policy has generated the Runtime Metric Map and
report artifacts.

## Helpers

The reference cleanup routine lives at
`skills/household-world/scripts/trace_preserving_cleanup.py`. Treat it as
executable documentation for public call order and recovery shape. It is not
permission to bypass MCP or read private backend state.

Use `skills/household-world/scripts/target_query_recovery.py` for offline
review of a saved public `runtime_metric_map.json`. It reads only public target
candidates.

Use `skills/household-world/scripts/scratchpad.py` when you need local memory
for strategy, retries, or current intent. The scratchpad is non-authoritative;
when scratchpad notes disagree with `cleanup_worklist`, trust
`cleanup_worklist`.
