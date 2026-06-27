# Architecture Cleanup Campaign

Source gate: `docs/plans/refactor-architecture-cleanup-campaign.md`

Latest user intent: resume the autonomous codebase simplification campaign
with fresh reduce-entropy discovery, architecture-report input, and verified
refactor slices until the stop condition is met.

Current slice:

- Slice 37 complete. Fresh post-Slice-36 discovery found the first-screen
  `ARCHITECTURE.md` diagram still showed retired `codex-cli` and
  `claude-code` as peer agent-engine cards while the surrounding text says
  they are rejected. Updated the diagram to show only `direct-runner` and
  `openai-agents-sdk` as current engines, with retired engines called out as
  rejected, and added a focused diagram guard. Next action is fresh
  post-Slice-37 discovery.

Last proven evidence:

- Fresh post-HEAD discovery found `scripts/reports/prune_pages_site.py`, a
  pure pass-through wrapper around the existing
  `roboclaws.devtools.pages_site` owner. The only tracked caller was the GitHub
  Pages workflow.
- Migrated `.github/workflows/ci.yml` to
  `python3 -m roboclaws.devtools.pages_site site`, deleted the wrapper, added a
  canonical module entrypoint, and added a subprocess regression test proving
  the module CLI prunes an unreferenced file.
- Focused Pages prune tests passed; `python -m roboclaws.devtools.pages_site
  --help` printed CLI help; stale wrapper path search returns only the
  intentional removal guard; ruff passed on touched files; and `git diff
  --check` passed.
- Post-`90e2c0d8` discovery checked current script wrappers, current package
  micro-modules, active docs/tests/recipes, and stale names from previous
  slices. No clear safe P1/P2 slice remained after shrink attempts.
- Post-`9c70b796` discovery repeated the high-noise summary, stale-token scan,
  tiny wrapper scan, active script path scan, and previous stale-owner checks.
  It found no new material safe slice.
- Report-only architecture review artifact:
  `/tmp/architecture-review-20260623_095651.html`.
- Fresh post-HEAD discovery after `39846ccb` found a current false-confidence
  candidate: `.venv/bin/python scripts/dev/check_python_quality_ratchet.py`
  fails on current source. The first safe vertical slice moved
  provider-registry command dispatch behind private helpers; focused provider
  catalog tests, Ruff, and `git diff --check` passed, and the quality-ratchet
  output no longer lists `roboclaws/agents/provider_registry.py`.
- The second safe vertical slice moved cleanup MCP server initialization setup
  into same-owner helpers and deleted shallow one-call/no-call helpers; focused
  MCP contract tests, Ruff, and `git diff --check` passed, and the
  quality-ratchet output no longer lists
  `RealWorldMolmoCleanupMCPServer.__init__` or
  `roboclaws/household/realworld_mcp_server.py` module-size growth.
- The third safe vertical slice simplified
  `LiveOpenAIAgentsCleanupRunner._run_sdk_agent` status writing without adding
  helper surface or growing the file; focused live-runtime tests, Ruff, and
  `git diff --check` passed, and the quality-ratchet output no longer lists
  that method.
- The fourth safe vertical slice moved repeated Agibot contract-test artifact
  reads and identity assertions into same-file helpers. Focused PLR0915 Ruff,
  focused contract tests, touched-file Ruff, and `git diff --check` passed;
  the quality-ratchet output no longer lists the two overlong Agibot contract
  tests and now reports only broader oversized-module baseline drift.
- The fifth safe vertical slice moved live-agent timing breakdown, MCP trace
  timing, control-plane metrics, timeline construction, and compact metric
  grouping from the Molmo cleanup launcher script to the agent-layer
  `roboclaws.agents.live_timing` owner. Focused timing tests, touched-file
  Ruff, and `git diff --check` passed; the quality-ratchet output no longer
  lists `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py`.
- The sixth safe vertical slice moved Agibot operator localization,
  run-enablement, bounded-local-nudge, and human-takeover-stop gate logic from
  the SDK subprocess adapter into the household operator-gates owner. Focused
  SDK runner source tests, focused physical Agibot contract tests, touched-file
  Ruff, and `git diff --check` passed; the quality-ratchet output no longer
  lists `roboclaws/household/agibot_sdk_runner.py` or
  `tests/contract/molmo_cleanup/test_physical_agibot_pilot.py`.
