# Forward-Only Post-Review Architecture Cleanup

**Status:** Implemented
**Created:** 2026-07-28
**Last reviewed:** 2026-07-29
**Current implementation contract:** Remove obsolete and duplicate active-code
surfaces without compatibility shims, restore one owner per current contract,
and preserve the supported household-world and planner-proof behavior through
explicit caller migration and full deterministic/live proof.
**Related plans:** `docs/plans/2026-07-27-restore-codex-mimo-responses-cells.md`,
`docs/plans/refactor-architecture-cleanup-campaign.md`,
`docs/plans/refactor-retire-ai2thor-vlm-direct.md`, and
`docs/plans/refactor-reduce-entropy-domain-first-launch-architecture.md`.
**Supersedes:** None. This is a new reviewed scope after the prior architecture
cleanup campaign saturated at Slice 42.

## Plan Ledger

- Plan status: DONE; implementation, required live proof, clean-room package
  proof, and the refreshed immutable candidate replay are complete.
- Source: five independent 2026-07-28 architecture/entropy reviews and a
  follow-up evidence review of their findings.
- Review sessions: `019fa800-db8f-7fa3-8b75-a5d1f070eec3`,
  `019fa819-b393-75a3-acb5-30b8883fcaa4`,
  `019fa835-ef37-71d3-939a-52291049db86`,
  `019fa836-0638-7340-9011-ee0e16535c82`, and
  `019fa836-1a6b-77a0-8d37-18ec50c04d17`.
- Planning loop: two bounded read-only rounds completed on 2026-07-28. The
  entropy, grill, and skeptic passes retained Waves 0-9 as one execution unit
  and tightened scope, packaging, sequencing, candidate, and live-cost gates.
- Compatibility decision: no backward compatibility is required. Migrate
  current in-repo callers and delete the old path in the same wave.
- Publication decision: the existing candidate remains evidence for the
  completed provider work but must not be published after this plan starts.
  Refresh and re-review a new candidate after all required waves and gates pass.
- Wave 0 baseline: `output/eval-harness/20260729T014637Z/eval_harness.json`
  selected 23 required rows. The candidate recipe and receipt map are frozen in
  `docs/status/active/forward-only-post-review-cleanup.md` before the first
  implementation commit.
- The existing candidate is superseded for publication. Its immutable evidence
  remains unchanged; Wave 9 must build a new candidate from final source.
- Final recommendation:
  `output/eval-harness/20260729T080334Z/eval_harness.json` selects the same 23
  source-derived rows after the last repairs. The approved live execution
  remains the six-row scoped manifest at
  `output/eval-harness/20260729T041434Z/final/scoped_execution_manifest.json`;
  session-live is explicitly excluded by the locked live envelope.
- Required live proof: all four fixed-prior provider rows plus the Kimi
  open-task and cleanup rows passed. Kimi fixed-prior and cleanup each used the
  single permitted repaired rerun; all other rows passed on attempt one. The
  accepted results contain zero provider failures, privacy leaks, and
  trajectory violations.
- Source reduction: relative to the approved plan commit, tracked cleanup
  source is net more than 3,700 lines smaller and the Python quality baseline
  did not grow.
- Refreshed candidate:
  `output/public-candidate/20260729T082627Z/` was built from source commit
  `5092fdd257d0b386415a4643cf350f750413216c`. Candidate commit
  `172eaf904088fa2dcf704729b8452497fa02ceeb` contains 1,042 reviewed source
  files with membership digest
  `09feb969817b89ea732bd64c13f6d42ea84518a167ec00e80f69b4bbee844b16`.
  Public-surface, pinned secret, non-recursive clean-room, mock, direct product,
  sdist/wheel membership, and isolated-install gates pass. Publication remains
  unauthorized pending a separate human decision.

## Preflight Contract

Preflight status: READY_FOR_REVIEW

Task source: mixed; user request plus the five review sessions listed above.

Canonical source: `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`.

Route: durable `$intuitive-flow` with `$intuitive-refactor` discipline for each
bounded cleanup wave.

Goal: make the current repository and installable runtime express one
forward-only architecture by deleting retired implementations, duplicate
dispatch/strategy owners, false verification surfaces, and compatibility
aliases while preserving the supported product behavior.

