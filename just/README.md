# Just Command Surface

Roboclaws uses a small composable Just grammar instead of exposing every
world/backend/preset/agent-engine combination as a separate recipe.

## Public Namespaces

- `run::*` is for humans and natural-language delegation.
- `agent::*` is for maintainer-level dispatch into private implementation
  modules.

Lower modules such as `molmo::*`, `harness::*`, `verify::*`, `mcp::*`,
`chat::*`, and `dev::*` are private. They remain runnable for
debugging, but they are hidden from `just --summary` and shell completion.

## Main Grammar

```bash
just run::surface surface=<surface> agent_engine=<engine> [world=<world>] [backend=<backend>] [preset=<preset>] [prompt=<goal>] [provider_profile=<profile>] [key=value ...]
```

Surfaces:

- `household-world`
- `planner-proof`

Household presets:

- `map-build`
- `cleanup`

Planner-proof still uses `intent=planner-proof`:

- `planner-proof`

Worlds and scenes:

- `molmospaces/val_0`
- `agibot-g2/map-12`
- `b1-map12`
- `planner-proof/default`

Backends are world-scoped, not a cross product:

- `mujoco` for MolmoSpaces household scenes and planner proof
- `isaaclab` for `world=b1-map12` and generic local Isaac runtime proof
- `agibot-gdk` for `world=agibot-g2/map-12`

MolmoSpaces household routes do not accept `backend=isaaclab`.

Agent engines:

- `openai-agents-sdk`
- `direct-runner`

Provider profiles are selected only for the SDK live engine. Examples include
`codex-router-responses`, `mimo-mify-responses`, `minimax-responses`, and
`kimi-openai-chat`.
`direct-runner` is a deterministic contract/eval baseline and does not accept
`provider_profile`; it is not a live robot agent runtime.

Validation-required maintainer engines stay out of the normal public engine
list. Use the repo-local maintainer docs and network guards before running
those routes.

Reports for non-Molmo tasks:

- `visual` is the default. Use it for human-facing runs that should produce
  reviewable images, timelines, and metrics.
- `minimal` is for cheaper semantic evidence during AI-agent iteration.

Household cleanup input/evidence lanes:

- `smoke` is the cheap synthetic contract sanity preset, not a real evidence
  lane.
- `world-public-labels` is the deterministic structured-label baseline. The
  agent receives observed object handles and structured labels, while
  destination/tool hints and pre-confirmed navigation permission are withheld.
- `camera-raw-fpv` withholds structured labels and provides raw camera
  artifacts for model-declared observations.
- `camera-grounded-labels` registers structured candidates from camera
  observations and requires `camera_labeler=<labeler>`.

`evidence_lane` decides what the agent sees. `camera_labeler` only applies to
`camera-grounded-labels` and decides how camera labels are produced. Use
`camera_labeler=grounding-dino` as the default deployment-like camera producer,
or labelers such as `yoloe`, `yolo-world`, and `omdet-turbo` for comparison.
Public `visual_grounding=...`
is no longer accepted on task routes; Visual Grounding Service terminology
remains internal service and benchmark provenance.

These lanes do not choose online/offline map behavior. Base Metric Map is
the current start-of-run map context: occupancy geometry, generated exploration
candidates, and public room-category hints when available. Use
`runtime_map_prior=...` when a cleanup run should consume a prebuilt Runtime
Metric Map snapshot or canonical Runtime Map Prior Snapshot. Historical
`minimal` / `rich` map artifacts may remain readable, but they are not current
product choices for operators or agents.

For timing work that should skip per-tool robot-view capture, keep the normal
`world-public-labels` lane and pass an explicit capture option such as
`robot_views=off`.

For `surface=household-world`, omit `preset=` for no-preset open household
goals and pass the operator goal through `prompt=...`. Use
`preset=cleanup prompt=...` only when the prompt narrows cleanup scope while
keeping cleanup evaluation.

## Live Agent Launch Behavior

`agent_engine=openai-agents-sdk` is the only active live-agent product engine.
It owns the cleanup/map-build MCP server process, SDK model calls, MCP trace,
model-call metrics, `run_result.json`, and the final checker. The route runs in
the foreground through the SDK runner and records probeable `live_status.json`
under the run directory.

Use the probe command to summarize an SDK live run:

```bash
just molmo::status
just molmo::status output/household/household-world/open-ended/openai-agents-live-world-public-labels/seed-7
```

The probe summarizes elapsed time, MCP tool progress, and
`run_result.json` / `report.html` readiness when those artifacts exist. Each
visual run owns its requested MCP port and backend slot; if the port is already
accepting connections, the launcher fails instead of choosing another port.

Repo-local `.env` keys route live SDK runs without editing user-level CLI
config. Normal users configure keys only; command shape controls behavior.

```bash
cp .env.example .env
# Fill CODEX_BASE_URL and CODEX_API_KEY for the default codex-router-responses / gpt-5.6-sol SDK route.
# Optional: set ROBOCLAWS_PROVIDER_PROFILE=mimo-mify-responses with XM_LLM_API_KEY.
# Optional: set ROBOCLAWS_PROVIDER_PROFILE=minimax-responses with MM_API_KEY.
```

