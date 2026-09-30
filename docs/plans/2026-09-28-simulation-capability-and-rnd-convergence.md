# Simulation Capability And R&D Convergence

**Status:** Active — implementation in progress; acceptance incomplete.
**Created:** 2026-09-28
**Last reviewed:** 2026-09-30
**Current implementation contract:** Existing SDK/MuJoCo/DINO contracts remain in force until migrated by this plan. Approved target: one product Skill delivery, three provider routes, fixed initiative state ownership, and a cross-scene visual cleanup milestone.
**Related ADRs:** [0136](../adr/0136-use-base-metric-map-and-first-class-household-launch-contracts.md), [0138](../adr/0138-use-detector-only-visual-grounding-sidecar.md), [0140](../adr/0140-use-eval-suites-as-first-class-architecture-layer.md), [0145](../adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md).
**Supersedes:** Future provider/Skill matrix and acceptance priorities in [model/CI alignment](2026-09-04-eval-baseline-model-and-ci-alignment.md) and [Skill delivery evaluation](2026-08-03-agent-skill-delivery-eval.md), only where explicitly changed below. Historical results and their original acceptance decisions remain intact.
**Implementation state owner:** `docs/status/active/simulation-capability-and-rnd-convergence.md` (create when execution begins; do not create parallel state in GSD).
**Execution checkpoint (2026-09-30):** Phase 1 ownership and the frozen visual case manifest are established. The active provider/catalog and console-default slices, deterministic repository gate, and strict visual producer fixes are landed. MiniMax real-DINO artifacts cover all 15 frozen case identities, and post-fix scene 10/11/13 replays are strict-checker clean. The capability acceptance remains open: the MiniMax first-attempt threshold is not met, MiMo Responses real-DINO smoke is incomplete, MiMo TP compatibility is 2/3 with one blocked row, and active provider migration is complete across catalog, eval rows, suites, and maintained launch documentation; historical route identities remain readable. The active capsule owns current evidence and next actions; historical artifacts remain immutable.

## Charter

Turn the next 6–8 weeks of development toward repeatable embodied-agent capability in simulation. First reduce the maintained delivery/provider combinations and conflicting progress records; then improve and measure one loop: visual discovery → navigation and reobservation → cleanup → outcome verification across household scenes.

The initial planning review is complete and implementation now proceeds under this contract. The original review-only restrictions applied to that planning round; they do not block the approved implementation and in-scope live verification. The main session owns this file and judges remaining acceptance gaps. Routine implementation defaults do not reopen settled choices. Material provider, resource, credential, privacy, publication, or real-robot changes still stop at the boundaries below.

## Why Work Has Felt Like Patching

The evidence supports a convergence problem, not a lack of all capability or all comparison testing:

- Five Skill delivery cells and multiple provider routes multiply readiness, prompt, artifact and matrix maintenance. They have not established a repeatable cross-scene advantage that justifies five product implementations.
- Comparisons continued after August: September 5 compared all five cells on Kimi, September 25 passed all five on MiniMax, and September 27/28 produced both blocked attempts and successful targeted reruns. Those are useful compatibility observations, mostly one scene/seed with public world labels; across-date model/content changes prevent a clean causal Skill ranking. See [baseline refresh](../status/active/local-eval-baseline-refresh.md) and `output/eval-harness/20260905T104543Z/`, `20260925T060604Z/`, `20260927T081341Z/`, `20260927T132336Z/` under the same output root.
- Real DINO already completed a visual cleanup loop in scene 0: direct 5/5 and SDK 4/5 with real CUDA provenance. This is a foundation to generalize, not proof of multi-scene reliability. See [DINO cleanup capability](2026-08-31-camera-grounded-dino-cleanup-capability.md).
- Progress ownership moves between plans, capsules and GSD. Old blocked narratives survive next to newer passing evidence, obscuring what currently prevents the capability milestone. The historical full packet remains 26 passed / 0 failed / 3 blocked even after later targeted checks pass.
- Hosted showcase rows currently use `world-public-labels`; hosted CI has no provisioned real DINO runtime. A green provider workflow alone cannot establish visual discovery.

Measure progress by newly reliable capability cases and resolved failure classes, with repeatability and provider identity attached. Deleting branches and increasing test counts are supporting work, not the product milestone.

## Approved Decisions

