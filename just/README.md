# Just Command Surface

Just is the small repository entrypoint layer. Product execution, process
lifecycle, validation, and specialist proofs belong to typed Python package
owners rather than private Just registries.

## Commands

The complete maintained surface is:

```text
run::surface
agent::eval
agent::verify
console::run
```

- `run::surface` launches a product surface through the typed launch catalog.
- `agent::eval` selects or runs eval-harness and eval-suite work.
- `agent::verify` runs the one required local/CI gate.
- `console::run` starts the local operator console.

There are no compatibility aliases or lower private command registries. A
retired command should be replaced at its caller with a canonical command or a
package CLI.

## Product Grammar

```bash
just run::surface surface=<surface> agent_engine=<engine> [world=<world>] [backend=<backend>] [preset=<preset>] [prompt=<goal>] [provider_profile=<profile>] [key=value ...]
```

Current surfaces are `household-world` and `planner-proof`. Household runs use
`preset=map-build`, `preset=cleanup`, or no preset for an open-ended prompt.

World/backend support is scoped rather than a cross product:

- MolmoSpaces household worlds use `backend=mujoco`.
- `world=b1-map12` uses `backend=isaaclab`.
- `world=agibot-g2/map-12` uses `backend=agibot-gdk`.
- `world=planner-proof/default` uses `backend=mujoco`.

The active engines are `openai-agents-sdk` for live agents and `direct-runner`
for deterministic product proofs. Only the SDK engine accepts a
`provider_profile`.

Household evidence is selected with `evidence_lane=world-public-labels`,
`camera-raw-fpv`, or `camera-grounded-labels`. The camera-grounded lane also
requires `camera_labeler=<labeler>`.

## Examples

```bash
just run::surface surface=household-world agent_engine=direct-runner preset=map-build evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just run::surface surface=household-world agent_engine=openai-agents-sdk preset=cleanup evidence_lane=world-public-labels provider_profile=kimi-openai-chat
just run::surface surface=household-world agent_engine=openai-agents-sdk prompt="find something useful to drink" provider_profile=kimi-openai-chat
just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=direct-runner mode=dry-run
just console::run
```

Use the package-owned live status probe for a running or completed SDK run:

```bash
python -m roboclaws.agents.live_status_cli [run-dir]
```

## Eval And Verification

```bash
just agent::eval recommend plan=docs/plans/example.md budget=focused
just agent::eval execute since=origin/main budget=focused
just agent::eval suite=smoke_regression budget=smoke
just agent::eval phoenix-project suite=smoke_regression [eval_results=<path>] [endpoint=http://127.0.0.1:6006] [output=<path>]
just agent::verify
```

`agent::eval` records selected, skipped, failed, and blocked rows under
`output/eval-harness/`. Live execution remains explicit through
`live_execution=run`.

`phoenix-project` is a read-only maintainer projection of a repo suite and an
optional existing `eval_results.json`. Without `endpoint` it writes a disabled
local mapping; an endpoint must be a loopback Phoenix HTTP origin.

## Specialist Package CLIs

Specialist proofs are Python interfaces, not hidden Just commands:

```bash
python -m roboclaws.household.planner_proof_execution --output-dir output/planner-proof --mode dry-run
python -m roboclaws.evals.visual_grounding_benchmark.runner --pipeline grounding-dino
python -m roboclaws.backends.isaaclab.runtime_preflight
python -m roboclaws.backends.isaaclab.runtime_smoke
.venv-isaaclab/bin/python -m roboclaws.backends.isaaclab.b1_navigation_proof
```

The visual-grounding product route starts its required sidecar automatically
unless `ROBOCLAWS_AUTOSTART_VISUAL_GROUNDING_SIDECAR=0`. Manual service and
readiness debugging use the package owners directly:

```bash
.venv-visual-grounding/bin/python -m roboclaws.household.visual_grounding_sidecar.service --pipeline real-router --adapter-mode real
python -m roboclaws.household.visual_grounding_sidecar.readiness --pipeline grounding-dino
```

Provider-sensitive workflows must first pass:

```bash
scripts/dev/network_status.sh
```
