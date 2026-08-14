# ADR-0148: Retire OpenClaw And Local Docker Runtime

Status: Accepted

Date: 2026-07-30

## Context

Roboclaws has two active agent engines: `direct-runner` and
`openai-agents-sdk`. OpenClaw remained only as a validation-required maintainer
route, and repo-owned workstation Docker remained only to support that route,
two uncalled image-smoke scripts, and stale operator-console cleanup logic.
Those surfaces imposed maintenance and verification obligations without a
current product or repo-configured CI consumer.

CloudML images and remote container runtimes are separate platform contracts.
They do not depend on workstation-local Docker ownership in this repository.

## Decision

Retire OpenClaw and repo-owned workstation-local Docker runtime, image-smoke,
and resource-management surfaces. Unknown engine values use the ordinary launch
validation path; there is no compatibility alias, deprecated command, or
replacement gateway.

Preserve the two active agent engines, current provider profiles, MCP and eval
contracts, host simulator and robot runtimes, and CloudML Docker/image build,
publish, selection, and remote-runtime contracts. Historical plans, archived
ADRs, retrospectives, research bodies, and immutable evidence remain history,
not current instructions. Residual `.openclaw-tmp/` and `.openclaw-token`
ignore rules remain as safeguards.

## Consequences

- Active launch, provider, Just, checker, skill, test, hook, and operator-console
  owners no longer implement or advertise OpenClaw.
- Maintained local tests and operator-console inventory do not invoke Docker.
- CloudML and other remote-platform image contracts remain unchanged.
- Reintroducing a gateway or local container runtime requires a new decision
  with a current product owner and verification contract.

## Partially Supersedes

- [ADR-0137](0137-retire-ai2thor-and-direct-vlm-public-surfaces.md), only where
  it retained OpenClaw as a generic model/provider-routing consumer.
- [ADR-0138](0138-use-detector-only-visual-grounding-sidecar.md), only where it
  retained OpenClaw text routes as a generic model/provider-routing consumer.

## Implementation

See
[`docs/plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md`](../plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md).
