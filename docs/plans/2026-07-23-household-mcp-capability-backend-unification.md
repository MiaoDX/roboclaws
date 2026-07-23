**Status:** Active; capability entitlement implemented, backend unification in progress
**Created:** 2026-07-23
**Last reviewed:** 2026-07-23
**Current implementation contract:** Household intents share one public surface and skill, but
the active generic MCP server still registers a cleanup-shaped superset of tools and Agibot
MapBuild retains a parallel server path.
**Related ADRs:** ADR-0136, ADR-0140; add a new ADR for task-scoped MCP entitlement and the
single-server backend contract before implementation.
**Supersedes / Superseded by:** Narrows and continues the server/profile cleanup direction in
`2026-06-11-household-map-launch-open-ended-contracts.md` and
`refactor-reduce-entropy-domain-first-launch-architecture.md`.
**Backward compatibility:** Not required. Migrate known in-repo callers and fixtures, then delete
old server ids, tool surfaces, entrypoints, aliases, and readers touched by this refactor.

## Plan Ledger

- Plan status: ACTIVE
- Session scope: household-mcp-capability-backend-unification
- Parent plan: none
- Child plans: none
- Last updated: 2026-07-23
- Current slice: Slice 2, move all backends behind the common household server.
- Next action: Preserve Agibot MapBuild parity in the common server, merge its live route, then
  delete the dedicated server/tool/CLI path.
- Blocked on: none; final live, Isaac, and physical proof may still require guarded blocker
  evidence.
- Do not touch from this session: unrelated eval, map/report cleanup, archived plans, `TODOS.md`,
  and `THOUGHTS.md`.

# Household MCP Capability And Backend Unification

## Outcome

Make the household agent boundary task-scoped, backend-neutral, and smaller:

```text
Surface + GoalContract + optional Preset
  -> required capability profiles
  -> exact immutable MCP tool surface for this Robot Run
  -> one Household MCP server
  -> one backend-neutral household contract
  -> MuJoCo | Isaac Lab | Agibot backend adapter
  -> public run artifacts + private evaluator evidence
```

The governing distinction is:

```text
Task does not require capability
  -> tool is not registered and the agent cannot see it

Task requires capability, backend cannot provide it
  -> tool is registered and returns structured blocked_capability
```

This replaces prompt-only disabling and backend/task-specific tool supersets with exact
capability disclosure.

## Refactor Gate

Selected route: bounded architecture refactor gate.

Why: the target seam is known, but it spans public MCP tools, launch propagation, live runners,
backend contracts, reports, evals, and physical safety evidence.

Redirect: use `intuitive-reduce-entropy` only if implementation discovers unrelated whole-repo
cleanup candidates. Do not broaden this plan into general report, map, or test-suite cleanup.

Refactor scope:

- MCP capability entitlement and exact tool registration;
- one household MCP server/composition root;
- backend-neutral sim/Isaac/Agibot behavior and evidence contracts;
- removal of the dedicated Agibot MapBuild server path;
- task-neutral renames only where the refactor changes ownership;
- backend-neutral long-horizon/final-state evaluator inputs.

Discovery source:

- user request on 2026-07-23;
- current `TaskPresetSpec` / `TaskIntentSpec` capability declarations;
- current `ContractProfile` and unused exact-registration router;
- generic and Agibot-specific MCP server implementations;
- current sim and physical eval/result contracts.

Accepted severities:

- P1: agent-visible tool surface disagrees with required capability declarations;
- P1: task absence and backend unavailability are conflated;
- P1: parallel Agibot MapBuild server/runner logic drifts from the household path;
- P1: physical result placeholders can look like authoritative final state;
- P2: cleanup/Molmo/realworld names remain on task-neutral owners;
- P2: duplicate server argv helpers, registration tables, finalizers, and checker branches.

Parked:

- enabling physical manipulation or claiming physical cleanup readiness;
- changing robot safety or emergency-stop policy;
- dynamic mid-run mutation of the MCP tool list;
- a new public `capabilities=` launch axis;
- rewriting static archived reports or historical planning records;
- unrelated map/report visual cleanup;
- a third-party eval framework.

