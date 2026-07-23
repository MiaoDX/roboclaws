# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: make complete baseline refreshes convenient and faster on
CloudML by running independent rows concurrently as preemptible r49 shards.

Current slice: local and CloudML execution now share scene-aware benchmark
cases and content-addressed multi-scene staging. Real two-scene CloudML
parallel proof remains; hybrid `auto` dependency handoff follows it.

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
- Content staging now stores immutable assets and code under digest paths and
  keeps `runs/<run-id>` manifests separate. The first local proof built the
  1,800,828,916-byte asset archive in 89.29 seconds; a later unchanged run
  reused both content entries in 4.90 seconds with a roughly 16 KB run
  directory. The source fingerprint includes all archived tree paths, sizes,
  mtimes, symlink targets, cache resources, and the complete map bundle, so an
  in-place resource change invalidates the source reference.
- Commit `001266a8` fixes the JuiceFS cache probe contract: `hit_count` counts
  matching candidate directories, not individual marker files. The complete
  baseline therefore reused both remote digest entries and uploaded only its
  small run manifests and scoped provider inputs.
- Final run `cloudml-baseline-content-store-4f3d4fec-20260722` selected 27 rows,
  dispatched 25 eligible rows as one CPU shard plus 14 preemptible r49 shards,
  and collected all 25 results with zero missing artifacts. Outcomes were 24
  passed, one failed, and two explicitly blocked for missing external-egress
  workers. No shard was preempted or retried.
- Cloud task wall time was 42 minutes 26 seconds, or 44 minutes 41 seconds from
  harness generation through the last CloudML task. Executed row durations sum
  to 3 hours 20 minutes 23 seconds, an effective 4.72x task-execution speedup.
  This is about 11 minutes 46 seconds faster than the previous 54-minute
  parallel baseline; part of that improvement is lower live-row runtime, not
  additional scheduler parallelism.
- Both Codex and MiMo Mify MapBuild matrices passed 5/5. World-public cleanup
  live passed 3/3. The sole executed failure was RAW-FPV cleanup:
  `raw_fpv_recovery_exhausted` after 168 successful model calls, zero provider
  failures, and 2/4 required grounded cleanup chains. This is product behavior,
  not CloudML, preemption, or provider availability.
- Commits `b0ef5d72` and `68b865d0` make local and CloudML share scene-aware
  case IDs, scene identity, dependency metadata, and a multi-scene staged asset
  manifest. Commit `91d126a0` limits outer scene expansion to the two current
  scene-portable MapBuild product rows; cleanup, open-ended, long-horizon, and
  provider matrices remain bound to their own scene-specific task contracts.
- Local run `local-multiscene-mapbuild-91d126a0` passed the world-public
  MapBuild case on `procthor-10k-val/0` and `procthor-objaverse-val/0`. The
  shared local scheduler preserved both case IDs but serialized them through
  the one MolmoSpaces visual-backend concurrency group.
- CloudML dry-run `cloudml-multiscene-mapbuild-91d126a0-dry` produced two
  independent preemptible one-r49 shards with the same case IDs, no blocked
  rows, and no submitted task IDs. The unchanged two-scene asset archive reused
  digest `cc229669ba262c286ce4856b1d4107b81eb18cb3a9698c15a467f414834fd34c`.

Next slice: after explicit CloudML submission confirmation, run and collect the
two real MapBuild shards concurrently. Then implement dependency-safe
local/CloudML handoff for real `execution_target=auto`.

Next proof: collect both real two-scene CloudML MapBuild cases and verify their
task intervals overlap. The following proof is a hybrid plan with one CloudML
producer and one local consumer in one aggregate report.

Stop condition: stop before provider identity substitution, uploading the full
`.env`, placing provider values in normal artifacts, destructive retry, or a new
cross-repo executor API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: native CloudML secret references/workload tokens and automatic
remote secret deletion are security hardening; direct Kimi/MiniMax remain
ineligible on the internal-only pool; FDS publication remains optional.
