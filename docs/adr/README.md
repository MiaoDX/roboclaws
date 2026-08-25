# Architecture Decision Records

This directory is the current durable architecture decision surface for
Roboclaws. Keep it small. ADRs here should constrain future implementation:
public command/API shape, MCP/tool contracts, private-data boundaries,
provider/cost/privacy boundaries, or durable subsystem ownership.

Do not use ADRs for phase logs, benchmark notes, proof reruns, implementation
checklists, or local validation handoffs. Those belong in `docs/plans/`,
`docs/status/active/`, `docs/retrospectives/`, or run artifacts.

Archived records remain available for traceability, but they are not current
guidance:

- [`archive/historical/`](archive/historical/) for decisions absorbed by the
  current architecture or no longer worth keeping on the read-first surface.
- [`archive/superseded/`](archive/superseded/) for records replaced by a newer
  current ADR.
- [`archive/execution-log/`](archive/execution-log/) for older ADR-shaped phase
  execution notes.

## Current ADRs

| # | Title | Why It Remains Current |
|---|-------|------------------------|
| [0003](0003-separate-cleanup-agent-view-from-private-evaluation.md) | Separate Cleanup Agent View From Private Evaluation | Core public/private cleanup boundary. |
| [0126](0126-bridge-camera-evidence-to-cleanup-handles-with-model-declared-observations.md) | Bridge Camera Evidence To Cleanup Handles With Model-Declared Observations | Public camera evidence to actionable cleanup handles. |
| [0131](0131-use-agibot-sdk-runner-as-real-robot-cleanup-backend.md) | Use Agibot SDK Runner As Real Robot Cleanup Backend | Real-robot backend ownership and safety boundary. |
| [0132](0132-keep-cleanup-memory-skill-first-and-remove-promoted-composite.md) | Keep Cleanup Memory Skill-First And Remove Promoted Composite | Keeps MCP small and cleanup strategy skill-side. |
| [0134](0134-use-public-done-readiness-gates.md) | Use Public Done Readiness Gates | Completion enforcement uses public evidence only. |
| [0135](0135-use-sanitized-report-performance-artifacts-for-speed-claims.md) | Use Sanitized Report Performance Artifacts For Speed Claims | Privacy and evidence boundary for live-agent speed claims. |
| [0136](0136-use-base-metric-map-and-first-class-household-launch-contracts.md) | Use Base Metric Map And First-Class Household Launch Contracts | Current map, launch-axis, intent, and evidence-lane contract. |
| [0137](0137-retire-ai2thor-and-direct-vlm-public-surfaces.md) | Retire AI2-THOR And Direct VLM Public Surfaces | Prevents revival of old public surfaces. |
| [0138](0138-use-detector-only-visual-grounding-sidecar.md) | Use Detector-Only Visual Grounding Sidecar | Current visual-grounding sidecar and VLM-retirement boundary. |
| [0139](0139-use-household-open-task-surface-with-presets.md) | Use Household Open Task Surface With Presets | Current household public surface and preset contract. |
| [0140](0140-use-eval-suites-as-first-class-architecture-layer.md) | Use Eval Suites As First-Class Architecture Layer | Separates product runs, validation matrices, eval suites, and harness recipes. |
| [0141](0141-use-eval-harness-as-maintainer-orchestration-facade.md) | Use Eval Harness As Maintainer Orchestration Facade | Maintained validation/eval orchestration facade. |
| [0142](0142-scope-isaac-to-digital-twin-and-retire-molmospaces-isaac.md) | Scope Isaac To Digital Twin And Retire MolmoSpaces Isaac | Keeps B1 Isaac current while retiring MolmoSpaces Isaac support. |
| [0144](0144-use-relative-pose-navigation-as-public-mcp-capability.md) | Use Relative Pose Navigation As Public MCP Capability | Distinguishes robot-local movement from waypoint navigation and preserves operator attribution. |
| [0146](0146-reuse-canonical-map-priors-for-agent-matrices.md) | Reuse Canonical Map Priors For Agent Matrices | Separates MapBuild quality, fixed-prior Agent comparison, and explicit end-to-end evaluation. |
| [0148](0148-retire-openclaw-and-local-docker-runtime.md) | Retire OpenClaw And Local Docker Runtime | Keeps active agent execution host-based while preserving CloudML image contracts. |
| [0149](0149-project-agent-observability-as-one-way-side-effects.md) | Project Agent Observability As One-Way Side Effects | Canonical privacy, ownership, and fail-open boundary for external observability. |
| [0150](0150-use-opik-as-the-sole-external-observability-backend.md) | Use Opik As The Sole External Observability Backend | Selects the one supported browser/deployment while keeping local evidence canonical. |

## Archived Superseded ADRs

| # | Title | Superseded By |
|---|-------|---------------|
| [0001](archive/superseded/0001-use-ai2thor-for-phase-1.md) | Use AI2-THOR for Phase 1 | ADR-0137 |
| [0004](archive/superseded/0004-use-separate-mcp-servers-for-ai2thor-and-molmo-cleanup.md) | Use Separate MCP Servers For AI2-THOR And Molmo Cleanup | ADR-0137 |
| [0130](archive/superseded/0130-default-composition-to-trace-preserving-skill-routines.md) | Default Composition To Trace-Preserving Skill Routines | ADR-0132 |
| [0133](archive/superseded/0133-use-http-visual-grounding-service-for-real-camera-labels.md) | Use HTTP Visual Grounding Service For Real Camera Labels | ADR-0138 |

## Adding A New ADR

1. Write an ADR only when the decision is durable and constrains future work.
2. Prefer updating `ARCHITECTURE.md` or `docs/human/**` when the architecture is
   already stable and the doc just needs to reflect it.
3. Use the next number above the highest ADR-shaped record in the repo. Do not
   fill gaps left by archived records.
4. Keep the ADR short. Link to a plan for phases, commands, tests, gates, and
   implementation sequencing.
5. Never rewrite a past ADR's decision body. Supersede it with a new ADR that
   references the old one, then move the old ADR to `archive/superseded/`.

## Archive Rule

When an ADR stops constraining current architecture, move it out of the root
decision surface. Do not keep stale records in the root just because they once
were accepted.