Stop condition:

- one active household FastMCP server and one package entrypoint remain;
- every run registers exactly the union of its required capability profiles;
- sim and physical backends share public request/response schemas;
- backend differences are limited to provenance, readiness, evidence, and structured blockers;
- the dedicated Agibot MapBuild server/tool registration path is deleted;
- current names describe domain ownership rather than one backend or one preset;
- focused tests, product/eval proofs, and required live or blocker evidence pass.

Low-value stop signal: stop extracting when the next proposed abstraction does not delete a
registry, server, runner branch, adapter special case, or duplicated contract rule.

## Current Problems

### 1. Capability declarations do not control registration

Launch metadata already distinguishes:

| Intent | Required profiles |
| --- | --- |
| MapBuild | `household_world`, `household_episode` |
| Cleanup | `household_world`, `household_manipulation`, `household_episode` |
| Open-ended | currently `household_world`, `household_episode` |

The profile catalog separately owns the corresponding public tools, and `MCPProfileRouter`
can register an exact profile. The active server bypasses that path and always registers
semantic, manipulation, and lifecycle tools. Evidence-lane selection currently controls the
same full list rather than task capability entitlement.

Consequences:

- MapBuild agents see `pick`, `place`, and receptacle tools they should never receive;
- prompt text and `cleanup_actions_enabled=False` are mistaken for an authorization boundary;
- Agent View can report profiles that do not match runtime registration;
- tests prove blocked behavior where absence is the intended contract.

### 2. Two household server implementations encode backend/task drift

The repo contains:

- generic `RealWorldMolmoCleanupMCPServer` for household intents and injected backends;
- dedicated `AgibotMapBuildMCPServer` with a second tool registry, finalizer, report path,
  visual-grounding flow, and live runner branch.

The public package router exposes only `household-world`, while the dedicated Agibot path is
started through private runner logic. The active Agibot runner and its checker expectations have
already drifted around which package server entrypoint and server id they expect.

### 3. Backend adapters expose different conceptual boundaries

MuJoCo and synthetic runs use `RealWorldCleanupContract`; Agibot has both a shared
`AgibotCleanupMCPContract` and a dedicated MapBuild server. Common behavior such as map
projection, observation shaping, tool-order enforcement, done readiness, artifact writing, and
private evaluation is therefore split across transport, task, and backend owners.

### 4. Names preserve obsolete ownership

Task-neutral components still use names such as `molmo_cleanup_realworld`,
`RealWorldMolmoCleanupMCPServer`, `make_molmo_realworld_cleanup_mcp`, and
`run_live_openai_agents_cleanup.py`, even though they run MapBuild, Cleanup, and Open-ended
tasks across multiple backends.

### 5. Physical final-state evidence is not equivalent to sim truth

The long-horizon grader is backend-neutral in intent but consumes simulator-authoritative
`final_locations` and `final_containment`. The current Agibot shared contract emits empty
private evaluation and placeholder scenario locations while manipulation remains blocked.
That is sufficient for navigation/perception rehearsal, not for authoritative physical task
success.

## Target Ownership

| Concern | Canonical owner |
| --- | --- |
| Intent/preset required profiles | `roboclaws.household.tasks` and `roboclaws.launch.intents` |
| Run-specific resolved capabilities | `GoalContract` / `LaunchPlan` |
| Profile-to-tool definitions | `roboclaws.mcp.profiles` |
| Exact composed tool registration | `roboclaws.mcp.entrypoint` |
| MCP transport/lifecycle/trace | one household MCP server |
| Server/backend assembly | `roboclaws.cli.household_agent_server` |
| Public household semantics and ordering | shared household contract modules |
| Simulator/Isaac/Agibot primitive execution | backend adapters |
| Public completion readiness | shared household done-readiness policy |
| Private goal truth and grading | eval adapters/graders, never MCP or Agent View |