Scope:

- Repair current source-of-truth, runnable examples, architecture navigation,
  active-status lifecycle, and the empty pytest regression surface.
- Delete the retired direct-provider implementation, metadata, extras, and
  tests that have no active production caller.
- Move Runtime Map Prior catalog loading/compatibility contracts out of evals
  so product code does not depend on the maintainer eval layer.
- Make eval explicitly repo-owned instead of exposing a partially functional
  installable CLI surface.
- Remove legacy MolmoSpaces `world=molmospaces/val_*` aliases and migrate all
  current callers to source-aware world IDs.
- Replace the `LaunchPlan -> just agent::run -> key=value dict -> positional
  argv` protocol with one typed executor and named backend adapters.
- Move active runtime code that is currently treated as a `scripts.*` library
  into owned `roboclaws` packages; leave scripts only as true one-shot tools or
  thin entrypoints, and delete wrappers that no longer have a caller.
- Make the household-world Skill the generic task-strategy owner, keep kickoff
  prompts run-specific, and keep MCP instructions response-local to state,
  safety, actionability, and immediate recovery.
- Remove the household projection private-symbol forwarding chain without
  mechanically splitting large domain owners.

Non-goals:

- No new product surface, provider profile, backend, MCP tool, artifact schema,
  report schema, simulator feature, or robot behavior.
- No compatibility aliases, deprecated import modules, dual dispatch paths, or
  temporary old/new world-ID acceptance at closeout.
- No bulk rewrite of historical plans, ADRs, retrospectives, or saved output;
  update only current guidance and current tracked fixtures/callers.
- No deletion merely because a file is large. A change must delete, merge,
  canonicalize, or move behavior to its declared owner.
- No broad migration of diagnostic, data-preparation, Isaac, Agibot, or visual
  grounding scripts that are not imported as libraries or reached by a current
  product/eval route.
- No artifact-GC command. The ignored 26 GB local `output/` tree is an operator
  storage concern and adding a new maintenance surface would not simplify the
  tracked architecture.
- No physical robot movement and no acceptance of the Omniverse EULA.

Entity budget: reuse=`LaunchPlan`, the public launch catalog, current backend
specs, `skills/household-world`, Runtime Map Prior Snapshot schemas, existing
eval suites, and existing package/clean-room gates; remove/merge=retired direct
providers, false regression gate, duplicate context/status surfaces, legacy
world aliases, product-to-eval imports, `roboclaws eval`/`agent eval` aliases,
`just agent::run`, positional lowering, active `scripts.*` library imports,
duplicate generic prompt strategy, and private projection facades; new=one
`roboclaws.maps.runtime_prior_catalog` product-contract owner and one typed
`roboclaws.launch.executor` owner, plus focused dependency and documentation
guards; add a distinct execution-envelope type only if Wave 5 proves that
`LaunchPlan` cannot own the lifecycle; expansion triggers=any new public axis,
schema, provider/backend behavior, dependency, persistent compatibility layer,
external publication, or hardware motion requires re-approval.

Context: must-read=this plan, `STATUS.md`, `ARCHITECTURE.md`,
`docs/agents/operating-runbook.md`,
`docs/status/active/architecture-cleanup-campaign.md`,
`docs/plans/2026-07-27-restore-codex-mimo-responses-cells.md`, launch catalog and
plans/executor code, provider registry and retired provider subtree,
Runtime-Prior selection/console consumers, household skill/prompt/MCP response
logic, packaging config, and affected tests; useful=current candidate gate
receipts, `just/README.md`, `docs/human/evaluation.md`, Python quality ratchet,
and focused import/caller searches; avoid-unless-needed=`.planning/**`, shipped
retrospectives, historical plan bodies, broad `output/**`, and unrelated
Isaac/Agibot evidence.

Acceptance:

- SUCCESS: every wave below is complete; current public commands and docs
  resolve; supported direct and SDK product routes pass; the sdist and wheel
  expose only the declared installable runtime; required deterministic,
  package, product, eval, and live gates pass; and a refreshed sanitized
  candidate is ready for a separate human publication decision.
