---
plan_scope: operator-console-workflow-simplification
status: DONE
created: 2026-06-30
last_reviewed: 2026-07-01
implementation_allowed: true
source:
  - user direction to make operator-console UI expose fewer, clearer workflows
  - discussion that UI-testable behavior must be a subset of headless/eval coverage
related_context:
  - ARCHITECTURE.md
  - docs/human/domain.md
  - docs/human/evaluation.md
  - docs/human/eval-harness-dimensions.md
  - docs/adr/0141-use-eval-harness-as-maintainer-orchestration-facade.md
  - docs/adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md
  - docs/plans/2026-06-26-map-build-quality-eval-harness.md
---

# Operator Console Workflow Simplification

## Plan Ledger

Status: DONE

Implemented: 2026-07-01

Current implementation: `roboclaws/operator_console/workflows.py`,
workflow-aware route payloads, workflow launch argv translation, and static UI
workflow action controls.

Verification:

- `./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console -q`
- `ruff check` and `ruff format --check` on touched operator-console files
- `node --check roboclaws/operator_console/static/app.js`
- Browser smoke on `python -m roboclaws.operator_console --host 127.0.0.1 --port 8876 --repo-root .`

Notes:

- The recommended-prior catalog is intentionally empty until an accepted,
  tracked Runtime Map Prior Snapshot exists. With-map workflows therefore show
  a visible empty state; the rendered with-map workflow buttons are disabled
  until a recommended prior or explicit operator override exists.
- Raw route axes remain available in Advanced; the main UI is workflow-first.

## Goal

Make the operator console a small product workflow surface instead of a route
matrix. Anything a human can test through the UI must map to a public
`just run::surface ...` route, an eval suite, or a contract/regression gate.
UI-only failures that matter must be promoted into automated coverage.

## Product Workflows

The main UI should be organized as:

1. choose a scene;
2. inspect scene state and available map prior;
3. run one of the supported workflow actions.

Supported main actions:

- `Build Map`
- `Open Task`
- `Cleanup`
- `Open Task With Map`
- `Cleanup With Map`
- `Prepare Standard Mess`
- `Reset Scene`

`Open Task With Map` and `Cleanup With Map` use a Runtime Map Prior Snapshot.
They should be disabled when no valid recommended or operator-selected map
prior is available for the selected scene/backend.

## Defaults

- Default evidence lane: `camera-grounded-labels` with the recommended camera
  labeler, because real robot routes do not have simulator public labels.
- `world-public-labels` remains a deterministic/eval lane, not the primary
  operator-console default.
- If the camera-grounded labeler or provider route is not ready, the UI reports
  a visible readiness blocker. It must not silently fall back to
  `world-public-labels`; simulator-only users may pick that lane from Advanced.
- Default cleanup preparation: `Prepare Standard Mess`, implemented through the
  existing relocation scenario setup with the standard relocation count.
- `relocation_count`, alternate scenario setup values, non-default evidence
  lanes, and model/provider changes belong in Advanced controls.
- The main model display shows the recommended model route and health state.
  Full model selection is available only through Advanced or Compare Models.

## Map Prior Policy

Each scene should have a recommended map prior selected before normal operator
use. The recommended prior is produced by running MapBuild for that scene,
potentially across multiple model/provider profiles in eval harness, then
choosing the best accepted Runtime Map Prior Snapshot for downstream use.

Rules:

- "Best accepted" means the candidate passes map-quality gates, preserves the
  public/private boundary, and provides the strongest downstream
  open-ended/cleanup utility evidence available for that scene. Provider health
  alone is not enough.
- The default prior for a scene comes from this per-scene recommended prior
  catalog, not from an arbitrary latest UI run.
- The recommended prior must match the selected world and backend.
- User override is allowed: an operator may explicitly select a different
  Runtime Map Prior Snapshot path for the current run.
- Ad hoc `Build Map` runs may be shown as recent candidate artifacts, but they
  should not become the default recommended prior until accepted through the
  catalog/eval path.
- If no recommended prior exists, the UI should say that clearly and offer
  `Build Map` or an explicit map override instead of silently falling back.

## Coverage Owners

Every enabled UI workflow action must declare one of:

- eval suite owner, such as `map_build_consumer`, `open_ended_goals`, or
  `cleanup_capability`;
- eval-harness row owner, such as a direct product row or live-agent eval row;
- unit/contract/regression test owner for operator-console behavior;
- `manual_operational_control` for non-eval actions such as stop, steer,
  resume, and artifact inspection.

No workflow action may exist only as an unowned UI path.

## Non-Goals

- Do not expose the full Cartesian product of world, intent, engine, provider,
  evidence lane, and scenario setup in the main UI.
- Do not make provider health or provider sweeps product capability proof.
- Do not expose private scoring truth, generated mess sets, relocated object
  identities, acceptable destinations, or hidden target counts to the agent.
- Do not treat manual UI clicking as baseline evidence unless the result is
  promoted into an automated eval, contract, or regression artifact.

## Acceptance Gates

- Main UI exposes workflow actions, not raw route matrix selection.
- The default generated command for operator workflows uses
  `evidence_lane=camera-grounded-labels`.
- With-map workflows require an explicit Runtime Map Prior Snapshot from the
  scene recommended-prior catalog or a user override.
- Route construction still resolves through `resolve_surface_launch` and
  `just run::surface`.
- Operator-console unit/contract coverage proves workflow ownership metadata,
  default evidence-lane selection, standard mess preparation, prior override
  validation, and no silent fallback to arbitrary latest map artifacts.
- Eval coverage remains headless through eval harness and suites; UI workflows
  only reference that coverage.

## Recommended Implementation Slice

1. Add operator-console workflow metadata beside or above the existing route
   registry.
2. Add scene recommended-prior catalog support with explicit empty-state
   behavior.
3. Rework the UI selection model to show scene, scene state, workflow actions,
   and an Advanced section.
4. Keep route launch plumbing thin by translating workflows into existing
   `just run::surface` arguments.
5. Prune route-matrix controls that no longer have workflow ownership.
