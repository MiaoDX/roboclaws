# Eval Baseline, Model, And CI Alignment

## Status

Approved plan for implementation in a separate context. Planning only; no
implementation changes are included in this plan. The provider-identity,
baseline-epoch, CI execution, and DINO entry-point decisions below are the
accepted scope and stop gates.

## Goal

Align provider model identity, eval baseline coverage, perception defaults, and
GitHub execution boundaries:

1. Pin `mimo-responses` and `mimo-tp-openai-chat` to `mimo-v2.5-pro`.
2. Move `kimi-openai-chat` to `kimi-k3`.
3. Add `mimo-tp-openai-chat` to the fixed-prior `baseline-refresh` provider
   matrix.
4. Make camera-derived Grounding DINO input the normal household-world product
   path, while retaining simulator/public-label lanes as explicit controls.
5. Make GitHub PR CI a named, deterministic subset of the eval baseline. CI
   must never attempt internal-only providers or resolve a profile that requires
   internal network access.

Kimi's provider documentation names the wire IDs `k3`, `k3-256k`,
`kimi-for-coding`, and `kimi-for-coding-highspeed`. The requested K3 family
label is therefore normalized to the wire ID `k3`; `k3-256k` remains an
explicit diagnostic/cost-tier variant.

## Non-goals

- Do not remove `world-public-labels` or other oracle/control lanes.
- Do not make PR CI run live providers, CloudML, MuJoCo GPU/DINO, hardware, or
  internal endpoints.
- Do not change provider fallback behavior; routes remain explicit and
  fail-closed.
- Do not republish historical baselines or promote a new durable catalog entry
  as part of this change.
- Do not treat the scheduled/manual external showcase as PR CI.

## Current Evidence

- `openai-agents-sdk` currently exposes five routes in
  `roboclaws/core/provider_catalog.py`.
- `mimo-responses` is an opaque environment-model route; its current contract
  accepts an arbitrary `MIMO_RESPONSES_MODEL`.
- `mimo-tp-openai-chat` defaults to `mimo-v2.5` and accepts
  `mimo-v2.5-pro` as an alternative.
- `kimi-openai-chat` still defaults in code to `kimi-k2.7-code`, and the
  provider catalog has not yet registered the new K3 IDs.
- Operator-console workflow metadata already defaults to
  `camera-grounded-labels` with `grounding-dino`, while launch examples,
  eval rows, and showcase rows still frequently use `world-public-labels`.
- `baseline-core` selects 18 rows; `baseline-live-default` 21; and
  `baseline-refresh` selects 25 without a prior and 29 with a fixed prior.
- `.github/workflows/ci.yml` currently runs deterministic lint/quality/tests,
  public-surface, and secret checks; it does not run the eval-harness provider
  matrix.
- `.github/workflows/showcase.yml` is a separate scheduled/manual external
  showcase for Kimi, MiMo TP, and MiniMax. It is not a baseline selector and
  must remain separate from PR CI.

## Recommended Shape

### Phase 1: Provider catalog and identity

Owner: `roboclaws/core/provider_catalog.py`, provider registry, launch/runtime
identity, tests, and model documentation.

- Add canonical `k3` and `k3-256k` model specs with the capabilities actually
  supported by the route; update the Kimi route default and compatible model
  list. Use `k3` as the production default and retain `k3-256k` as an explicit
  diagnostic/cost-tier variant.
- Change `mimo-tp-openai-chat` default and compatible model list to exactly
  `mimo-v2.5-pro`.
- Keep `MIMO_RESPONSES_MODEL` as a required deployment variable for
  `mimo-responses`, but validate it fail-closed as exactly `mimo-v2.5-pro`.
  This preserves endpoint/key/model deployment wiring while preventing an
  untracked model from entering artifacts or comparisons. The authoritative
  owner of this validation must be named in implementation (provider registry
  readiness versus route-model resolution); it must reject a mismatching
  deployment rather than rewrite its configured value.
- Update provider readiness, route payload, redaction, telemetry identity, and
  provider catalog tests. Do not add compatibility aliases for old model ids.
- Update `docs/human/model-matrix.md`,
  `docs/human/eval-harness-dimensions.md`,
  `docs/human/model-route-verdicts.yaml`, and operator/runbook references.

Acceptance:

- `resolve_route_model` accepts only `mimo-v2.5-pro` for both MiMo routes.
- `mimo-responses` with any other configured model is an actionable readiness
  failure, not a silent fallback.
- Kimi wire requests use the provider-documented `k3` or `k3-256k` IDs, while
  reports may expose a stable public family label `kimi-k3` plus the exact
  selected public model ID.
- The five provider profiles remain explicit and no wire-API fallback exists.

### Phase 2: Baseline provider matrix

Owner: `skills/eval-harness/catalog/rows.json`, selector tests, baseline docs,
and fixed-prior matrix reports.

- Add a first-class `mimo-tp-openai-chat` fixed-prior consumer row.
- Keep the fixed-prior comparison matrix explicit and provider-keyed. It will
  contain five cells: Codex Responses, MiMo Responses, MiMo TP Chat, Kimi
  Chat, and MiniMax Responses.
- Keep `mimo-responses` and Codex eligible only for local/CloudML according to
  their internal provider policy. They must never be dispatched from GitHub CI.
- Keep MiMo TP an external/local-or-trusted-showcase route; its baseline row
  may execute only where its external egress and credentials are authorized.
- Do not add the MiMo TP cell to `baseline-live-default`; that profile remains
  the small default Kimi live proof. The five-cell comparison belongs to
  `baseline-refresh` with an explicit fixed prior.

Expected counts after this phase:

- `baseline-core`: 18 rows.
- `baseline-live-default`: 21 rows.
- `baseline-refresh` without prior: 25 rows.
- `baseline-refresh` with fixed prior: 30 rows.

Acceptance:

- Selector tests assert the new row appears only when the fixed prior is
  supplied and is absent from `baseline-core` and `baseline-live-default`.
- Provider matrix identity records the exact profile/model/wire API.
- A blocked internal provider remains blocked evidence and is never replaced by
  an external provider.
- New matrix artifacts use an explicit matrix/case-set epoch (for example a
  dated `baseline_refresh_v2` identity) so K2.7/MiMo 2.5 evidence cannot be
  silently compared with the new K3/MiMo v2.5-pro population. Existing
  historical artifacts remain immutable.

Before making K3 the default, run a credentialed, local-only identity probe
(outside PR CI) with a fresh session and automatic compaction/truncation
disabled:

| Probe | Model ID | Thinking | Context payload | Expected signal |
|---|---|---|---|---|
| control | `k3-256k` | on | below 256K | successful K3 response |
| boundary-low | `k3-256k` | on | near 256K | success or explicit limit behavior |
| boundary-high | `k3-256k` | on | just above 256K | provider limit/compact/error, never silently relabeled |
| large-window | `k3` | on | above 256K and below 1M | accepted only when account/route permits |
| thinking-off | `k3-256k` | off | small | expected K2.6 routing/error signal, negative control |
| invalid-id | intentionally invalid | on | small | records whether this endpoint silently falls back |

Capture status, usage/context fields, response headers when available, and the
exact requested ID in private diagnostic evidence. A generic 200 is not proof
of model identity. The boundary-high result is attributable only when the
client did not compact/truncate first. A successful invalid-ID request is
classified as fallback/identity-ambiguous, not as model support.

### Kimi K3 Probe Result (2026-09-04)

The local `kimi-openai-chat` endpoint was probed directly at the configured
Chat Completions route. No key, full prompt, or response body was persisted.
The provider reference used for the probe was
<https://www.kimi.com/code/docs/kimi-code/models.html>.

- `k3-256k` returned HTTP 200 with `response.model=k3-256k` for small,
  100K-token, 220K-token, 250K-token, and 260K-token requests.
- A request above the 256 Ki token boundary (approximately 270K prompt
  tokens) returned HTTP 401 with the provider message
  `k3-256k supports only 256K context.`
- The same approximately 270K request sent to `k3` returned HTTP 200 with
  `response.model=k3`.
- An intentionally invalid model ID returned HTTP 401 with a provider message
  directing the caller to use `k3`; this endpoint did not exhibit arbitrary
  invalid-ID fallback during the probe.
- `k3`, `kimi-for-coding`, and `kimi-for-coding-highspeed` each returned a
  response model matching the requested ID on small control requests.