- Fresh post-`4bb038bc` discovery found a shrinkable duplicate-owner candidate
  in visual grounding: both the sidecar adapter and benchmark runner sanitized
  runtime parameters locally while the request/response contract owner existed
  in `roboclaws.household.visual_grounding`. The safe vertical slice merged
  sanitizer ownership into that contract module and migrated both callers.
  Focused visual-grounding unit/contract tests, touched-file Ruff, and
  `git diff --check` passed; the quality-ratchet output no longer lists
  `scripts/visual_grounding/adapters.py` or
  `scripts/visual_grounding/run_visual_grounding_benchmark.py`.
- The final slice for this campaign group moved Agibot simulated runtime
  envelope builders, stage JSON/HTML artifact writing, and relative-path
  formatting into `roboclaws.household.agibot_contract_rehearsal_runtime`.
  `agibot_contract_rehearsal.py` now delegates those runtime shapes, and
  `agibot_contract_rehearsal_stages.py` calls the canonical writer instead of
  carrying a second local copy. The focused Agibot rehearsal tests passed;
  touched-file Ruff and `git diff --check` passed. The quality-ratchet output
  no longer lists `roboclaws/household/agibot_contract_rehearsal.py` or
  `roboclaws/household/agibot_contract_rehearsal_stages.py`; it still fails on
  unrelated oversized-module drift listed under parked work.
- Fresh post-`12b66126` discovery found a current false-confidence candidate:
  `.venv/bin/python scripts/dev/check_python_quality_ratchet.py` failed with
  new complexity rows in
  `scripts/molmo_cleanup/molmospaces_worker_outputs.py` and two
  operator-console test helpers.
- Slice 29 moved robot-view artifact path naming and scene-alignment point
  collection into same-owner private helpers in
  `scripts/molmo_cleanup/molmospaces_worker_outputs.py`. Focused robot-view
  worker tests, touched-file Ruff, touched-file format check, and
  `git diff --check` passed. The quality-ratchet output no longer lists
  `molmospaces_worker_outputs.py`; it still fails on two operator-console test
  helper PLR0915 rows plus broader oversized-module baseline drift.
- Slice 30 split overlong operator-console scene-sampler readiness and static
  asset assertion helpers into same-file assertion vocabulary. Focused tests,
  PLR0915 Ruff, touched-file Ruff, touched-file format check, and
  `git diff --check` passed. The quality-ratchet output now reports only
  oversized-module baseline drift and no current Ruff complexity rows.
- Slice 31 replaced the MolmoSpaces map-preparation semantic category branch
  ladder with an ordered rule table in the same map-preparation owner. Focused
  map-preparation contract coverage, direct C901 Ruff, touched-file Ruff,
  touched-file format check, and `git diff --check` passed. The quality-ratchet
  summary now reports zero Ruff complexity violations; the full ratchet command
  still fails only on oversized-module baseline drift.
- Post-`29e3d316` discovery found duplicate live-run timing ownership:
  `scripts/molmo_cleanup/run_live_codex_cleanup.py` still carried local runner
  timing and MCP trace timing helpers while `roboclaws.agents.live_timing`
  already owned the active OpenAI Agents timing interface. Slice 32 moved the
  Codex-specific timing interpretation into that existing agent-layer owner,
  kept the retired Codex runner script and output schema intact, and reduced
  `run_live_codex_cleanup.py` from 1455 to 1393 lines. Focused Codex timing
  tests, active OpenAI Agents timing tests, touched-file Ruff, touched-file
  format check, ratchet summary, and `git diff --check` passed. The full
  ratchet still fails only on broader oversized-module baseline drift.
- Post-`7cd1b445` discovery found a small same-owner duplicate stack in
  `roboclaws.operator_console.interactions`: operator message and resume JSONL
  source errors used parallel formatter helpers. Slice 33 merged that private
  formatting into one parameterized helper while preserving source labels and
  user-facing error text. Focused interaction source-error tests, touched-file
  Ruff, touched-file format check, ratchet summary, and `git diff --check`
  passed. `interactions.py` shrank from 895 to 881 lines; the full ratchet
  still fails only on broader oversized-module baseline drift.
- Post-`60f9fd67` discovery pass 1 checked current ratchet summary, top
  oversized household/report/operator-console/script owners, stale/public alias
  hits, checker legacy flags, operator-console state JSON source helpers, and
  raw-FPV semantic aliasing. No clear safe P1/P2 slice remained after shrink
  attempts: the hits were public migrations already parked, broad report/test
  sprawl, legitimate artifact/link ownership, or domain-heavy visual-label
  aliasing that needs a larger contract.
