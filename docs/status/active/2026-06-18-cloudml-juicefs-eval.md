# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: make complete baseline refreshes convenient and faster on
CloudML by running independent rows concurrently as preemptible r49 shards.

Current slice: the complete CloudML baseline refresh, preemptible r49 support,
and the MapBuild live-matrix timeout follow-up are complete. Hybrid `auto`
dependency handoff remains.

Current blocker: no CloudML execution or credential-transport blocker. Direct
Kimi/MiniMax rows remain ineligible on the internal-only worker pool. The
remaining known executed-row behavior issue after the targeted follow-up is
RAW-FPV cleanup capability, not CloudML runtime.

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
  staging.
- Commit `9cfeee42` adds task-level `preemptible: true` for r49 shards while
  retaining their `GUARANTEED` resource priority. The complete run launched 14
  preemptible GPU shards plus one non-preemptible CPU shard concurrently; none
  was preempted.
- Run `cloudml-baseline-refresh-preemptible-9cfeee42-20260722` selected 27 rows,
  collected all 25 eligible rows, and completed in about 54 minutes 12 seconds.
  The row durations sum to about 4 hours 11 minutes, for an effective 4.6x
  speedup. That report records 23 passed, two failed, and two explicitly
  blocked; the MapBuild failure was then cleared by the targeted follow-up.
- Commit `dd4d4ade` gives MapBuild provider matrices an explicit 1500-second
  live budget. Follow-up run `cloudml-mapbuild-budget-dd4d4ade-20260722` passed
  the Codex matrix 5/5; cleanup cells completed in 1144.758 and 1250.085
  seconds, proving the old 1200-second failure was a budget boundary.
- RAW-FPV cleanup remains a product capability failure:
  `raw_fpv_recovery_exhausted` after 3/4 required grounded cleanup chains.

Next slice: implement dependency-safe local/CloudML handoff for real
`execution_target=auto`, then run a representative hybrid baseline.

Next proof: generate and execute a hybrid plan with one CloudML producer and one
local consumer, then collect one aggregate report without changing row identity.

Stop condition: stop before provider identity substitution, uploading the full
`.env`, placing provider values in normal artifacts, destructive retry, or a new
cross-repo executor API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: native CloudML secret references/workload tokens and automatic
remote secret deletion are security hardening; direct Kimi/MiniMax remain
ineligible on the internal-only pool; FDS publication remains optional.