- BLOCKED_NEEDS_DECISION: implementation discovers an active non-test consumer
  for a surface marked for deletion, a required schema/public behavior change
  beyond this plan, or an owner boundary that cannot be resolved with the two
  approved new modules.
- BLOCKED_NEEDS_LOCAL_VALIDATION: a required provider, simulator, package,
  operator-console, or live eval proof cannot run after its guarded preflight.
- INTERMEDIATE_ONLY: none. A partially migrated dispatch, world-ID, provider,
  script-import, or strategy path is not merge-ready.
- No regressions: retain exactly the four current OpenAI Agents SDK provider
  profiles; deterministic direct-runner behavior; Base/Runtime Metric Map and
  Runtime Map Prior Snapshot privacy/contracts; household MCP tools; operator
  console workflows; report/eval artifact schemas; fail-loud dependencies; and
  real-robot safety gates.

Verification: deterministic=`uv sync --extra dev`, `ruff check .`,
`ruff format --check .`, Python quality ratchet, focused unit/contract tests per
wave, then `./scripts/dev/run_pytest_standalone.sh -q`; integration=public
command-resolution/doc guards, dependency-direction guard, eval suites,
package membership, clean-room source install, isolated sdist/wheel installs, and
artifact/privacy scans; product-run=direct-runner map-build and cleanup on the
canonical source-aware MolmoSpaces world plus one SDK cleanup and open-ended
run; local-live-manual=four provider health probes, the bounded four-profile
fixed-prior/map-build-consumer matrix plus the two named Kimi smoke rows with
`live_execution=run`, and operator-console launch/status inspection;
`just dev::network-status` applies only to routes guarded by the runbook;
optional=artifact-size reporting and exploratory additional scene rows only
after all required gates pass.

Execution: main=root owns sequencing, atomic wave boundaries, conflict checks,
live-proof decisions, candidate refresh, and final completion judgment;
worker=none by default; worker-goal=none.

To execute: `/goal execute docs/plans/2026-07-28-forward-only-post-review-cleanup.md with intuitive-flow`

Optional tracking: none.

Approval: `LGTM`, `approve`, or `go ahead` approves this contract, including
the explicit live row/attempt/request ceiling below; edits request revision.

## Locked Architecture Decisions

1. **Forward-only means delete, not deprecate.** Known in-repo callers move in
   the same wave; tests assert the removed path is rejected or absent.
2. **Installable distribution artifacts are product/runtime only.** The wheel
   and sdist exclude `roboclaws.evals` and repo-only eval assets. Eval suites and
   the harness remain Git-checkout-owned through `just agent::eval`; do not
   package them merely to preserve an accidental `roboclaws eval` alias.
3. **Public launch resolution happens once.** A typed plan/execution envelope
   crosses the executor boundary; public and implementation backend IDs remain
   distinct fields rather than repeated `backend=` strings.
4. **Skill owns generic task strategy.** Run context owns the goal, budget,
   selected lane, and episode facts. MCP responses may prescribe the next
   safe/actionable recovery step but do not restate the whole task policy.
5. **Source-aware world IDs are canonical.** Replace `molmospaces/val_N` with
   `molmospaces/procthor-10k-val/N`; do not keep an alias parser.
6. **Runtime Prior consumption is a product/map contract.** Candidate scoring,
   selection reports, and promotion remain eval concerns.
7. **Script directories are not importable architecture layers.** Reusable or
   launched runtime logic belongs under `roboclaws`; one-shot operator tools may
   stay under `scripts` without becoming package APIs.

## What Already Exists

| Need | Existing owner to reuse | Plan treatment |
| --- | --- | --- |
| Public-axis parsing and validation | `roboclaws.launch.catalog` and `LaunchPlan` | Keep; remove the second private parse/lowering path. |
| Agent-engine/provider profile truth | `roboclaws.agents.provider_registry` and `roboclaws.launch.agent_engines` | Keep the four SDK profiles; delete direct-provider-only fields. |
| Runtime Map Prior artifact schema | `roboclaws.maps.runtime_prior_snapshot` | Keep unchanged; add only the missing product catalog owner beside it. |
| Eval selection and grading | `roboclaws.evals` plus repo suite JSON | Keep repo-owned; stop presenting it as an installable runtime CLI. |
| Household strategy | `skills/household-world/SKILL.md` | Deepen as the sole generic strategy owner. |
| Run-specific prompt rendering | `roboclaws.agents.prompts.household_cleanup` | Narrow to facts and per-run constraints; do not replace it with a new prompt framework. |
| MCP state/safety/actionability | `roboclaws.household.household_mcp_server` | Keep response-local guidance; remove duplicated whole-task strategy. |
| Runtime lifecycle and artifacts | Current SDK runner plus `roboclaws.agents` helpers | Move the remaining script-owned runtime into these package owners. |
| Verification | Existing launch, provider, console, eval, household contract, package, and candidate gates | Extend focused guards; do not create a parallel test harness. |

