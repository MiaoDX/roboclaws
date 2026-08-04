---
plan_scope: agent-skill-delivery-eval
status: DONE_DEFAULT_UNCHANGED_CONFIRMATION_REQUIRED
source:
  - 2026-08-03 cleanup live failure investigation
  - 2026-08-03 agent skill delivery discussion
last_reviewed: 2026-08-04
---

# Agent Skill Delivery Evaluation

## Goal

Repair the known cleanup live-run correctness regressions, then compare four
OpenAI Agents SDK Skill-delivery families under a reproducible eval contract.
Use five experiment cells so delivery mechanism and delivered content are not
confounded.

## Current State

- Runtime correctness and five delivery cells are implemented. Commit
  `b56aa1a7` then removed the duplicated kickoff goal from Agent instructions:
  the Skill remains system-level instructions and the run goal is now sent
  only as user input.
- The post-refactor matrix at `output/eval-harness/20260804T121407Z/` used one
  frozen provider/model (`kimi-openai-chat` / `kimi-k2.7-code`), cleanup seed 7,
  and three serial repetitions per cell. All 15 trials reached terminal run
  evidence; raw checker evidence was used because the harness currently labels
  several checker rejections as `environment_blocked`.
- `no-skill` was the only 3/3 cell and restored 5/5 objects in every trial.
  `static-full` passed 2/3, `dynamic-full` 1/3, `dynamic-routed` 0/3, and the
  accepted Sandbox attempt 2 passed 1/3. The failed trials were behavior/checker
  failures, not provider or infrastructure failures.
- Among passing trials, `no-skill` had a 64/63 median model/tool call count and
  563,122 median input tokens. The two `static-full` passes had a 63/63
  passing-only median and 619,895 median input tokens. These efficiency samples
  are too small to rank independently, but they show no efficiency penalty for
  `no-skill`.
- Sandbox attempt 1 exposed an input-history compatibility bug: the
  camera-grounded history parser tried to JSON-decode `read_selected_skill`
  output. The parser now ignores known non-camera tool outputs while preserving
  strict malformed-camera rejection. Attempt 2 used a sanitized, digest-pinned
  Docker image and passed the isolation contract: network mode `none`, zero
  mounts/path grants, zero sensitive environment variables, only the selected
  Skill materialized, and only `read_selected_skill` exposed. The Sandbox live
  catalog row now also requires provider readiness, so missing credentials fail
  closed before any subprocess can reload local dotenv values.
- This one-scene result challenges `static-full` as the product default, but it
  is not broad enough to remove the Skill globally. The default remains
  unchanged pending a reviewed multi-scene `no-skill` versus `static-full`
  confirmation. `dynamic-full`, `dynamic-routed`, and `sandbox-skills` have no
  promotion case from this matrix. No durable baseline or catalog artifact was
  published.
- The invalid `20260803T023049Z` baseline remains retained as evidence and
  unpublished. The public robot MCP surface remains atomic.

### Post-Refactor Matrix Result

| Cell | Passes | Restoration by trial | Model/tool calls by trial | Passing-only median model/tool | Decision |
| --- | ---: | --- | --- | --- | --- |
| `no-skill` | 3/3 | 1.0, 1.0, 1.0 | 58/57, 68/67, 64/63 | 64 / 63 (`n=3`) | Best observed quality; needs broader confirmation |
| `static-full` | 2/3 | 1.0, 1.0, 0.4 | 57/56, 69/70, 40/40 | 63 / 63 (`n=2`) | Default unchanged, but challenged |
| `dynamic-full` | 1/3 | 0.6, 1.0, 0.6 | 48/47, 61/60, 62/61 | 61 / 60 (`n=1`) | No promotion case |
| `dynamic-routed` | 0/3 | 0.4, 0.0, 0.6 | 47/46, 35/34, 50/50 | n/a | No promotion case |
| `sandbox-skills` | 1/3 | 0.8, 1.0, 0.6 | 61/59, 55/64, 61/59 | 55 / 64 (`n=1`) | Isolation passed; quality remains exploratory |

The pre-refactor baseline at `output/eval-harness/20260803T122000Z/` and
`output/eval-harness/20260803T124500Z/` passed all comparable cells 3/3, but it
duplicated the kickoff goal in instructions and user input and is not the
current prompt contract. Sandbox isolation evidence for the current matrix is
`output/eval-harness/20260804T121407Z/preflight/sandbox-isolation-sanitized.json`.

Official SDK references used for the decision:

- [Agents: dynamic instructions](https://openai.github.io/openai-agents-python/agents/#dynamic-instructions)
- [Sandbox Agents](https://openai.github.io/openai-agents-python/sandbox_agents/)
- [Sandbox Agent concepts](https://openai.github.io/openai-agents-python/sandbox/guide/)

## Scope

### Phase 1: Repair Existing Failures

1. Preserve and verify the current checker/eval fail-closed changes. Product
   checker failure must remain an eval failure, and eval-only flags must not be
   passed into the product checker.
2. Supersede the lifecycle decision in ADR-0134 while retaining its public-only
   evidence boundary. Make `done` terminal-only: it writes terminal artifacts
   exactly once and ends the Robot Run. A premature `done` records a terminal
   incomplete outcome which the checker rejects; it never returns a recovery
   worklist for another Agent turn.
3. Make Agent View readiness the sole pre-terminal completion authority. Add
   one compact, versioned `completion` snapshot under the existing `readiness`
   section. Compute it after every nonterminal atomic MCP response, including
   recoverable errors, and project that same snapshot onto the response and
   public trace with source tool and monotonic response identity. It contains
   public blockers and executable next actions derived from the existing
   contract-owned cleanup worklist; it contains no private evaluator truth.
4. At SDK continuation boundaries, carry forward the latest recorded
   `completion` snapshot and its digest. Do not reconstruct blockers, worklists,
   or scan strategy from trace history or rejected `done` calls. Missing,
   malformed, or stale continuation state fails closed as terminal-incomplete.
   Do not add a cleanup-specific query tool solely to repair Agent memory.
5. Preserve source and generated inspection waypoint identity in actionable
   candidate projections so returned recovery work is executable.
6. Update the household-world Skill so it no longer instructs the Agent to use
   `done` as a closeout probe or to retry `done` after recovery.

### Phase 2: Compare Skill Delivery

Add an eval-only Skill-delivery dimension with four requested families and five
cells. The extra `dynamic-full` control is required to isolate delivery
mechanism from content selection:

| Cell | Contract | Permitted comparison |
| --- | --- | --- |
| `no-skill` | Kickoff and MCP tools only; no household Skill body or index. | Versus `static-full`: effect of adding the frozen current Skill through the static path. |
| `static-full` | Current full `SKILL.md` rendering as a static instructions string. | Current control and default-retention baseline. |
| `dynamic-full` | SDK dynamic instructions callback returning content byte-identical to `static-full` for the same run. | Versus `static-full`: callback delivery mechanism only. |
| `dynamic-routed` | SDK dynamic instructions callback rendering only frozen shared, intent, and evidence-lane guidance. | Versus `dynamic-full`: routed-content ablation only. |
| `sandbox-skills` | Official `SandboxAgent` plus `Skills`, with a minimal read-only Skill bundle and explicit restricted capabilities. | Feasibility, isolation, discovery/load behavior, and exploratory quality only. |

Record the mode, effective instruction/index digest, included bytes and token
estimate, load/materialization events, tool surface, and sandbox posture in
each run artifact.

The comparable primary matrix uses one provider/model, scene, seed set, MCP
surface, checker, budget, and timeout across the first four cells. Only the
declared delivery/content fields may differ. The sandbox row is exploratory
because its base prompt, Skill discovery, and file-reading capabilities change
the model-visible surface; execute and report it, but do not use it to select
the product default.

## Experiment Contract

- Primary lane: `world-public-labels`, matching the current live cleanup
  baseline and the failed fresh proof.
- Primary provider: freeze one CloudML-eligible internal Responses profile and
  resolved model/deployment before manifest creation, without provider fallback.
- Trials: three per cell on the frozen `cleanup.repeated_seed7` sample and
  repetition indices. This is a bounded screening result, not a general claim
  across scenes or seeds.
- Concurrency: at most two active live rows for the selected provider to reduce
  execution time. Interleave cells by repetition using a predetermined balanced
  order. Concurrent wall time is descriptive only and cannot rank candidates.
- Retry: disabled for agent behavior and provider failures. Infrastructure
  retries follow the existing CloudML eval policy and create a new attempt.
- Confirmation: run both `static-full` and the selected non-sandbox candidate
  for three trials on `camera-grounded-labels`; if `static-full` is selected,
  this is one three-trial cell. Do not run a full DINO five-cell matrix unless
  the primary result leaves the decision unresolved and a new cost review
  authorizes it.
- Metrics: pass@k/pass^k, terminal outcome, restored/accepted counts, pending
  work, `done` calls, model calls, tool calls, redundant observations/actions,
  prompt bytes/tokens, wall time, provider failures, and policy violations.
- Freeze in the scoped manifest: suite/sample versions, scene and seed,
  repetition indices, prompt and goal hash, MCP profile and complete tool
  surface, provider profile, resolved model/deployment and settings, budgets,
  timeout, checker/grader versions, SDK version, dependency identities, CloudML
  image digest, row count, attempt policy, concurrency, and total cost ceiling.
- Record per row under existing eval trial/runtime artifacts: requested delivery
  cell, effective instruction digest per model call, content/index digest,
  bytes and token estimate, callback/load/materialization events, complete
  model-visible tool surface, SDK version, and sandbox posture. Do not create a
  second top-level result schema solely for this experiment.

## Sandbox Safety Contract

- Sandbox delivery is eval-only and cannot become the product default from this
  plan.
- Materialize only the selected Skill bundle. Do not expose the repository,
  run outputs, private evaluation, host configuration, or arbitrary mounts.
- Disable sandbox network. Use an explicit capability list rather than
  `SandboxAgent` defaults.
- The official `Skills` capability needs a narrowly isolated read path for the
  model to open the materialized Skill. Use an explicit capability list; do not
  enable general shell access or SDK default capabilities. Prove with
  deterministic negative tests that no network, credentials, host files, repo,
  run outputs, or private grader data are reachable before a live sandbox row.
- If the selected provider or CloudML worker cannot support the isolated
  official SandboxAgent path, record the row as blocked. Do not substitute a
  broader local shell or another provider.

## Non-Goals

- No `transport_object`, `clean_observed_object`, or other public composite MCP
  tool.
- No new public launch axis; Skill delivery remains an eval/runtime experiment
  until a later reviewed promotion decision.
- No physical robot movement, provider fallback, durable baseline publication,
  canonical Runtime Map Prior promotion, or broad prompt rewrite.
- No claim that three repetitions of one frozen sample establish statistical
  superiority or generalization. A full baseline refresh remains the reviewed
  follow-up after a delivery mode is selected.

## Entity Budget

- Reuse: current live runner, Agent View/worklist owner, MCP trace, eval suite,
  harness row schema, CloudML sharding, and existing Skill source.
- Remove/merge: remove `done` recovery semantics and stale Skill instructions;
  do not add a second cleanup strategy owner.
- New: one closed eval-only delivery-cell field within existing runtime identity;
  one scoped comparison report only if existing eval result projections cannot
  express the matrix.
- Expansion trigger: public launch-axis changes, public MCP tools, general
  shell access, a second provider matrix, all-mode DINO runs, or baseline
  publication require separate review.

## Acceptance

- Deterministic and focused contract gates pass for checker ownership, terminal
  `done`, pre-terminal readiness, candidate waypoint identity, instruction
  delivery, sandbox isolation, and eval result fail-closed behavior.
- A premature `done` terminates once as incomplete; an exhausted SDK turn with
  no `done` fails explicitly. Neither path can enter a rejected-`done`
  continuation loop or be recovered into an eval pass.
- The `static-full` primary cell runs first as the fresh three-trial Phase 1
  live proof. Only a 3/3 result with complete terminal evidence and zero
  lifecycle, policy, product-checker, or provider failures opens the remaining
  matrix. Reuse these trials as the matrix control when the frozen identity and
  CloudML image digest are unchanged.
- Every matrix cell has complete identity and terminal evidence; blocked cells
  remain blocked rather than passing through artifact recovery.
- Promotion eligibility requires `pass^3`, zero policy/privacy/lifecycle/product
  or provider failures, and no worse restored/accepted/pending-work outcome in
  any paired trial. Among eligible candidates, rank unnecessary model/tool work
  before prompt size; require directionally consistent work reduction in at
  least two of three pairs plus a better median. Wall time is not a promotion
  metric for concurrently executed rows.
- Only `static-full` versus `dynamic-full`, and `dynamic-full` versus
  `dynamic-routed`, support causal mechanism/content claims. Other comparisons
  are descriptive. Sandbox cannot win promotion in this plan.
- The selected candidate and `static-full` control pass camera-grounded
  confirmation before any default-change recommendation.
- Results are presented for human review before changing the default delivery
  mode or publishing a durable baseline.

## Verification

Deterministic:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
```

Selection and product proof:

```bash
just agent::eval recommend \
  plan=docs/plans/2026-08-03-agent-skill-delivery-eval.md \
  budget=focused
```

Run the focused product/live rows through the frozen CloudML scoped-manifest
workflow when provider placement supports it. Use local execution only for
rows that the existing provider contract requires to remain local; do not move
rows merely to obtain a favorable result. A full baseline refresh is a later
step after human selection of the delivery mode.

## Stop Gates

- Stop for a public MCP or launch-contract expansion, sandbox access beyond the
  narrow Skill bundle, provider/cost expansion, private-data exposure, or
  publication request.
- Stop after Phase 1 if deterministic or fresh live evidence still shows a
  correctness failure; do not compare delivery modes on a broken lifecycle.
- Stop inconclusive if `static-full` fails, evidence identity is incomplete,
  correctness differs adversely, or workload signals conflict. Do not add
  trials, providers, scenes, or cost without review.
- Stop after the primary matrix when one non-sandbox candidate wins the quality
  gate clearly. Run only that candidate and the `static-full` control through
  camera-grounded confirmation.

## Implementation Defaults

- The compact completion snapshot is projected after every nonterminal tool
  response, not only observation responses or continuation boundaries.
- SDK continuation serializes the latest canonical snapshot; it may add SDK
  budget telemetry but owns no cleanup policy or worklist derivation.
- Sandbox capability readiness is a deterministic preflight. If the available
  CloudML worker cannot meet the isolation contract, record the row blocked;
  do not broaden access or substitute another provider.
