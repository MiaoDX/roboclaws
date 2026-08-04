---
plan_scope: eval-evolution-agent-sdk
status: PLANNING_LOOP_REVIEWED
created: 2026-08-04
last_reviewed: 2026-08-04
implementation_allowed: false
source:
  - user request for a formal Skill and MCP optimization capability
  - user requirement that all live optimization use OpenAI Agents SDK, never Codex CLI
  - agent-planning-loop entropy, docs-grill, and skeptic review on 2026-08-04
related_context:
  - STATUS.md
  - ARCHITECTURE.md
  - docs/human/evaluation.md
  - docs/human/mcp-skills-and-semantic-profiles.md
  - docs/plans/2026-06-14-eval-driven-architecture.md
  - docs/plans/2026-06-22-agent-view-module-refactor.md
  - docs/plans/2026-08-03-agent-skill-delivery-eval.md
  - docs/adr/0140-use-eval-suites-as-first-class-architecture-layer.md
  - docs/adr/0141-use-eval-harness-as-maintainer-orchestration-facade.md
historical_evidence:
  - git show 9049b7c5^:docs/harness-self-improvement-loop.md
---

# Eval Evolution With OpenAI Agents SDK

## Goal

Create a formal, bounded R&D capability that uses evaluation evidence to improve
Roboclaws Skills and the existing MCP capability surface without weakening the
agent's general intelligence or allowing the optimizer to rewrite its own
measurement system.

The optimizer and the robot under test are separate OpenAI Agents SDK Agents:

```text
Evolution Campaign
  -> Optimizer Agent (`agents.Agent` / `Runner`)
  -> structured hypothesis and isolated candidate patch
  -> deterministic candidate gates
  -> frozen candidate identity
  -> paired training eval matrix (Robot Agent via OpenAI Agents SDK)
  -> quality-first selection
  -> one sealed holdout confirmation
  -> human-approved promotion
```

A Codex-family model may be selected through the existing
`provider_profile=codex-responses` route. It is a model/provider choice, not an
agent engine. This plan must not add or invoke `codex-cli`, `codex exec`, a TUI,
app-server, or a bare-host Codex process.

## Why Now

Roboclaws already has most of the measurement and delivery foundations:

- `just agent::eval` is the sole maintainer eval facade;
- `roboclaws.evals` owns suites, trials, graders, repetition, failure classes,
  reports, and reviewed regression promotion;
- current selector/promotion code demonstrates hard-gates-first ranking,
  content-addressed identity, and explicit maintainer approval;
- provider registry, Agents SDK tracing, model settings, retry policy, usage,
  and restricted Skill delivery already exist;
- Agent View is now a stable public evidence boundary, so the parked
  Eval-To-Evolution follow-up has a concrete target;
- the April 2026 self-improvement loop showed material gains, but its tmux/TUI,
  CLI, shell-script, and Markdown-log implementation predates the current
  architecture and must not be restored.

Historical evidence remains useful: one-variable iterations moved the navigator
task from 127+ tool calls and 3/9 targets to 37 calls and 9/9 targets; the Skill
rewrite produced the largest coverage gain; and a real simulator run exposed a
physics bug that fake tests missed.

## Decisions

1. The capability name is **Eval Evolution**.
2. `roboclaws.evals` owns the control plane. There is no second harness, product
   launch axis, or independent report system.
3. Both optimizer proposal generation and robot trials use
   `agent_engine=openai-agents-sdk`. They record separate roles and identities.
4. `static-full` remains the Skill baseline. `no-skill` is a negative control
   that may diagnose Skill regressions but can never be promoted by this loop.
5. A campaign targets exactly one kind of change. Skill and MCP changes cannot
   be mixed in one candidate or iteration.
6. Candidate generation never mutates the main checkout. Only a separately
   approved promotion command may apply an accepted patch, and it does not
   commit, change defaults, or publish a baseline.
7. Quality, privacy, checker, trajectory, and terminal-evidence gates are
   authoritative. Calls, tokens, cost, and latency rank only eligible
   candidates.
8. Only one training winner reaches the sealed holdout. Holdout output never
   returns to the optimizer, and holdout failure ends the campaign.
9. The existing restricted `sandbox-skills` runtime is not generalized into
   the optimizer. V1 uses a standard Agents SDK Agent with narrow host-owned
   tools. A dedicated SandboxAgent backend is optional later and must preserve
   the same semantic boundary.

## Non-Goals