Do not create a second task registry, tool registry, server catalog, or backend capability table.
The launch catalog and contract profiles remain the two existing canonical sources.

## Accepted Decisions

### A. Tool surfaces are immutable per Robot Run

Resolve capabilities before starting the MCP process. Register exactly that tool set and keep it
stable until the run terminates. This preserves SDK tool caching, reproducible traces, and a
reviewable authorization boundary.

### B. Entitlement and availability are separate

For a selected tool:

- entitlement comes only from the resolved capability profiles;
- availability comes from the selected backend adapter;
- an unavailable entitled tool returns `blocked_capability` with provenance and recovery text;
- a non-entitled tool is absent from MCP `tools/list` and rejected if called out of band.

### C. One server, multiple backend adapters

Keep one server process per live Robot Run, but only one server implementation. Backend selection
must not select a different public tool registry, prompt vocabulary, report schema, or completion
contract.

### D. Direct-runner remains non-MCP

Do not force deterministic direct proof through transport. It should reuse the same backend/public
evidence datatypes and completion/eval predicates where useful, but remain a cheap Python-level
contract baseline.

### E. Rename only when ownership becomes canonical

Perform renames in the same slice that merges/deletes the old owner. Do not run a standalone mass
rename. Do not leave compatibility aliases or legacy readers for old contracts touched by this
refactor. Static archived reports and historical planning text may remain as inert records only.

### F. Private evaluation stays out of the public server surface

Sim and physical runs may use different evaluator evidence producers, but the grader consumes a
shared private evidence contract. Backend state used by grading must never be added to MCP tools,
GoalContract, skill text, or Agent View.

## Open-Ended Capability Decision

The free-form prompt is known before launch; what is not reliably known without semantic
interpretation is whether that prompt will require manipulation later. Per-prompt minimum
privilege would therefore require either an extra model-backed classification step or mutable
capability escalation. Both add implementation, latency, failure modes, and audit complexity.

This refactor uses task-level progressive disclosure instead:

1. MapBuild and Cleanup receive their exact deterministic profile sets.
2. Open-ended is intentionally defined as a broad household task contract and receives
   `household_world`, `household_manipulation`, and `household_episode`.
3. The Open-ended surface is still immutable for the Robot Run; there is no preflight provider
   call, keyword classifier, or dynamic tool escalation.
4. If a stable narrower goal class becomes useful, promote it to an explicit preset/intent with
   its own deterministic profile set rather than classifying arbitrary prompts at runtime.

This is deliberate broad entitlement, not a fallback. Progressive disclosure is guaranteed at
the declared task/preset boundary, not separately for every free-form prompt.

## Rename And Deletion Map

Apply these names as their owning slices land:

| Current | Target action |
| --- | --- |
| `molmo_cleanup_realworld` server id | rename to `household_world` |
| `RealWorldMolmoCleanupMCPServer` | rename to `HouseholdWorldMCPServer` |
| `make_molmo_realworld_cleanup_mcp` | rename to `make_household_world_mcp` |
| `realworld_mcp_server.py` | rename to `household_mcp_server.py` |
| `realworld_mcp_backend.py` | rename to `household_mcp_tools.py` or merge into the server when smaller |
| `household_cleanup_server_argv` and `map_build_server_argv` | replace with one `household_server_argv` |
| `run_live_openai_agents_cleanup.py` | rename to `run_live_openai_agents_household.py` if it remains the common runner |
| `RealWorldCleanupContract` | rename to `HouseholdRuntimeContract` after shared task semantics are centralized |
| `CleanupBackendSession` / `build_cleanup_backend_session` | rename to household backend terms when all intent callers use the common protocol |
| `AgibotCleanupMCPContract` | rename to `AgibotHouseholdBackend` after it no longer owns MCP/report policy |
| `AgibotMapBuildMCPServer` and tool module | migrate unique adapter behavior, then delete |
| `agibot_map_build_agent_server.py` | delete after the common composition root owns the route |
| special Agibot live MapBuild runner | merge into the common household live runner, then delete |

