# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: use Mify `xiaomi/mimo-v2.5-pro` as the only default MiMo
route and pause obsolete MiMo routes without removing diagnostic access.

Current slice: scoped provider-env staging and bounded live proof are complete.
Hybrid `auto` dependency handoff and the complete baseline refresh remain.

Current blocker: no credential-transport blocker. The `mimo-1000` channel was
removed. CloudML permits eight concurrent r49 resource units for this account;
the earlier two-shard ceiling occurred because six unrelated r49 jobs were
already running. This queue does not offer r49 `BEST_EFFORT` resources.

Last proven evidence:

- Commits `ab7c855c` and `fabb06bf` load registry-required values from `.env`,
  stage one `0600` dotenv per provider shard, mount it read-only, and bootstrap
  both old and new eval images without putting values in argv/YAML/reports.
- Eval Harness focused regression passes 211 tests; provider-env tests include
  special-character round-trip, registry mapping, temp cleanup, mount policy,
  resume, and secret-sentinel checks.
- Live run `provider-fabb06bf-live` collected all three rows with no missing
  results. API Router passed 3/3 in 397.722 seconds; MiMo Mify passed 3/3 in
  692.858 seconds.
- MiMo Inside reached `mimo-1000` and failed after two calls classified by the
  runtime as `provider_transient_failure/upstream_unavailable`. The aggregate
  currently promotes this to `harness_bug_unclassified`, which is a separate
  eval-classification defect.
- Local Mify Pro proof passed OpenAI Chat 3/3, Responses 3/3, and one cleanup
  worklist tool-call case. The active MiMo baseline now selects
  `mimo-mify-responses`; Inside and token-plan routes remain diagnostic-only.
- Across 258 generated and collected files, no current API-key value was found.
  Provider base URLs remain normal non-secret route metadata.
- The third r49 shard initially exceeded the eight-unit account quota because
  six unrelated r49 jobs plus two eval shards were already active. It submitted
  successfully through resume after one unit was released, without re-uploading
  staging. A `BEST_EFFORT` smoke was rejected before task creation because the
  queue has no preemptible r49 resource class.

Next slice: implement dependency-safe local/CloudML handoff for real
`execution_target=auto`, then run a representative hybrid baseline.

Next proof: generate and execute a hybrid plan with one CloudML producer and one
local consumer, collect one aggregate report, then run the full baseline refresh.

Stop condition: stop before provider identity substitution, uploading the full
`.env`, placing provider values in normal artifacts, destructive retry, or a new
cross-repo executor API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: native CloudML secret references/workload tokens and automatic
remote secret deletion are security hardening; direct Kimi/MiniMax remain
ineligible on the internal-only pool; FDS publication remains optional.