- No Codex CLI, Claude Code, tmux/TUI automation, or historical harness revival.
- No multi-agent proposer/judge debate in V1.
- No optimizer access to raw eval definitions, grader/checker code, private
  truth, holdout identity, provider secrets, or promotion policy.
- No automatic commits, PRs, default changes, baseline/catalog publication, or
  regression-corpus mutation.
- No public MCP tool add/remove/rename, capability-profile change, public launch
  axis, physical safety behavior change, or real-robot movement.
- No claim that one scene or one successful run proves general improvement.
- No generic framework extraction from the map-specific selector or canonical
  prior promoter. Reuse their policy shape, not their domain code.

## Architecture

### Maintainer Facade

Extend the existing command without adding a second control plane:

```bash
just agent::eval evolve \
  campaign=<campaign.json> \
  live_execution=run

just agent::eval evolve-promote \
  report=<selection-report.json> \
  manifest=<maintainer-approved.json>
```

Do not expose `optimizer_agent_engine`; it is invariantly
`openai-agents-sdk`. The campaign selects only an existing optimizer
`provider_profile`, with `codex-responses` as the recommended initial profile.

### Ownership

```text
roboclaws.evals
  campaign parsing, budgets, iteration state, sanitized feedback
  candidate validation/materialization, train/holdout orchestration
  selection report and promotion verification

roboclaws.agents
  reusable OpenAI Agents SDK provider/model/tracing/usage mechanics
  narrow optimizer Agent adapter and tool surface

existing eval suites and graders
  authoritative product quality and privacy evidence

skills/eval-evolution
  maintainer workflow, campaign preparation, evidence review, stop rules

skills/cloudml-eval-ops
  unchanged remote placement, submission, monitoring, and collection
```

`roboclaws.evals.runner` remains a thin dispatcher. Evolution mechanics belong
in focused modules rather than accumulating in the runner.

## Trust Boundary

### Optimizer View

The optimizer must never receive an `eval_sample`, raw run directory, raw
provider log, grader config, or selection manifest. The trusted orchestrator
projects a versioned `eval_evolution_feedback_v1` packet containing only:

- campaign and public target identity/digests;
- the current allowlisted Skill or MCP description source;
- public MCP schema and public Agent View/tool-trace evidence needed to reason;
- sanitized categorical failure class and approved public explanation;
- aggregate quality status and work/usage metrics;
- prior candidate hypothesis, patch digest, and accepted/rejected status;
- remaining optimizer/candidate/token/time budget.

An explicit forbidden-key and content validator must reject private goal
references, hidden targets, acceptable destinations, generated mess identity,
scenario setup secrets, grader/checker internals, selection thresholds, holdout
references, credentials, endpoints, and host paths before every optimizer call.

### Optimizer Tools

The Agents SDK optimizer receives only narrow function tools:

- read the single declared evolution target and approved public supporting
  context;
- read the current sanitized feedback packet;
- submit one schema-validated hypothesis and candidate patch.

It receives no shell, generic filesystem, git, network fetch, patch-application,
eval-launch, commit, or publication tool. The host owns validation, application,
tests, eval launch, and artifact writing.

### Candidate Workspace

For every candidate the host must:

1. verify the baseline commit and target digest;
2. create a fresh ignored workspace under
   `output/eval-evolution/<campaign-id>/candidates/by-sha256/<digest>/` as a
   complete baseline source snapshot, not a patch-only overlay;
3. reject absolute paths, traversal, symlinks, unexpected files, binary diffs,
   oversized diffs, and writes outside the campaign allowlist;
4. reject changes to `roboclaws/evals/**`, `evals/**`, graders, checkers,
   holdout definitions, private truth, manifests, provider configuration,
   promotion policy, launch axes, credentials, and the main checkout;
5. apply the patch only inside the candidate workspace;
6. record the exact patch, parent identity, target kind, mutable paths, digest,
   optimizer identity/usage, gates, eval identity, and terminal status.

The trusted candidate materializer owned by
`roboclaws.evals.evolution_candidates` creates the snapshot and supplies its
root to deterministic gates and product trials. Those consumers must not
reconstruct or apply the candidate patch themselves. Candidate identity is
content-addressed and immutable after gates begin.

## Target Classes

### Skill Campaign

V1 supports one declared `skills/<name>/SKILL.md` per campaign. The optimizer may
rewrite the Skill body within campaign byte/diff limits. It may not edit
`skill.json`, scripts, examples, other Skills, product prompts, MCP code, or eval
policy in the same candidate.

This is the first complete vertical slice because Skill text is inert input;
host validation plus product eval can safely exercise it without executing
optimizer-authored Python.

