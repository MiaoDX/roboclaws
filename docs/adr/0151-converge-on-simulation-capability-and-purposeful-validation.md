# ADR-0151: Converge On Simulation Capability And Purposeful Validation

Status: Accepted

Date: 2026-10-08

Maintaining multiple Skill delivery modes and provider combinations has not
established a repeatable cross-scene advantage. We concentrate product and
evaluation work on visual discovery, navigation, cleanup and verification in
simulation, accepting narrower integration coverage to invest in that capability.

The Agent Skill layer owns one product delivery, `static-full`, with `no-skill`
available only as an explicit eval control. The provider catalog owns exactly
`mimo-responses`, `minimax-responses` and `mimo-tp-openai-chat`; historical readers
recognize retired identities without enabling execution. MiMo Responses is the
local launch default, while every eval row explicitly names its provider.
Missing dependencies or provider configuration fail without fallback.

The eval layer keeps world-label compatibility proof separate from real-DINO
visual capability. Deterministic checks gate ordinary PRs; trusted hosted runs
use the two external providers, and the existing local GPU runtime owns DINO
proof. Complete case identities, immutable PASS/FAIL/BLOCKED outcomes and
per-scene thresholds govern acceptance. Bounded transport retries are reported
separately; there are no automatic trial retries or best-of selection. Private
evaluation truth remains outside agent inputs, and durable baseline promotion
remains a human decision.

Each initiative retains one stable `docs/status/active/<slug>.md` status owner
through execution, GSD handoff and closure. Plans own scope and acceptance;
GSD owns its execution cursor and evidence; `STATUS.md` links current priorities.
This avoids competing progress records as execution mechanisms change.

[ADR-0145](0145-scope-eval-harness-profiles-to-purposeful-baselines.md) continues
to govern purposeful eval profiles; this decision narrows its earlier provider
inventory. The [approved convergence plan](../plans/2026-09-28-simulation-capability-and-rnd-convergence.md)
owns exact case sets, numerical acceptance, resource limits and implementation
gates. Acceptance of this decision does not assert that those gates have passed.
