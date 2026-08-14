# Skill-First MCP Architecture

The root [`README.md`](../../README.md) owns the big-picture MCP and skill
design principles. This note is the companion reference for how Roboclaws
connects agent skills, MCP tools, semantic robot capabilities, and execution
backends without making teammates read the GSD phase logs.

![MCP skills and semantic profile architecture](mcp-skills-and-semantic-profiles.svg)

## Reference Summary

Roboclaws uses a **skill-first, MCP-bounded** architecture:

1. A user gives an **open-ended goal**, such as "clean the room" or "inspect
   this room."
2. The goal resolves to a **surface open-task contract** plus either a
   natural-language `prompt=...` or an optional preset such as
   `surface=household-world preset=map-build` or
   `surface=household-world preset=cleanup`.
3. The surface or preset selects, defaults, or creates an **agent skill**.
4. The skill may call scripts, examples, checks, and MCP tools.
5. The **MCP capability profile** keeps the public robot capability boundary stable.
6. The execution backend runs environment-specific primitives.
7. Reports and evals feed the task and skill lifecycle.

The design bias is to keep reusable behavior in skills and to resist adding
new MCP tools unless the behavior clearly belongs in the robot capability
contract.

This aligns with the "skill issue" framing discussed by Andrej Karpathy on
[No Priors](https://www.youtube.com/watch?v=kwSVtQ7dziU): with capable agents,
the bottleneck shifts to how well we define tasks, give context, build tools,
run loops, evaluate outputs, and maintain reusable agent behavior. Roboclaws
applies that idea to robotics by letting skills evolve while MCP capability
profiles stay bounded and auditable.

A profile is not a task recipe. It is closer to the capability side of a skill
manifest: a named, reusable environment of public tools, evidence boundaries,
blocked capabilities, provenance expectations, and private-data exclusions. A
runnable surface and optional preset answer "what public run is this and how is
it accepted?", a skill answers "how should I accomplish this goal?", and a
profile answers "which stable robot capabilities may this skill rely on?"

## Abstraction Ladder

Build from the bottom up, but let the agent enter from the top:

| Level | Owns | Examples | What to watch |
| --- | --- | --- | --- |
| Open-ended goal | Human intent | "clean the room", "inspect this room" | Do not turn this into one opaque MCP tool. |
| Runnable surface and optional preset | Public command, parameters, report shape, acceptance gates | `surface=household-world prompt=...`, `surface=household-world preset=map-build`, `surface=household-world preset=cleanup` | Keep it separate from strategy and backend implementation. |
| Agent skill | Reusable behavior package | `household-world` | Skills can evolve, merge, split, and be pruned. |
| Trace-preserving skill routine | Skill-side reusable execution shape | scripted cleanup loop, `navigate -> observe -> pick -> place` | Default home for reusable composition before MCP promotion. |
| Composite action | Describes a skill's internal behavior shape | `navigate -> observe -> pick -> place` | Descriptive by default, not a separate artifact. |
| Composed semantic capability | Bounded capability or service | localization, navigation, search, transport | Promote only when the boundary is stable. |
| Atomic semantic capability | Small public robot action | observe, move, turn, pick, place, open, close | Prefer these for MCP capability contracts. |
| Environment primitive | Backend-specific implementation | MuJoCo actuation, Isaac rendering, robot API call | Not agent-facing by default. |
| Execution backend | Actual environment | MolmoSpaces, Isaac Lab, RBY1M, Agibot G2 | Backends differ; profiles should not pretend otherwise. |

Capability profiles sit beside this ladder as reusable public environments for
skills. For example, `surface=household-world preset=map-build` can select a
map-building skill that requires household world capabilities and forbids
manipulation, while `surface=household-world preset=cleanup` can select a
cleanup skill that requires the same world capabilities plus manipulation. Both
presets can share the same world profile without making the profile own either
task.

Composition is the rule. A task or skill may require multiple capability
profiles or capability modules, but a new profile should not be made by copying
another profile's tool list and adding more tools. For example,
`preset=cleanup` should require `household_world` plus manipulation
capabilities; it should not define a cleanup profile that duplicates the whole
world profile. The selected skill is where composite behavior such as
`navigate_to_object -> pick -> navigate_to_receptacle -> open? -> place` lives.

Real-robot deployment should use the same public layers. A physical run should
change backend variant, provenance, safety gate, and blocked-capability status;
it should not need a separate robot-only task taxonomy when the public task,
skill requirement, and profile shape already fit.

Household inspection routines should start as skills by default. Internally,
they may perform a composite action such as `search -> navigate -> observe ->
verify`. They should not become MCP tools unless several skills need the same
stable capability and the public trace semantics are clear.

## Skill Library Lifecycle

Skills are where reusable behavior evolves:

```text
Open-ended goal
  -> search/select existing skill
  -> if no good skill exists, solve with lower-level tools
  -> record trace/report/eval
  -> extract or improve reusable skill behavior
  -> periodically refactor, merge, prune, and re-evaluate skills
```

The skill layer can hold long-running behavior, prompt strategy, scripts,
examples, checks, and maintenance notes. It is the right home for reusable
strategy such as generated-mess cleanup, grocery placement, target search, or
room inspection. Public command names, parameters, reports, and acceptance gates
belong to runnable surfaces and intents.

MCP is different: it is the public robot capability boundary. A skill can call
many MCP tools, but the skill itself is not automatically a robot capability
claim.

Eval Evolution may optimize existing MCP descriptions or bounded public
response projections, but it does not let candidates change the public tool
set. Description candidates may change only allowlisted summaries while tool
identity, classification, provenance, and ordering remain frozen. Behavior
candidates are materialized by digest, checked without importing or executing
candidate Python on the trusted host, and run only in the dedicated isolated
worker after a campaign-bound attestation passes.

The trusted MCP server creates the baseline-public projection before the
candidate boundary. The candidate receives one sanitized JSON request and
returns one validated JSON response; it never receives raw world state,
provider credentials, eval/checker code, holdout data, or durable output access.
Candidate failure fails the call closed. There is no same-process or trusted-host
fallback, and promotion remains a separate human-approved operation.

A **trace-preserving skill routine** is the preferred first shape for repeated
composition. It can use scripts, evals, structured output, and explicit recovery
while still leaving MCP bounded to public capabilities. If a routine is later
promoted into MCP, the skill should stop duplicating the lower-level call chain
and call the promoted capability instead.

## Skill Manifests

Maintained skills include a small `skill.json` manifest next to `SKILL.md`.
The manifest is not another runtime API. It is a human/test-readable contract
for the skill library:

- which MCP capability profiles or modules the skill expects;
- which tools are required, optional, or privileged;
- which scripts belong to the skill;
- which artifacts count as evidence;
- when to refactor the skill or promote behavior into MCP.

This keeps reusable behavior shareable without hiding task strategy inside the
core MCP server. See `skills/README.md` for the manifest fields.

## MCP Promotion Rule

Resist adding MCP tools by default. Promote behavior from a skill or script
into an MCP tool only when all of these are true:

1. Multiple skills need it.
2. Inputs and outputs are stable for one capability profile.
3. It has traceable substeps or a clear atomic meaning.
4. It uses only public allowed information.
5. It belongs in the robot capability boundary, not just agent strategy.

For example, observation belongs in MCP because it is a stable capability with
clear artifact output. A full inspection or cleanup routine usually belongs in
a skill because it is task strategy.

Promoted composite tools should be rare enough that an empty promoted-tools
surface is the normal state. A non-empty promoted surface should mean the
composition has become a backend-enforced, cross-client capability contract, not
merely a faster way to call several tools.

## Composite Actions and Privileged Tools

A **composite action** is an honest behavior shape built from lower-level
semantic capabilities. It records or preserves its substeps. It is descriptive
by default, not a separate maintained artifact.

A **privileged tool** is a non-canonical tool that uses information or execution
power a robot would not generally have. Privileged tools can stay useful for
demos, debugging, smoke tests, or proof loops, but they must not be treated as
canonical robot capability claims.

Examples:

| Behavior | Classification | Why |
| --- | --- | --- |
| Household inspection routine | Agent skill with a composite action inside | It combines search, navigation, observation, and verification. |
| `put_in_refrigerator(object)` | Skill or composite action, depending on packaging | It can be decomposed into navigate, open, place, close. |
| Selected-object cleanup transport | Agent skill routine | The cleanup skill composes `navigate_to_object -> pick -> navigate_to_receptacle -> open? -> place/place_inside -> close?` through public atomic tools. It remains skill-side unless promotion criteria are met; it is not exposed as a default MCP tool. |
| Hidden acceptable-destination lookup | Privileged/private evaluator data | It must never enter public profile metadata. |

## Current Capability Profiles

The current household profile head is task-neutral. Public intents such as
`map-build` and `cleanup` select skills and acceptance gates inside
`surface=household-world`; profiles describe reusable capability environments
and backend variants.

### `household_world`

Canonical public capability tools cover household world evidence only:

- public metric map and fixture context;
- runtime metric map snapshots, observed-object priors, and update candidates
  exposed through `metric_map()` / Agent View;
- Runtime Map Prior Snapshot artifacts that package online
  `runtime_metric_map_v1` output or offline Agibot `navigation_memory.json`
  conversion into one downstream consumer contract;
- room and waypoint navigation for evidence capture;
- public observation, camera adjustment, visual candidate declaration, and
  visible-object inspection.

`household_world` is shared by `preset=map-build`, `preset=cleanup`,
inspection, search, no-preset household goals, and future household presets.
It excludes manipulation and task-completion tools such as `pick`, `place`,
`open_receptacle`,
`close_receptacle`, and `done`.

The artifact boundary is task-neutral: `preset=map-build` may emit a raw
`runtime_metric_map.json`, and map-conversion skills may turn Agibot
`navigation_memory.json` into `runtime_map_prior_snapshot_v1`. Cleanup
and open household tasks consume the canonical snapshot or its runtime-map
payload through `runtime_map_prior=...`; they should not add an Agibot-specific
loading path. Movable-object priors from any snapshot remain `needs_confirm`
until current-run evidence observes them again.

Backend variants such as `api_semantic_synthetic`, `molmospaces_subprocess`,
and `agibot_gdk` are profile metadata/config. They are not new public task
names or copied profile ids. ROS2/Nav2 is a future backend candidate, not an
active profile variant.

### `household_manipulation` and `household_episode`

Cleanup skills compose `household_world` with manipulation and lifecycle
capabilities when they need to move objects:

- `household_manipulation` owns object/receptacle navigation plus
  `pick`, `place`, `place_inside`, `open_receptacle`, and `close_receptacle`.
- `household_episode` owns explicit task completion through `done` and
  active-run operator steering through `check_operator_messages`.

`done` is also the authoritative completion-readiness checkpoint. When public
run state shows that closeout is premature, the server returns a structured
`completion.blockers` payload with public recovery hints while preserving the
older top-level `error_reason` / `required_tool` fields during migration.
Readiness policies may use Agent View, public tool traces, public worklists,
semantic substeps, and public run acceptance configuration; they must not use
hidden mess membership, acceptable destination sets, private manifests, or
scorer truth. Do not add a separate default MCP tool just to ask whether `done`
is ready.

`check_operator_messages` is a public steering checkpoint for supported
operator-console routes. Ordinary MCP responses may expose only a pending hint
when unread operator steering exists; the message text is retrieved through
`check_operator_messages`, which marks queued messages as seen. It is not a
post-`done` mutation path: terminal runs keep their report and checker evidence
fixed, and follow-up work starts as a linked run from the operator console.

Physical backends may expose these tools as structured `blocked_capability`
responses until manipulation is proven.

### Legacy cleanup-shaped profiles

`molmospaces_cleanup_v1` is no longer an active selectable MCP contract profile.
It remains only as historical report metadata for archived MolmoSpaces cleanup
artifacts. New skills and MCP routers compose `household_world`,
`household_manipulation`, and `household_episode` directly.

`real_robot_cleanup_v1` is likewise a historical artifact metadata value for
older physical-pilot reports. Active physical routes should describe required
capabilities through the household world, manipulation, and episode profiles,
with manipulation returning structured `blocked_capability` responses until
physical proof exists.

- `metric_map` returns backend-neutral public map semantics. Sim and offline
  map-artifact paths may derive this from a Nav2-shaped map bundle;
  Agibot-backed runs derive it from an SDK-exported agent view generated from
  operator-authored map context.
- `metric_map` is the current map-reading path. The Base Metric Map exposes
  occupancy/free-space context, generated candidates, and public room-category
  hints when available; Runtime Metric Map evidence adds observed anchors and
  target candidates during a run. Historical `static_fixture_projection` artifacts may
  still be displayed for old reports, but active skills should discover
  destinations through metric-map evidence and target-query resolution rather
  than reading static fixture projection first.
- `navigate_to_room`, `navigate_to_waypoint`, `navigate_to_visual_candidate`,
  `navigate_to_object`, and `navigate_to_receptacle` resolve cleanup goals to
  bounded physical navigation actions when enough public grounding is available.
  Current physical provenance may be `agibot_gdk_normal_navi` or
  `blocked_capability`.
- `observe`, `adjust_camera`, `declare_visual_candidates`, and
  `inspect_visible_object` stay grounded in robot-camera artifacts.
- `pick`, `place`, `place_inside`, `open_receptacle`, and `close_receptacle`
  are present only as structured `blocked_capability` responses until physical
  manipulation is proven.

This profile exists so reports can distinguish
`physical_navigation_pilot=true` from `physical_cleanup_ready=false`. Agibot
runs additionally render SDK-owned subphase reports for agent-view export,
policy observation, and waypoint navigation, keeping GDK-specific execution
evidence outside the Roboclaws Python runtime.

## Design Considerations

### Keep Profiles Capability-Oriented

There is no premature universal robot API here. Household simulator and
physical-robot backends can share capability-family names while exposing
different executable or blocked behavior.

Prefer names that describe reusable capability environments:

- `household_world`
- `household_manipulation`

Task-like public work belongs in the surface open-task contract and optional
preset catalog:

- `surface=household-world prompt=...`
- `surface=household-world preset=map-build`
- `surface=household-world preset=cleanup`

Reusable strategy names belong in skills:

- `household-world`

Backend variants such as `molmospaces_subprocess`, `api_semantic_synthetic`, or
`agibot_gdk` should be profile metadata or run configuration, not the primary
task or skill name.

### Compose Requirements, Do Not Copy Profiles

Reusable capability profiles should remain small enough to be shared:

- `household_world` owns world understanding and evidence capture.
- A manipulation capability profile owns `pick`, `place`, `open_receptacle`,
  and `close_receptacle` when those tools are available or blocked.
- Agent skills declare the profiles they require, then compose tools into
  strategy.

This keeps future household tasks cheap to add. Object search, inspection,
navigation rehearsal, and cleanup can share the same world profile without each
creating a copied profile with the same map, observation, and waypoint tools.

### Keep Planning in the Agent and Skills

The model should plan over capabilities. Skills should capture reusable
behavior. MCP should expose bounded abilities and semantic services, not
whole-goal tools like `cleanup_room()`.

This keeps behavior inspectable: the report can show the steps the agent or
skill chose instead of hiding the work behind one tool call.

When a cleanup or inspection routine becomes repetitive, first make it a
trace-preserving skill routine with tests and report evidence. Promote it into
MCP only when the composition itself must be discoverable, schema-validated,
and enforced across clients or backend variants.

### Prefer Forward-Only Cleanup

Profiles define the current public surface. When a profile replaces an older
server, recipe, or skill shape, update in-repo callers and remove the stale
surface instead of keeping compatibility shims. Historical report rendering can
keep reading archived artifacts, but active MCP and skill entrypoints should
live at the current profile head.

## How a Request Flows

```text
Open-ended goal
  -> runnable surface and optional preset selection
  -> skill library search / skill creation
  -> selected skill calls scripts and MCP tools
  -> capability profile constrains public capabilities
  -> execution backend runs primitives
  -> trace/report/eval feeds skill maintenance
```

For Molmo cleanup, the profile keeps the public cleanup surface separate from
private scoring and planner proof evidence. A clean report can therefore be
honest about whether the result is `api_semantic`, `planner_backed`, or
`blocked_capability`.

## Adding a New Profile

When adding a profile, start from the capability contract, not the task or skill:

1. Name the reusable capability environment, such as `household_world`, or
   keep an existing backend/domain id only while migrating older surfaces.
2. Check whether the new need can be represented as a skill requirement over
   existing profiles. Do not copy one profile's tools into another profile just
   to make a task-specific bundle.
3. List capability families: perception, localization, mapping, navigation,
   manipulation, memory, and episode.
4. List canonical public tools.
5. List privileged tools separately.
6. List private terms that must never appear in public metadata.
7. Add contract tests that prove profile validation fails closed.
8. Update the relevant human doc if the new profile changes how teammates
   should reason about the system.

Do not add a new profile just to rename a demo recipe or skill. Demo recipes
choose how to run a scenario; skills own reusable behavior; semantic profiles
describe what public robot capabilities the agent is allowed to rely on.

## Where to Look in the Repo

| Need | File |
| --- | --- |
| Profile declarations and built-ins | `roboclaws/mcp/profiles.py` |
| Generic profile router helper | `roboclaws/mcp/entrypoint.py` |
| Household-world MCP server | `roboclaws/household/household_mcp_server.py` |
| Skill library convention | `skills/README.md` |
| Household-world skill | `skills/household-world/SKILL.md` |
| Runtime map prior snapshot code | `roboclaws/maps/runtime_prior_snapshot.py` |
| Agibot navigation-memory converter | `python -m roboclaws.maps.runtime_prior_conversion agibot-navigation-memory` |
| Profile/router contract tests | `tests/contract/mcp/test_semantic_profiles.py` |
| Skill manifest tests | `tests/contract/skills/test_skill_manifests.py` |
| Shareable architecture diagram | `docs/human/mcp-skills-and-semantic-profiles.svg` |

Planning artifacts for Phase 136 explain the implementation history, but this
document is the human entry point for sharing the architecture with teammates.
