# Phase 4: Route Proof And Rollout - Research

**Researched:** 2026-09-02
**Domain:** Cross-route household runtime proof, eval harness, camera Grounding DINO, operator-console and Agibot metadata rollout
**Confidence:** HIGH (repository contracts and commands)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Cover cleanup, MapBuild, and no-preset open-ended household SDK paths.
- Include camera-grounded/DINO inputs, operator-console use, and Agibot resolver metadata.
- Reuse the same context contract without adding a profile picker or launch axis.
- Keep `baseline` as an explicit unmanaged comparison; never silently fall back to it.
- Preserve complete traces, reports, MCP artifacts, and DINO artifacts as reviewable content-addressed evidence.
- Enforce privacy boundaries: no private scoring truth, credentials, raw prompts, or full tool payloads in model input or telemetry.
- Run deterministic tests and focused eval recommendation/execution gates.
- Run documented local camera-grounded product proof only when provider/network/runtime readiness passes; otherwise retain guarded blocker output and stop.
- Do not authorize real-robot movement, provider bake-offs, public contract changes, or durable artifact schema changes in this phase.

### the agent's Discretion
none stated.

### Deferred Ideas (OUT OF SCOPE)
none stated.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| REQ-route-proof-and-rollout | Validate shared context contract across cleanup, MapBuild, open-ended SDK, DINO, operator console, and Agibot metadata while preserving baseline, privacy, and reviewable artifacts | Existing public run grammar, eval suites/profiles, operator gates, DINO sidecar preflight, and Agibot map-context contracts below |
</phase_requirements>

## Summary

Phase 4 is a proof/rollout planning phase. The implementation boundary is the existing shared state/context contract from Phases 1-3; route plans should add focused regression assertions and execute existing public commands, not introduce launch axes or artifact schemas. The maintained proof layers are product runs (`just run::surface`), eval harness selection/execution (`just agent::eval`), versioned suites, and package-level checks. `[VERIFIED: codebase]`

The minimum matrix is explicit cleanup, MapBuild, and no-preset open-ended SDK, with world-label `baseline` retained as an unmanaged comparison and camera-grounded/DINO proved only through the real detector sidecar when readiness passes. Operator-console and Agibot checks validate route metadata and safety gating; they do not authorize physical motion. `[VERIFIED: ROADMAP.md, CONTEXT.md, docs/human/evaluation.md, docs/human/agibot-g2-cleanup-pilot.md]`

**Primary recommendation:** Plan serial deterministic gates first, then focused eval recommendation/execution, then conditional local DINO product proof; every unavailable provider/network/GPU/sidecar/robot prerequisite must produce a sanitized blocked artifact and terminate live proof.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Shared snapshot/context contract | API / Backend | Storage (run artifacts) | Runtime owns model-input assembly and checkpoint reads |
| Route/eval selection and comparison | API / Backend | CLI / operator surface | Eval harness owns matrix, budgets, baseline identity, and reports |
| DINO acquisition | API / Backend | External sidecar | Existing camera adapter calls detector and registers public handles |
| Operator-console readiness | Browser / Client | API / Backend | UI displays layered gates; launcher enforces hard and movement gates |
| Agibot resolver metadata | API / Backend | Storage | Map conversion exposes canonical public map/pose metadata, not private truth |
| Trace/report/artifact review | Storage | API / Backend | Existing JSON/Markdown/content digests are canonical evidence |

## Standard Stack

### Core

| Component | Version | Purpose | Why Standard |
|---|---|---|---|
| Python stdlib + repo `.venv` | Python 3.12.12 | Runtime, artifact and contract checks | Existing project runtime `[VERIFIED: environment]` |
| pytest standalone wrapper | repo tool | Deterministic unit/contract tests | Required on ROS-jazzy hosts `[VERIFIED: docs/agents/operating-runbook.md]` |
| `just` facade | installed | Public product/eval commands | Canonical launch grammar `[VERIFIED: just/README.md]` |

### Supporting

| Component | Purpose | When to Use |
|---|---|---|
| `just agent::eval` | Select and execute focused deterministic/product/live rows | Every phase gate and baseline comparison |
| Grounding DINO HTTP sidecar | Real camera candidate acquisition | Only after visual runtime, weights, image, and sidecar readiness |
| Operator Console | Layered launch/readiness proof | Validate metadata and movement safety without physical motion |
| Agibot map-context converter | Resolver metadata contract | Offline/map-build metadata checks; no GDK movement |