| Area | Target contract |
| --- | --- |
| Skill product path | `static-full` only; internal rendering/routing helpers may remain where used by this path. No selectable dynamic delivery variants. |
| Skill control | `no-skill` is an explicit eval-only control, outside daily required matrices. Use for Skill/core-runtime investigations and occasional regression comparisons. |
| Retired Skill paths | Remove executable `dynamic-full`, `dynamic-routed`, `sandbox-skills`, their dedicated launch/readiness/test paths and unused dependencies. Preserve historical identity/report reading and independent Eval Evolution isolation. |
| Local development | CLI and operator console default to `mimo-responses`. Explicitly supplied supported profiles override the default. No provider fallback. |
| Active routes | Exactly `mimo-responses`, `minimax-responses`, `mimo-tp-openai-chat`. Preserve current supported model contracts; this is not another model-version migration. |
| External validation | MiniMax is mandatory primary capability validation. MiMo Token Plan is mandatory CI compatibility validation. |
| Retired providers | Remove current Kimi/Qwen executable support, selections, readiness, CI rows, dedicated tests and current guidance. Keep Git history, historical evidence/readers and credential-name redaction. |
| CI trigger boundary | Ordinary PRs require deterministic checks. Provider live gates run on trusted main, schedule and manual workflows. This latest approved split supersedes the earlier proposal to require two live providers on each related PR. |
| Provider failure | Quota/service/credential/runtime failure produces `BLOCKED`, never a passing acceptance. Preserve valid passes and rerun only affected items when their evidence identity still matches. |
| State ownership | One fixed `docs/status/active/<slug>.md` record per initiative throughout its lifetime, including GSD. Plans own scope/design/acceptance; GSD owns execution structure/evidence; `STATUS.md` owns priorities and links. |
| Capability direction | Simulation first. Real robot work is deliberately on hold. MapBuild enables the visual cleanup loop; open-ended goals remain regression coverage. |
| Cleanup investment | No artificial two-day or one-week cap. Clean up what is necessary for these decisions and capability delivery; unrelated platform rewrites are outside scope. |

The local default is a launch convenience, not an implicit eval treatment. Every eval/CI row must resolve and record an explicit provider; a missing required route/configuration fails with an actionable error. MiMo Responses still requires its existing endpoint/key/model triple. DINO can supply text observation candidates to text-only routes; this plan does not assert MiMo raw-image support.

## Scope And Architecture Ownership

| Owning layer | Existing seam to change | Boundary |
| --- | --- | --- |
| Agent Skill / SDK driver | `roboclaws/agents/skill_delivery.py`, `roboclaws/agents/drivers/openai_agents_live.py`, sandbox delivery/probe modules, `skills/household-world/`, relevant prompt tests | One rendered product Skill; strategy and recovery live here, not in the server. Audit actual Skill content paths before edits. |
| Engine / provider profiles | `roboclaws/core/provider_catalog.py`, provider registry/readiness/model modules and SDK client construction | Three runnable routes; preserve current identity, privacy and transport contracts. Historical identifiers cannot become executable routes. |
| Runnable surfaces / console | `roboclaws/launch/agent_engines.py`, `roboclaws/launch/catalog.py`, `roboclaws/operator_console/workflows.py` and frontend launch metadata | One source for the local product default; both front doors consume it. Eval launch requests provide their own explicit profiles. |
| Eval suites / harness | `roboclaws/evals/{runner,session_live,trial_execution}.py`, `roboclaws/evals/harness/`, `skills/eval-harness/catalog/rows.json`, existing suite specs and graders | Purposeful matrices, explicit execution identity, multiscene cases, complete outcome evidence. Reuse current artifact/report contracts. |
| CI / showcase | `.github/workflows/ci.yml`, `.github/workflows/showcase.yml`, `config/showcase-manifest.json`, `roboclaws/evals/showcase*.py` | Deterministic PR gate; trusted external live gates; honest world-label versus real-DINO proof boundary. |
| MCP / backend primitives | Existing public observe/navigation/map/pick/place/done contracts and MuJoCo adapter | Fix proven failures in the loop; preserve public/private separation and thin server ownership. No new task orchestration layer. |
| Project documentation | `AGENTS.md`, `STATUS.md`, `docs/status/active/README.md`, `docs/agents/operating-runbook.md`, architecture/human docs, current GSD pointers | Fixed state owner; one current conclusion linked to immutable attempts. No second project-management system. |

