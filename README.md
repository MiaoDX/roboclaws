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
rendered as HTML reports instead of buried in terminal logs.

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

The advisory [live report](https://miaodx.com/roboclaws/) is rebuilt from the
latest GitHub Actions showcase. It reports each row independently, so a
provider timeout remains visible instead of hiding successful evidence from
the other providers. Canonical report bundles remain Actions artifacts.

| Capability | Agent route | Showcase coverage | Evidence |
| --- | --- | --- | --- |
| Deterministic smoke | `direct-runner` | Cleanup contract baseline | [Latest status](https://miaodx.com/roboclaws/) |
| Map build | `openai-agents-sdk` + `kimi-openai-chat` | Camera-grounded map-build sample | [Latest status](https://miaodx.com/roboclaws/) |
| Household cleanup | `openai-agents-sdk` | Kimi, MiMo, and MiniMax samples | [Latest status](https://miaodx.com/roboclaws/) |
| Open household goal | `openai-agents-sdk` | Kimi, MiMo, and MiniMax samples | [Latest status](https://miaodx.com/roboclaws/) |
| Operator console | Local SDK routes | Interactive Build Map, Open Task, and Cleanup workflows | Local-only operator surface |
| Maintainer gate | `just agent::verify` | Lint, architecture, contract, and mock tests | [CI workflow](https://github.com/MiaoDX/roboclaws/actions/workflows/ci.yml) |

Run a model-backed household task by selecting one of the public provider
profiles:

```bash
just run::surface surface=household-world agent_engine=openai-agents-sdk preset=cleanup provider_profile=kimi-openai-chat evidence_lane=world-public-labels
just run::surface surface=household-world agent_engine=openai-agents-sdk preset=cleanup provider_profile=mimo-tp-openai-chat evidence_lane=world-public-labels
just run::surface surface=household-world agent_engine=openai-agents-sdk preset=cleanup provider_profile=minimax-responses evidence_lane=world-public-labels
```

The [capability showcase workflow](https://github.com/MiaoDX/roboclaws/actions/workflows/showcase.yml)
runs weekly or by manual dispatch. It is advisory evidence, not a merge gate.

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