No external package installation is needed; package legitimacy audit is not applicable.

## Architecture Patterns

### Proof flow

```text
focused deterministic tests
  -> eval recommend (plan-aware manifest)
  -> eval execute (serial, budgeted, explicit baseline)
  -> product runs (cleanup / map-build / open-ended)
  -> conditional DINO sidecar proof
  -> content-addressed reports + traces + blocker receipt
```

### Required route identities

- Cleanup: `surface=household-world preset=cleanup`; compare managed context path against explicit `evidence_lane=world-public-labels` `scenario_setup=baseline`.
- MapBuild: `preset=map-build`; Runtime Metric Map and evidence digests must remain readable.
- Open-ended: no preset, SDK engine, explicit provider profile, prompt; no implicit baseline fallback.
- Camera/DINO: `evidence_lane=camera-grounded-labels camera_labeler=grounding-dino`; require composite observation, detector provenance, public handles, and no simulator-label substitution. `[VERIFIED: camera-grounded plans]`
- Operator/Agibot: use existing console route metadata and `agibot_g2/map-12` context artifact; dry-run gates may be advisory, while localization/run-enable/E-stop remain mandatory for any `real_movement_enabled=true`. `[VERIFIED: operator-console plan, agibot pilot]`

### Evidence and privacy pattern