Keep names such as `cleanup_worklist`, cleanup-specific reports, and cleanup eval schemas where
they still describe genuinely cleanup-only data. Historical plan/retrospective text is not a
rename target, but no active reader or alias is retained for compatibility with it.

## Execution Slices

### Slice 0: Lock The Contract With Characterization Tests And ADR

Architecture claim: the intended tool matrix and backend evidence boundary must be executable
specifications before deleting parallel implementations.

Changes:

- add an ADR for immutable task-scoped tool entitlement, one household server, and separate
  backend availability;
- add a table-driven test for expected tools by required profile combination;
- add negative tests proving MapBuild MCP `tools/list` excludes all manipulation tools;
- add tests proving Cleanup includes manipulation tools;
- add tests proving an entitled but unavailable physical capability returns
  `blocked_capability`;
- add a backend-conformance fixture for shared response fields and provenance;
- characterize current Agibot MapBuild artifacts that must survive server deletion;
- record active current-name references so later rename gates distinguish current code from
  history.

Proof:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/contract/mcp/test_semantic_profiles.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py \
  tests/contract/molmo_cleanup/test_physical_agibot_pilot.py
```

Stop gate: do not start server deletion until the common test fixture can express both sim and
Agibot behavior without importing the dedicated server as the expected architecture.

### Slice 1: Compose Profiles And Register Exact Tools

Architecture claim: `LaunchPlan.required_capabilities` is the only source of agent tool
entitlement.

Changes:

- extend the existing MCP profile router to compose an ordered tuple of profiles and reject
  duplicate/conflicting tool descriptors;
- propagate resolved capability profiles from launch plan through the private runner into the
  server process;
- replace unconditional semantic + atomic + lifecycle registration with composed profile
  registration;
- delete `public_tool_names_for_evidence_lane`; evidence lanes affect observation data, not task
  authority;
- make server dispatch reject any call outside the resolved surface even if a backend handler
  exists;
- derive Agent View capability metadata from the actual registered list;
- require `runtime_extra_public_tool_names=[]` for normal product runs;
- remove MapBuild prompt language about calling manipulation tools merely to verify blockers;
- keep backend handlers internal and reusable without registering them.

Expected tool sets:

```text
MapBuild
  household_world + household_episode

Cleanup
  household_world + household_manipulation + household_episode

Open-ended
  household_world + household_manipulation + household_episode
