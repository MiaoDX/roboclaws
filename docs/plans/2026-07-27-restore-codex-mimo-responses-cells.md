# Restore Codex And MiMo Responses Cells

**Status:** Partially implemented; Codex live proof blocked
**Created:** 2026-07-27
**Last reviewed:** 2026-07-27
**Current implementation contract:** Expose separate `codex-responses` and `mimo-responses`
OpenAI Agents SDK provider profiles. Resolve each profile's endpoint, key, and request model only
from local environment variables, and preserve separate live eval provenance without emitting
those values.
**Related plan:** `docs/plans/2026-07-24-public-core-internal-integration-minimization.md`
**Supersedes:** Only the prior plan's single-`custom-responses` provider-matrix decision.

## Plan Ledger

- Plan status: BLOCKED_NEEDS_LOCAL_VALIDATION
- Session scope: restore-codex-mimo-responses-cells
- Parent plan: `docs/plans/2026-07-24-public-core-internal-integration-minimization.md`
- Child plans: none
- Last updated: 2026-07-27
- Current slice: implementation and MiMo live proof are complete; Codex live proof remains.
- Next action: resolve Codex provider HTTP 403, rerun health, then execute its fixed-prior row.
- Blocked on: Codex provider entitlement/configuration. Two explicit request-model attempts returned
  HTTP 403; no endpoint-specific header compatibility or further model guessing is approved.
- Latest proof: implementation commit `d449d29a`; MiMo provider health passes and
  `output/eval-harness/20260727-dual-responses-proof/mimo/household_world_map_consumer_fixed_prior/mimo-responses-fixed-prior/eval_results.json`
  records 2/2 passing samples. Ruff, format, the full standalone pytest suite, and exact secret
  scans pass. Codex health is blocked before product execution.
- Do not touch from this session: provider-specific Router transport/header behavior, MiniMax/Kimi
  semantics, CloudML ownership, simulator scoring, physical movement, publication, or
  `job_config_template.yaml`.

## Approved Contract

The public provider matrix must retain four independent cells:

| Public profile | Wire API | Public model label | Required local environment |
| --- | --- | --- | --- |
| `codex-responses` | Responses | `codex` | `CODEX_RESPONSES_BASE_URL`, `CODEX_RESPONSES_API_KEY`, `CODEX_RESPONSES_MODEL` |
| `mimo-responses` | Responses | `mimo` | `MIMO_RESPONSES_BASE_URL`, `MIMO_RESPONSES_API_KEY`, `MIMO_RESPONSES_MODEL` |
| `minimax-responses` | Responses | `MiniMax-M3` | existing MiniMax variables |
| `kimi-openai-chat` | Chat Completions | `kimi-k2.7-code` | existing Kimi variables |

The tracked tree must contain no endpoint defaults. Provider keys, endpoints, and actual request
model IDs stay in gitignored local configuration. Reports and artifacts may expose the public
profile/model labels and non-secret provenance, but never the configured endpoint, key, or request
model.

## Scope

- Replace `custom-responses` with `codex-responses` and `mimo-responses` across the provider
  registry, OpenAI Agents SDK runtime, provider probes, benchmark matrix, operator console,
  launch helpers, eval samples/catalog, reports, docs, and tests.
- Keep one shared standard Responses implementation. The two profiles differ only in explicit
  environment ownership and stable public provenance.
- Restore separate fixed-prior live eval rows for Codex and MiMo.
- Make readiness diagnostics list every missing required variable instead of collapsing to one
  model-specific error.
- Migrate the local `.env` only after resolving the corresponding legacy values without printing
  them. `.env` remains untracked.
- Remove stale `custom-responses` names and `CUSTOM_RESPONSES_*` configuration; do not retain a
  compatibility alias.

## Non-Goals

- Do not restore Codex Router custom headers, special settings, wire adapters, or automatic
  fallback.
- Do not restore Mify, gateway, cluster, deployment, or other infrastructure identities in public
  names or artifacts.
- Do not add a dynamic provider plugin/config-file system.
- Do not change MiniMax, Kimi, direct-runner, task policy, map semantics, or simulator behavior.
- Do not publish, promote a durable baseline, rewrite history, or move a physical robot.

## Entity Budget

- Reuse: provider registry, one OpenAI Responses runtime path, readiness/probe helpers, existing
  eval provider matrix, redaction layer, `.env` loading, and standard verification commands.
- Remove/merge: remove the ambiguous single custom profile and its one-cell eval identity.
- New: exactly two closed-catalog neutral profiles and one additional fixed-prior provider row.
- Expansion trigger: any provider-specific transport quirk, compatibility alias, fifth provider
  cell, dynamic plugin/config owner, or public endpoint/model value requires re-approval.

## Acceptance

- `supported_provider_profiles("openai-agents-sdk")` returns exactly Codex Responses, MiMo
  Responses, MiniMax Responses, and Kimi Chat.
- Codex and MiMo resolve distinct environment triples and public provenance while sharing the
  standard Responses implementation.
- Missing configuration reports all missing variables for the selected profile.
- No deleted `custom-responses` profile or `CUSTOM_RESPONSES_*` variable remains in active source,
  tests, eval samples, or current docs.
- The baseline fixed-prior matrix selects four provider cells and stores distinct Codex/MiMo rows.
- Focused provider, runtime, launch, eval, operator-console, and redaction tests pass; Ruff and the
  full standalone pytest suite pass.
- Codex and MiMo provider health plus fixed-prior live eval rows pass from a fresh shell. A concrete
  credential/provider blocker is `BLOCKED_NEEDS_LOCAL_VALIDATION`, not success.
- Tracked files and emitted eval artifacts contain no configured endpoint, key, request model, or
  internal domain.

## Verification

Deterministic:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
```

Focused integration:

```bash
./scripts/dev/run_pytest_standalone.sh -q tests/unit/providers tests/unit/evals \
  tests/unit/agents/test_live_runtime.py tests/unit/operator_console \
  tests/contract/dev_tools/test_coding_agent_env_helpers.py \
  tests/contract/dev_tools/test_task_agent_just_recipes.py
just agent::eval recommend plan=docs/plans/2026-07-27-restore-codex-mimo-responses-cells.md budget=focused
```

Required local/live proof after provider readiness:

```bash
just dev::model-provider-health agents-sdk --probe codex-responses --require-all
just dev::model-provider-health agents-sdk --probe mimo-responses --require-all
```

Execute the selected fixed-prior Codex and MiMo rows serially from one frozen Runtime Map Prior.
Preserve blocked/failed attempts and do not publish or promote the resulting baseline.

## Stop Conditions

- Stop for an endpoint-specific transport/header requirement, ambiguous legacy-to-new credential
  mapping, overlapping edits in owned files, a material provider-cost/resource expansion, or any
  request to publish durable artifacts.
- Completion requires deterministic proof and both live provider cells, unless a concrete external
  readiness blocker is recorded as `BLOCKED_NEEDS_LOCAL_VALIDATION`.
