# Refactor Just Command Surface

**Status:** Done
**Created:** 2026-07-31
**Last reviewed:** 2026-08-01
**Current implementation contract:** Forward-only migration from Just-owned runtime
orchestration to typed package owners.
**Related architecture:** `ARCHITECTURE.md`, `just/README.md`

## Plan Ledger

- Session scope: `refactor-just-command-surface`
- Current slice: complete
- Next action: none; the pending eval baseline remains a separate human-confirmation decision
- No-touch scope: provider routes, privacy boundaries, artifact schemas, physical movement,
  durable eval baseline publication

## Refactor Gate

Refactor scope: the active `just/**` command layer and its direct launch, eval,
operator-console, CI, test, skill, and human-doc callers.

Discovery source: the approved 2026-07-31 ponytail, ponytail-ultra, and
intuitive-reduce-entropy reviews.

Target: make Python package owners consume typed launch state directly and reduce Just to a
small set of canonical repo entrypoints.

Accepted severities: P1 ownership drift and stale reachable command surfaces; P2 wrapper,
duplicate-registry, and self-preserving test/docs cleanup required by those P1 cuts.

Architecture simplification claim: Just may select a canonical repo task, but it must not own
product strategy, launch-axis normalization, child lifecycle, scenario taxonomies, checker
policy, or a second private dispatch registry.

Behavior-change policy: command migration is intentionally forward-only. Migrate known in-repo
callers and delete the old recipe in the same slice. Do not add aliases, compatibility shims,
re-exports, or thin adapters for retired paths.

## Accepted Checklist

1. Make the household and planner launch executor call package owners directly; delete the
   typed-plan-to-environment-to-Just bridge.
2. Delete `molmo::*`, `harness::*`, `mcp::*`, private `verify::*`, and the dynamic
   `agent::harness` / `agent::mcp` / forwarding verify registries after migrating callers.
3. Preserve only these canonical Just tasks:
   - `run::surface`
   - `agent::eval`
   - `console::run`
   - directly implemented `agent::verify`
4. Move still-current planner, visual-grounding, Isaac, B1, and standalone process behavior to
   existing package CLIs or eval rows; delete obsolete research aliases and wrappers.
5. Remove internal fake-Just argv representations where typed launch state is already available.
6. Update CI, current docs, skills, runtime guidance, tests, and emitted rerun commands to the
   canonical surface. Historical plans and retrospectives are records, not active callers.
7. Run changed-code review, documentation alignment, and the evidence ladder below.

## Surface Metrics

- Baseline recipe implementation: 2,203 lines under `just/*.just`.
- Baseline public summary: six commands backed by five private implementation modules.
- Final recipe implementation: 64 lines under `just/*.just`.
- Final public summary: exactly four commands: `run::surface`, `agent::eval`,
  `console::run`, and directly implemented `agent::verify`.
- Achieved reductions: zero Python calls to retired Just runtime recipes, zero active callers of
  retired Just paths, and package-owned launch axes and child lifecycles.

## Execution Slices

1. Typed household launch: move shell-owned normalization, sidecar/process orchestration,
   runner dispatch, validation, and reporting into existing package owners; delete
   `molmo::household-world-impl` and its environment protocol.
2. Planner and specialist proof ownership: replace executor/harness callbacks with package
   composition; register current proofs through eval where appropriate.
3. Command-surface deletion: collapse verify to one direct CI command, remove agent dispatch
   facades and private modules, and migrate all current callers.
4. Internal representation cleanup: pass typed launch args/plans inside console and eval code;
   format Just commands only as public provenance when needed.
5. Changed-code review, human-doc cleanup, final proof, source-plan closeout, and active-capsule
   removal.

## Evidence Ladder

- L0: `just --summary`, stale-path searches, architecture import graph, `git diff --check`.
- L1: focused launch, eval, operator-console, household, planner, and dev-tool unit tests.
- L2: command/CLI contracts, eval catalog execution contracts, CI gate, standalone full suite.
- L3: direct-runner map-build, cleanup, open-task, and planner-proof product runs; operator-console
  host smoke; one low-cost OpenAI Agents SDK live proof when guarded provider readiness allows it.
- Specialist L3 proofs are required when their behavior changes: visual-grounding sidecar,
  Isaac/B1 runtime, and Agibot readiness. Physical movement remains out of scope.

## Risks And Invariants

- Preserve process-group cleanup, occupied-port failure, locks, signals, run directories, logs,
  `.env` loading, provider telemetry/cost, live status, trace redaction, and rerun provenance.
- Preserve Base/Runtime Metric Map boundaries, private scoring separation, report and artifact
  schemas, and current direct-runner versus OpenAI Agents SDK semantics.
- Keep Isaac dependencies isolated in `.venv-isaaclab` and EULA handling fail-closed.
- Do not publish or promote the pending eval baseline candidate.

## Parked

- Renaming the four retained canonical commands.
- Changing provider profiles, live-agent policy, eval metrics, report schemas, or hardware safety
  gates.
- Cleanup outside direct callers of the retired Just surface unless it is a P0/P1 regression
  exposed by verification.

## Stop Condition

Stop when every accepted checklist item is implemented, current callers use only the minimal
surface, required deterministic and product proofs pass, any unavailable live/specialist proof
has a concrete guarded blocker, docs describe current truth, and no remaining finding in this
scope is clearer than Parked.

## Completion Evidence

- Shipped in commit `dcd0ae2d` (`refactor: simplify command and runtime ownership`).
- `just agent::verify` and the standalone full pytest suite pass.
- Ruff, format, architecture, quality-ratchet, report-contract, and stale-path gates pass.
- The final architecture graph contains 528 modules and 1,624 edges with zero SCCs,
  bidirectional package pairs, package-to-script edges, or forbidden policy violations.
- Direct-runner map-build, five-object cleanup, and planner dry-run product proofs pass.
- OpenAI Agents SDK/Kimi, operator-console, Isaac runtime, B1 navigation, and provider proof
  surfaces pass; no physical movement occurred.
- The pending eval baseline was neither published nor promoted.

## Saturation Follow-Up

Final multi-agent saturation review found two clear slices after the initial command-surface
proof:

1. Move scene-sampler readiness, source preparation, scanner execution, and worklist alignment
   from `scripts/operator_console/**` into `roboclaws.worlds.molmospaces`; migrate callers and
   tests, delete the scripts, and make the architecture checker reject embedded script commands.
2. Move five live `scripts/maps/**` CLI adapters to their existing `roboclaws.maps` owners;
   migrate current docs, skills, and tests, then delete the scripts.

Both slices are forward-only. They preserve runtime behavior and artifact contracts, add no
aliases or adapters, and must pass focused owner/caller tests plus the canonical verification
gate before this plan returns to Done.

Completion removed all nine scripts, migrated live callers to package CLIs or direct imports,
removed the unused `roboclaws.maps` eager re-exports, and extended the architecture checker to
cover embedded, composed, f-string, and dynamic-import script references. Focused scene-sampler,
map, launch, provider, Just, and architecture tests pass. The exact regenerated graph is 528
modules / 1,624 edges with all policies green. The staged-tree quality ratchet also split
household execution policy and argument lowering into the direct
`roboclaws.launch.household_execution` owner; lifecycle orchestration remains in
`roboclaws.launch.household`, with no alias or re-export between them.
