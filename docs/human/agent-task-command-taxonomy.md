# Surface And Agent Command Taxonomy

The implemented public command model is the surface open-task catalog in
`just run::surface`, with optional presets for repeated household jobs. Older
task ids are retired.

## Public Surface

Normal users should start with:

```bash
just run::surface surface=<surface> agent_engine=<engine> [world=<world>] [backend=<backend>] [preset=<preset>] [prompt=<goal>] [provider_profile=<profile>] [key=value ...]
```

Current surfaces:

- `household-world`
- `planner-proof`

Current household presets:

- `map-build`
- `cleanup`

No-preset household runs are open-ended prompt-driven tasks.

Current household backend ids are world-scoped, not a cross product:

- `mujoco` for MolmoSpaces household scenes
- `isaaclab` for `world=b1-map12`
- `agibot-gdk` for `world=agibot-g2/map-12`

MolmoSpaces + Isaac is retired from active command support.
The default household world remains `molmospaces/procthor-10k-val/0`; additional
source-aware MolmoSpaces world ids can be catalog/admission rows rather than
new public surfaces.

Current agent engines:

- `direct-runner`
- `openai-agents-sdk`

Other engine values fail current launch validation instead of acting as
compatibility aliases or hidden maintainer routes.

`prompt=...` without a household preset runs the default open-task contract.
`preset=cleanup prompt=...` keeps cleanup semantics while narrowing the
user-scoped cleanup request.

## Maintainer Dispatch

The maintained repository tasks are explicit:

```bash
just agent::verify
just agent::eval recommend|execute|suite=<suite>|promote-regression ...
just console::run
scripts/dev/network_status.sh
```

Specialist proof runners and process controls are package CLIs. Retired command
paths have no private aliases or compatibility adapters.

## Validation And Eval Layers

These layers are maintainer surfaces, not ordinary product-run axes:

| Layer | Command Shape | Use |
| --- | --- | --- |
| Eval harness | `just agent::eval recommend|execute ...` | Selects and records deterministic gates, product rows, eval-suite rows, live-agent eval rows, blockers, and regression-promotion guidance for a plan, diff, or explicit request. |
| Eval suite | `just agent::eval suite=<suite> ...` | Runs versioned samples, trials, graders, aggregate metrics, and failure replay. |
| Package proof | `python -m roboclaws.<owner>` | Executes a specialist proof at its implementation owner. |

The eval harness answers "what should this change validate and evaluate?" Eval
suites answer "is this capability improving across a stable benchmark?" Package
CLIs execute specialist proofs without adding another dispatch taxonomy.

## Evidence Lanes

Household cleanup/map-build routes use `evidence_lane` to describe what the
agent sees:

- `world-public-labels`
- `camera-raw-fpv`
- `camera-grounded-labels` with `camera_labeler=<labeler>`

`smoke` is a cheap verification preset/private runner mode, not a public
evidence lane.

## Verification

The command taxonomy is covered by:

```bash
./scripts/dev/run_pytest_standalone.sh -q tests/contract/dev_tools
just --summary
just agent::verify
```