- Post-`60f9fd67` discovery pass 2 independently checked the ratchet proof,
  exact oversized-module failures, small script/module surfaces, repeated
  private-helper names, text/JSON source readers, live MolmoSpaces aliases, and
  operator-console JSONL/source helpers. The ratchet summary still reports
  zero Ruff complexity violations, and the full ratchet still fails only on
  oversized-module baseline drift. No implementation slice passed the campaign
  bar: remaining candidates require public command migration, broader
  test-suite/report restructuring, domain-contract decisions, or would only
  move lines without deleting, merging, or canonicalizing a real concept.
- Fresh post-`ce26d3ca` discovery found the quality ratchet now passes after
  later baseline/contract updates, but the opt-in Molmo live CI workflow still
  carried one stale `claude-code-kimi-k2.6` matrix entry and one stale Pages
  artifact download step. Slice 34 aligned the workflow to the live-report
  registry owner and added
  `tests/unit/molmo_cleanup/test_ci_live_workflow_entries.py` so future
  workflow matrix/download entries match `MODEL_ENTRIES`. Focused CI-live
  report tests, stale-reference search, touched-file Ruff, touched-file format
  check, the Python quality ratchet, and `git diff --check` passed.
- Fresh post-Slice-34 discovery found the last Claude Code Molmo live CI entry
  still reached a retired public launch engine. `just run::surface ... agent_engine=claude-code`
  fails with `unsupported agent_engine 'claude-code'`, so that row could only
  produce a failed opt-in CI leg. Slice 35 removed
  `claude-code-mimo-v2.5` from `MODEL_ENTRIES`, the GitHub Actions matrix, and
  Pages artifact downloads; removed the dead `--skip-version-check`/Claude
  binary branch from `run_ci_live_cleanup_matrix.py` and rehearsal recipes; and
  strengthened the registry/workflow guard to prove each entry resolves through
  the canonical launch catalog. Focused CI-live tests, dry-run single/all
  matrix commands, stale-reference search, touched-file Ruff, Python quality
  ratchet, and `git diff --check` passed. The pre-commit scoped Molmo suite
  also exposed and fixed an environment-dependent Isaac fake-backend assertion:
  imported robot USD artifacts may coexist with a missing URDF source while
  still recording the missing-URDF blocker.
- Fresh post-Slice-35 discovery found the MolmoSpaces apple-to-apple grid was
  still a current `just` recipe and contract-tested maintainer surface, but
  its cleanup rows launched retired `codex-cli` and `claude-code` engines.
  Slice 36 collapsed the active grid to the current OpenAI Agents SDK Codex
  router route, kept the online/offline Runtime Metric Map and camera-lane
  axes, and added a regression test that resolves every generated cleanup row
  through `roboclaws.launch.catalog.resolve_surface_launch`. Focused
  apple2apple tests, recipe contract tests, stale retired-engine search for
  the grid, touched-file Ruff, Python quality ratchet, and `git diff --check`
  passed.
- Fresh post-Slice-36 discovery found live human-doc source drift:
  `ARCHITECTURE.md` embeds `docs/architecture.svg`, and the diagram's
  agent-engine layer still presented `codex-cli` and `claude-code` as current
  cards. Slice 37 updated the diagram to show the active SDK/direct engines
  and a retired-engine rejection note, then added
  `tests/contract/dev_tools/test_architecture_diagram.py` to keep the diagram
  aligned with current launch docs. Focused diagram/public-engine tests,
  stale-card search, touched-file Ruff, Python quality ratchet, and
  `git diff --check` passed.

Completed slice batch:

- Slice 1: canonicalized launch route tests on `roboclaws.launch.catalog` and
  removed one shallow compatibility module.
- Slice 2: removed one launch-plan compatibility alias while preserving public
  trace text.
- Slice 3: removed one unused launch task-spec compatibility alias.
- Slice 4: removed one duplicate root example wrapper while preserving the
  canonical nested manual wrapper.
- Slice 5: removed nine root script symlink shims while preserving canonical
  subdirectory scripts.
- Slice 6: removed the OpenClaw bootstrap's stale `SIM_SERVER_URL`
  compatibility fallback while preserving canonical `ROBOCLAWS_MCP_URL`
  defaulting and overrides.