```

Proof:

- table-driven unit/contract tests for all three rows;
- MCP `tools/list` assertions, not only Agent View metadata assertions;
- out-of-band manipulation call against MapBuild is rejected as unknown/non-entitled;
- Open-ended exposes the declared broad surface without a provider-backed capability-resolution
  call;
- Agibot Cleanup still exposes required manipulation tools and reports blockers while Agibot
  MapBuild does not expose them.

### Slice 2: Move All Backends Behind The Common Household Server

Architecture claim: backend selection changes primitive execution and evidence provenance, not
the MCP server implementation.

Changes:

- move unique Agibot MapBuild map, navigation, observation, visual-grounding, readiness, and
  artifact behavior into the Agibot backend adapter or shared household finalizer;
- normalize Agibot handler signatures to the same public tool requests used by sim;
- make the common `household_agent_server` assemble synthetic, MuJoCo, Isaac Lab, and Agibot
  adapters through one path;
- route every live household intent through one server argv helper and one server id;
- merge the special Agibot live runner lifecycle into the common SDK household runner;
- preserve backend-specific safety gates and locks in launch/operator code;
- delete `AgibotMapBuildMCPServer`, its duplicate tool module, dedicated CLI entrypoint, and
  dedicated live-runner path once parity tests pass.

Do not move task strategy into the backend adapter. The adapter owns primitives, readiness,
provenance, and state/evidence export only.

Proof:

- the same MapBuild server contract tests run against MuJoCo, Isaac fixtures, and Agibot dry-run;
- Agibot MapBuild still produces Runtime Metric Map, trace, Agent View, report, and readiness
  evidence;
- `rg` finds one active FastMCP household server class and one active package server target;
- no live route imports `agibot_map_build_mcp_server`.

### Slice 3: Normalize Backend And Completion Evidence

Architecture claim: public task semantics are shared; exact state truth is an evaluator-side
backend concern.

Changes:

- rename/generalize cleanup-shaped backend session protocols only where all household intents use
  them;
- centralize public response shaping, semantic-order errors, done readiness, completion claim,
  trace writing, and common artifact finalization;
- keep simulator/Isaac/Agibot differences in primitive implementations and provenance fields;
- define a private `FinalStateEvidence` packet for locations, containment, held-object state,
  receptacle state, source provenance, confidence, and source errors;
- implement an exact simulator evidence producer;
- implement a physical evidence adapter that may combine GDK pose/log evidence, independent
  cameras/sensors, or human-reviewed evidence;
- return `unavailable`/`inconclusive` when physical final state is not observable; never emit
  placeholder scenario locations as authoritative physical truth;
- update the long-horizon grader to consume the shared evidence packet while keeping the private
  goal reference grader-only.

Portable physical checks available before manipulation proof:

- map acquired;
- waypoint/source/destination navigation evidence;
- observation and artifact readiness;
- tool sequence and privacy boundary.

Checks that remain blocked/inconclusive without independent physical evidence:

- target object identity and final placement;
- containment;
- empty gripper;
- receptacle closed state;
- semantic completion of a manipulation goal.

Proof:

- the same grader predicates pass on exact sim evidence;
- missing physical evidence produces `inconclusive` or `blocked`, not a false pass or ordinary
  behavior failure;
- no private final-state packet appears in Agent View, MCP responses, prompt text, or public trace;
- existing privacy-leak tests remain green.

### Slice 4: Rename Canonical Owners And Remove Stale Surfaces

Architecture claim: current names describe the household domain; backend/task names remain only
on genuine backend/task implementations.

Changes:

- apply the rename/deletion map above while updating all in-repo callers;
- migrate server id expectations in launch plans, reports, checkers, eval fixtures, operator
  state, and tests to `household_world`;
- remove duplicate argv helpers and task-specific live server launch branches;
- delete obsolete server policies whose only purpose was identifying the old implementation;
- update README, ARCHITECTURE, `just/README.md`, household skill, local-runtime docs, and Agibot
  pilot docs;
- do not add compatibility aliases or preserve old artifact readers; migrate checked-in current
  fixtures and let external/archived artifacts remain unsupported.

Search proof:

```bash
rg -n -F \
  -e 'molmo_cleanup_realworld' \
  -e 'RealWorldMolmoCleanupMCPServer' \
  -e 'make_molmo_realworld_cleanup_mcp' \
  -e 'AgibotMapBuildMCPServer' \
  -e 'agibot_map_build_agent_server' \
  README.md ARCHITECTURE.md just skills roboclaws scripts tests docs/human
```

Expected result: no active current-contract references. Explicit archived/historical readers or
fixtures must be documented at the exact remaining line rather than hidden behind aliases.

## Verification Ladder

Run focused proof after each slice. Do not defer all validation until the rename.

### L0: Static ownership and stale-surface checks

```bash
ruff check roboclaws tests scripts
ruff format --check roboclaws tests scripts
rg -n "FastMCP|SUPPORTED_SERVER_TARGETS|register_.*mcp_tools" roboclaws
```

### L1: Unit and mock proof

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/contract/mcp/test_semantic_profiles.py \
  tests/unit/launch \
  tests/unit/agents \
  tests/unit/operator_console
```

### L2: Contract/integration proof

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py \
  tests/contract/molmo_cleanup/test_molmo_realworld_agent_server.py \
  tests/contract/molmo_cleanup/test_physical_agibot_pilot.py \
  tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py \
  tests/contract/dev_tools/test_task_agent_just_recipes.py
