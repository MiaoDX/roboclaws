# Project Status

Last updated: 2026-10-08

This dashboard owns current priorities, next action and links. The fixed
initiative capsule owns detailed execution state and evidence; this file is
not a changelog or a second acceptance ledger.

## Current Focus

Simulation-first, cross-scene visual cleanup is the active priority. The
[approved convergence plan](docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md)
owns scope and acceptance, and the
[initiative capsule](docs/status/active/simulation-capability-and-rnd-convergence.md)
owns current implementation and verification state. Real-robot work is parked.

Product/provider convergence is implemented: one static-full Skill, an explicit
eval-only no-skill control, and three active routes (MiMo Responses, MiMo TP,
MiniMax). Historical identities remain readable without executable retired
routes. [ADR-0151](docs/adr/0151-converge-on-simulation-capability-and-purposeful-validation.md)
records the durable decisions.

Three-provider readiness and real-DINO readiness pass. The standard repository
gate passed after complete-cohort validation was added. Compact external
bread/cleanup proofs and the paired MiniMax Skill control pass, but full
initiative acceptance remains incomplete. Refer to the capsule for current-code
verification and exact attempt identities.

## Next Action

Complete the current development-scene DINO replay after removing contradictory
completion/recovery instructions. Then close visual discovery failures, prepare
the new frozen scene/epoch manifest, and implement bounded full external
execution with trusted current-code hosted proof. Keep world-label compatibility
and real-DINO capability evidence separate.

## Current Acceptance Gaps

- Real-DINO MiniMax v1 covers all 15 identities but misses acceptance. The latest
  development replay before the strategy fix restored 3/5 with incomplete heading
  coverage. MiMo Responses development smoke is still incomplete.
- Former reserved scenes 11/13 were inspected during diagnosis. The capsule fixes
  new reserved scene IDs before further tuning; readiness and the next full
  executable manifest remain to be completed.
- Matched full external case lists, cumulative token/runtime envelopes and
  sharding still need implementation. Current case caps exceed the existing
  60-minute hosted shard envelope. No full schedule or baseline is promoted.
- The preserved MiMo TP compatibility cohort is 2/3 with one blocked stall;
  later compact successes do not rewrite that cohort.

Provider/network readiness failures from the earlier restricted environment
are historical. Retired Kimi quota requirements do not block the new scope.

## Related Work And Historical Evidence

- [Local baseline refresh](docs/status/active/local-eval-baseline-refresh.md):
  full packets and later targeted reruns remain separate; no baseline promotion.
- [State-First Context Manager](docs/status/active/state-first-context-manager.md):
  typed checkpoints/continuation and DINO input proofs are implemented. Its
  historical Kimi comparison remains incomplete in its original packet; that
  retired route is outside the new convergence acceptance contract.
- [Skill delivery comparison](docs/status/active/skill-delivery-multiscene-probe.md):
  historical comparison remains inconclusive and did not establish a ranking.
- [Codex Responses investigation](docs/status/active/codex-responses-api-investigation.md):
  Codex Responses and CloudML batch eval are retired from active support.
- [Opik migration](docs/plans/2026-08-25-opik-only-observability-migration.md):
  Opik is the sole external observability backend. Local JSON/Markdown and
  human promotion remain canonical; see ADR-0150 for the boundary.

## Human And Agent Sources

- Orientation and runnable examples: [README.md](README.md).
- Architecture and layer ownership: [ARCHITECTURE.md](ARCHITECTURE.md).
- Public launch grammar: [just/README.md](just/README.md).
- Evaluation and proof boundaries: [evaluation docs](docs/human/evaluation.md).
- Model routes: [model matrix](docs/human/model-matrix.md).
- Local hazards and checks: [operating runbook](docs/agents/operating-runbook.md).
- Human docs index: [docs/human/README.md](docs/human/README.md).
- Initiative status ownership: [active-state guide](docs/status/active/README.md).
- GSD execution cursor, when applicable: [.planning/STATE.md](.planning/STATE.md).
- Durable decisions: [ADRs](docs/adr/README.md); shipped history:
  [retrospectives](docs/retrospectives/).

Plans own design and acceptance; an initiative retains its fixed capsule through
GSD and closure. GSD owns execution structure/evidence and links that capsule.
Parked ideas remain in TODOS.md and THOUGHTS.md, outside the current priority.