During implementation, record these durable contract changes in a short ADR and link it here; allocate its number from the then-current ADR directory. Do not create a second plan in that ADR.

## Implementation Sequence

The complete scope is phases 1–5 below. Phases are dependency boundaries, not separate proposals requiring repeated approval. After phase 1 establishes ownership and inventory, Skill and provider changes may proceed independently with distinct file owners; converge before matrix migration. CI wiring and capability case preparation may overlap after their contracts are fixed. Capability acceptance depends on all required proof, not on a cleanup deadline.

### 1. Establish Ownership And Freeze The New Contract

1. Create the initiative capsule at the path above. It owns current work state (`planned`, `active`, `blocked`, `done`, `parked`), verification state (`not-run`, `partial`, `passed`, `failed`, `blocked`), current conclusion, next action, evidence references, and stop/resume conditions. These dimensions must not be collapsed into a single green/red badge.
2. Change the stage-based rules in AGENTS/runbook/status README to fixed initiative ownership. GSD STATE links to that capsule for initiative status and retains its own execution cursor and phase evidence. Plans contain the contract and review decisions, not another running progress narrative.
3. Keep the capsule path stable on completion/parking, containing a short terminal conclusion, evidence links and resume conditions. Update `docs/status/active/README.md` and its closure template, which currently says to delete/archive task files, so this stable-owner rule is unambiguous; if long narrative moves to a retrospective, leave a stable link/redirect and no competing live owner at the destination.
4. Inventory and reconcile these initial records: `docs/status/active/local-eval-baseline-refresh.md`, `docs/status/active/state-first-context-manager.md`, `docs/status/active/skill-delivery-multiscene-probe.md`, the camera-grounded DINO/MapBuild records, and stale `.planning/STATE.md` pointers. Resolve current conclusions from cited evidence; mark each current/historical/retired disposition explicitly. Do not bulk-migrate every old capsule. The quota-blocked historical Kimi comparison remains historical/incomplete; record that its old acceptance requirement is superseded for the new target, rather than rerunning a retired provider or rewriting that packet as passing.
5. Trim `STATUS.md` to current priorities, active initiative links, next action and real blockers. Real robots are parked, and unavailable retired providers are not blockers for the new scope. Preserve historical reports through existing links.
6. Inventory executable versus historical readers before deleting Skill/provider branches. Identify callers, fixtures, manifests, CLI/UI options, SDK imports, extras, and report/regrade validation. Freeze the new matrix epoch and capability case contract before collecting replacement evidence.

Exit: one state owner and a traceable mapping from each current priority to its plan/evidence; explicit current/historical boundaries; no duplicated manually maintained initiative status in GSD or plans. Check linked paths and a small representative handoff/closure example; add automated structure checks only if an existing mechanism can cheaply enforce this invariant.

### 2. Collapse Skill Delivery And Provider Support

**Skill changes**

- Keep `static-full` as the sole product behavior. Remove public delivery-selection choices beyond the product's canonical value; put `no-skill` selection at the eval boundary so product launch cannot silently enter an ablation.
- Retain useful prompt assembly/section helpers internally. Remove callback/SandboxAgent machinery used only by retired delivery modes, sandbox readiness probes and dedicated executable tests.
- Fix the no-skill kickoff text that still says “Use the bundled household-world skill instructions.” Its task, tool descriptions and MCP guidance remain available; document exactly what is withheld (Skill body/index). Keep parity in paired cases except that intended treatment.
- Separate historical identity validation from active execution validation. Report/regrade may recognize all former delivery IDs; CLI/runtime dispatch rejects the three retired modes. Exercise retained old artifacts through the reader, not through an old live adapter.
- Remove the `openai-agents[docker]` extra and resulting lock entries only after proving there are no remaining consumers. After removal, run `uv sync --extra dev`, import/readiness checks and a residual-reference scan; remove sandbox-specific tests only after no imports remain. Eval Evolution's candidate subprocess/UID/network isolation is independent and stays intact. The shared Skill-cell validator currently serves active dispatch and historical regrade (`roboclaws/agents/skill_delivery.py`, `roboclaws/evals/runner.py`); split those responsibilities before deletion and test both directions: old identities remain readable, while active launch/environment dispatch rejects retired IDs without importing sandbox runtime.

**Provider changes**

