# Project Status

Last updated: 2026-10-11

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

The repaired scene0 and current-code scene10 development replays pass with real
CUDA DINO at 4/5. Scene12's latest replay visits all waypoints but remains 3/5
with mandatory heading recovery unfinished;
MiMo Responses scene0 passes at4/5 with enforced cumulative tokens; scene10
attempt2 is blocked after a second 180-second model-response stall (68 responses,
3/4 chains). A successful readiness probe remains separate.
MiMo scene12 smoke finishes with four chains and public readiness, but restoration
is3/5, so it fails capability acceptance. The fresh MapBuild/cleanup suite is
terminal: all three builders and scene0 cleanup pass; scene10 cleanup is blocked
by a180s response stall, and scene12 cleanup fails at the100-decision budget.
A backend support-attribution fix passes22 focused checks, the full repository
gate, and a fresh40-view CUDA DINO diagnostic (`55f879d8`). New-code scene12
cleanup smoke under `55f879d8` reaches4 chains and authoritative done but
remains3/5 restored; a bounded50-view forward-reobservation diagnostic still
finds no public Plate candidate and zero private RemoteControl pixels. This is
evidence of fixture/evidence-readiness risk, not proof that the threshold is
impossible; attribution repair alone does not establish discovery or capability
acceptance.
A fix for contradictory composite
tool controls passes the standard gate; its MiniMax scene12 replay is blocked
by provider billing limit after44 successful responses.
Resolve fixture readiness and remaining visual failures, complete local smoke, prepare
the new frozen scene/epoch manifest, and implement bounded full external
execution with trusted current-code hosted proof. Keep world-label compatibility
and real-DINO capability evidence separate.

## Current Acceptance Gaps

- Real-DINO MiniMax v1 covers all 15 identities but misses acceptance. The post-fix scene0
  development replay passes at 4/5, with full waypoint coverage and zero disturbances;
  this does not replace the failed cohort. MiMo Responses development smoke is incomplete.
- Former reserved scenes 11/13 were inspected during diagnosis. A new
  readiness attempt marks scene15 structurally ready with5/5 feasible targets.
  Its 50-view real-DINO scan still finds no public RemoteControl candidate
  (only low-pixel private evidence), so visual readiness is not yet accepted.
  Scene14 loads and validates its map but has only2 targets satisfying the
  current cleanup rules at seed7, so it is fixture-infeasible for the
  five-target contract. Readiness and final execution freeze remain
  incomplete; attempts are recorded under `reserved-readiness-attempt2/` and
  `scene15-feasibility-forward-live-attempt1/` without altering the prepared
  v2 case lists.
- Per-run cumulative token enforcement is implemented and live-verified,
  including the actual MiMo Responses request-model identity. Case sharding and
  bounded compact workflow wiring pass deterministic checks and a real local
  MiniMax case through execution and merge.
  Prepared full lists now match providers, including open-ended and MapBuild;
  their standard gate and real blocked-mode CLI planning/merge proof pass.
  Full execution and trusted current-code hosted proof remain incomplete.
  No full schedule or baseline is promoted.
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
