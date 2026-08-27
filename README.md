# Roboclaws

[CI](https://github.com/MiaoDX/roboclaws/actions/workflows/ci.yml) ·
[Live showcase report](https://miaodx.com/roboclaws/) ·
[Python](./pyproject.toml) · [License](./LICENSE)

> **Let's Bring Brain To Robots**

**Visible household-robot demos driven by MCP tools, reusable skills, and
model-backed agent runtimes.** Roboclaws makes each run reviewable through
maps, frames, tool traces, scores, and public/private evaluation boundaries.

It answers three practical questions:

- How can an AI agent drive a robot?
- What context and tools does the agent need?
- What did the agent actually do in the simulated or robot-backed world?

![Surface, intent, skill, and capability profile architecture](docs/human/mcp-skills-and-semantic-profiles.svg)

## Quick Start

Start with the [live showcase report](https://miaodx.com/roboclaws/) to see the
latest model-backed and deterministic results. The [showcase workflow](.github/workflows/showcase.yml)
owns the scheduled/manual CI runs and links each attempt to its artifacts.

For local execution, installation, command grammar, and provider setup, use
[just/README.md](just/README.md), [model-matrix.md](docs/human/model-matrix.md),
and [local-runtime.md](docs/human/local-runtime.md).

## Current Capabilities

The [live showcase report](https://miaodx.com/roboclaws/) is advisory evidence
rebuilt from GitHub Actions. Each row is independent, and canonical bundles
remain Actions artifacts.

| Demo | View the effect | CI definition |
| --- | --- | --- |
| Deterministic smoke | [Latest report](https://miaodx.com/roboclaws/) | [Smoke row](.github/workflows/showcase.yml) |
| Map build | [Latest report](https://miaodx.com/roboclaws/) | [Kimi row](.github/workflows/showcase.yml) |
| Household cleanup | [Latest report](https://miaodx.com/roboclaws/) | [Kimi / MiMo / MiniMax rows](.github/workflows/showcase.yml) |
| Open household goal | [Latest report](https://miaodx.com/roboclaws/) | [Kimi / MiMo / MiniMax rows](.github/workflows/showcase.yml) |

The local [operator console](just/README.md) and maintainer gate
(`just agent::verify`) are documented separately.

## Documentation

- [Architecture and operating modes](ARCHITECTURE.md)
- [Commands and verification](just/README.md)
- [Models and local runtime](docs/human/model-matrix.md) · [keys and artifacts](docs/human/local-runtime.md)
- [Current project status](STATUS.md)
- [Human documentation index](docs/human/README.md)

## License

MIT