- Use the provider catalog as the single owner of the local product default; remove Kimi hardcoding in console metadata and migrate CLI/UI callers. Keep lower-level eval rows explicit so this convenience cannot leak into CI or change comparisons.
- Remove active Kimi/Qwen registrations, adapters/readiness and model overrides that only serve those providers. Audit `roboclaws/agents/model_matrix_benchmark.py`, `roboclaws/agents/drivers/openai_agents_profile_runtime.py`, `openai_agents_run_config.py`, `openai_agents_provider_runtime.py`, `roboclaws/agents/thinking_policy.py`, `roboclaws/household/apple2apple_test_grid.py`, `roboclaws/evals/showcase.py`, `config/showcase-manifest.json`, plus catalog/launch/readiness seams. Migrate current in-repo examples/manifests and tests. Preserve generic client/runtime utilities used by the three supported routes.
- Migrate active guidance and matrix docs in the same change: `docs/human/model-matrix.md`, `docs/agents/operating-runbook.md`, `docs/human/evaluation.md`, `docs/human/contributing.md`, current selector/catalog manifests, and workflow documentation. Add a post-change scan that rejects retired IDs in active executable/docs surfaces while allowing historical reports and readers.
- Keep minimal read-only historical provider/model identity and redaction of old credential names. Do not keep a generic factory capable of launching retired routes as a compatibility bridge.
- Preserve current model selections and environment-owned private wire identity. No silent fallback when MiMo Responses is unavailable locally; allow the operator to explicitly choose another supported route.

Exit: product launches reject retired Skill/provider inputs actionably; omitted local CLI and console profiles both resolve to MiMo Responses; eval rows name a supported profile explicitly and never inherit the local default; active Kimi/Qwen registrations and rows are absent by catalog/selector checks; old reports still parse/regrade without importing retired engines; static-full and no-skill controls preserve public/private input boundaries; Evolution isolation tests continue to pass.

### 3. Rebuild Purposeful Matrices And CI Gates

Reuse the current harness catalog, selectors, completion reports and showcase runner. Avoid a second CI-specific eval engine or evidence store. Reversion to an old report reader must never re-enable an execution row.

| Context | Required proof | Placement and limits |
| --- | --- | --- |
| Ordinary PR | Standard deterministic gate plus affected identity, launch, selector, historical-reader and workflow tests | Untrusted PRs receive no live secrets; never `pull_request_target` executing contributor code. |
| Local development | MiMo Responses for iteration; affected deterministic tests | Existing local workstation; usage/cost recorded even when effectively free. |
| Trusted main / manual small live gate | MiniMax primary compact capability cases; MiMo TP compact compatibility cases, including tool calls, completion and artifact identity | External providers only; explicit profiles, static-full, hosted CPU/world-label evidence. A main result governs capability acceptance, not retroactive PR merging. |
| Scheduled full external regression | Identical versioned multiscene case set for MiniMax and MiMo TP, plus current open-ended/MapBuild regression scope | Full set, same seeds/graders/budgets and world-label lane on the existing hosted runtime. Do not call this visual proof. |
| Local visual milestone gate | Real DINO discovery → navigation/reobservation → cleanup → verification, with MiniMax primary full multiscene proof and MiMo Responses local-default smoke | Existing MuJoCo/DINO GPU workstation; `camera-grounded-labels`, actual CUDA detector provenance, one visual runtime at a time. |
| Explicit Skill control | Paired static-full/no-skill on identical supported provider/cases | Requested for Skill/core runtime effects or periodic analysis; absent from everyday required baseline. |

Implementation tasks:

1. Migrate profile selection (`baseline-core`, `baseline-live-default`, `baseline-refresh`, `baseline-ci`, adaptive) and row manifests together. Keep deterministic profiles deterministic, place no-skill only in an explicit opt-in selection, and remove obsolete providers/delivery modes from recommendations as well as execution. Do not hardcode current row counts as a goal.
2. Define small/full case lists explicitly in the existing manifests. The full external manifest must freeze exact case IDs, seeds, suite/epoch, grader, lane and provider pairing before execution. MiniMax and MiMo TP share a common multiscene cleanup case set for comparison; MapBuild/open-ended rows are explicitly marked common or provider-specific, with the current manifest mismatch resolved before acceptance. Initial small-gate default: one representative cleanup case per external provider and one open-ended tool-use case per provider; preserve separate row outcomes. DINO-specific cases cannot be silently relabeled as world-label successes.
3. Use the existing trusted showcase workflow for provider execution and extend its main/schedule/manual routing as needed. Define trusted events/refs exactly: protected `main` push or schedule on the default protected branch, and manual dispatch only when the selected ref is that protected branch (or an equivalent server-side protected-ref check); never expose provider secrets to fork/untrusted contributor code. Keep ordinary deterministic CI separate; avoid running duplicate provider matrices from both workflows. Current showcase publication is not a prerequisite for live validation, and failure must not publish a misleading success artifact. Keep immutable per-case `PASS`/`FAIL`/`BLOCKED` outcomes: small smoke gates require every expected case to pass; full cohorts require every expected case to be accounted for, zero `BLOCKED`/`not_run`, frozen aggregate and per-scene/reserved thresholds (at least one successful case per scene), and explicit reporting of any allowed behavioral failures. Repair/test mixed passed+blocked aggregation in the existing showcase path; never relabel failures as passes to satisfy a cohort threshold.
4. Select secrets per provider shard; no MiMo Responses internal environment in hosted workflows. Maximum two external provider shards concurrently. Before enabling the scheduled full gate, calculate setup/provisioning, selected case caps, and evidence-upload margin against the workflow deadline; measure representative runtimes; then freeze provider-call, token and total-runtime envelopes and fit the sharding plan within those bounds. Do not silently truncate full coverage or inherit incompatible one-case budgets. Retain the existing 60-minute per-shard timeout only if that calculation passes; material aggregate cost/resource expansion follows the stop condition. A missing provider/configuration is a local product readiness hard error, an eval row `BLOCKED` with a typed reason such as `model_or_provider_unavailable`, and a trusted workflow failure/non-success required check; it must never become a skipped green result.
5. Preserve `PASS`, `FAIL`, `BLOCKED` distinctions in authoritative artifacts even if GitHub exposes only success/failure. Any missing required item keeps capability acceptance incomplete. Deterministic PR merging does not imply milestone acceptance.
6. Retain all attempt histories. A targeted replacement is eligible only for the same code/content, suite epoch, scene/seed, grader, provider/model, evidence lane, map/prior identity and budget. If any relevant identity changed, rerun the affected cohort instead of stitching incompatible passes. Aggregate current acceptance via existing report/capsule references; the old full packet remains unchanged.
7. No automatic trial reruns or best-of retries. Existing bounded transport retry remains separately reported; quota stays non-retryable. Behavioral failures cannot be replaced by a later success in the same acceptance cohort; a behavior repair creates a new affected cohort/version. Infrastructure-blocked attempts remain separate, and exact-identity reruns may complete missing capability evidence. Report original first-attempt reliability separately from completed capability-case success; never present a repaired/rerun outcome as the original attempt passing. Durable baseline/catalog promotion remains a separate human decision.

Exit: trigger/secret policy is covered deterministically; both small external shards run under the trusted workflow; scheduled full lists match across providers; selectors contain no retired executable cells; local DINO gate has a distinct, required evidence reference. A green world-label workflow cannot close the visual milestone.

### 4. Build And Iterate The Cross-Scene Visual Capability

Start from the already-proven scene-0 loop. Diagnose failures by discovery, map/handle grounding, navigation/reobservation, manipulation, outcome verification, or provider/runtime interruption. Change the smallest owning layer, then rerun the affected cases before broader proof. Avoid starting another provider/platform expansion to explain an unmeasured capability problem.

**Case contract — proposed implementation defaults, not previously approved numerical targets:**

