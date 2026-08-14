# Roboclaws

[CI (main)](https://github.com/MiaoDX/roboclaws/actions/workflows/ci.yml)
[Live Reports](https://miaodx.com/roboclaws/)
[Python](./pyproject.toml)
[Install](https://docs.astral.sh/uv/)
[License](./LICENSE)

> **Let's Bring Brain To Robots**

**Visible household-robot demos driven by MCP tools, reusable skills, and live-agent SDK/direct runtimes.**

Roboclaws is a thin demo repo for making AI-driven robotics behavior reviewable:
frames, maps, tool traces, scores, and public/private evaluation boundaries are
published as HTML reports instead of buried in terminal logs.

![Surface, intent, skill, and capability profile architecture](docs/human/mcp-skills-and-semantic-profiles.svg)

It answers three practical questions:

- How can an AI agent drive a robot?
- What context and tools does the agent need?
- What did the agent actually do in the simulated or robot-backed world?

## MCP and Skill Design Principles

Roboclaws treats reusable robot behavior as **skills first** and MCP tools as a
bounded public robot capability surface.

The short version:

- Public runs use `just run::surface` with `surface=...`, optional
  `preset=...`, and natural-language `prompt=...`.
- Skills own task strategy such as map-build, cleanup, and open household
  goals.
- MCP exposes bounded robot capabilities such as observe, navigate, pick,
  place, and done.
- Private evaluator truth stays out of agent inputs and public profile
  metadata.

The detailed profile and skill reference is
[docs/human/mcp-skills-and-semantic-profiles.md](docs/human/mcp-skills-and-semantic-profiles.md).

## Run Demos With Just

Install the project once:

```bash
uv sync --extra dev
```

The `dev` extra includes the standard MolmoSpaces/MuJoCo CPU runtime used by
local cleanup demos. Isaac Lab is scoped to the B1 / Map 12 digital-twin route
and generic local runtime proof; keep it isolated in `.venv-isaaclab/` and do
not treat it as part of normal MolmoSpaces demos.

The public command grammar is named-parameter only. Public household launches
name the operator-facing surface, world or scene, backend runtime, optional task
preset, and agent engine separately:

```bash
just run::surface surface=<surface> agent_engine=<engine> [world=<world>] [backend=<backend>] [preset=<preset>] [prompt=<goal>] [key=value ...]
```

For full command routing, profiles, and maintainer-only recipes, read
[just/README.md](just/README.md).

To monitor and launch the supported local SDK household routes from a
standalone browser console, run:

```bash
just console::run
```

The console uses the same world/backend/preset/agent-engine catalog for local
SDK/direct runs, but its main screen is organized around product workflow
actions: Build Map, Open Task, and Cleanup. Runtime Map Prior Snapshot use is a
workflow setting, while standard mess preparation and reset are scene setup or
operations controls. Advanced controls expose raw launch axes for maintainers;
browser-submitted launches still resolve through the public catalog rather than
arbitrary shell commands.

## Demo Matrix

GitHub Actions publishes the report site at
[miaodx.com/roboclaws](https://miaodx.com/roboclaws/). If a link looks stale,
check the [CI workflow](https://github.com/MiaoDX/roboclaws/actions/workflows/ci.yml):
Pages republishes from successful `main` runs.

| Demo | Run it locally | Report |
| --- | --- | --- |
| Map build | `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=map-build agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=camera-grounded-labels camera_labeler=grounding-dino seed=7 scenario_setup=baseline` | Local artifact today. Use `agent_engine=direct-runner` only for deterministic contract baselines. |
| Household cleanup | `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=world-public-labels seed=7 scenario_setup=relocate-cleanup-related-objects relocation_count=5` | [Molmo live index](https://miaodx.com/roboclaws/molmo/live/) |
| Open household goal | `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat prompt="find something useful to drink"` | Local artifact today. |
| Planner proof | `just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=direct-runner mode=dry-run` | Local artifact today. |
| Operator console | `just console::run` | Local-only operator surface. |
| Maintainer gate | `just agent::verify mock` | CI status: [workflow](https://github.com/MiaoDX/roboclaws/actions/workflows/ci.yml) |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the code map and the full operating
mode contract.

## Documentation Map


| Need                             | Read                                                                                                       |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Code map and operating modes     | [ARCHITECTURE.md](ARCHITECTURE.md)                                                                         |
| Human setup/runbooks/domain docs | [docs/human/README.md](docs/human/README.md)                                                               |
| Detailed MCP profile reference   | [docs/human/mcp-skills-and-semantic-profiles.md](docs/human/mcp-skills-and-semantic-profiles.md)           |
| Eval suites and validation       | [docs/human/evaluation.md](docs/human/evaluation.md)                                                       |
| Skill library convention         | [skills/README.md](skills/README.md)                                                                       |
| Public command grammar           | [just/README.md](just/README.md)                                                                           |
| Local keys and report artifacts  | [docs/human/local-runtime.md](docs/human/local-runtime.md)                                                 |
| MolmoSpaces settings             | [docs/human/molmospaces-settings.md](docs/human/molmospaces-settings.md)                                   |
| Current project focus            | [STATUS.md](STATUS.md)                                                                                     |
| Agent operating rules            | [AGENTS.md](AGENTS.md)                                                                                     |


## License

MIT
