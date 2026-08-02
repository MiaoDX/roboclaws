**Status:** Done
**Created:** 2026-08-02
**Last reviewed:** 2026-08-02
**Current implementation contract:** Household runtime semantics depend on one typed backend port;
runtime code never reads the concrete adapter or guesses capabilities with `getattr`.
**Related ADRs:** ADR-0136, ADR-0140
**Supersedes / Superseded by:** Continues the backend-neutral boundary established by
`2026-07-23-household-mcp-capability-backend-unification.md`; does not reopen its hardware gate.
**Backward compatibility:** Public launch grammar, MCP tools, schemas, artifacts, provider routes,
and observable household behavior remain unchanged. Internal compatibility facades are not kept.

## Plan Ledger

- Plan status: DONE
- Session scope: household-backend-port-refactor
- Parent plan: none
- Child plans: none
- Last updated: 2026-08-02
- Current slice: Complete.
- Next action: None; reopen only for a regression against this gate.
- Blocked on: nothing
- Do not touch from this session: public launch/tool/schema/artifact contracts, live provider routes,
  simulator behavior, real-robot movement, unrelated eval work, `TODOS.md`, and `THOUGHTS.md`.

# Household Backend Port Refactor

## Refactor Gate

Selected route: `intuitive-refactor` ratchet campaign over a known architecture seam.

Why: `HouseholdBackendSession` is the intended backend-neutral boundary, but runtime callers can
still reach its concrete adapter and several helpers type themselves against private runtime state.

Redirect: use `intuitive-reduce-entropy` only after this accepted checklist is exhausted. Do not
broaden this campaign into unrelated whole-repo cleanup.

Refactor scope:

- Target boundary: `HouseholdRuntimeContract -> HouseholdBackendPort -> backend adapters`.
- Replace public raw adapter exposure and capability guessing with cohesive typed port operations.
- Move planner scene, observed binding, location relations, capabilities, and runtime evidence
  through canonical typed values owned by the household/backend boundary.
- Internalize or remove single-implementation Protocols that merely expose
  `HouseholdRuntimeContract` private state.
- Replace the two known cross-package private imports with public owner APIs.

Discovery source:

- 2026-08-02 repo entropy and architecture review;
- `codebase-design` deep-module review;
- whole-repo `plan-eng-review`, scope choice C;
- architecture import graph: 527 modules, 1,647 internal edges, zero SCCs, zero bidirectional
  package pairs, and zero policy violations before implementation.

Accepted severities:

- P1: runtime modules access `HouseholdBackendSession.backend` or concrete adapter private state.
- P1: backend capabilities and planner data are inferred with `Any`/`getattr` instead of a typed
  backend-owned contract.
- P2: one-implementation Protocols expose private runtime fields without creating substitutability.
- P2: cross-package callers import underscore-prefixed helpers.

Accepted cleanup checklist:

- [x] Define one cohesive typed `HouseholdBackendPort` implemented by synthetic, MolmoSpaces, and
  Isaac Lab adapters (or explicit adapter wrappers at the existing composition root).
- [x] Make `HouseholdBackendSession` keep its adapter private and expose only canonical operations
  and typed values needed by household runtime semantics.
- [x] Migrate planner scene/binding, location-relation, capability, snapshot, robot-view, runtime
  evidence, and lifecycle callers away from raw adapter access and capability guessing.
- [x] Delete the raw `.backend` escape hatch and prove no runtime caller reads adapter-private state.
- [x] Internalize or remove `RealWorldPayloadContract`, `RuntimeMapTargetContract`,
  `VisualCandidateDeclarationContract`, `DoneReadinessContract`, and `ToolResponseContract` where
  they only describe the sole `HouseholdRuntimeContract` implementation.
- [x] Replace `_parse_last_json_object` and
  `_reject_legacy_robot_view_camera_control_flag` cross-package imports with public owner APIs.
- [x] Preserve serialized outputs and public launch/MCP/schema/artifact/provider behavior exactly.

Parked cross-seam / future ideas:

- Physical Agibot validation remains under its existing blocked plan and operator gates.
- Public backend/plugin extensibility is not introduced; add it only with a real external consumer.
- Broad module moves or naming campaigns outside the accepted backend seam are out of scope.

## Target Architecture