- Three development scenes and two reserved scenes, with three fixed seed/trial cases per scene (15 cases per full provider/lane cohort). Existing scenes 0/10/12 are development candidates subject to current asset/readiness checks. Choose and freeze the two reserved scene IDs before strategy tuning; they are not additional scenes chosen after seeing failures. Before first acceptance, scheduled development regression uses only the frozen development subset for both external providers; the reserved cohort runs at the declared final checkpoint. Once that checkpoint is evaluated, the complete accepted case set may become routine full regression but is no longer claimed as unseen holdout evidence. A later generalization claim requires a new reserved set.
- Each case starts with a valid Base Metric Map and no private movable-object inventory. Build semantic evidence through the existing MapBuild/observation path. Freeze whether the case builds a fresh Runtime Metric Map or consumes a content-addressed prior; never mix the two treatments or reuse movable-object truth from another trial. At least one full end-to-end case per development scene includes fresh MapBuild.
- Every acted-on object must originate from public DINO observations and an actionable public handle. Trace evidence includes discovery, navigation/reobservation, cleanup actions and authoritative completion. The grader may inspect private truth; neither Skill nor planner may consume it.
- Reuse the current five-object case acceptance where applicable: at least four grounded successful cleanup chains, at least 90% sweep coverage, no more than two disturbances, and authoritative successful `done`. Validate fixture feasibility before freezing the cases; change the contract/epoch before tuning if a scene cannot support it.
- Initial milestone threshold: at least 12/15 successful first attempts overall and 5/6 on reserved cases for MiniMax with real DINO. Also report each scene's numerator/denominator and failure class; overall success must not hide a scene with zero successful trials. These are bounded engineering acceptance thresholds, not a statistical claim about all homes.
- MiMo Responses must pass one representative real-DINO case per development scene using the product default. MiMo TP's required proof is the small/full external compatibility matrix above; image-native parity is not implied. Scheduled full external cohorts each use the same 15 cases and acceptance thresholds for their own world-label lane, separately from visual results.
- Open-ended goals remain an explicit regression row family and MapBuild quality remains a prerequisite; neither becomes a second new product milestone. Use existing suite/schema/grader extensions only where a measurable case is missing.

The executor records these defaults, exact scenes/seeds, fixture readiness, run/token/time caps and existing resource envelope before live collection. Resolve ordinary fixture choices in implementation; seek a new decision only if the target capability, acceptance standard, cost/resource class, or privacy boundary must materially change. No new cloud/GPU provisioning is part of this plan.

Development cases may drive strategy fixes. Reserved cases are a final check; if their failures are inspected to tune behavior, label them development evidence and freeze a new reserved set/version before claiming reserved-scene generalization. Do not build a new holdout service; reuse existing eval controls where appropriate and record access honestly.

Exit: reproducible case manifest, real-DINO MiniMax full cohort meeting the frozen acceptance, MiMo Responses development smoke, both external required gates, MapBuild/open-ended regression evidence, and per-case failures/usage/latency reported without hiding blocked denominators.

### 5. Close The Initiative With A Usable Capability Packet

1. The capsule links the frozen contract, code identity, run manifests, first-attempt outcomes, grader results, per-scene/provider/lane metrics, cost/latency and unresolved limits. Report original execution first-attempt reliability and completed capability-case success as separate fields. Use existing local JSON/Markdown reports and optional Opik projection, not a new dashboard/schema.
2. Work can be implemented while verification is blocked; report that distinction. Do not mark the initiative accepted/done until required new-contract evidence is complete. Missing required provider or real-DINO proof is not waived by deterministic tests or legacy evidence.
3. Update the global dashboard to the delivered capability and next measured bottleneck. Close/supersede relevant old active work with evidence and resume conditions; preserve every original failure/block. Park real robots with their existing operator/readiness prerequisites for a future explicit return.
4. Hand off a runnable public launch example, an exact replay command from the actual run artifact, and the current remaining failure classes. Baseline publication/promotion, real-robot motion and new resource expansion are separate decisions.

## Verification Contract

Plan/diff selection should begin with the repository facade:

```bash
just agent::eval recommend plan=docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md budget=focused
just agent::eval execute plan=docs/plans/2026-09-28-simulation-capability-and-rnd-convergence.md budget=focused
```

`recommend` is read-only gate selection, not implementation or live proof. The planning-time selection at `output/eval-harness/20260928T094641Z/eval_harness.{json,md}` selected 19 rows and still surfaced legacy Kimi/retired-cell rows; that is expected evidence for phase 2/3 migration, not an acceptance result. After migration, inspect selected row identities before `execute`; focused selection alone cannot satisfy the explicit full-cohort visual and scheduled gates. Current live execution requires `live_execution=run`; exact row-specific commands must be generated from the migrated catalog and retained with the artifacts, not invented as new CLI options in this plan.