```

Required assertions include:

- MapBuild tools exclude every manipulation tool on every backend;
- Cleanup tools include manipulation even when a physical backend returns blockers;
- evidence lane changes observations but not entitlement;
- Agent View tools exactly equal server registration;
- server id, trace schema, artifacts, and checker identity are backend-neutral;
- private evaluator evidence never enters public artifacts.

### L3: Product, eval, and live proof

Start with the maintained selector:

```bash
just agent::eval recommend \
  plan=docs/plans/2026-07-23-household-mcp-capability-backend-unification.md \
  budget=focused

just agent::eval execute \
  plan=docs/plans/2026-07-23-household-mcp-capability-backend-unification.md \
  budget=focused
```

At minimum exercise deterministic suites covering MapBuild consumer, Open-ended, Cleanup, and
long-horizon grading. Because this refactor changes live-agent/server/runtime behavior, also run
the relevant live product proofs by default.

Before provider/system live routes:

```bash
just dev::network-status
```

Required live/product evidence when available:

- MuJoCo MapBuild with OpenAI Agents SDK: tool list excludes manipulation and Runtime Metric Map
  artifacts pass;
- MuJoCo Cleanup with SDK: manipulation tools are present and cleanup checker passes;
- one information/search Open-ended goal and one manipulation Open-ended goal: both receive the
  same declared broad immutable surface without a separate provider call;
- one long-horizon manipulation goal: private final-state grader passes;
- B1/Isaac MapBuild or its concrete GPU/runtime blocker;
- Agibot MapBuild dry-run plus hardware preflight/status evidence; run real movement only under
  the existing enablement, localization, e-stop, and operator safety gates.

If a required provider, GPU runtime, or physical robot proof cannot run, record the exact guarded
preflight/status blocker. Do not substitute a narrower deterministic test and claim the live
surface is proven.

## Surface Metrics

Record before/after values in the implementation handoff:

- active household FastMCP server classes: target `2 -> 1`;
- active package MCP server targets: remain `1`;
- household live server argv helpers: target `2 -> 1`;
- dedicated Agibot MapBuild server/tool/CLI modules: target `3 -> 0`;
- current server ids for household runs: target `2 -> 1`;
- runtime extra tools outside resolved profiles: target `0`;
- MapBuild-visible manipulation tools: target `0` on every backend;
- backend-specific public request/response schema forks: target `0`;
- placeholder physical final-state fields treated as authoritative: target `0`;
- net active server/registration/runner code: must decrease; explain any increase with a deleted
  duplicate owner and a focused test.

## Risks And Stop Gates

1. Open-ended intentionally has broader entitlement than some individual prompts need. Keep that
   contract explicit; add a narrower preset/intent only when it represents a stable product task.
2. Renaming server ids changes checker and artifact identity. Migrate current in-repo readers in
   the same slice, then delete old readers and aliases.
3. Deleting the Agibot server before moving camera/readiness/report behavior can regress the only
   physical MapBuild route. Characterization and dry-run parity are mandatory first.
4. Tool absence may expose prompts or skills that still instruct unavailable calls. Prompt,
   skill, tool-list, and negative-call tests must migrate together.
5. Backend-neutral response schemas must not erase physical provenance or make blocked hardware
   look simulated-successful.
6. A shared final-state evidence packet must remain private. Treat any public leak as P0 and stop.
7. Concurrent work currently touches eval runner/runtime files. Execution must inspect the
   worktree and isolate task-owned hunks before changing those files.

## Definition Of Done

- The launch plan names the exact capability profiles for every run.
- The MCP server registers only tools from those profiles.
- MapBuild never exposes manipulation tools, including Agibot MapBuild.
- Cleanup exposes manipulation tools; unsupported physical primitives return structured blockers.
- Open-ended always receives its documented broad immutable profile set without a provider-backed
  classification call or dynamic escalation.
- One backend-neutral household MCP server serves synthetic, MuJoCo, Isaac Lab, and Agibot.
- Dedicated Agibot MapBuild server/registration/CLI/runner code is deleted after parity proof.
- Old server ids, entrypoints, aliases, and artifact readers touched by the refactor are deleted;
  no backward-compatibility path remains.
- Current server, runner, and backend owners touched by this refactor no longer contain obsolete
  Molmo, cleanup, or realworld ownership claims; genuinely cleanup-only data keeps cleanup names.
- Sim and physical public schemas match; backend provenance and readiness remain explicit.
- Long-horizon grading consumes a backend-neutral private final-state evidence contract.
- Physical runs without authoritative final-state evidence report blocked/inconclusive.
- Focused static, unit, contract, eval, live, and hardware/blocker evidence is recorded.
- Documentation describes one server, profile-scoped tools, and backend-specific readiness only.

## Preflight Contract

Preflight status: APPROVED 2026-07-23 by the explicit execution goal

Task source: user request + this plan

Canonical source: `docs/plans/2026-07-23-household-mcp-capability-backend-unification.md`

Route: durable `$intuitive-flow` for the full bounded architecture refactor

Goal: Make MCP entitlement task-scoped and immutable, converge every household backend on one
public server/contract, and delete the parallel and obsolete implementation surfaces without
backward-compatibility shims.

Scope:

- Lock the task/profile/tool matrix and backend evidence boundary with an ADR and characterization
  tests before deletion.
- Compose existing MCP profiles into the exact per-run tool surface for MapBuild, Cleanup, and
  broad-contract Open-ended tasks.
- Move synthetic, MuJoCo, Isaac Lab, and Agibot execution behind one household server and common
  public request/response contract while retaining backend readiness, provenance, and safety.
- Normalize private final-state evidence for long-horizon grading; unsupported physical evidence
  is blocked/inconclusive rather than inferred from placeholders.
- Apply task-neutral renames only as ownership converges; migrate current in-repo callers, docs,
  tests, and fixtures, then delete replaced server ids, entrypoints, aliases, and readers.

Non-goals:

- No physical manipulation enablement or claim of physical cleanup readiness.
- No robot safety, localization, emergency-stop, or movement-authorization policy change.
- No dynamic MCP tool mutation, provider-backed prompt classification, keyword classifier, or
  public `capabilities=` launch axis.
- No conversion of `direct-runner` into an MCP client.
- No general map/report/test cleanup, third-party eval framework, archived artifact migration, or
  historical document rewrite.

Entity budget:

- reuse: `TaskPresetSpec` / `TaskIntentSpec.required_capabilities`, `GoalContract`, `LaunchPlan`,
  `roboclaws.mcp.profiles`, `MCPProfileRouter`, the generic household server/CLI, existing backend
  sessions, Agent View, run artifacts, and eval harness.
- remove/merge: dedicated Agibot MapBuild server/tool/CLI/live-runner path, unconditional and
  duplicate tool registries, duplicate server argv helpers, cleanup-shaped common owner names,
  backend-specific public schema branches, placeholder physical final-state truth, and current
  compatibility readers touched by the refactor.
- new: one ADR; composed-profile validation in the existing router; one private
  `FinalStateEvidence` contract and backend producers, preferably in an existing evidence/eval
  owner; focused conformance tests. A new production module is allowed only when it replaces a
  duplicate owner or prevents the private evaluator contract from entering server code.
- expansion triggers: a new public launch axis/tool/profile/server/registry, dynamic capability
  escalation, physical manipulation enablement, safety-policy changes, a compatibility bridge, or
  a backend-specific public schema requires re-approval.

Context:

- must-read: this plan, `STATUS.md`, `ARCHITECTURE.md`,
  `docs/human/mcp-skills-and-semantic-profiles.md`, `docs/human/evaluation.md`,
  `docs/human/local-runtime.md`, `roboclaws/household/tasks.py`,
  `roboclaws/launch/intents.py`, `roboclaws/mcp/profiles.py`,
  `roboclaws/mcp/entrypoint.py`, `roboclaws/household/realworld_mcp_server.py`,
  `roboclaws/household/agibot_map_build_mcp_server.py`,
  `roboclaws/cli/household_agent_server.py`, and `roboclaws/evals/long_horizon_grader.py`.
- useful: `roboclaws/household/agibot_map_build_mcp_tools.py`,
  `roboclaws/household/agibot_sdk_runner.py`, `roboclaws/household/backend_contract.py`, current
  run artifacts/checkers, and the focused tests named in the verification ladder.
- avoid-unless-needed: shipped retrospectives, archived ADR execution logs, static historical
  reports, unrelated plans, and parked `TODOS.md` / `THOUGHTS.md` work.

Acceptance:

- SUCCESS: MCP `tools/list` exactly matches the declared task profiles on every backend; MapBuild
  has no manipulation tools; Cleanup and Open-ended have manipulation entitlement; entitled but
  unavailable primitives return `blocked_capability`; one backend-neutral server/entrypoint and
  public schema remain; the dedicated Agibot path and touched legacy ids/readers are deleted;
  Agent View matches actual registration; long-horizon grading consumes private backend-neutral
  final-state evidence; absent physical truth is blocked/inconclusive; all required deterministic,
  integration, product-run, and available local/live gates pass.
- BLOCKED_NEEDS_DECISION: none at preflight. Stop for re-approval on any entity-budget expansion
  trigger or if Agibot behavior cannot fit the shared public contract without changing it.
- BLOCKED_NEEDS_LOCAL_VALIDATION: required provider/MuJoCo/Isaac Lab/Agibot proof is unavailable
  because of network, credentials, runtime, GPU, hardware, or operator safety gates. Record the
  guarded blocker; the branch is not fully complete or merge-ready until the affected gate passes.
- INTERMEDIATE_ONLY: none unless the human explicitly approves an implementation checkpoint.
- No regressions: current canonical household MapBuild, Cleanup, Open-ended, Base/Runtime Metric
  Map, Agent View privacy, report/artifact, operator safety, and direct-runner baseline contracts
  continue to pass. Old ids and artifact readers intentionally receive no compatibility guarantee.

Verification:

- deterministic: run the L0-L2 static, unit, and contract commands in this plan, including profile
  composition, `tools/list`, out-of-band denial, backend conformance, server identity, artifact,
  long-horizon final-state, and private-truth leak assertions.
- integration: run
  `just agent::eval recommend plan=docs/plans/2026-07-23-household-mcp-capability-backend-unification.md budget=focused`,
  then the recommended
  `just agent::eval execute plan=docs/plans/2026-07-23-household-mcp-capability-backend-unification.md budget=focused`;
  also run `just agent::eval suite=long_horizon_tasks budget=smoke`.
- product-run: exercise MuJoCo MapBuild with both `direct-runner` and
  `openai-agents-sdk`, MuJoCo Cleanup with `openai-agents-sdk`, and two Open-ended SDK prompts
  (information/search and manipulation) through `just run::surface`; prove the declared immutable
  tool matrix and required artifacts for each route.
- local-live-manual: run `just dev::network-status` before provider routes; require B1/Isaac
  MapBuild proof or its concrete runtime blocker, Agibot MapBuild dry-run plus hardware
  preflight/status evidence, and real Agibot movement only under existing enablement,
  localization, emergency-stop, and operator authorization gates.
- optional: broader provider/pass^k matrices only after the required focused gates are green.

Execution:

- main: root session owns slice ordering, shared-worktree isolation, architecture/stop-gate
  decisions, focused commits, live-gate judgment, and final complete/blocked status.
- worker: none initially; use an isolated bounded worker only if later approved for inventory or a
  non-overlapping verification scope.
- worker-goal: none.

To execute:

```text
/goal execute docs/plans/2026-07-23-household-mcp-capability-backend-unification.md with intuitive-flow
```

Optional tracking: none

Approval: `LGTM`, `approve`, or `go ahead` approves execution; edits request revision.