```text
HouseholdRuntimeContract
        |
        v
HouseholdBackendPort
        |
   +----+---------+
   |              |
Synthetic      Subprocess adapters
               |- MolmoSpaces
               `- Isaac Lab
```

Ownership rules:

- Runtime owns household semantics, policy, ordering, and public response shaping.
- Adapters own environment execution, projection, backend capabilities, and backend evidence.
- The port returns canonical household datatypes; it does not expose the adapter object.
- No duplicate interface, compatibility facade, or `getattr` capability registry remains.

## Campaign Contract

- Campaign overlay: true
- Current quality signal: one public raw adapter escape hatch, direct private-state reads, five
  one-implementation Protocol seams, and two cross-package private imports.
- Architecture pressure: the nominal backend-neutral session is shallow and leaks adapter details
  into runtime policy and planner code.
- Behavior-change policy: internal structure only; public and serialized behavior is invariant.
- Architecture simplification claim: all household/backend interaction has one typed owner and
  callers cannot bypass it.
- Surface metrics: raw adapter properties, `getattr` capability probes, private cross-package
  imports, single-implementation Protocols, migrated callers, and public contracts touched.
- Verification inventory: stale-reference searches; focused unit/contract pytest through
  `scripts/dev/run_pytest_standalone.sh`; Ruff; format; architecture import graph; broader standalone
  pytest after the final slice.
- Checkpoint cadence: after each independently verified vertical slice.
- Active capsule: `docs/status/active/household-backend-port-refactor.md`
- Continue criteria: the next slice deletes/bypasses a leak, has one canonical owner, preserves
  behavior, and has focused proof.
- Stop/park criteria: public contract change, unavailable simulator/hardware proof, new plugin
  architecture, or an ownership decision outside this gate.
- Discovery cadence: none until the accepted checklist is complete.
- Clear queue: typed port and caller migration; protocol internalization; private-import cleanup.
- Parked registry: physical hardware proof; public plugin architecture; unrelated module layout.
- Rejected low-value registry: renames or file splitting that do not delete a concept or close the
  backend seam.
- Saturation stop rule: checklist complete, no raw adapter/private-state access in runtime, focused
  and broad gates green, remaining findings outside accepted scope.
- Consecutive no-clear-candidate passes: 0

## Slice 1 Architecture Claim

- Owner layer: household backend boundary.
- Current friction: planner/navigation/runtime helpers inspect a concrete adapter through the
  session and infer optional capabilities dynamically.
- Simplification: introduce the typed port at the existing owner, keep the adapter private, and
  expose cohesive operations for current callers.
- Behavior-change class: internal contract migration; serialized behavior unchanged.
- Files likely touched: household backend contract/adapters, planner/navigation callers, and their
  focused tests.
- Proof: exact stale-access search, backend contract and planner/navigation unit/contract tests,
  Ruff, format check, and architecture graph.
- Non-goals: new backend behavior, public plugin API, launch/schema changes, or live simulator runs.

## Evidence Ladder

- L0: no `.backend` access outside adapter ownership, no runtime reads of adapter-private fields,
  and no cross-package underscore imports in the accepted scope.
- L1: backend session, planner binding/requests, navigation, and helper unit tests.
- L2: household runtime/MCP contract tests and serialized response assertions.
- L3: not required unless implementation changes simulator, provider, or physical runtime behavior;
  if such a change becomes necessary, stop and revise the gate first.

## Stop Condition

Mark `DONE` only when every accepted checklist item is complete, `HouseholdRuntimeContract` cannot
reach a concrete backend adapter, outputs remain contract-identical, focused and broad proof pass,
changed-code review finds no accepted P0/P1/P2 issue, and human architecture docs match the result.

## Closeout

- Implementation: `HouseholdRuntimeContract -> HouseholdBackendPort -> synthetic / MolmoSpaces /
  Isaac Lab adapters`; no raw adapter escape hatch or runtime capability probing remains.
- Simplification: five single-implementation runtime Protocols and two cross-package private
  imports were removed.
- Proof: focused and full household suites passed; changed-code review repairs passed; final
  `just agent::verify` passed with zero architecture SCCs, bidirectional package pairs, or policy
  violations.
- Human docs: `ARCHITECTURE.md` and `docs/human/technical-design.md` aligned; README and remaining
  `docs/human/**` checked and left unchanged because public behavior did not change.
