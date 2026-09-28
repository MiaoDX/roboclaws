# Local baseline failure fixes

Status: ACTIVE. Owner: root intuitive-flow session. Latest intent: implement
the five known issues and rerun corresponding proof. Source: the user-approved
diagnosis and `local-eval-baseline-refresh.md`; original evidence remains at
`output/eval-harness/20260927T081341Z/`.

Proven causes:

- Prior matching discarded the number in "Generated exploration candidate 5",
  selected all seven rooms, and stopped after observing the first. Target
  Query independently stripped numbers and ranked the already observed wrong
  candidate first. Public identity constraints now precede semantic ranking.
- MiniMax resolved the drink query after only one waypoint, observed the other
  six, then called `done` without resolving again. The grader correctly saw
  the stale `exhausted_public_search_budget=false`. Resolving against the saved
  final map returns `not_found` with exhaustion true. Skill and continuation
  instructions now explicitly require fresh final resolution before `done`.
- Kickoff instructions mentioned Codex's household namespace while the Skill
  used `roboclaws__*`; the SDK actually exposes unprefixed names. The failing
  model called nonexistent `household__metric_map`. Both instruction sources
  now use the exposed names; no runtime alias or grader relaxation was added.
- MiniMax's HTTP 500 body explicitly reported Token Plan exhaustion (2056).
  The classifier treated it as transient and retried. The specific quota
  message now wins over generic server-error classification.
- MiMo TP's 42nd model request stalled beyond 180s, after 41 successes. The
  original trace does not establish whether the cause was upstream or network.
  A successful recheck would establish availability, not a repaired root cause.

Accepted scope and proof:

- Preserve numbered public target identity in prior selection and target-query
  matching. Regression tests plus the original direct area-inspection eval.
- Require a fresh final target resolution after negative-search observations
  in the household skill and continuation instructions; original MiniMax drink
  sample must pass without weakening the grader.
- Remove conflicting legacy tool namespaces from active kickoff/skill text;
  recheck original MiniMax dynamic-full cleanup and tool-surface contracts.
- Classify explicit Token Plan quota exhaustion as non-retryable quota rather
  than HTTP 500 transient failure; test classification and retry behavior,
  and recheck MiniMax sandbox trial when provider readiness permits.
- Recheck original MiMo TP cleanup stall using the unchanged bounded timeout.
  Do not infer a local repair from a transient stall or substitute providers.

Current slice: implementation is in place; corresponding live proof is in
progress. No workers or competing task owners. The numbered-target original
sample and the three-sample direct open-ended smoke suite pass in
`output/evals/baseline-fixes/household_world_open_ended_goals/` (stamps
`numbered-target-attempt1` and `direct-open-ended-regression`). Numbered matching,
stale fixture recovery, provider retry, prompt delivery, and continuation tests
pass. Whole-repo Ruff lint/format checks pass.

Live proof: `mimo-tp-cleanup-attempt1` is running under
`output/evals/baseline-fixes/household_world_map_consumer_fixed_prior/`, with the
original provider and unchanged 180s stall timeout. No live-trial retries.
Provider probe passes MiMo TP but MiniMax still returns HTTP 500 with the
explicit Token Plan usage limit (2056). MiniMax behavior proof remains blocked;
the repaired classification is tested as non-retryable quota. Preserve this
distinction from actual goal behavior acceptance.

Verification: repo `.venv`, standalone pytest wrapper, Ruff, then sample-sharded
eval CLI runs using the canonical prior, original providers, new output dirs,
and no live-trial retries. Live quota/availability must be recorded explicitly.

Stop condition: accepted fixes verified or a fresh external blocker prevents
remaining live proof. No baseline promotion, cloud tasks, private-truth hints,
credential changes, or grader relaxation. No unrelated cleanup is parked here.