### MCP Description Campaign

The next slice supports descriptions/docstrings and declared public schema text
for existing MCP tools. An AST/token validator must prove that the delta changes
only allowlisted string literals associated with the selected existing tools.

It cannot add, remove, rename, wrap, reorder, or redirect tools; change imports,
decorators, signatures, control flow, defaults, validators, capability profiles,
or response fields; or introduce dynamic string evaluation.

### MCP Behavior And Projection Campaign

The full product goal includes improving existing-tool public response
projections and bounded validation/recovery behavior. It is gated because a
path allowlist does not stop optimizer-authored Python from reading process
environment or repository files.

Before any such candidate receives a live eval, prove a candidate execution
boundary with malicious fixtures:

- candidate MCP process receives no provider credentials or unrelated secrets;
- grader, checker, eval definitions, private truth, holdout, repo outputs, and
  host configuration are unreadable, not merely omitted from prompts;
- candidate cannot mutate the main checkout or durable artifacts;
- live Agent provider credentials remain in a separate trusted process;
- candidate sees only approved public runtime assets and atomic MCP traffic;
- private-leak, path traversal, symlink, `/proc`, environment, subprocess,
  network, and filesystem probes fail closed;
- the same boundary is available on the chosen local or CloudML placement.

Until this proof passes, the optimizer may produce MCP behavior proposals and
run deterministic static/tests review, but live execution and promotion remain
`blocked_by_candidate_isolation`. Do not silently substitute a broader shell,
same-process execution, or a different provider.

## Campaign Contract

Add an `eval_evolution_campaign_v1` manifest. The trusted maintainer-authored
manifest freezes:

- campaign id, target kind/id, mutable path allowlist, baseline commit and
  target digest;
- optimizer provider/profile/model/settings and robot provider/profile/model;
- declared training suites, samples/scenes, seeds, repetitions, and an
  orchestrator-only sealed holdout reference;
- deterministic gates, authoritative quality gates, ranking metrics, baseline
  identity, paired-comparison policy, and a mandatory minimum-improvement rule;
- optimizer turn, candidate, live-trial, provider-concurrency, token, cost,
  wall-time, timeout, and retry ceilings;
- SDK/dependency versions, product tool surface, grader/checker versions,
  execution placement, image/runtime identity, and artifact schemas;
- sanitized-feedback schema/version and the exact optimizer-visible function
  tool-surface digest;
- candidate path/diff limits and the required promotion policy.

Campaign policy is immutable after the first optimizer call. Infrastructure
retries use the existing classified-attempt rules; behavior/provider failures
do not retry. Budget exhaustion produces `inconclusive`, never a candidate
quality failure.

Recommended promotion-capable defaults:

- at most 3 sequential candidates, one hypothesis/target kind per candidate;
- at most 2 optimizer revision turns before each candidate is frozen;
- at least 3 training scenes with 3 paired repetitions per baseline/candidate;
- exactly one finalist on at least 2 unseen holdout scenes with 3 paired
  repetitions;
- provider concurrency at most 2 for quality/work comparison and at most 1 when
  latency is a ranking metric;
- automatic retry disabled; at most one new attempt for a classified
  infrastructure/preemption failure;
- explicit token, cost, and wall-time ceilings are required; there is no hidden
  default that can spend provider budget.

An implementation smoke campaign may use one candidate, two training scenes
with one repetition, and one holdout scene with one repetition. It proves the
workflow only and is never promotion-capable.

## Selection And Holdout

Training comparisons are paired: baseline and candidate use identical suite,
sample/scene, seed, repetition, prompt/goal, provider/model/settings, MCP tool
surface, grader/checker versions, budgets, and execution placement.

Selection order:

1. reject missing identity, incomplete evidence, privacy leak, checker failure,
   trajectory violation, terminal-contract failure, or product-quality
   regression;
2. require the campaign's declared multi-scene quality threshold;
3. require improvement over the paired baseline on at least one frozen primary
   objective by its campaign-authored threshold, while preserving every
   authoritative quality gate; a neutral rewrite is not an improvement;
4. among eligible candidates, rank paired model/tool calls, tokens, cost, and
   calibrated latency according to the frozen policy;
5. select at most one training winner;
6. resolve and run the sealed holdout once in the trusted orchestrator;
7. accept only if holdout quality gates pass and the frozen minimum-improvement
   rule still holds without a declared regression.

The primary objective may be a quality margin or an eligible efficiency metric,
but it and its threshold are frozen before the first optimizer call. If no
candidate satisfies the rule, terminate as `no_improving_candidate`; do not run
the holdout or promote a merely different patch.

