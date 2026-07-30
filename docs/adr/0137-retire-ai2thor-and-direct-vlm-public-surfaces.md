# 0137. Retire AI2-THOR And Direct VLM Public Surfaces

Date: 2026-06-11

Partially superseded by [ADR-0148](0148-retire-openclaw-and-local-docker-runtime.md)
for its OpenClaw-only provider-routing carve-out.

## Status

Accepted.

## Context

Roboclaws started with AI2-THOR navigation/game demos and direct VLM-policy
loops. The active product contract has since moved to household-world cleanup,
map-build, open-ended household goals, planner-proof evidence, public/private
evaluator boundaries, runtime maps, and future real-robot parity.

Keeping AI2-THOR as `backend=ai2thor` would imply parity with MuJoCo, Isaac Lab,
and Agibot GDK, but it does not implement the household cleanup/map-build
contract. The old stack also carried separate MCP profiles, skills, reports,
CI jobs, examples, and local runtime hazards.

## Decision

Retire the active AI2-THOR and direct VLM-policy public surfaces.

Removed public axes:

- `surface=ai2thor-world`
- `surface=ai2thor-games`
- `backend=ai2thor`
- `agent_engine=vlm-policy`
- AI2-THOR intents such as navigation, photo capture, territory, and coverage

Current public surfaces are `household-world` and `planner-proof`. Current
household backends are MuJoCo, Isaac Lab, and Agibot GDK variants under the
same launch catalog and report contract.

## Consequences

- Active docs, CI, tests, just recipes, examples, and skills should no longer
  advertise AI2-THOR or direct VLM-policy routes.
- Historical plans, retrospectives, and archived evidence may keep references
  to the old stack, but they are not current launch guidance.
- Generic model/provider routing remains available where active household
  live-agent, OpenClaw, model-matrix, or visual-grounding flows use it.
- Future navigation-only household work should be added as a fresh household
  intent with household reports and MCP capabilities, not by reviving the old
  AI2-THOR game stack.

## Supersedes

- [ADR-0001](archive/superseded/0001-use-ai2thor-for-phase-1.md)
- [ADR-0004](archive/superseded/0004-use-separate-mcp-servers-for-ai2thor-and-molmo-cleanup.md)