- Slice 7: removed the empty `roboclaws.openclaw` source package and stopped
  the pre-commit hook from routing staged changes in that retired package.
- Slice 8: removed an unreferenced AI planning roadmap that conflicted with
  the current GitHub issue tracker guidance.
- Slice 9: moved operator-console wrapper/display-run id normalization to one
  state owner and updated history to call it.
- Slice 10: deleted private path-containment helpers in favor of the native
  `Path.is_relative_to(...)` interface.
- Slice 11: deleted four stale agent-only docs for retired AI2-THOR/OpenClaw
  game and refactor-harness surfaces while preserving current run guidance and
  historical planning evidence.
- Slice 12: deleted the unused provider timing proxy script wrapper and updated
  the implemented provider-timing plan to name only the module owner.
- Slice 13: replaced the stale OpenClaw image-upgrade checklist command with
  the current maintainer dispatcher route and added a contract guard.
- Slice 14: replaced stale OpenClaw doc paths in bootstrap comments,
  plugin-allowlist guidance, and OpenClaw bootstrap contract-test guidance.
- Slice 15: deleted the unused private `roboclaws.launch.context` module and
  added a focused guard.
- Slice 16: deleted the no-caller cleanup report regeneration script wrapper
  and added a focused guard while preserving the artifact-report owner.
- Slice 17: deleted the no-caller Kimi-only key checker wrapper and its
  wrapper-only tests while preserving the generic provider health-check owner.
- Slice 18: updated stale OpenClaw image-bump docs away from the missing TODO
  and retired game-script examples while preserving current OpenClaw maintainer
  routes.
- Slice 19: moved model-matrix benchmark catalog and wire helper logic from
  private script-directory modules to the `roboclaws.agents` owner while
  preserving the public dev benchmark command.
- Slice 20: deleted the Pages prune script wrapper and migrated CI to the
  `roboclaws.devtools.pages_site` module CLI.
- Slice 21: deepened provider-registry CLI dispatch so `_main(...)` is no
  longer the command formatting owner.
- Slice 22: deepened cleanup MCP server initialization while reducing the
  module size below its previous line count.
- Slice 23: simplified OpenAI Agents runner status-loop control flow without
  changing the public live-runner script.
- Slice 24: extracted test-local Agibot artifact-read and run-identity helpers
  so two contract tests no longer exceed the PLR0915 quality-ratchet threshold.
- Slice 25: moved reusable OpenAI Agents live timing interpretation out of the
  Molmo cleanup launcher script and into the agent runtime layer.
- Slice 26: moved Agibot operator safety-gate interpretation out of the SDK
  subprocess adapter and into the household operator-gates owner.
- Slice 27: merged visual-grounding runtime-parameter sanitization into the
  visual-grounding contract owner and removed two duplicate private helpers.
- Slice 28: moved Agibot simulated runtime envelopes, stage artifact writing,
  and relative-path formatting into the Agibot contract-rehearsal runtime
  owner, and updated contract tests to assert active GDK navigation claims
  instead of scanning capability-profile metadata strings.
- Slice 29: deepened MolmoSpaces worker robot-view output assembly and
  scene-alignment point collection inside the current worker-output owner.
- Slice 30: split operator-console scene-sampler readiness and static
  overview/output UI assertion helpers so tests no longer produce current
  PLR0915 quality-ratchet rows.
- Slice 31: deepened MolmoSpaces map-preparation room category rules into an
  ordered table and added interface-level priority/fallback coverage.
- Slice 32: moved Codex live-run timing calculation and MCP trace timing reads
  into the existing agent-layer live timing owner.
- Slice 33: merged duplicate operator-console JSONL source-error formatting in
  the interactions owner.
- Slice 34: removed the stale opt-in CI live-report `claude-code-kimi-k2.6`
  workflow matrix/download surfaces and added a regression guard tying the
  workflow to the `MODEL_ENTRIES` registry.
- Slice 35: removed the broken opt-in CI live-report `claude-code-mimo-v2.5`
  registry/workflow row and deleted the now-dead Claude version-check branch
  from the live CI matrix runner.
- Slice 36: migrated the current MolmoSpaces apple-to-apple grid away from
  retired `codex-cli` / `claude-code` launch rows to the active
  `openai-agents-sdk` Codex router route and added launch-catalog validation
  for generated cleanup rows.