## Target Data Flow

Current launch/runtime flow:

```text
named public axes
  -> launch catalog -> LaunchPlan(argv + canonical fields)
  -> just agent::run
  -> agent_run key=value parsing and route validation
  -> 26 positional values / just molmo::household-world-impl
  -> source-tree live script or direct runtime
  -> artifacts, console state, eval polling
```

Target flow:

```text
named public axes
  -> launch catalog -> typed LaunchPlan
  -> launch.executor
       |-- direct adapter -> household/planner runtime
       `-- SDK adapter    -> packaged live runtime
  -> artifacts, console state, eval polling

Public backend:          mujoco | isaaclab | agibot-gdk
Implementation backend: typed adapter field, never another backend=<value>
```

Target strategy flow:

```text
household-world Skill      run context             MCP response
generic task strategy   +  goal/budget/lane   +   state/safety/next action
          \____________________|_________________________/
                               v
                         SDK agent turn
```

Target dependency direction:

```text
maps.runtime_prior_catalog <- operator_console
            ^
            `---------------- eval selection/promotion

launch catalog -> launch executor -> agents/household/backends
eval harness   -> public product launch/executor + artifact graders
```

The `LaunchPlan` and executor docstrings should retain the short target-flow
diagram if the final implementation has more than one process boundary. Other
modules should prefer normal type/function documentation over duplicated ASCII
comments.

## Failure And Test Model

| Boundary | Realistic failure | Required handling and user-visible result | Primary proof owner |
| --- | --- | --- | --- |
| Current docs/status | Example omits a conditionally required axis or active capsule is terminal | Contract test rejects the tracked source before publication | `tests/contract/dev_tools/test_task_agent_just_recipes.py` and active-status guards |
| Provider deletion | An active health/SDK path still imports retired direct code | Wave 0 caller gate blocks deletion; final import search and provider transport tests fail loudly | `tests/unit/providers/test_provider_catalog.py`, `tests/unit/agents/test_provider_transport.py` |
| Runtime Prior catalog move | Console and eval normalize the same catalog entry differently | One shared loader/classifier returns the same result; malformed/private input remains an actionable error | `tests/unit/evals/test_runtime_prior_selection.py`, `tests/unit/operator_console/test_routes.py` |
| Wheel boundary | Installed runtime accidentally imports repo-only eval assets | Isolated wheel test fails during build; runtime CLI reports only supported product commands | package/clean-room contract tests plus wheel membership inspection |
| World-ID migration | A stale alias reaches a current route or saved current fixture | Resolver rejects it with the exact source-aware replacement; all current sampler rows use canonical IDs | `tests/unit/launch/test_scene_sampler.py`, `test_environment_setup_catalog.py` |
| Typed executor | Adapter receives a valid plan but loses an override, environment field, redaction rule, or exit status | Named envelope validation fails before subprocess creation; terminal error remains visible in status/artifacts | launch unit tests, `tests/contract/dev_tools/test_task_agent_just_recipes.py`, console launcher tests |
| Runtime package move | Eval/readiness expects a deleted script or subprocess cannot import the new package owner | Capability/import preflight gives an actionable error; no silent fallback to the script path | `tests/unit/agents/test_live_runtime.py`, eval identity tests, open-ended artifact gate |
| Strategy consolidation | Prompt loses a required safety/completion rule or conflicts with MCP state | Deterministic responsibility tests plus live eval catch trajectory/completion/privacy regression | `tests/unit/agents/test_household_cleanup_prompts.py`, household MCP contracts, four-profile live matrix |
| Projection facade removal | Direct-import migration changes monkeypatch ownership or leaks private map truth | Focused contract/privacy tests fail; no fallback alias is added | `tests/contract/molmo_cleanup/test_household_runtime_contract.py`, `test_household_mcp_server.py` |