Repo-local OpenAI Agents SDK provider routes may run on the work network.
`codex-router-responses` handles its Router transport compatibility
internally; callers select it like any other provider profile.

Provider/model facts are centralized in
`roboclaws/agents/provider_registry.py`, with current live verdicts in
`docs/human/model-route-verdicts.yaml` and narrative notes in
`docs/human/model-matrix.md`.

`codex-cli` and `claude-code` are retired active engines. Current
`run::surface`, `agent::run`, eval-harness, and operator-console routes reject
them instead of launching Docker wrappers or hidden fallbacks. The old
Docker-backed Codex/Claude helper route has been removed; use
`agent_engine=openai-agents-sdk` for live provider runs.

Current task mappings:

- `surface=household-world preset=map-build`: `household-world` with `task_intent=map-build` and cleanup actions disabled
- `surface=household-world preset=cleanup`: `household-world` with `task_intent=cleanup`
- `surface=household-world prompt=...`: `household-world` with an open-ended goal contract
- `surface=planner-proof intent=planner-proof`: planner-proof bundle runner

Python owns route metadata and reusable launch pieces:

- Public task specs live in domain packages such as `roboclaws.household.tasks`,
  then register through `roboclaws.launch.catalog`.
- Live-agent driver helpers and kickoff prompts live under `roboclaws.agents`.
- MCP server startup goes through `python -m roboclaws.cli.agent_server`, with
  launch-shaped household targets selecting the household server variants.
- Direct deterministic household runs through
  `python -m roboclaws.household.household_world_episode`; the example script
  is a thin wrapper for manual use.

## Examples

```bash
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=map-build agent_engine=openai-agents-sdk provider_profile=codex-router-responses evidence_lane=camera-grounded-labels camera_labeler=grounding-dino scenario_setup=baseline
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=openai-agents-sdk provider_profile=codex-router-responses evidence_lane=world-public-labels
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco agent_engine=openai-agents-sdk provider_profile=codex-router-responses prompt="我渴了，帮我找些解渴的东西"
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=world-public-labels runtime_map_prior=output/map/runtime_metric_map.json
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=camera-raw-fpv
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just agent::harness molmo-visual-grounding-benchmark pipeline=grounding-dino
just agent::eval recommend plan=docs/plans/example.md budget=focused
just agent::eval execute since=origin/main budget=focused
just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=direct-runner mode=dry-run
```

Product-like `camera_labeler=grounding-dino` runs auto-start the local real
sidecar from the dedicated visual-grounding environment when the default
`VISUAL_GROUNDING_BASE_URL` is not already reachable. The sidecar defaults to
DINO base recall (`IDEA-Research/grounding-dino-base`,
`box_threshold=0.25`, `text_threshold=0.20`).

You can also start it manually:

```bash
.venv-visual-grounding/bin/python scripts/visual_grounding/serve_visual_grounding_service.py \
  --pipeline real-router --adapter-mode real
```

The `camera-grounded-labels` product route runs a fail-fast sidecar readiness
check before starting the simulator or agent. A running `--pipeline
grounding-dino` service without real adapters is treated as contract-only
evidence and still blocks product runs instead of producing an ambiguous cleanup
failure. Set `ROBOCLAWS_AUTOSTART_VISUAL_GROUNDING_SIDECAR=0` to disable local
auto-start. Each run writes `visual_grounding_readiness.json` into its artifact
directory so a report can prove whether it used a real adapter.

To exercise only the HTTP contract without real model dependencies, start the
configurable service in its default mode. It should return explicit unavailable
evidence instead of fake candidates:

```bash
.venv/bin/python scripts/visual_grounding/serve_visual_grounding_service.py --pipeline grounding-dino
```

To inspect the sidecar adapter slots without starting a service:

```bash
.venv/bin/python scripts/visual_grounding/serve_visual_grounding_service.py --list-adapters
```

Detailed sidecar dependency and corpus commands live in
`docs/human/molmospaces-settings.md`.

## Maintainer Dispatch

Use `agent::*` only when you are intentionally bypassing the human task grammar:

```bash
just agent::run <dispatch-target> <agent-engine> [report|evidence-lane] [key=value ...]
just agent::verify <target> [args ...]
just agent::harness <target> [args ...]
just agent::mcp up
```

`agent::run` is a private maintainer dispatcher. Public callers should use
`run::surface`; the dispatcher accepts the surface-level `household-world`
target plus explicit `task_intent` and `task_preset` launch context.

The required PR gate is reproducible locally with
`just agent::verify ci-required`. Use `just agent::verify mock` for a faster
loop when you do not need the mock HTML report artifact.

Use `just agent::eval recommend|execute ...` when a plan or diff needs the
eval-harness facade instead of a hand-written fixed proof list. The harness
writes JSON, Markdown, and HTML under `output/eval-harness/` and records
selected, skipped, run, failed, and blocked rows with source-signal rationale.

For tests, set `ROBOCLAWS_JUST_TRACE=1` to print the lower-level command route
without launching the underlying simulator or agent.
