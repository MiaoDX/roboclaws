# Post-Review Architecture Simplification

**Status:** Done
**Created:** 2026-08-02
**Last reviewed:** 2026-08-02
**Current implementation contract:** Execute the five approved cleanup candidates from the
2026-08-02 multi-route architecture review without changing public launch, MCP, schema, report,
artifact, provider, simulator, or hardware behavior.
**Related plans:** `2026-07-30-post-cleanup-saturation-refactors.md`,
`2026-08-02-household-backend-port-refactor.md`

## Plan Ledger

- Plan status: DONE
- Session scope: post-review-architecture-simplification
- Parent plan: none
- Child plans: none
- Last updated: 2026-08-02
- Current slice: complete
- Next action: none
- Blocked on: nothing
- Do not touch from this session: durable eval baseline publication, provider routes, simulator or
  real-robot behavior, public launch/MCP/schema/report/artifact contracts, unrelated plans,
  `TODOS.md`, and `THOUGHTS.md`

## Refactor Gate

Selected route: `$intuitive-flow` durable execution through an `$intuitive-refactor`
selected-slice ratchet campaign.

Discovery source: approved 2026-08-02 baseline architecture, ponytail, ponytail-ultra, and
`intuitive-reduce-entropy` review packet at HEAD `a455b133`.

Goal: remove two proven lifecycle/authoring regressions, merge duplicate household artifact
ownership, and delete two remaining P2 compatibility/dispatch surfaces.

Accepted severities: three P1 and two P2 candidates.

Accepted cleanup checklist:

- [x] Restore process environment when session-live HTTP server construction or startup fails.
- [x] Remove the MolmoSpaces scene-bundle generator's generic-session/private-backend escape.
- [x] Give direct and MCP household runs one canonical artifact/result composition owner.
- [x] Remove eval-harness mapping-to-argv option-registry duplication.
- [x] Use `agent_scratchpad.json` as the sole live scratchpad filename and delete migration logic.

Behavior-change policy:

- Internal lifecycle correction and owner consolidation are accepted.
- Existing public commands, serialized keys and values, report content, artifact paths, provider
  selection, and simulator/robot behavior are invariant.
- Any required public artifact migration, new schema, compatibility layer, or new dependency is a
  hard stop and requires a revised approved contract.

Architecture simplification claim: lifecycle state has one exception-safe owner, backend-specific
authoring uses its concrete adapter, household artifact composition has one canonical owner,
eval-harness options have one parser/registry, and the scratchpad has one filename.

Surface metrics:

- process-environment leak paths: 1 -> 0
- generic-session/private-backend authoring escapes: 1 -> 0
- household artifact/result composition owners: 2 -> 1
- eval-harness option registries/round trips: 2+ -> 1
- live scratchpad filenames and migration branches: 2 -> 1
- new public contracts, modules, registries, or dependencies: 0

## Evidence Ladder

- L0: exact searches prove stale environment, backend escape, dynamic artifact hooks/private prior
  reads, duplicated eval option registry, and `cleanup_scratch.json` live references are gone.
- L1: focused session-live, scene-bundle generator, scratchpad, eval-harness, direct-run artifact,
  and MCP artifact unit tests.
- L2: household MCP/runtime/report/artifact contract tests and public eval CLI routing tests.
- L3: not required unless implementation changes provider, simulator, visual, or physical runtime
  behavior; if it does, stop and revise the gate.
- Final: Ruff, format, architecture import graph, standalone full suite, and `just agent::verify`.

## Execution Order

1. Fix session-live environment restoration and prove startup-failure isolation.
2. Fix the documented MolmoSpaces bundle generator and prove real owner use without expanding the
   backend port.
3. Consolidate direct/MCP artifact composition behind the existing artifact owner while preserving
   exact serialized outputs.
4. Remove eval argument round-trip duplication and the legacy scratchpad filename.
5. Run changed-code cleanup, full proof, human-doc alignment, closeout, and delete the active
   capsule.

## Risks And Stops

- Artifact consolidation is medium-high risk because public evidence must remain byte/contract
  equivalent. Work one payload group at a time and retain route-specific inputs only where real.
- Stop if a current external consumer requires `cleanup_scratch.json`, the selector module's
  standalone CLI is a documented contract, or the scene generator needs cross-backend state.
- Stop if focused parity tests cannot establish artifact equivalence without a schema decision.
- Low-value stop signal: only renames, file motion, or speculative abstractions remain.

## Parked

- Package re-exports, `shlex` micro-cleanup, unrelated dependency pruning, prompt consolidation,
  hardware validation, baseline publication, and public backend/plugin extensibility remain parked.

## Stop Condition

Mark DONE only when all five checklist items are complete, public serialized behavior is unchanged,
focused and final gates pass, changed-code review has no accepted finding, docs match HEAD, semantic
commits exist for each coherent slice, and the active capsule is removed.

## Closeout

Completed 2026-08-02. The five accepted simplifications shipped in semantic commits:

- `567c4198` restores session-live environment state across server startup failures.
- `085d2764` gives MolmoSpaces bundle authoring its concrete backend.
- `92362075` consolidates direct and MCP household run artifact ownership.
- `c44534be` consumes eval-harness overrides without the argv registry round trip.
- `e8e13d15` retires the legacy cleanup scratchpad filename.
- `f150052c` closes changed-code review findings for parser errors, scratchpad byte preservation,
  thread-start cleanup, and normalized Runtime Map prior summary parity.

Final proof passed: exact stale-surface searches, focused unit and contract suites, full-repo Ruff
and format checks, the architecture import graph (528 modules, 1652 edges, no violations), the
complete standalone test suite, and `just agent::verify`. Human documentation required no update
because public commands, schemas, serialized keys, reports, artifact paths, and runtime behavior
remain unchanged. No live provider, simulator, physical robot, baseline, or catalog route ran.