No boundary above may fail silently. A missing package, invalid envelope,
unsupported alias, malformed catalog, or unavailable live dependency must
produce an actionable error and nonzero status.

## Wave Dependencies

```text
Wave 0 inventory
  -> Wave 1 current truth
       |-- Wave 2 provider deletion -----------.
       |-- Wave 3 product/eval boundary -------+-> Wave 5 typed executor
       `-- Wave 4 source-aware worlds ---------'        |
                                                  v
                                           Wave 6 runtime package move
                                                  |
                                                  v
                                           Wave 7 strategy owner
                                                  |
                                                  v
                                           Wave 8 projection facade
                                                  |
                                                  v
                                           Wave 9 full proof/candidate
```

Waves 2-4 are logically independent after Wave 1, but execution defaults to
sequential in the shared checkout because they overlap provider/launch/eval
tests and current docs. Do not create parallel worktrees or delegate workers
unless the human explicitly changes the execution contract.

## Execution Waves

### Wave 0 - Baseline And Ownership Inventory

- Record the exact current import/caller graph for every deletion and move.
- Record public command traces and focused test baselines before changing
  lowering, world IDs, prompt strategy, or runner ownership.
- Freeze the current-source absence-guard set as `README.md`, `ARCHITECTURE.md`,
  `STATUS.md`, `docs/human/**`, `docs/agents/**`, `skills/**`, `just/**`,
  `roboclaws/**`, `tests/**`, `evals/**`, and tracked current fixtures. Exclude
  `.planning/**`, historical plan/ADR/retrospective bodies, archived status,
  and ignored output unless they present a current runnable command.
- Run
  `just agent::eval recommend plan=docs/plans/2026-07-28-forward-only-post-review-cleanup.md budget=focused`
  and preserve its selected deterministic/live gates as a baseline snapshot,
  not the final post-migration matrix.
- Recover and freeze, verbatim, the previously reviewed candidate recipe:
  candidate build/source/output command; membership, secret, private-value,
  import, current-example, package, and artifact scans; clean-room setup;
  sdist/wheel build, inspection, and isolated installs; deterministic/product
  gates; and the expected receipt path for each command. Use the current
  candidate evidence, builder/CI recipes, and prior execution session as the
  sources. Do not start implementation if the recipe or receipt map remains
  ambiguous.
- Mark the existing public candidate superseded-for-publication once the first
  implementation commit lands. Do not modify its immutable evidence directory.

Gate: no target may be deleted while an unexplained active non-test caller
remains, and no implementation commit may land until the candidate recipe and
receipt map are reproducible.

### Wave 1 - Current Truth And False Gates

- Add explicit `provider_profile` values to every current SDK example and state
  the conditional grammar: required for `openai-agents-sdk`, forbidden for
  `direct-runner`.
- Replace nonexistent `realworld_contract.py` and `realworld_cleanup.py`
  architecture navigation with actual owners.
- Mechanically classify every `docs/status/active/*.md` capsule, but mutate only
  capsules with an explicit terminal status. Archive terminal capsules with
  unique proof/rationale under `docs/retrospectives/`; delete only duplicate or
  pointer-only terminal capsules. Leave active, blocked, ambiguous, and evidence
  JSON surfaces untouched, then update `STATUS.md` and guard active state plus
  current runnable commands.
- Merge any unique durable vocabulary from unreferenced `CONTEXT.md` into
  `docs/human/domain.md`, `docs/agents/domain.md`, or `ARCHITECTURE.md`, then
  delete `CONTEXT.md`.
- Remove the empty pytest `regression` layer from `pyproject.toml`,
  `tests/conftest.py`, `tests/README.md`, and `just dev::test`. Preserve the
  distinct eval suite/promotion concepts named `smoke_regression` and
  `eval-regression`.
- Add focused tests that parse current public documentation examples and fail
  when `active/` contains terminal state.

Gate: all current examples resolve, current navigation paths exist, and no
documented pytest command exits 5 because it selects zero tests.

### Wave 2 - Retired Direct-Provider Deletion

- Delete `roboclaws/core/provider_factory.py`, `provider_runtime.py`,
  `provider_safety.py`, `provider_retry.py`, and `roboclaws/core/providers/**`.
- Delete their provider-only unit tests and migrate any genuinely shared parser
  or error behavior only if Wave 0 finds an active caller.
- Remove `direct_provider_adapter`, `direct_required_env_keys`, and their
  helpers/entries from `roboclaws.agents.provider_registry`.
- Remove the obsolete `anthropic` and `openai` optional extras and `instructor`
  dependency surface after confirming active SDK/provider-health imports remain
  satisfied by their actual owners; update `uv.lock`.
- Add absence/caller guards so tests cannot keep the retired stack alive again.

Gate: no active import, metadata field, dependency extra, test, or current doc
names the removed direct-provider API; all four SDK profiles still resolve and
their deterministic transport tests pass. Stop rather than removing `openai`
or another dependency still required by the SDK runtime or provider health.

### Wave 3 - Product/Eval Boundary And Wheel Contract

- Create `roboclaws.maps.runtime_prior_catalog` as the owner of catalog schema,
  loading, normalization, compatibility/staleness classification, and
  auto-enable decisions.
- Migrate operator console and eval selection/promotion to that owner. Keep
  candidate scoring, reports, and promotion orchestration under `roboclaws.evals`.
- Remove product-to-eval imports and add a static dependency-direction test.
- Make `just agent::eval` invoke the repo eval CLI directly. Remove the
  `roboclaws.cli.main eval` and `agent eval` aliases.
- Retain `roboclaws.evals`, `evals/**`, and eval skill/catalog/harness assets in
  the Git checkout only. Exclude them from both wheel and sdist after all product
  imports are gone.
- Build and inspect both artifacts, install each in isolation, prove product
  imports/CLI work, and prove eval imports/assets and the `roboclaws eval`,
  top-level `eval`, and `roboclaws agent eval` aliases are absent. Keep the
  actionable Git-checkout-only explanation in source documentation.

Gate: `operator_console` imports no `roboclaws.evals`; sdist/wheel behavior
matches the documented product/runtime scope; repo-native eval suites still
pass from the Git checkout.

### Wave 4 - Source-Aware MolmoSpaces World IDs

- Replace current `molmospaces/val_N` IDs with
  `molmospaces/procthor-10k-val/N` in world specs, defaults, scene sampler,
  console/catalog state, current docs, skills, tests, and tracked current
  fixtures/artifacts.
- Delete `legacy_molmospaces_world_ids`, alias tables, alias parsing branches,
  and migration wording.
- Keep historical plan/retrospective prose unchanged unless it is presented as
  a current runnable command.
- Add negative tests proving legacy IDs fail with an actionable source-aware
  replacement and positive tests for every current sampler row.

Gate: current tracked code/docs/tests contain no live alias caller; default and
explicit source-aware worlds resolve and complete the deterministic product
proof.

### Wave 5 - One Typed Launch Executor

- Extend `LaunchPlan` with the smallest typed/named execution data needed by
  adapters; do not add a second parallel plan type unless the resolved plan and
  execution envelope have materially different lifecycles.
- Add one `roboclaws.launch.executor` owner with a closed typed backend/runner
  dispatch table. Do not add a dynamic/general plugin registry.
- Migrate direct-runner map-build, cleanup, open-ended, and planner-proof first;
  then migrate all SDK household intents.
- Remove duplicate public/private route validation, repeated public and
  implementation `backend=` keys, hard-coded redaction indexes, and the 26-item
  positional lowering protocol.
- Migrate console and eval product runners to execute the resolved plan rather
  than reconstruct public commands.
- Remove `just agent::run` and `roboclaws.cli.agent_run` after the final caller
  moves. Keep `just run::surface` as the thin public facade.
- Remove inactive OpenClaw product-dispatch/rerun lowering that generates a
  public command the catalog rejects. Preserve separately guarded Gateway
  lifecycle/maintainer commands; do not revive OpenClaw as an active product
  engine.

Gate: one public parse produces one typed plan and one executor dispatch; all
current routes retain named trace/redaction behavior and no test relies on
argument order.

### Wave 6 - Move Active Runtime Out Of `scripts`

- Inventory modules under `scripts/` that are imported by tests, reached by the
  typed executor, or used by eval readiness as runtime identities.
- Move the active OpenAI Agents household runner and its reusable lifecycle,
  status, budget, metrics, and subprocess helpers under the appropriate
  `roboclaws.agents` / `roboclaws.household` owners.
- Move other current reusable script-library modules only when the inventory
  proves an active import/API role. Keep genuine one-shot operational tools in
  `scripts`.
- Migrate tests and patch targets to package APIs. Delete old wrappers rather
  than preserving import aliases.
- Make eval readiness inspect package/runtime capabilities instead of checking
  for `scripts/molmo_cleanup/run_live_openai_agents_household.py`.

Gate: product/eval execution and readiness do not launch or identify a
source-tree script path; migrated product owners and their tests do not import
`scripts.*`. Tests for retained one-shot operator, diagnostic, data-preparation,
Isaac, Agibot, or visual-grounding tools may still import those script modules.
Remaining scripts are independently executable tools, not hidden production
packages.

### Wave 7 - Single Strategy Owner

- Diff the household-world Skill, kickoff prompt constants/renderers, and MCP
  response instructions by responsibility.
- Move generic search, sweep, cleanup ordering, completion, and recovery policy
  into `skills/household-world/SKILL.md`.
- Reduce kickoff prompts to run identity, operator goal, selected evidence lane,
  budgets, required artifacts, and episode-specific facts.
- Keep MCP response instructions only when derived from the current response:
  safety blocker, required next tool, actionability state, or bounded immediate
  recovery. Remove whole-task restatements.
- Remove the rule that kickoff text generically overrides canonical Skill
  strategy; explicit operator task and public safety/tool responses remain
  authoritative.
- Add responsibility-level prompt/response contract tests instead of snapshotting
  duplicated paragraphs.

Gate: generic strategy has one owner and all required deterministic prompt/MCP,
privacy, trajectory, and completion tests pass. Run the bounded live matrix once
in Wave 9 after the projection cleanup rather than paying for a duplicate Wave 7
matrix.

### Wave 8 - Household Projection Facade Cleanup

- Select the existing fixture-projection or projection module as the owner for
  each helper currently forwarded through private assignments.
- Replace `_name = other_module._name` facade chains with direct calls/imports
  from the canonical owner and migrate test patch sites.
- Delete aliases and facade-only code after all callers move.
- Do not split `HouseholdRuntimeContract` solely to reduce line count; extract
  only when a helper obtains a clear independent state/lifecycle contract
  already required by this plan.

Gate: no multi-hop private-symbol forwarding chain remains, focused household
map/Agent View/privacy tests pass, and the quality ratchet does not regress.

### Wave 9 - Full Proof And Candidate Refresh

- Run all deterministic, package, clean-room, product, eval, provider-health,
  live, artifact, privacy, and operator-console gates from the preflight.
- Regenerate `just agent::eval recommend ...` from final source, resolve every
  artifact dependency to a nonempty final path, and freeze the final manifest
  before any live row runs.
- Run live gates under the exact envelope below. Any permitted post-repair
  rerun is a new recorded attempt under the repository live-verification policy.
- Refresh the sanitized public candidate from the final verified source; scan
  membership, secrets, internal identifiers, imports, runnable examples,
  package contents, and emitted artifacts by replaying the Wave 0 frozen recipe
  into a new candidate/receipt root. Any required recipe change stops for plan
  contract review.
- Update `README.md`, `ARCHITECTURE.md`, `STATUS.md`, human docs, and a
  retrospective to the final architecture. Mark this plan Implemented only
  after every required gate passes.
- Present the new immutable candidate evidence for a separate human publication
  decision. This plan does not authorize publication.

## Required Commands And Proof Matrix

Start with:

```bash
uv sync --extra dev
just agent::eval recommend plan=docs/plans/2026-07-28-forward-only-post-review-cleanup.md budget=focused
```

Per-wave deterministic minimum:

```bash
ruff check .
ruff format --check .
.venv/bin/python scripts/dev/check_python_quality_ratchet.py
./scripts/dev/run_pytest_standalone.sh -q <focused-test-paths>
git diff --check
```

Final deterministic and repo-native eval gates:

```bash
./scripts/dev/run_pytest_standalone.sh -q
just agent::verify mock
just agent::eval suite=smoke_regression budget=smoke
just agent::eval suite=open_ended_goals budget=smoke
just agent::eval suite=map_build_quality budget=smoke
just agent::eval suite=map_consumer_no_prior budget=smoke
```

Final direct product gates use the canonical source-aware world:

```bash
just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=map-build agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino scenario_setup=baseline seed=7
just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=cleanup agent_engine=direct-runner evidence_lane=world-public-labels scenario_setup=relocate-cleanup-related-objects seed=7
```

Ordinary OpenAI Agents SDK routes use their provider readiness and health
preflights; `just dev::network-status` is required only for OpenClaw,
`just chat::run`, OpenClaw local/integration gates, and system-provider Claude
Code routes named by the runbook. Require one health probe for each of:

```text
codex-responses
mimo-responses
minimax-responses
kimi-openai-chat
```

Use the current
`just dev::model-provider-health agents-sdk --probe <profile> --require-all`
grammar, with no probe retry.

The required live eval rows are exactly the four catalog rows named
`map-build-consumer-openai-agents-sdk-<profile>` plus
`openai-agents-sdk-cleanup-live-eval` and
`openai-agents-sdk-open-task-live-eval`. The four fixed-prior rows each run the
two tracked `map_consumer_fixed_prior` samples against the same explicit,
nonempty, frozen, read-only Runtime Map Prior Snapshot. The two additional rows
run the tracked Kimi smoke manifests: three cleanup trials and three open-ended
samples. This provides cleanup and open-ended coverage on every profile plus
the broader representative Kimi samples.

Freeze `max_parallel=1`, `ROBOCLAWS_OPENAI_AGENTS_MAX_TURNS=128`,
`ROBOCLAWS_OPENAI_AGENTS_INCOMPLETE_TURN_CONTINUATION_ATTEMPTS=0`, and
`ROBOCLAWS_OPENAI_AGENTS_MODEL_SERVICE_RETRY_ATTEMPTS=0`. Run one initial
attempt per row. After a code/config repair, rerun only the failed row at most
once; never rerun a passing row, and stop on the first systemic provider
failure. The initial envelope is 14 trials and at most 1,792 model-service
attempts plus four one-request health probes. A single permitted rerun of a
largest three-trial row raises the hard ceiling to 2,176 model-service attempts
plus the four health probes. Stop for approval before adding profiles, rows,
samples, trials, concurrency, continuations, model retries, or further reruns.
Record actual request counts and provider-reported cost when available.

If a required route is unavailable, record its readiness/health evidence and
stop at `BLOCKED_NEEDS_LOCAL_VALIDATION`; deterministic substitution is not
completion.

## Completion Checklist

- [x] Current docs contain no broken SDK example or nonexistent owner path.
- [x] Explicitly terminal capsules are absent from `docs/status/active/` without
      deleting active/blocked/ambiguous work; `CONTEXT.md` and the empty pytest
      regression surface are gone.
- [x] Retired direct-provider code, metadata, extras, tests, and dependencies
      are gone.
- [x] Product code does not import eval; Git checkout, sdist, and wheel scopes
      are explicit and tested.
- [x] Legacy `molmospaces/val_*` world IDs are rejected and absent from current
      callers.
- [x] Public launch resolution lowers once through a typed executor; private
      string/positional dispatch is gone.
- [x] Product/eval runtime code is imported from `roboclaws`, not `scripts`.
- [x] Generic household strategy has one Skill owner; prompt and MCP response
      responsibilities are narrow and tested.
- [x] Household projection helpers have one direct owner without private facade
      chains.
- [x] Source size/owner count is net lower, no compatibility layer was added,
      and the Python quality baseline did not grow.
- [x] Full deterministic, product, package, eval, live, privacy, and candidate
      gates pass.
- [x] Refreshed candidate is presented for human review; publication remains
      unauthorized.
