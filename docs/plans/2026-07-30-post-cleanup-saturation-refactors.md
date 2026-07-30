# Post-Cleanup Saturation Refactors

**Status:** Done
**Created:** 2026-07-30
**Last reviewed:** 2026-07-30
**Current implementation contract:** Execute the five approved P1 cleanup
slices from the 2026-07-30 multi-agent architecture review, preserving current
public run and maintainer command grammar while deleting stale owners and
finishing canonical typed/state boundaries.
**Related plan:** `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`

## Plan Ledger

- Status: DONE.
- Current slice: none; all five approved slices are committed and verified.
- Next action: none for this bounded cleanup packet.
- Blocker: none.
- Active capsule: archived by deletion at closeout.

## Preflight Contract

Task source: approved 2026-07-30 multi-agent architecture, ponytail, ultra, and
reduce-entropy review packet.

Route: `$intuitive-refactor` ratchet executed through durable `$intuitive-flow`.

Goal: remove the remaining proven stale surfaces and duplicate owners without
changing supported household-world, planner-proof, eval, or operator workflows.

Scope:

1. Delete the legacy test-only `roboclaws.core.run_artifacts` module and gate.
2. Delete the unconnected provider timing proxy, stale switch/docs/report
   ingestion, tests, and its direct `aiohttp` dependency.
3. Replace the `Just -> roboclaws.cli.main agent -> Just` maintainer dispatch
   loop with direct public-to-private Just forwarding while preserving public
   `agent::*` commands and trace behavior.
4. Canonicalize operator-console active/terminal phase predicates and correct
   `emergency_stopped` classification.
5. Stop re-encoding canonical `LaunchPlan` fields into string overrides,
   remove dead launch-only helpers/metadata proven unused, and delete the
   retired `map-build-codex` backend inspection sub-surface.

Non-goals:

- No new public axes, commands, schemas, providers, runtimes, artifacts, or
  compatibility aliases.
- No broad module splitting, Protocol removal, package re-export cleanup,
  prompt wording consolidation, or unrelated dependency pruning.
- No provider, simulator, Docker, hardware, or publication action.

Entity budget: reuse=public Just grammar, `LaunchPlan`, current launch adapters,
household artifact owners, operator-console state-summary owner; remove/merge=
two stale runtime surfaces, one duplicate command dispatcher, duplicate phase
sets, string copies of typed launch state, retired backend inspectors; new=no
runtime entities; expansion triggers=external API consumer, publication
artifact compatibility need, public behavior change, or unavailable required
product proof requires a stop and re-approval.

Acceptance:

- SUCCESS: all five slices are committed; exact stale-reference searches pass;
  focused unit/contract tests, Ruff, formatting, the standalone full suite, and
  direct-runner household map-build/cleanup command proofs pass.
- BLOCKED_NEEDS_DECISION: a current external/public consumer is proven for a
  deletion target, or the typed launch migration requires a new public schema.
- BLOCKED_NEEDS_LOCAL_VALIDATION: a required deterministic product proof cannot
  run in this checkout for a concrete environment reason.
- INTERMEDIATE_ONLY: none.
- No regressions: preserve public `just agent::*` and `just run::surface`
  grammar, four SDK provider profiles, direct-runner behavior, artifact/privacy
  contracts, eval suite availability, and operator-console safety gates.

Verification:

- L0: exact caller/import/env/command absence searches for each deleted owner.
- L1: focused module tests and touched-file Ruff/format checks per slice.
- L2: command routing, report/artifact, launch, eval, and operator-console
  contract tests.
- L3: direct-runner household map-build and cleanup public commands; live
  provider proof is not required because no provider transport behavior is
  changed and the timing producer is currently unreachable.
- Final: `uv sync --extra dev`, `ruff check .`, `ruff format --check .`, and
  `./scripts/dev/run_pytest_standalone.sh -q`.

## Approved Queue

| Slice | Severity | Architecture value | Status |
| --- | --- | --- | --- |
| Legacy run artifacts | P1 | Remove one test-only artifact owner and false contract gate | Done |
| Provider timing proxy | P1 | Remove one inert producer/reader contract and stale switch | Done |
| Maintainer dispatch loop | P1 | Remove one dispatcher and duplicate target registries | Done |
| Operator phase taxonomy | P1 | Merge phase owners and fix terminal classification | Done |
| Typed launch boundary | P1 | Remove string copies/reparse and retired backend inspectors | Done |

## Parked

- Package-level re-export facades, `shlex` micro-cleanup, single-implementation
  Protocols, default-prompt consolidation, and unrelated direct dependency
  declarations remain outside this accepted packet.
- Historical outputs and immutable candidate receipts are not rewritten.

## Completed Summary

- Legacy `roboclaws.core.run_artifacts`, its only consumer test, and the
  self-preserving `verify::contract` entry were removed. Current household
  artifact/report contracts and `just verify::contract` pass unchanged.
- Provider timing proxy implementation/contract, report ingestion, CI/eval
  switch plumbing, tests, architecture claim, and direct `aiohttp` declaration
  were removed. SDK model-call metrics and performance reports pass unchanged.
- Public `agent::*` recipes now validate against and forward directly to the
  canonical private Just registry. The Python dispatcher and duplicate target
  sets were removed; launch execution/redaction helpers now live in the launch
  runners owner instead of a CLI module.
- Operator-console active and terminal run phases now have one normalized owner
  in `state_summary`. State, checker, interactions, launcher, and inventory use
  the shared predicates; `done` and `emergency_stopped` release terminal locks
  and no longer appear attachable or running.
- `LaunchPlan` now carries canonical launch axes, goal context, scenario setup,
  and relocation count directly. Adapter-only options remain in `overrides`;
  environment export, execution, eval spawning, and rerun reconstruction consume
  the typed plan. Dead evaluation/task metadata and retired backend inspectors
  are gone, and current apple-to-apple/CI command generators use canonical
  `prompt=` input.

## Verification Result

- Exact stale-reference searches for all deleted launch helpers, evaluation
  metadata, and backend inspector commands return no matches.
- Focused launch, eval, dev-tools, MCP, Molmo cleanup, script, and operator
  console suites pass, including the scoped pre-commit suites.
- Public trace proofs preserve canonical routes and private dependency
  redaction. Actual direct-runner cleanup and camera-grounded map-build product
  runs complete and write their reports; Grounding DINO records 35 successful
  events with zero failures in the map-build proof.
- `uv sync --extra dev`, `ruff check .`, `ruff format --check .`, the Python
  quality ratchet, `git diff --check`, and
  `./scripts/dev/run_pytest_standalone.sh -q` pass.
- Ultra review found one typed-boundary regression before commit: Agibot live
  map-build could ignore a non-Kimi provider profile after canonical overrides
  were stripped. The adapter now receives `plan.provider_profile` directly and
  has a no-environment regression test.

## Scope Changes

The only execution-time scope addition was migrating two current in-repo public
command generators from removed `task=` input to canonical `prompt=` after the
full scoped gate proved they were live callers. No compatibility alias was
reintroduced and no public schema or command was added.

## Stop Condition

Stop after the five approved slices and final proof. Newly observed P2 cleanup
is parked; only a P0/P1 regression caused by these edits may expand the queue.