Holdout sample identities, manifests, private truth, artifacts, and detailed
failure diagnostics remain invisible to the optimizer before and after the
run. A failed, blocked, or inconclusive holdout ends the campaign and cannot
trigger another adaptive iteration.

Every persisted optimizer feedback packet, candidate summary, and selection
report must pass the same forbidden-key/privacy validator used before optimizer
calls. Privacy validation is an artifact write gate, not only an in-memory API
check.

## Promotion

Add evolution-specific selection and promotion schemas rather than
genericizing map-specific code:

- `eval_evolution_candidate_v1`;
- `eval_evolution_selection_report_v1`;
- `eval_evolution_promotion_manifest_v1`.

Promotion requires `maintainer_approved=true` and binds:

- baseline commit and unchanged target digest;
- candidate patch SHA-256 and materialized candidate digest;
- campaign, training, selector, sealed-holdout, and artifact digests;
- optimizer and robot Agents SDK provider/model/SDK identities;
- exact mutable paths and target kind;
- accepted quality gates and limitations;
- human reviewer identity, review timestamp, or an immutable external review
  reference.

Promotion fails closed on a dirty/mixed target file, stale base, digest
mismatch, missing holdout, non-promotable negative control, or absent approval.
It applies only the reviewed patch to the main checkout. It does not commit,
change a product default, publish a baseline/catalog, or promote regressions.

## Implementation Phases

### Phase 0: Contracts And Threat Model

1. Record the durable Agents-SDK-only, optimizer/private-boundary, sealed
   holdout, and human-promotion decisions in a focused ADR.
2. Add campaign, feedback, candidate, selection, and promotion schemas plus
   strict loaders/validators.
3. Add malicious fixtures for private-key leakage, traversal, symlinks,
   forbidden paths, patch authority, stale identity, and budget exhaustion.
4. Extend `just agent::eval` grammar with `evolve` and `evolve-promote`; default
   execution remains dry/blocked until `live_execution=run` is explicit.

Stop if a sanitized optimizer view cannot be derived without exposing raw eval
or grader-owned data.

### Phase 1: Skill Vertical Slice

1. Implement the OpenAI Agents SDK optimizer adapter using existing provider
   registry, model settings, tracing, retry, and usage owners.
2. Expose only the narrow read-target/read-feedback/submit-candidate tools.
3. Materialize content-addressed candidate workspaces and validate Skill-only
   patches.
4. Run deterministic gates before any live provider call.
5. Execute paired training suites, quality-first selection, one sealed holdout,
   and the explicit human promotion path.
6. Add `skills/eval-evolution/SKILL.md` and maintainer documentation.

Stop without promotion if the bounded live proof does not preserve every
authoritative quality gate and beat the paired `static-full` baseline by the
frozen minimum-improvement rule.

### Phase 2: MCP Description Slice

1. Add exact target identity for existing public MCP tool descriptions/schema
   strings.
2. Implement AST/token delta validation and adversarial fixtures.
3. Reuse the Phase 1 campaign, selection, holdout, and promotion flow without a
   new result schema or runner.
4. Verify that `codex-cli` remains rejected and the public tool set/signatures
   are byte/structurally unchanged outside approved descriptions.

Stop before live execution if the validator cannot prove a text-only delta.

### Phase 3: MCP Behavior Isolation Gate

1. Design and prove a separate credential-scrubbed, private-data-isolated
   candidate MCP runtime while the trusted Agents SDK process retains provider
   access.
2. Run malicious candidates against every stated denial boundary locally and
   on the selected remote placement.
3. Only after that proof, allow declared existing-tool response projection and
   bounded validation/recovery candidates into paired live evals.
4. Keep public tool additions/removals/renames and physical safety changes out
   of scope for this plan.

If no suitable isolation backend exists on CloudML, record the phase as
blocked; Skill and MCP-description evolution remain valid shipped capability.

### Phase 4: End-To-End Proof And Closeout

1. Run one bounded Skill smoke campaign end to end with optimizer and robot
   identities both recorded as OpenAI Agents SDK.
2. Run one MCP-description campaign through deterministic and live gates when
   provider/runtime preflight permits.
3. Run MCP behavior live proof only if Phase 3 isolation passed.
4. Verify rejected/inconclusive campaigns leave the worktree and durable
   artifacts unchanged.
5. Run focused tests, repo-wide Ruff/format, standalone pytest, and the
   diff-selected `just agent::eval recommend|execute` gates.