- Sending `thinking={"type":"disabled"}` still returned K3 response-model
  labels and non-zero reasoning-token usage. The documented K3-to-K2.6
  thinking-off routing was not reproduced through this payload and remains
  provider/API-version ambiguous; do not use it as a verified identity signal.

Interpretation: the endpoint provides strong, attributable evidence that `k3`
and `k3-256k` are accepted model IDs and that their context limits differ as
documented. The result does not prove account-wide 1M entitlement or explain
all client-side fallback behavior. Keep the identity probe as a local/manual
pre-default gate, not as a PR-CI test.

### Phase 3: DINO default and oracle controls

Owner: launch catalog/defaulting, eval live-runtime defaults, operator console,
catalog rows, examples, and contract tests.

- Enumerate the exact public entry points first: launch catalog resolution,
  direct CLI defaults, operator-console workflow/query defaults, eval live
  runtime defaults, and showcase manifest rows. Then make
  `camera-grounded-labels` plus `grounding-dino` the default for the bounded
  household-world cleanup/open-ended/map-build product routes that support
  that lane. Intended coverage is as broad as possible: `mujoco`/MolmoSpaces,
  `isaaclab`/B1 Map 12, and `agibot-gdk`/Agibot G2 Map 12. The synthetic
  `api_semantic_synthetic` smoke backend is not a real DINO target and remains
  a deterministic control; `planner-proof` is a separate surface without
  household evidence lanes.
- Preserve explicit `world-public-labels` as a simulator/public-label control
  and preserve any `world-oracle-labels` grader/control lane already used by
  tests. These lanes must remain opt-in and clearly named as controls.
- Update default eval/product rows and showcase-facing examples only where the
  row is intended to measure the normal product path. Keep dedicated oracle
  controls separate so historical capability comparisons remain interpretable.
- Keep DINO sidecar readiness fail-fast. No silent sim-oracle fallback is
  allowed when the default camera lane is selected.

Acceptance:

- Launch resolution with no explicit evidence lane selects
  `camera-grounded-labels` and `camera_labeler=grounding-dino` for the targeted
  household workflows.
- Explicit `evidence_lane=world-public-labels` still works and is visibly
  represented as a control.
- Missing DINO dependency/sidecar produces `environment_blocked` or an
  actionable launch error, never an oracle-backed success. Unsupported
  backends/routes must have an explicit documented default/error behavior;
  they must not silently switch to simulator labels.
- Focused contract tests cover CLI, operator-console, eval live-runtime, and
  baseline row identity.

### Phase 4: CI as a baseline subset

Owner: eval selector/catalog, `.github/workflows/ci.yml`, CI docs/tests.

Introduce a named `baseline-ci` profile (or an equivalently explicit
deterministic profile) whose selected rows are a strict subset of the
baseline catalog:

- route-trace contract tests;
- eval unit tests;
- deterministic smoke regression;
- deterministic map-build quality/consumer contract coverage;
- deterministic open-ended contract coverage;
- existing `just agent::verify` lint, quality, architecture, pytest, public
  surface, and secret checks.

The CI profile must enforce all of the following at selection time:

- `expense=deterministic` only;
- no `provider:*` execution requirement;
- no `provider_network_scope=internal` or `external`;
- no `live-agent`, CloudML, GPU/DINO, local-simulator, hardware, or external
  network row.

This is a prohibition on provider execution and provider egress, not a claim
that the GitHub job has no network access: checkout, package installation,
`just` download, and secret-scanning setup still use ordinary CI network
access. The CI contract must be tested with provider-related environment
variables present to prove they are ignored and no provider row is selected.

Use the catalog/selector to generate the CI manifest rather than maintaining a
second hand-written row list. Keep `.github/workflows/showcase.yml` as the
scheduled/manual external showcase. It may run Kimi, MiMo TP, and MiniMax
rows, but it is not PR CI and is not allowed to imply internal-provider
availability.

Acceptance:

- A CI profile manifest is provably a set subset of `baseline-core` rows.
- A selector regression test fails if an internal or external provider row is
  added to `baseline-ci`.
- The exact CI command runs without provider credentials and without any live
  execution request; dependency-download network access remains expected.
- Selection and execution tests reject an internal or external provider row
  even when it is requested through an explicit profile/row override.