Every terminal run keeps `run_result.json`, completion marker, trace/report, and DINO/runtime artifacts with digests. Assertions must scan model input and telemetry for forbidden private scoring truth, credentials, raw prompts, and full tool payloads. Opik projection is fail-open and receives only allowlisted public identity; local JSON/Markdown remains canonical. `[VERIFIED: docs/human/evaluation.md, PRD]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Eval matrix selection | New bespoke runner or fixed row list | `just agent::eval recommend/execute` | Existing harness records budgets, identities, blockers, and reports |
| Public launch routing | New flags/profile picker | `just run::surface` typed axes | Locked public grammar |
| DINO integration | Alternate detector or fallback | Existing detector-only sidecar/composite tool | Preserves provenance and fail-closed behavior |
| Evidence storage | New ledger/schema | Existing run artifacts, completion, digests, reports | Prevents contract/schema expansion |
| Agibot semantics | Agibot-only agent input | Canonical Runtime Metric Map / resolver metadata | Keeps backend-neutral model context |

## Runtime State Inventory

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | Existing `output/` traces, reports, DINO bundles, runtime maps, checkpoints | Read and audit; no migration or relabeling |
| Live service config | DINO sidecar/provider endpoints and Opik endpoint may be machine-local | Preflight only; do not alter config |
| OS-registered state | None relevant to proof planning | None |
| Secrets/env vars | Provider keys and DINO settings in gitignored `.env` | Source only for guarded live proof; never copy into artifacts |
| Build artifacts / installed packages | `.venv`, `.venv-visual-grounding`, optional Isaac env | Check readiness; no package changes |

## Common Pitfalls

1. **Baseline ambiguity:** a managed run silently using `baseline` invalidates comparison. Assert requested/effective scenario and preserve `baseline` as explicit unmanaged row. `[VERIFIED: CONTEXT.md, evaluation.md]`
2. **False DINO evidence:** simulator producers, zero detector events, or missing composite calls cannot pass camera proof. Stop before provider execution if identity drifts. `[VERIFIED: camera-grounded plans]`
3. **Artifact incompleteness:** terminal `done` without `run_result.json`, trace/report, or digest-bound DINO assets is not accepted evidence.
4. **Privacy leakage:** grader truth, credentials, raw prompts, and full tool payloads must be absent from model input, telemetry, and Opik projection.
5. **Unsafe Agibot interpretation:** map metadata rehearsal is not physical navigation; never enable real movement or cleanup manipulation in this phase.
6. **Replacing live gates with unit tests:** if provider/network/runtime readiness is unavailable, retain guarded blocker output and classify live proof incomplete/blocked.

## Code Examples

Canonical deterministic/eval commands:

```bash
./scripts/dev/run_pytest_standalone.sh -q
just agent::verify
just agent::eval recommend plan=docs/plans/2026-09-01-state-first-context-manager.md budget=focused
just agent::eval execute plan=docs/plans/2026-09-01-state-first-context-manager.md budget=focused
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=open_ended_goals budget=smoke
just agent::eval suite=map_build_quality budget=smoke
just agent::eval suite=map_consumer_no_prior budget=smoke
```

Conditional product examples:

```bash
just run::surface surface=household-world agent_engine=openai-agents-sdk preset=cleanup evidence_lane=world-public-labels provider_profile=kimi-openai-chat
just run::surface surface=household-world agent_engine=direct-runner preset=map-build evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just run::surface surface=household-world agent_engine=openai-agents-sdk prompt="find something useful to drink" provider_profile=kimi-openai-chat
scripts/dev/network_status.sh
```

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| `just` | Public commands | yes | installed | — |
| Python / repo `.venv` | deterministic/eval | yes | 3.12.12 | — |
| NVIDIA driver (`nvidia-smi`) | DINO/Isaac local proof | yes | command present | Guarded blocker if runtime/weights unavailable |
| Provider credentials/endpoints | SDK live rows | unknown until guarded preflight | — | Record blocked receipt; no fake fallback |
| Grounding DINO sidecar + visual env | camera proof | unknown until preflight | — | Record blocked receipt; stop live gate |
| Agibot GDK robot/localization/E-stop | physical route | intentionally not authorized | — | Do not run; metadata/dry-run only |

## Validation Architecture

### Test Framework
| Property | Value |
|---|---|
| Framework | pytest via standalone wrapper |
| Quick run | `./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents tests/unit/evals tests/unit/operator_console` |
| Full suite | `./scripts/dev/run_pytest_standalone.sh -q` |

### Phase Requirements -> Test Map
| Requirement | Behavior | Test Type | Automated Command |
|---|---|---|---|
| REQ-route-proof-and-rollout | Cleanup/MapBuild/open-ended route identity and context contract | focused contract/eval | `just agent::eval recommend ...` then `execute ...` |
| REQ-route-proof-and-rollout | Baseline explicit and no silent fallback | unit/eval selector | `./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals` |
| REQ-route-proof-and-rollout | DINO composite/provenance/privacy artifacts | focused unit + conditional live | DINO tests; guarded `run::surface` |
| REQ-route-proof-and-rollout | Operator and Agibot metadata/safety gates | operator/map contract | `./scripts/dev/run_pytest_standalone.sh -q tests/unit/operator_console tests/unit/maps` |

### Wave 0 Gaps
None identified; plans should add only narrowly scoped assertions if an existing route lacks identity/privacy coverage.

## Security Domain

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | yes | Existing provider-key and endpoint preflight; never emit secrets |
| V3 Session Management | no | No new sessions |
| V4 Access Control | yes | Public/model vs grader/operator boundaries |
| V5 Input Validation | yes | Validate launch identity, artifact digests, metadata schemas |
| V6 Cryptography | yes | Reuse existing SHA-256 content digests; do not hand-roll |

## Sources

### Primary (HIGH confidence)
- `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, phase `04-CONTEXT.md`
- `docs/plans/2026-09-01-state-first-context-manager.md`
- `docs/human/evaluation.md`, `docs/agents/operating-runbook.md`, `just/README.md`
- Camera-grounded/DINO plans dated 2026-08-31; operator-console and Agibot rehearsal plans
- Existing `tests/unit/evals`, `tests/unit/operator_console`, `tests/unit/agents` route/provenance/privacy tests

## Open Questions (RESOLVED)

1. **RESOLVED:** Exact provider/network/DINO readiness is environment-dependent at execution time; use the documented preflight and retain its concrete output, classifying unavailable live proof as `BLOCKED_NEEDS_LOCAL_VALIDATION`.
2. **RESOLVED:** Durable baseline/catalog publication is explicitly out of scope; Phase 4 records comparison evidence only and defers publication to a later human decision.

## Metadata

**Confidence breakdown:** Standard stack HIGH (existing commands); Architecture HIGH (locked context and docs); live readiness MEDIUM (must be probed at execution).
**Research date:** 2026-09-02
**Valid until:** 2026-09-30 or until route/eval contracts change