- Slice 37: aligned the top-level architecture diagram's agent-engine layer
  with the current SDK/direct public engine set and added a focused diagram
  guard.

Next proof:

```bash
node /home/mi/.codex/skills/intuitive-reduce-entropy/scripts/high-noise-summary.mjs --examples 8
.venv/bin/python scripts/dev/check_python_quality_ratchet.py
# Then run a fresh targeted post-Slice-35 stale-surface discovery pass.
```

Stop condition:

- Stop for public contract migration, unavailable proof, external/hardware
  evidence, or two consecutive fresh post-HEAD no-clear-candidate handoffs.
- Current stop reason: not met after Slice 35; reset discovery from the new
  HEAD and require fresh no-clear passes before parking again.

No-touch scope:

- Do not remove historical plan/ADR evidence solely because it names retired
  surfaces.
- Do not change live simulator/provider behavior in this campaign without a
  focused proof gate.

Parked work:

- Public MolmoSpaces `world=molmospaces/val_*` alias removal needs an accepted
  public command migration; current docs still describe selected aliases as
  launchable.
- Broader cleanup demo contract tests currently fail on missing
  `agent_view.observed_objects`; resolve as a separate Agent View v2/test
  migration decision. This also blocks broad artifact-report re-render proof
  for historical run-result shells; wrapper deletions should use focused
  no-caller/importability proof unless that owner behavior is changed.
- Obsolete checker flag removal needs public checker CLI migration approval
  because it would change an actionable error into a generic unknown-flag error.
- `scripts/molmo_cleanup/run_molmospaces_scene_camera_comparison.py` remains
  parked: it is a pass-through module CLI wrapper, but it is still the path
  used by `just/molmo.just` and covered by a CLI contract test. Removing it
  safely would need a separate recipe/test migration around a simulator-heavy
  surface.
- No-clear pass 1 parked `scripts/maps/check_bundle.py`,
  `scripts/maps/export_agibot_map_bundle.py`, and
  `scripts/molmo_cleanup/prepare_molmospaces_room.py` because they still own
  real CLI argument/default behavior instead of pure pass-through wrapper
  behavior.
- Remaining current quality-ratchet queue: broader oversized-module baseline
  drift across Agibot, Molmo, visual-grounding, and test files. Treat as
  architecture pressure and try safe owner-local shrink slices before
  considering a baseline refresh.
- Latest quality-ratchet residual after Slice 28: failures remain in
  `agibot_map_build_mcp_server.py`, `realworld_contract.py`, several
  `scripts/molmo_cleanup/*` files, and large contract/unit tests. These are
  outside the final Agibot runtime-owner slice.
- Latest quality-ratchet residual after Slice 29: current complexity rows
  remain in
  `tests/unit/operator_console/test_scene_sampler_readiness_export.py:_assert_projection_readiness_and_candidates`
  and
  `tests/unit/operator_console/test_static_assets.py:test_static_app_uses_overview_workspace_and_outputs_copy`.
  Treat broader oversized-module drift as architecture pressure and prefer
  safe owner-local shrink slices before any baseline refresh.
- Latest quality-ratchet residual after Slice 33: no current Ruff complexity
  rows remain. Remaining full-ratchet failures are oversized-module baseline
  drift across household, launch, operator-console, scripts, and large tests;
  select only owner-local shrink slices that delete, merge, canonicalize, or
  clearly deepen a real owner concept.
- Fresh post-`ce26d3ca` quality-ratchet proof passes:
  `python-quality-ratchet: ok (2 Ruff violations at/below baseline, 83 oversized modules at/below baseline)`.
- No-clear pass 1 after Slice 33: public MolmoSpaces alias/checker-flag
  migrations remain parked; `operator_console.state` already centralizes JSON
  source errors; remaining oversized owners need broader domain contracts or
  test-suite restructuring rather than a safe autonomous slice.
- No-clear pass 2 after Slice 33: `run_molmospaces_scene_camera_comparison.py`
  remains a live recipe wrapper; the small map/preparation scripts still own
  CLI defaults or output formatting; `operator_console.jsonl_sources` and the
  merged interaction source-error helper already cover the JSONL/source-error
  owner; public MolmoSpaces `val_*` aliases remain documented/tested launch
  surfaces; remaining quality-ratchet failures are oversized-module baseline
  drift that needs a new owner-specific plan or reviewed baseline decision.