- Documentation distinguishes PR CI, local baseline refresh, CloudML-capable
  internal rows, and the external scheduled showcase.

## Verification Plan

Deterministic checks:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q \
  tests/unit/providers \
  tests/unit/evals/test_eval_harness_baseline_profiles.py \
  tests/unit/evals/test_eval_harness_selector.py \
  tests/unit/launch \
  tests/unit/operator_console
```

Generate and inspect manifests for `baseline-ci`, `baseline-core`,
`baseline-live-default`, and `baseline-refresh` with and without a fixed prior.
Assert row counts, provider identities, CI subset relation, DINO defaults, and
internal-provider exclusion.

Run the existing `just agent::verify` and the exact new CI eval command locally
with provider environment cleared. Do not run live providers as part of PR CI
verification.

Live/manual proof is separate and gated:

- local/CloudML proof for `mimo-responses` and Codex only after their internal
  endpoint readiness passes;
- local/trusted showcase proof for Kimi K3, MiMo TP K3-equivalent route, and
  MiniMax;
- DINO product proof on a machine with the required sidecar/GPU.

No durable baseline publication is accepted if any required row is blocked,
unavailable, or behavior-failing.

## Risks And Stop Gates

- **Model identifier risk:** use provider-documented wire ID `k3`, not the
  internal/public family label `kimi-k3`. Run the identity probe before
  promoting K3 as the default; any successful invalid-ID call is treated as
  fallback/identity-ambiguous.
- **Opaque MiMo Responses risk:** retain the environment variable but reject
  every value except `mimo-v2.5-pro`; do not silently rewrite a deployment's
  configured model.
- **Baseline comparability risk:** old K2.7/MiMo 2.5 evidence remains
  historical; do not overwrite it or mix it into new comparisons without an
  explicit model identity.
- **Perception availability risk:** DINO is a default input contract, not a
  reason to silently use sim labels. Missing DINO blocks the row.
- **CI network risk:** any CI job that selects `provider_network_scope=internal`
  or calls a provider-backed row is a hard stop.
- **CI wording risk:** do not describe PR CI as network-isolated. The supported
  guarantee is no provider execution or provider egress.
- **Scope risk:** do not add MiMo TP to the default Kimi live profile unless a
  separate maintainer decision expands that profile.

## Alternatives Considered

1. Remove `MIMO_RESPONSES_MODEL` and hard-code `mimo-v2.5-pro`.
   Rejected for now because it changes deployment wiring more than required;
   strict validation preserves explicit endpoint configuration while enforcing
   the requested model identity.
2. Make CI run all of `baseline-core`.
   Rejected because that includes simulator/DINO/product rows and would make CI
   dependent on local-only runtime capabilities. A named deterministic subset
   is safer and honestly represents CI coverage.
3. Delete public-label/oracle lanes after making DINO default.
   Rejected because controls are needed to separate perception failures from
   task-strategy failures and to preserve interpretable historical evidence.

## User Review Decisions

The following decisions are now resolved for implementation approval:

- Confirm that `MIMO_RESPONSES_MODEL` remains present but is constrained to
  `mimo-v2.5-pro`, with a fail-closed mismatch error.
- Confirm that MiMo TP enters `baseline-refresh` fixed-prior matrix only, not
  `baseline-live-default`.
- Confirm that CI gets a named deterministic `baseline-ci` profile and the
  contract is “no provider execution/egress,” while ordinary dependency
  downloads remain allowed.
- Use provider wire ID `k3` for the Kimi K3 default; include the local-only
  `k3-256k` identity/context probe before promotion and keep its result as
  diagnostic evidence.
- Apply the DINO default to household-world cleanup/open-ended/map-build on
  MuJoCo, Isaac Lab, and Agibot GDK. Keep synthetic smoke as a deterministic
  control and planner-proof outside this lane; unsupported runtime behavior is
  explicit block/error, never sim-oracle fallback.
- Approve a new matrix/case-set epoch for the changed model population.

## Recommended Next Action

Execute phases 1-4 in order in a separate context, stopping after Phase 1 for
focused provider-contract review and after Phase 4 for CI manifest review.

## Shortcut

If the user wants a smaller first change, execute only Phase 1 and Phase 2;
leave DINO default migration and CI profile introduction as explicitly parked
follow-up work.
