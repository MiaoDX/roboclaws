# Roboclaws Technical Design

Roboclaws is a thin embodied-agent demo repo. Its current design target is
household-world cleanup, map building, open-ended household goals, and planner
proof evidence with honest public/private boundaries.

For the implementation map, read [`ARCHITECTURE.md`](../../ARCHITECTURE.md).
For domain vocabulary, read [`domain.md`](domain.md). Durable platform
decisions live in [`docs/adr/`](../adr/).

## Product Shape

Current public work is selected by a small launch catalog:

```text
surface + world + backend + intent + agent_engine + provider_profile + evidence_lane
```

For household work, the public selector is now the `household-world` open-task
surface plus either `prompt=...` or optional `preset=map-build|cleanup`. The
internal goal contract still records `task_intent` for artifacts and checkers.

The active surfaces are:

- `surface=household-world`
- `surface=planner-proof`

The household presets are:

- `preset=map-build`
- `preset=cleanup`

No-preset household runs are open-ended prompt-driven tasks.

The launch catalog resolves these axes once into a typed launch plan.
`roboclaws.launch.executor` owns the closed direct/SDK adapter dispatch and
child-process lifecycle; product, console, and eval callers execute that plan
instead of rebuilding private commands or positional argument lists.

The design goal is not to hide a whole task behind one opaque tool. Every
serious run should leave reviewable evidence: a goal contract, public MCP/tool
trace, runtime map or report artifacts, and a human-readable `report.html`.

## Household World Direction

The household stack starts from a Base Metric Map: occupancy/free-space
context, generated exploration candidates, and public room-category hints when
available. Map-build and observations enrich that context into a Runtime Metric
Map. Downstream runs can consume either raw `runtime_metric_map.json` or the
canonical `runtime_map_prior_snapshot_v1` package.
`roboclaws.maps.runtime_prior_catalog` owns catalog loading, compatibility, and
auto-enable policy for product consumers. Candidate scoring, selection reports,
and explicit promotion remain eval responsibilities.

Cleanup separates:

- public agent-facing evidence;
- private evaluator truth;
- semantic scene mutation provenance;
- planner-backed manipulation proof;
- blocked-capability claims for work that has not been physically proven.

This is why the same report can show an agent-facing trace and private scoring
without leaking private truth into MCP profile metadata or agent inputs.

## Backend Strategy

Backends are variants under the same surface/preset contract:

- `mujoco` for standard MolmoSpaces local cleanup.
- `isaaclab` for the B1 / Map 12 digital-twin route and generic Isaac runtime
  proof needed by that route.
- `agibot-gdk` for Agibot SDK map, observation, and navigation boundaries.

Backend-specific implementation details stay below the launch catalog. A new
backend should preserve public artifact names, profile requirements, and checker
semantics before claiming parity. MolmoSpaces household scenes use MuJoCo as
the active backend; MolmoSpaces Isaac support is retired rather than kept as a
hidden or compatibility route.

## Agent Strategy

Agent engines are product runtimes, not tasks:

- deterministic direct runner;
- OpenAI Agents SDK live route.

Retired agent engines are ordinary unsupported values. The product does not
retain gateway, local-container, compatibility, or deprecated-command routes.
Script-style proof and dry-run paths belong under direct runners, harness
recipes, or backend adapters; they are not public agent engines.

Reusable behavior belongs in skills. The maintained `household-world` skill
has cleanup, map-build, and open-ended sections selected by GoalContract,
TaskIntentSpec, and optional TaskPresetSpec. The goal contract and checker
policy decide what completion means for a run.

## Evaluation Strategy

Evaluation is a first-class maintainer layer above individual reports. Product
runs still use `just run::surface ...`; the eval harness selects which
deterministic gates, product rows, eval suites, and live-agent evals a plan or
diff must run; eval suites run versioned samples, repeated trials,
deterministic graders, aggregate metrics, and failure replay. Harness recipes
remain lower-level execution mechanics.

The first eval command shape is `just agent::eval ...`. Eval samples must reuse
the current household surfaces, MCP tools, public/private evidence split, and
Base Metric Map / Runtime Metric Map contracts instead of introducing a
parallel task taxonomy.

Evaluation is repository-owned maintainer code. Source and wheel distributions
contain the product runtime but omit `roboclaws.evals`, eval definitions, and
the eval-harness skill; maintainers run evals from a Git checkout through
`just agent::eval`.

## Current Non-Goals

- Do not reintroduce retired surfaces as compatibility shims.
- Do not expose private generated mess truth or hidden acceptable destinations
  to agents.
- Do not claim physical manipulation readiness without planner-backed or
  robot-backed evidence.
- Do not add backend-specific public task ids when a backend variant can live
  under the existing household surface.
