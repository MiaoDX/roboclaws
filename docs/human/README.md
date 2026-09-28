# Human Docs

This folder is the human-readable documentation surface beyond the root
`README.md`, `ARCHITECTURE.md`, and `STATUS.md`.

AI agents should also read these docs when they need human-facing context.

## Read First

- [Domain vocabulary](domain.md)
- [Agent/task command taxonomy](agent-task-command-taxonomy.md)
- [Evaluation suites](evaluation.md)
- [Eval harness dimensions](eval-harness-dimensions.md)
- [Technical design](technical-design.md)

## Reference

- [MolmoSpaces settings](molmospaces-settings.md)
- [Local runtime reference](local-runtime.md)
- [Model matrix](model-matrix.md)
- [Model route verdicts](model-route-verdicts.yaml)
- [Skill-first MCP architecture](mcp-skills-and-semantic-profiles.md)
- [UT and CI design](ut_ci_design.md)
- [Contributing](contributing.md)

## Specialized Runbooks

- [Agibot G2 Cleanup Pilot](agibot-g2-cleanup-pilot.md)
- [Architecture hygiene review](architecture-hygiene-review.md)

## AI-Agent Docs

Other `docs/` folders are still useful to agents, but they are not the normal
human review surface:

- `docs/adr/` - durable decision records
- `docs/plans/` - pre-GSD plans and generated planning detail
- `docs/retrospectives/` - shipped history
- `docs/status/active/` - parallel work notes
- `docs/ai/` - implementation evidence, experiments, and agent-only runbooks