6. Update human evaluation/Skill-first MCP docs and archive the active capsule.

## Acceptance Criteria

- Contract tests prove `codex-cli` remains unsupported and both optimizer and
  robot live roles use `openai-agents-sdk` with distinct identities.
- Optimizer-visible feedback passes the forbidden-key/privacy validator; raw
  private eval data and sealed holdout data are never exposed.
- Traversal, symlink, shell, git, credential, `/proc`, network, repository
  output, eval/grader/checker, private-truth, and unauthorized-write probes fail
  closed at the boundary relevant to each target class.
- Every candidate records hypothesis, target kind, parent identity, exact patch,
  mutable paths, digest, provider/model/SDK identity, usage, gates, eval
  identities, and terminal status.
- A campaign cannot mix Skill and MCP changes, mutate its frozen policy, or
  modify the main checkout during generation/evaluation.
- Deterministic gates run before paid live trials.
- Baseline/candidate comparisons are paired and multi-scene for any promotion
  claim.
- Quality/privacy/checker/trajectory gates dominate efficiency ranking.
- A neutral candidate cannot reach holdout or promotion; one frozen primary
  objective must meet its paired minimum-improvement threshold.
- Only one training winner reaches holdout, and holdout never feeds another
  optimization iteration.
- `no-skill` cannot be selected or promoted.
- Promotion requires an accepted report, a digest-bound
  `maintainer_approved=true` manifest, unchanged source identity, and a clean
  target file; promotion applies no unrelated edits and creates no commit.
- Failed, blocked, or inconclusive campaigns leave defaults, baselines,
  catalogs, regression samples, and public MCP surfaces unchanged.
- At least one bounded live Skill campaign completes through the Agents SDK
  optimizer and Agents SDK robot runner before the capability is called usable.

## Verification

Focused deterministic gates should include:

```bash
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/evals \
  tests/unit/agents \
  tests/contract/dev_tools/test_eval_just_recipe.py \
  tests/contract/dev_tools/test_backend_catalog_just_recipes.py

ruff check .
ruff format --check .
```

Standard repo gate:

```bash
just agent::verify
./scripts/dev/run_pytest_standalone.sh -q
```

Live proof uses a frozen campaign manifest and existing provider/runtime
preflights. CloudML execution, when selected, follows
`skills/cloudml-eval-ops/SKILL.md`; no local/provider substitution is allowed
after freeze.

## Stop Gates And Review Decisions

Stop and request human review before:

- expanding provider, cost, concurrency, workspace, hardware, or remote
  placement beyond the frozen campaign;
- adding/removing/renaming public MCP tools or changing capability profiles,
  launch axes, physical safety behavior, or real-robot authority;
- weakening an isolation, privacy, checker, trajectory, or quality gate;
- applying a selected patch, changing defaults, or publishing durable evidence.

Implementation defaults that do not require another product decision:

- optimizer provider defaults to `codex-responses` but remains selectable among
  existing Agents SDK provider profiles;
- human-only promotion and terminal holdout failure;
- V1 ships Skill evolution first, then MCP description evolution;
- MCP behavior live execution stays gated on proven candidate isolation;
- campaign-local target identity is sufficient; do not add `evolution_target`
  to every generic EvalResult until multiple independent consumers demand it.

## Rejected Or Parked

- **Rejected:** restore the April harness, Codex CLI comparison adapter,
  tmux/TUI control, shell-script run numbering, or manual Markdown logbook.
- **Rejected:** make SandboxAgent/Docker a mandatory V1 dependency or loosen the
  existing restricted `sandbox-skills` capability list.
- **Rejected:** genericize Runtime Map Prior selection/promotion code.
- **Rejected:** let the optimizer define graders, thresholds, selection policy,
  holdout, retries, or promotion.
- **Parked:** proposer ensembles, judge agents, debate, automatic PRs/commits,
  regression promotion, default switching, and baseline publication.
- **Parked:** global capability-slice row taxonomy and generic
  `evolution_target` fields until campaign-local identity proves insufficient.

## New-Window Handoff

After human approval, start a fresh implementation window with:

```text
Implement docs/plans/2026-08-04-eval-evolution-agent-sdk.md through
$intuitive-flow. Preserve the full phased scope and stop gates. Start at Phase
0, use OpenAI Agents SDK for the optimizer and robot trials, and do not add or
invoke Codex CLI. Do not run MCP behavior candidates live until Phase 3's
malicious isolation proof passes. Use an active capsule and commit each phase
separately after its required gates.
```