| Change | Necessary proof |
| --- | --- |
| Skill retirement | Focused Skill/prompt/driver/eval tests, negative retired-input cases, no-skill content isolation, old-artifact report/regrade sample, existing Evolution isolation checks; paired static-full/no-skill live sample because this phase changes Skill behavior. |
| Providers/defaults | Catalog, model resolution, readiness, SDK payload, CLI/UI default and explicit-override tests; retired route rejection, historical identity/redaction; local MiMo Responses and both external provider live evidence. |
| Matrix / CI | Selector/profile tests, trusted-event and secret boundary checks, matched case lists, missing-provider blocked result, bounded timeout and retry behavior; actual trusted live workflow outputs when execution is authorized. |
| State ownership | Changed docs/links, fixed owner across planning→GSD→closure, current conclusion versus immutable attempts; no status re-expansion in multiple files. |
| Visual capability | Existing public/private boundary, completion/checker and MapBuild tests; real local DINO readiness/provenance and frozen multiscene runs; separately identified world-label compatibility regression. |

Run affected deterministic tests during each change, then the standard repository gate (`just agent::verify`, including its prescribed lint/format/test checks). Use the local `.venv`/`uv` and standalone pytest wrapper per the runbook. Required live proof is part of implementation acceptance. If blocked, capture sanitized readiness/preflight output identifying the provider, missing resource or runtime prerequisite; stop dependent acceptance while retaining completed independent work.

Current execution has moved beyond plan review. Continue with the affected implementation and live proof through the active capsule, preserving exact case identity and separate first-attempt versus repair/replay outcomes. `just agent::verify` is the deterministic repository gate; the frozen MiniMax real-DINO cohort, MiMo Responses development smoke, MiMo TP compatibility gate, MapBuild readiness, and the final capability packet remain required before this plan can move to `Done`. Do not publish a baseline or treat checker-clean repair replays as cohort acceptance.

## Risks And Stop Conditions

- Removing execution support can break old readers if identity validation shares the active catalog. Separate those responsibilities before deleting registrations; avoid a broad compatibility framework.
- A global MiMo default can leak into eval/CI. Require explicit manifest identity and negative tests; no internal endpoint fallback on GitHub.
- Hosted CPU/world-label checks leave a real-DINO proof obligation. Keep that obligation visible and blocked until local evidence exists; do not silently substitute detector stubs or require unapproved infrastructure.
- Provider quotas can delay capability acceptance after code merges. Keep useful implementation progress, retain passed evidence, and resume only compatible missing portions. Never use retired providers to turn the new matrix green.
- Old historical failures and old phase requirements can be mistaken for active blockers. Record explicit supersession and the new acceptance basis; do not manufacture a green old packet.
- Narrow case counts can overfit. Freeze scenes/seeds and report reserved-scene use honestly. Numerical defaults are revisable before collection with rationale; lowering them after failures requires an explicit decision.
- Stop for a material provider/resource/cost expansion, credential change, private-truth exposure, durable baseline/catalog publication or real-robot motion. Ordinary in-scope fixes and repeat attempts under unchanged bounds do not need repeated permission.

Non-goals: new agent engine, new provider, model training or detector bakeoff, raw-FPV provider migration, CloudML resurrection, a new evaluator/observability/project-management platform, universal status-history rewriting, or an arbitrary calendar cap on convergence work.

## Planning Review Ledger

Round 1: entropy, documentation/grill, and skeptic reviews completed. Accepted findings are incorporated above: separate active/historical Skill validation, enumerate Kimi/Qwen residues, assert the MiMo default owner, preserve fixed capsules through closure, define mixed-status cohort acceptance and budget feasibility, protect reserved scenes, separate first-attempt from infrastructure-rerun metrics, and specify trusted refs, case identity, readiness semantics, active-doc migration, and lock verification. No user-review decision was raised.

Round 2: narrowed skeptic follow-up passed with no material blockers after those revisions. Parked as implementation detail: name the canonical case-manifest path and keep cohort-level acceptance status separate from individual row status when the existing showcase aggregation is repaired. No new user decision or scope change is required. All reviewers were read-only; no live providers, simulators, commits, or implementation edits were run.

**Recommended next action:** Continue implementation from the active capsule. Finish the remaining provider/catalog migration outside the console surface, close the required matrix/live proof gaps, and address the capability cases by their recorded failure class. Then update the capsule, global dashboard, and this plan with the final capability packet or the concrete external blocker. Preserve phases 2–5 and all proof/stop gates; do not lower the frozen acceptance thresholds or replace failed first attempts with repair replays.
