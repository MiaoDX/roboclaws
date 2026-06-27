# Refactor: Architecture Cleanup Campaign

**Status:** Active
**Created:** 2026-06-23
**Source:** `$intuitive-reduce-entropy` saturation scan,
`$improve-codebase-architecture` report-only review, `$intuitive-refactor`
ratchet campaign

## Scope

Run repeated, verified refactor slices that make the current architecture
smaller and truer. Prefer stale-surface deletion, duplicate-owner merge,
canonical-owner migration, compatibility shim removal, stale tests/docs
removal, and bounded module deepening.

## Campaign Gate

Campaign overlay: true

Current quality signal:

- Tracked first-party source has 229 Python files and about 91k lines.
- Several current tests still import compatibility owners that the public
  launch path no longer uses.
- High-noise local artifacts exist, but ignored runtime outputs are not in
  scope unless tracked references make them live.

Architecture pressure:

- Public launch axes are canonical in `roboclaws.launch`.
- Thin runtime/server adapters should not preserve obsolete wrappers.
- Tests should prove current owners instead of keeping stale import paths alive.

Verification inventory:

- Focused pytest through `./scripts/dev/run_pytest_standalone.sh ...`.
- Ruff through `.venv/bin/ruff check ...` when source Python changes.
- Stale-reference searches with `rg`.
- `git diff --check` for every slice.

Checkpoint cadence:

- Update `docs/status/active/architecture-cleanup-campaign.md` after each
  verified slice.
- Commit each verified slice atomically.

Active capsule:

- `docs/status/active/architecture-cleanup-campaign.md`

Continue criteria:

- The next slice deletes, merges, or canonicalizes a real concept.
- The slice is internal or has an accepted public migration.
- Focused proof can observe the changed behavior.

Stop/park criteria:

- Product/design decision required.
- Public CLI/import/schema/report migration lacks accepted scope.
- Hardware, credentials, manual proof, or unavailable external contract is
  required.
- Two consecutive post-HEAD discovery handoffs find no clear safe P1/P2 slice
  after shrink attempts.

Current stop reason:

- Not met after Slice 34. The earlier post-Slice-33 stop was reopened by a
  fresh current workflow/registry drift found at `ce26d3ca`; resume discovery
  from the new verified HEAD.

Discovery source:

- Repo entropy saturation scan against current HEAD.
- Architecture report-only review using Roboclaws domain terms and architecture
  module/interface/seam vocabulary.

Surface metrics:

| Slice | Surfaces deleted | Duplicate owners merged | Callers migrated | Tests/docs updated | Public contracts |
| --- | ---: | ---: | ---: | ---: | --- |
| Delete `devtools.commands` launch shim | 1 | 1 | 2 | 2 | preserved |
| Remove `LaunchPlan.mode` alias | 1 | 1 | 4 | 2 | preserved |
| Remove `TaskSurfaceSpec.name` alias | 1 | 1 | 0 | 0 | preserved |
| Delete duplicate root cleanup example wrapper | 1 | 1 | 0 | 0 | preserved |
| Delete root script symlink shims | 9 | 9 | 0 | 0 | preserved |
| Delete `SIM_SERVER_URL` bootstrap fallback | 1 | 1 | 0 | 1 | preserved |
| Delete empty `roboclaws.openclaw` package | 1 | 1 | 1 | 1 | preserved |
| Delete stale AI issues roadmap | 1 | 1 | 0 | 0 | preserved |
| Move operator-console display run id to state owner | 0 | 1 | 1 | 0 | preserved |
| Delete private path-containment helpers | 4 | 4 | 4 | 0 | preserved |
| Delete stale AI2-THOR/harness agent docs | 4 | 4 | 0 | 0 | preserved |
| Delete provider timing proxy script wrapper | 1 | 1 | 0 | 1 | preserved |
| Replace stale OpenClaw image-update command | 1 | 1 | 0 | 2 | preserved |
| Replace stale OpenClaw doc paths | 0 | 1 | 0 | 3 | preserved |
| Delete unused launch context holder | 1 | 1 | 0 | 1 | preserved |
| Delete cleanup report regeneration script wrapper | 1 | 1 | 0 | 1 | preserved |
| Delete Kimi-only key checker wrapper | 1 | 1 | 0 | 1 | preserved |
| Update stale OpenClaw image-bump docs | 0 | 1 | 0 | 2 | preserved |
| Move model-matrix benchmark helpers to agent owner | 2 | 1 | 1 | 1 | preserved |
| Delete Pages prune script wrapper | 1 | 1 | 1 | 2 | preserved |
| Deepen provider registry CLI dispatch | 0 | 1 | 0 | 0 | preserved |
| Deepen cleanup MCP server initialization | 3 | 1 | 0 | 0 | preserved |
| Simplify OpenAI Agents runner status loop | 0 | 1 | 0 | 0 | preserved |
| Shrink Agibot contract-test PLR0915 rows | 0 | 1 | 0 | 0 | preserved |
| Move live timing interpretation to agent owner | 0 | 1 | 1 | 1 | preserved |
| Move Agibot operator gates to household owner | 0 | 1 | 1 | 1 | preserved |
| Merge visual-grounding runtime parameter sanitizer | 0 | 2 | 2 | 1 | preserved |
| Move Agibot contract-rehearsal runtime owner | 0 | 1 | 2 | 1 | preserved |
| Deepen MolmoSpaces robot-view output owner | 0 | 1 | 0 | 0 | preserved |
| Split operator-console assertion helpers | 0 | 1 | 0 | 0 | preserved |
| Deepen MolmoSpaces category rules | 0 | 1 | 0 | 1 | preserved |
| Move Codex live timing to agent owner | 0 | 1 | 1 | 0 | preserved |
| Merge operator-console source-error helpers | 0 | 1 | 0 | 0 | preserved |
| Align Molmo live CI workflow with report registry | 1 | 1 | 0 | 1 | preserved |

Low-value stop signal:

- Only ignored artifacts, wording polish, single-file neatness, or line motion
  remains.

Discovery cadence:

- Run a fresh reduce-entropy discovery handoff when the candidate queue is
  exhausted.

Consecutive no-clear-candidate passes: 0

## Candidate Queue

Fresh post-HEAD discovery after `39846ccb` found that the Python quality
ratchet fails on current source. The first safe slice removed the new
`provider_registry.py:_main` complexity violation by deepening provider
registry CLI dispatch behind private command helpers while preserving the
public module CLI.

Next clear candidates:

- Fresh post-HEAD discovery on 2026-06-25 found a current false-confidence
  candidate: `.venv/bin/python scripts/dev/check_python_quality_ratchet.py`
  failed with new complexity rows in
  `scripts/molmo_cleanup/molmospaces_worker_outputs.py` plus two
  operator-console test helpers. Slice 29 removed the MolmoSpaces worker output
  rows. Slice 30 split the operator-console assertion helpers, so the ratchet
  now reports only oversized-module baseline drift.

The quality-ratchet proof now passes at `ce26d3ca` after later
baseline/contract updates:
`python-quality-ratchet: ok (2 Ruff violations at/below baseline, 83 oversized modules at/below baseline)`.
Fresh post-`ce26d3ca` discovery found one current false-confidence candidate:
the opt-in Molmo live CI workflow still scheduled/downloaded
`claude-code-kimi-k2.6`, while the `MODEL_ENTRIES` registry no longer declares
that entry. Slice 34 removed the stale workflow matrix/download surfaces and
added a focused guard tying the workflow to the registry.

Next clear candidates:

- Run fresh post-Slice-34 discovery from the new verified HEAD.

Checked and parked:

- Tiny script wrapper scan: `scripts/molmo_cleanup/run_molmospaces_scene_camera_comparison.py`
  is still a live `just/molmo.just` recipe path and has a CLI contract test.
  Removing it safely would require a separate recipe/test migration around a
  simulator-heavy surface.
- Tiny script scan: `scripts/maps/check_bundle.py`,
  `scripts/maps/export_agibot_map_bundle.py`, and
  `scripts/molmo_cleanup/prepare_molmospaces_room.py` still own real CLI
  argument/default behavior rather than pure pass-through wrapper behavior.
- Current stale-token scan: remaining hits are intentional regression guards,
  current public aliases, historical docs explicitly marked as historical, or
  compatibility readers for persisted artifacts.
- Second post-HEAD handoff after `9c70b796` rechecked the same script-wrapper,
  package micro-module, stale owner-name, docs/tests/recipes, and high-noise
  surfaces. It found no new material safe slice.
- Third post-HEAD handoff after `39846ccb` found a new false-confidence
  candidate: `scripts/dev/check_python_quality_ratchet.py` fails on current
  source. Medium-risk handling split this into safe internal slices for each
  new complexity violation before considering broader oversized-module
  baseline drift.
- Fresh 2026-06-25 handoff after `12b66126` found four new current complexity
  rows. Slice 29 removed the two MolmoSpaces worker-output rows. Remaining
  current complexity rows were
  `tests/unit/operator_console/test_scene_sampler_readiness_export.py:_assert_projection_readiness_and_candidates`
  and
  `tests/unit/operator_console/test_static_assets.py:test_static_app_uses_overview_workspace_and_outputs_copy`;
  Slice 30 removed both rows. A direct summary check then exposed one remaining
  C901 row in `roboclaws/maps/molmospaces_preparation.py`; Slice 31 replaced
  that branch ladder with ordered category rules and interface-level coverage,
  leaving the ratchet summary at zero Ruff complexity violations.
- Post-`29e3d316` discovery checked the remaining oversized-module drift and
  found a bounded duplicate-owner slice in live-run timing: the retired Codex
  runner still carried local timing and MCP trace helpers while
  `roboclaws.agents.live_timing` already owned the active live-agent timing
  interface. Slice 32 moved only that internal timing interpretation into the
  agent owner and preserved the script path, tested error labels, and output
  schema.
- Post-`7cd1b445` discovery found one more bounded same-owner merge in
  `roboclaws.operator_console.interactions`: operator message and resume JSONL
  source-error formatting used parallel private helpers. Slice 33 merged those
  helpers while preserving source labels and existing error text.
- Post-`60f9fd67` discovery pass 1 checked current ratchet summary, top
  oversized household/report/operator-console/script owners, stale/public alias
  hits, checker legacy flags, operator-console state JSON source helpers, and
  raw-FPV semantic aliasing. It found no clear safe P1/P2 slice after shrink
  attempts.
- Post-`60f9fd67` discovery pass 2 independently checked the ratchet proof,
  exact oversized-module failures, small script/module surfaces, repeated
  private-helper names, text/JSON source readers, live MolmoSpaces aliases, and
  operator-console JSONL/source helpers. The ratchet summary still reports
  zero Ruff complexity violations, and the full ratchet still fails only on
  oversized-module baseline drift. No implementation slice passed the campaign
  bar: remaining candidates require public command migration, broader
  test-suite/report restructuring, domain-contract decisions, or would only
  move lines without deleting, merging, or canonicalizing a real concept.
- Fresh post-`ce26d3ca` discovery confirmed the quality ratchet now passes, but
  found current CI workflow drift against the live-report registry. Slice 34
  removed the stale `claude-code-kimi-k2.6` workflow matrix entry and stale
  Pages artifact download step, then added a registry/workflow sync guard in
  `tests/unit/molmo_cleanup/test_ci_live_workflow_entries.py`.

The campaign is active again after Slice 34. Park only after fresh
post-Slice-34 discovery satisfies the no-clear-candidate stop rule.

The campaign resumed on explicit user instruction after the final verified
Slice 28 stop.

## Completed Slices

- 2026-06-23: Deleted the test-only `roboclaws.devtools.commands` launch
  compatibility module. Migrated dev-tool route tests to
  `roboclaws.launch.catalog.resolve_surface_launch` and `LaunchError`, so tests
  now prove the canonical public launch catalog directly.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/dev_tools/test_task_agent_just_recipes.py::test_surface_router_is_importable_source_of_truth tests/contract/dev_tools/test_code_just_recipes.py::test_retired_photo_task_facade_rejects_ai2thor_surface -q
  rg -n "roboclaws\.devtools\.commands|resolve_surface_run|CommandError|ResolvedCommand" roboclaws tests docs/human docs/agents just scripts .github pyproject.toml
  git diff --check
  ```

- 2026-06-23: Removed the `LaunchPlan.mode` compatibility accessor and
  migrated tracked callers/tests to the canonical `evidence_mode` field. Kept
  the public trace label `mode=...` unchanged as output text only.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/dev_tools/test_task_agent_just_recipes.py::test_surface_router_is_importable_source_of_truth tests/contract/dev_tools/test_task_agent_just_recipes.py::test_python_launch_plan_accepts_world_labels_sanitized_lane tests/unit/evals/test_eval_runner.py::test_live_surface_command_uses_current_public_launch_axes -q
  rg -n "plan\.mode|resolved\.mode|\.mode ==|\.mode\b" roboclaws tests
  git diff --check
  ```

- 2026-06-23: Removed the unused `TaskSurfaceSpec.name` compatibility accessor.
  No tracked current caller used the alias; launch task specs now expose only
  `surface_id`.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/dev_tools/test_task_agent_just_recipes.py::test_surface_router_is_importable_source_of_truth tests/contract/dev_tools/test_task_agent_just_recipes.py::test_surface_launch_plan_exposes_domain_metadata_before_dispatch tests/unit/launch/test_environment_setup_catalog.py -q
  rg -n "TaskSurfaceSpec|surface\.name|spec\.name|\.name ==|Compatibility accessor|compatibility accessor" roboclaws/launch tests/unit/launch tests/contract/dev_tools docs/human docs/agents just scripts .github pyproject.toml
  git diff --check
  ```

  Note: the first proof attempt used a nonexistent specific test selector in
  `tests/unit/launch/test_environment_setup_catalog.py` and failed during
  collection before executing tests; the corrected focused command above passed.

- 2026-06-23: Deleted the duplicate root
  `examples/molmospaces_realworld_cleanup.py` wrapper. The canonical manual
  wrapper remains at `examples/molmo_cleanup/molmospaces_realworld_cleanup.py`,
  and current tracked callers already use that nested path.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/checkers/test_check_molmo_realworld_cleanup_result.py::test_checker_rejects_legacy_canonical_robot_view_camera_control_flag -q
  python examples/molmo_cleanup/molmospaces_realworld_cleanup.py --help
  rg -n "examples/molmospaces_realworld_cleanup|examples/molmo_cleanup/molmospaces_realworld_cleanup|molmospaces_realworld_cleanup.py" README.md ARCHITECTURE.md STATUS.md docs/human docs/agents just scripts tests roboclaws .github pyproject.toml examples
  git diff --check
  ```

  Note: a broader proof attempt against
  `tests/contract/molmo_cleanup/test_molmospaces_realworld_cleanup.py` exposed
  unrelated current artifact-shape failures around missing
  `agent_view.observed_objects`. The wrapper deletion was narrowed to
  stale-reference and canonical-wrapper proof.

- 2026-06-23: Deleted nine unreferenced root `scripts/*` symlink shims:
  `check_kimi_key.py`, `control_ui_watcher.py`, `network_status.sh`,
  `openclaw-bootstrap.sh`, `openclaw-defaults.env`,
  `openclaw_plugin_allowlist.py`, `regenerate_molmo_cleanup_report.py`,
  `run_pytest_standalone.sh`, and `write_pages_index.py`. Current tracked
  docs, tests, and recipes already use canonical subdirectory paths such as
  `scripts/dev/run_pytest_standalone.sh` and
  `scripts/openclaw/openclaw-bootstrap.sh`.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/providers/test_check_kimi_key.py tests/unit/openclaw/test_control_ui_watcher.py tests/unit/scripts/test_network_status_guard.py tests/contract/openclaw/test_openclaw_bootstrap.py::test_plugins_allow_seeded_from_canonical_allowlist tests/contract/openclaw/test_openclaw_bootstrap.py::test_bootstrap_reads_canonical_plugin_allowlist -q
  rg -n "scripts/(check_kimi_key\.py|control_ui_watcher\.py|network_status\.sh|openclaw-bootstrap\.sh|openclaw-defaults\.env|openclaw_plugin_allowlist\.py|regenerate_molmo_cleanup_report\.py|run_pytest_standalone\.sh|write_pages_index\.py)" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents just scripts tests roboclaws .github pyproject.toml
  for p in scripts/dev/check_kimi_key.py scripts/openclaw/control_ui_watcher.py scripts/dev/network_status.sh scripts/openclaw/openclaw-bootstrap.sh scripts/openclaw/openclaw-defaults.env scripts/openclaw/openclaw_plugin_allowlist.py scripts/reports/regenerate_molmo_cleanup_report.py scripts/dev/run_pytest_standalone.sh scripts/reports/write_pages_index.py; do test -e "$p"; done
  git diff --check
  ```

  Note: two earlier OpenClaw proof attempts used nonexistent specific test
  selectors; the corrected command above passed.

- 2026-06-23: Removed the stale `SIM_SERVER_URL` translate-and-warn fallback
  from `scripts/openclaw/openclaw-bootstrap.sh`. The bootstrap interface now
  names only `ROBOCLAWS_MCP_URL`, while the default
  `http://host.docker.internal:18788/mcp` and explicit override behavior are
  preserved. Added a contract guard so the old HTTP sim-server owner does not
  return as a compatibility path.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/openclaw/test_openclaw_bootstrap.py::test_mcp_seeds_server_transport_and_url tests/contract/openclaw/test_openclaw_bootstrap.py::test_mcp_url_env_override_honored tests/contract/openclaw/test_openclaw_bootstrap.py::test_bootstrap_has_no_sim_server_url_compatibility_path -q
  bash -n scripts/openclaw/openclaw-bootstrap.sh
  .venv/bin/ruff check tests/contract/openclaw/test_openclaw_bootstrap.py
  rg -n -F "SIM_SERVER_URL" scripts/openclaw tests/contract/openclaw just/openclaw.just just/chat.just just/molmo.just roboclaws/cli/household_agent_server.py docs/human/openclaw README.md ARCHITECTURE.md AGENTS.md CLAUDE.md
  git diff --check
  ```

  Note: the stale-reference search now returns only the intentional regression
  guard in `tests/contract/openclaw/test_openclaw_bootstrap.py`; production
  bootstrap, recipes, current docs, and runtime adapters no longer reference
  the legacy variable.

- 2026-06-23: Deleted the empty `roboclaws.openclaw` source package and removed
  the pre-commit hook branch that still treated `roboclaws/openclaw/*` as a
  current source owner. OpenClaw maintainer implementation remains under
  `scripts/openclaw/`; the tracked `tests/unit/openclaw` test still targets
  `scripts/openclaw/control_ui_watcher.py` directly.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/dev_tools/test_verify_just_recipes.py::test_pre_commit_runs_scoped_tests_by_default_with_full_fast_opt_in tests/contract/dev_tools/test_verify_just_recipes.py::test_pre_commit_no_longer_infers_retired_domains tests/unit/openclaw/test_control_ui_watcher.py -q
  test ! -e roboclaws/openclaw && python - <<'PY'
  import importlib.util
  spec = importlib.util.find_spec('roboclaws.openclaw')
  assert spec is None, spec
  PY
  .venv/bin/ruff check tests/contract/dev_tools/test_verify_just_recipes.py tests/unit/openclaw/test_control_ui_watcher.py
  rg -n "roboclaws/openclaw|roboclaws\.openclaw|tests/unit/openclaw" .githooks tests/contract/dev_tools tests/unit/openclaw roboclaws scripts examples docs/human docs/agents README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md pyproject.toml .github
  git diff --check
  ```

  Note: local generated `roboclaws/openclaw/__pycache__` files were removed
  before the import proof; they were untracked cache from retired modules. The
  stale-reference search now returns only the intentional regression guard in
  `tests/contract/dev_tools/test_verify_just_recipes.py`.

- 2026-06-23: Deleted `docs/ai/planning/issues-roadmap.md`, an unreferenced
  current-looking AI2-THOR/OpenClaw issue roadmap that conflicted with the
  current issue-tracker source of truth in `docs/agents/issue-tracker.md` and
  GitHub Issues. Historical planning and retrospective evidence was left
  untouched.

  Proof:

  ```bash
  rg -n "docs/ai/planning/issues-roadmap.md|docs/ai/planning|issues-roadmap.md|GitHub Issues Roadmap|Issue 1: AI2-THOR|roboclaws/openclaw/skill.py|roboclaws/openclaw/bridge.py" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai .github just scripts tests pyproject.toml
  test ! -e docs/ai/planning/issues-roadmap.md && test -f docs/agents/issue-tracker.md && test -f docs/agents/triage-labels.md
  git diff --check
  ```

- 2026-06-23: Moved the duplicated operator-console display run id rule from
  `roboclaws.operator_console.history` to the existing
  `roboclaws.operator_console.state` owner. History now calls
  `display_run_id(...)`, so nested wrapper-attempt ids are normalized by one
  operator-state interface instead of two private helpers.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console/test_state.py::test_state_surfaces_malformed_nested_live_status_and_run_result tests/unit/operator_console/test_state.py::test_state_follows_nested_live_attempt_under_console_wrapper tests/unit/operator_console/test_history.py::test_latest_run_payload_uses_history_index_and_nested_attempt_artifacts tests/unit/operator_console/test_history.py::test_latest_run_payload_surfaces_malformed_run_sidecar -q
  .venv/bin/ruff check roboclaws/operator_console/state.py roboclaws/operator_console/history.py
  rg -n "def _display_run_id|_display_run_id\(|display_run_id\(" roboclaws/operator_console tests/unit/operator_console -g '*.py'
  git diff --check
  ```

  Note: the first proof attempt used stale specific test selectors and failed
  during collection before executing tests; the corrected focused command above
  passed.

- 2026-06-23: Deleted four private `_is_relative_to` helpers in
  `roboclaws.operator_console.paths`, `roboclaws.operator_console.state`,
  `roboclaws.operator_console.server`, and `roboclaws.devtools.pages_site`.
  The repo's Python floor is 3.12, so these modules now use the native
  `Path.is_relative_to(...)` interface directly for operator artifact serving,
  preview serving, and Pages prune containment checks.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console/test_operator_console.py::test_operator_console_serves_only_operator_output_artifacts tests/unit/operator_console/test_operator_console.py::test_operator_console_serves_scene_preview_assets tests/contract/reports/test_pages_site_prune.py::test_prune_pages_site_does_not_allow_references_outside_site -q
  .venv/bin/ruff check roboclaws/operator_console/paths.py roboclaws/operator_console/state.py roboclaws/operator_console/server.py roboclaws/devtools/pages_site.py
  rg -n "def _is_relative_to|_is_relative_to\(" roboclaws tests -g '*.py'
  git diff --check
  ```

  Note: the stale-helper search exits with no matches, which is the expected
  result.

- 2026-06-23: Deleted four stale agent-only docs under `docs/ai/` that still
  described retired AI2-THOR/OpenClaw game, refactor-regression, and navigator
  harness surfaces as runnable implementation guidance. Their referenced
  modules, examples, and scripts no longer exist in the current codebase; the
  shipped historical context remains in `.planning/` and current run guidance
  remains in `README.md`, `ARCHITECTURE.md`, `just/README.md`, and
  `docs/human/`.

  Deleted:

  - `docs/ai/deployment/ai2thor-rendering.md`
  - `docs/ai/experiments/refactor-regression.md`
  - `docs/ai/experiments/view-experiment-2026-04.md`
  - `docs/ai/harness/self-improvement-loop.md`

  Proof:

  ```bash
  test ! -e docs/ai/deployment/ai2thor-rendering.md
  test ! -e docs/ai/experiments/refactor-regression.md
  test ! -e docs/ai/experiments/view-experiment-2026-04.md
  test ! -e docs/ai/harness/self-improvement-loop.md
  rg -n "docs/ai/(deployment/ai2thor-rendering|experiments/refactor-regression|experiments/view-experiment-2026-04|harness/self-improvement-loop)|benchmark_ai2thor_rendering|capture_refactor_regression|analyze_refactor_regression|harness/run-next|harness/run.sh|harness/README" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  git diff --check
  ```

- 2026-06-23: Deleted the unused private
  `scripts/dev/provider_timing_proxy.py` wrapper. The provider timing proxy is
  already owned and launched through the module CLI
  `python -m roboclaws.agents.provider_timing_proxy`, including from
  `start_provider_timing_proxy(...)`; the implemented plan text now names only
  the canonical module owner.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents/test_provider_timing_proxy.py::test_provider_timing_proxy_cli_rejects_out_of_range_bind_port
  .venv/bin/python -m roboclaws.agents.provider_timing_proxy --help
  rg -n "scripts/dev/provider_timing_proxy.py" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai docs/plans/2026-06-11-coding-agent-provider-timing-proxy.md just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check roboclaws/agents/provider_timing_proxy.py tests/unit/agents/test_provider_timing_proxy.py
  git diff --check
  ```

- 2026-06-23: Replaced the stale
  `just openclaw::run photo` command in the OpenClaw image-upgrade checklist
  with the current maintainer dispatcher route
  `just agent::run household-world.cleanup openclaw-gateway world-public-labels`.
  Added a focused contract guard proving the doc no longer points at the
  removed private command and that the current dispatcher trace still resolves
  to the OpenClaw live implementation route without launching Docker or a
  provider.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/contract/dev_tools/test_task_agent_just_recipes.py::test_openclaw_image_update_doc_uses_current_maintainer_dispatch
  ROBOCLAWS_JUST_TRACE=1 just agent::run household-world.cleanup openclaw-gateway world-public-labels
  rg -n "just openclaw::run photo|openclaw::run" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check tests/contract/dev_tools/test_task_agent_just_recipes.py
  git diff --check
  ```

  Note: the stale-reference search now returns only intentional regression
  guards in `tests/contract/dev_tools/test_task_agent_just_recipes.py`.

- 2026-06-23: Replaced stale OpenClaw documentation paths that pointed to the
  removed `docs/openclw/` and root `docs/model-matrix.md` locations. OpenClaw
  bootstrap comments, the plugin allow-list module docstring, and OpenClaw
  bootstrap contract-test guidance now point at the current documentation
  owners under `docs/human/openclaw/`, `docs/ai/openclaw/`, and
  `docs/human/model-matrix.md`.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/contract/openclaw/test_openclaw_bootstrap.py::test_nvidia_curated_to_single_multi_image_model tests/contract/openclaw/test_openclaw_bootstrap.py::test_only_curated_providers_supported tests/contract/openclaw/test_openclaw_bootstrap.py::test_advertised_context_windows_clear_flush_headroom tests/contract/openclaw/test_openclaw_bootstrap.py::test_mcp_seeds_per_agent_tools_profile_minimal tests/contract/openclaw/test_openclaw_bootstrap.py::test_bootstrap_reads_canonical_plugin_allowlist
  bash -n scripts/openclaw/openclaw-bootstrap.sh
  .venv/bin/ruff check scripts/openclaw/openclaw_plugin_allowlist.py tests/contract/openclaw/test_openclaw_bootstrap.py
  rg -n "docs/openclw|openclw|docs/model-matrix\.md" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  git diff --check
  ```

  Note: the stale-path search exits with no matches, which is the expected
  result.

- 2026-06-23: Deleted the unused private
  `roboclaws.launch.context` module. Launch callers use the canonical
  `LaunchPlan` and `resolve_surface_launch(...)` interfaces; no tracked code,
  tests, or current docs referenced `LaunchContext`. Added a focused launch
  regression guard so the removed context-holder module does not return as
  launch-package surface area.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/unit/launch/test_environment_setup_catalog.py::test_launch_package_does_not_keep_unused_context_holder tests/unit/launch/test_environment_setup_catalog.py::test_launch_backend_catalog_exposes_private_implementation_choices tests/contract/dev_tools/test_task_agent_just_recipes.py::test_surface_router_is_importable_source_of_truth
  test ! -e roboclaws/launch/context.py && python - <<'PY'
  import importlib.util
  spec = importlib.util.find_spec('roboclaws.launch.context')
  assert spec is None, spec
  PY
  rg -n "LaunchContext|roboclaws\.launch\.context|launch/context\.py|launch\.context" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check tests/unit/launch/test_environment_setup_catalog.py roboclaws/launch
  git diff --check
  ```

  Note: the stale-reference search now returns only the intentional regression
  guard in `tests/unit/launch/test_environment_setup_catalog.py`.

- 2026-06-23: Deleted the no-caller private
  `scripts/reports/regenerate_molmo_cleanup_report.py` wrapper. The current
  owner for cleanup report re-rendering is
  `roboclaws.household.artifact_report`, whose importable
  `rerender_cleanup_reports_from_artifact_paths(...)` function remains covered
  directly by report contract tests.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/contract/reports/test_molmo_cleanup_artifact_report.py::test_regenerate_cleanup_report_script_wrapper_stays_removed tests/contract/reports/test_molmo_cleanup_artifact_report.py::test_load_cleanup_scenario_artifact_uses_adjacent_private_manifest
  python - <<'PY'
  from roboclaws.household.artifact_report import rerender_cleanup_reports_from_artifact_paths
  assert callable(rerender_cleanup_reports_from_artifact_paths)
  print(rerender_cleanup_reports_from_artifact_paths.__name__)
  PY
  test ! -e scripts/reports/regenerate_molmo_cleanup_report.py && rg -n "regenerate_molmo_cleanup_report|scripts/reports/regenerate_molmo_cleanup_report.py" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check roboclaws/household/artifact_report.py tests/contract/reports/test_molmo_cleanup_artifact_report.py
  git diff --check
  ```

  Note: a broader report re-render proof still hits the pre-existing parked
  Agent View v2 artifact-shape failure (`agent_view.observed_objects` /
  missing `agent_view_v2` sections). The wrapper deletion does not change that
  owner behavior, so this slice used no-caller and importability proof.

- 2026-06-23: Deleted the no-caller private
  `scripts/dev/check_kimi_key.py` wrapper and its wrapper-only tests. Current
  provider health checks are owned by `scripts/dev/check_model_providers.py`,
  which covers both `agents-sdk:kimi-openai-chat` and
  `provider:kimi-coding-chat` routes with Kimi-specific request and response
  guards.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/unit/providers/test_check_model_providers.py::test_provider_probe_defaults_cover_kimi_and_payload tests/unit/providers/test_check_model_providers.py::test_kimi_provider_probe_validates_provider_response_source tests/unit/providers/test_check_model_providers.py::test_kimi_provider_probe_validates_response_message_shape tests/unit/providers/test_check_model_providers.py::test_kimi_provider_probe_reads_reasoning_content_from_valid_response tests/unit/providers/test_check_model_providers.py::test_select_probe_can_limit_kimi_route_across_sdk_and_provider_probes
  test ! -e scripts/dev/check_kimi_key.py && test ! -e tests/unit/providers/test_check_kimi_key.py
  rg -n "check_kimi_key|scripts/dev/check_kimi_key.py|test_check_kimi_key" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check scripts/dev/check_model_providers.py tests/unit/providers/test_check_model_providers.py
  git diff --check
  ```

  Note: historical plans/research may still mention earlier Kimi-key smoke
  checks as dated evidence. They are not current run guidance and were left as
  history.

- 2026-06-23: Updated current OpenClaw image-bump docs that still pointed
  maintainers at a nonexistent TODO and retired territory/coverage phase
  scripts. The tool-profile note now treats `minimal + alsoAllow` as the
  current default until an image probe or accepted plan changes it, and the
  image-update checklist now names only current OpenClaw maintainer routes.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/contract/dev_tools/test_task_agent_just_recipes.py::test_openclaw_image_update_doc_uses_current_maintainer_dispatch
  ! rg -n "active TODO|minimal\\+alsoAllow:\\[bundle-mcp\\]|territory/coverage scripts|just openclaw::run photo" docs/ai/openclaw
  .venv/bin/ruff check tests/contract/dev_tools/test_task_agent_just_recipes.py
  git diff --check
  ```

- 2026-06-23: Moved the model-matrix benchmark catalog and wire-format helpers
  from sibling modules under `scripts/dev/` into the package owner
  `roboclaws.agents.model_matrix_benchmark`. The public
  `just dev::model-matrix-benchmark` command still executes
  `scripts/dev/benchmark_model_matrix.py`, but the CLI now imports provider
  route cases, result models, endpoint/payload/header helpers, response
  parsing, and stream parsing from the canonical agent/provider module instead
  of mutating `sys.path` for private script-directory helpers. The two old
  script helper modules were deleted and the MiMo migration guard now allows
  the package owner as the only helper surface for the still-current benchmark
  `mimo-v2.5-pro` probe rows.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/unit/providers/test_model_matrix_benchmark.py tests/contract/regression/test_mimo_v25_migration_guard.py
  rg -n "model_matrix_benchmark_catalog|model_matrix_benchmark_wire|scripts/dev/model_matrix_benchmark_catalog.py|scripts/dev/model_matrix_benchmark_wire.py" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check scripts/dev/benchmark_model_matrix.py roboclaws/agents/model_matrix_benchmark.py tests/contract/regression/test_mimo_v25_migration_guard.py
  git diff --check
  ```

- 2026-06-23: Deleted the pass-through
  `scripts/reports/prune_pages_site.py` wrapper and migrated the GitHub Pages
  workflow to the canonical module CLI
  `python3 -m roboclaws.devtools.pages_site site`. The package owner already
  held the Pages pruning implementation and direct unit/contract tests; this
  slice added the missing module entrypoint plus a subprocess regression test
  that proves `python -m roboclaws.devtools.pages_site` deletes unreferenced
  files before CI relies on it.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh -q tests/contract/reports/test_pages_site_prune.py
  python -m roboclaws.devtools.pages_site --help
  rg -n "scripts/reports/prune_pages_site.py|prune_pages_site.py" README.md ARCHITECTURE.md STATUS.md AGENTS.md CLAUDE.md docs/human docs/agents docs/ai just scripts tests roboclaws .github pyproject.toml
  .venv/bin/ruff check roboclaws/devtools/pages_site.py tests/contract/reports/test_pages_site_prune.py
  git diff --check
  ```

- 2026-06-23: Deepened the `roboclaws.agents.provider_registry` module CLI by
  moving command-specific model and route dispatch out of `_main(...)` into
  private helpers. This removed the new Python quality-ratchet complexity
  violation for `provider_registry.py:_main` while preserving the public
  `python -m roboclaws.agents.provider_registry ...` interface and provider
  route outputs.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/providers/test_provider_catalog.py -q
  .venv/bin/ruff check roboclaws/agents/provider_registry.py tests/unit/providers/test_provider_catalog.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on other current files, but no longer
  lists `roboclaws/agents/provider_registry.py`. The remaining failures are
  tracked as the next candidate queue.

- 2026-06-23: Deepened `RealWorldMolmoCleanupMCPServer` initialization by
  moving runtime trace setup, public artifact bootstrap, FastMCP registration,
  and initialization event writing behind same-owner private methods. The
  slice also deleted three shallow one-call/no-call helpers, so the MCP server
  module is smaller than before the slice while the public
  `make_molmo_realworld_cleanup_mcp(...)` interface and registered MCP tool
  contract are preserved.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py::test_realworld_mcp_registered_tools_match_profile_public_surface tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py::test_agent_sdk_camera_grounded_composite_tool_is_opt_in tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py::test_realworld_mcp_tool_files_are_layered_by_capability -q
  .venv/bin/ruff check roboclaws/household/realworld_mcp_server.py tests/contract/molmo_cleanup/test_molmo_realworld_mcp_server.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on other current files, but no longer
  lists `RealWorldMolmoCleanupMCPServer.__init__` or
  `roboclaws/household/realworld_mcp_server.py` module-size growth.

- 2026-06-23: Simplified
  `LiveOpenAIAgentsCleanupRunner._run_sdk_agent` by writing the initial versus
  continuation status through one expression at the top of each SDK attempt.
  This removed the new C901 violation without adding helper surface, changing
  the public script command, or growing the already-oversized runner file.

  Proof:

  ```bash
  .venv/bin/ruff check --select C901 scripts/molmo_cleanup/run_live_openai_agents_cleanup.py
  ./scripts/dev/run_pytest_standalone.sh tests/unit/agents/test_live_runtime.py::test_openai_agents_cleanup_runner_invokes_sdk_then_checker tests/unit/agents/test_live_runtime.py::test_openai_agents_cleanup_runner_continues_incomplete_sdk_turn tests/unit/agents/test_live_runtime.py::test_openai_agents_cleanup_runner_fails_after_bounded_continuation -q
  .venv/bin/ruff check scripts/molmo_cleanup/run_live_openai_agents_cleanup.py tests/unit/agents/test_live_runtime.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on other current files, but no longer
  lists `LiveOpenAIAgentsCleanupRunner._run_sdk_agent`.

- 2026-06-23: Shrunk two new Agibot contract-test PLR0915 rows by moving
  repeated artifact reads and run-identity assertions into same-file helpers.
  The slice keeps the contract assertions, public artifact names, and test
  targets unchanged while making the test owner easier to scan.

  Proof:

  ```bash
  .venv/bin/ruff check --select PLR0915 tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py tests/contract/molmo_cleanup/test_physical_agibot_pilot.py
  ./scripts/dev/run_pytest_standalone.sh tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py::test_molmospaces_agibot_contract_rehearsal_writes_simulated_report tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_physical_agibot_pilot_uses_sdk_runner_reports_without_movement -q
  .venv/bin/ruff check tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py tests/contract/molmo_cleanup/test_physical_agibot_pilot.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on broader oversized-module baseline
  drift, but no longer lists the two overlong Agibot contract tests.

- 2026-06-23: Moved reusable OpenAI Agents live timing interpretation out of
  `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py` and into the
  agent-layer `roboclaws.agents.live_timing` module. This was the smallest
  safe slice for the medium-risk oversized-launcher candidate: public
  `live_timing.json`, model metrics writing, and launcher behavior are
  preserved, while tests now import the timing/timeline interface from the
  canonical live-agent owner.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/agents/test_live_runtime.py::test_openai_agents_control_plane_metrics_parse_server_log tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_timeline_partitions_runner_and_attribution tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_compact_metrics_surface_structured_detail_errors tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_compact_metrics_tolerates_plaintext_detail tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_compact_metrics_extracts_valid_budget_detail tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_fails_aloud_on_malformed_mcp_timing_source -q
  .venv/bin/ruff check scripts/molmo_cleanup/run_live_openai_agents_cleanup.py roboclaws/agents/live_timing.py tests/unit/agents/test_live_runtime.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on broader oversized-module baseline
  drift, but no longer lists
  `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py`.

- 2026-06-23: Moved Agibot operator localization, run-enablement,
  bounded-local-nudge, and human-takeover-stop gate interpretation out of
  `roboclaws.household.agibot_sdk_runner` and into the household-layer
  `roboclaws.household.agibot_operator_gates` owner. This was the smallest
  safe slice for the medium-risk Agibot SDK runner oversized-module candidate:
  public physical-pilot payloads and SDK runner behavior are preserved, while
  contract tests now import the gate interface from the canonical owner instead
  of SDK-runner private helpers.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_agibot_sdk_runner_sources.py tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_physical_agibot_pilot_uses_sdk_runner_reports_without_movement tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_agibot_bounded_local_nudge_uses_operator_config_with_conservative_caps tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_agibot_bounded_local_nudge_rejects_unconfirmed_or_loose_operator_config tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_physical_agibot_real_movement_requires_operator_gates tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_physical_agibot_human_takeover_stop_covers_runtime_navigation_failures tests/contract/molmo_cleanup/test_physical_agibot_pilot.py::test_physical_agibot_localization_gate_enforces_optional_thresholds -q
  .venv/bin/ruff check roboclaws/household/agibot_sdk_runner.py roboclaws/household/agibot_operator_gates.py tests/contract/molmo_cleanup/test_physical_agibot_pilot.py tests/unit/molmo_cleanup/test_agibot_sdk_runner_sources.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on broader oversized-module baseline
  drift, but no longer lists `roboclaws/household/agibot_sdk_runner.py` or
  `tests/contract/molmo_cleanup/test_physical_agibot_pilot.py`.

- 2026-06-23: Merged visual-grounding runtime-parameter sanitization into
  `roboclaws.household.visual_grounding.safe_runtime_parameters` and migrated
  both `scripts/visual_grounding/adapters.py` and
  `scripts/visual_grounding/run_visual_grounding_benchmark.py` off their
  duplicate private helpers. This was a safe shrink of a medium-risk
  oversized-module candidate: the visual-grounding request/response contract
  owner now owns the interface for safe runtime knobs, while sidecar adapter
  behavior and benchmark matrix behavior are preserved.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_visual_grounding.py::test_safe_runtime_parameters_keeps_only_json_scalar_knobs tests/contract/visual_grounding/test_visual_grounding_service.py::test_real_mode_reports_grounding_dino_device_unavailable tests/contract/visual_grounding/test_visual_grounding_service.py::test_real_mode_rejects_malformed_request_runtime_parameter tests/contract/visual_grounding/test_visual_grounding_benchmark.py::test_visual_grounding_first_wave_matrix_covers_required_sweeps -q
  .venv/bin/ruff check roboclaws/household/visual_grounding.py scripts/visual_grounding/adapters.py scripts/visual_grounding/run_visual_grounding_benchmark.py tests/unit/molmo_cleanup/test_visual_grounding.py tests/contract/visual_grounding/test_visual_grounding_service.py tests/contract/visual_grounding/test_visual_grounding_benchmark.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on broader oversized-module baseline
  drift, but no longer lists `scripts/visual_grounding/adapters.py` or
  `scripts/visual_grounding/run_visual_grounding_benchmark.py`.

- 2026-06-23: Moved Agibot simulated runtime envelopes, stage result JSON/HTML
  writing, and relative-path formatting into
  `roboclaws.household.agibot_contract_rehearsal_runtime`. This was the
  smallest safe slice for the medium-risk Agibot contract-rehearsal oversized
  module candidate: `agibot_contract_rehearsal.py` no longer owns stage-runtime
  artifact rendering, `agibot_contract_rehearsal_stages.py` calls the canonical
  writer, and contract tests now assert that active simulated run evidence does
  not claim `agibot_gdk_normal_navi` while allowing capability-profile metadata
  to describe possible physical provenance.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py::test_molmospaces_agibot_contract_rehearsal_writes_simulated_report tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py::test_molmospaces_agibot_contract_rehearsal_cli_runs_without_gdk tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py::test_molmospaces_agibot_cleanup_action_rehearsal_records_simulated_substeps -q
  .venv/bin/ruff check roboclaws/household/agibot_contract_rehearsal.py roboclaws/household/agibot_contract_rehearsal_stages.py roboclaws/household/agibot_contract_rehearsal_runtime.py tests/contract/molmo_cleanup/test_molmospaces_agibot_contract_rehearsal.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on unrelated broader oversized-module
  drift, but no longer lists
  `roboclaws/household/agibot_contract_rehearsal.py` or
  `roboclaws/household/agibot_contract_rehearsal_stages.py`.

- 2026-06-25: Deepened
  `scripts/molmo_cleanup/molmospaces_worker_outputs.py` by moving robot-view
  artifact path naming and scene-alignment point collection behind same-owner
  private helpers. This removed the current quality-ratchet complexity rows
  for `write_robot_views` and `_scene_points` while preserving the worker
  command interface and robot-view output schema.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_molmo_cleanup_subprocess_backend.py::test_worker_robot_views_uses_robot_head_camera_for_fpv tests/unit/molmo_cleanup/test_molmo_cleanup_subprocess_backend.py::test_worker_robot_views_keeps_backend_local_fallback_without_pose -q
  .venv/bin/ruff check scripts/molmo_cleanup/molmospaces_worker_outputs.py
  .venv/bin/ruff format --check scripts/molmo_cleanup/molmospaces_worker_outputs.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on two unrelated operator-console test
  helper PLR0915 rows plus broader oversized-module baseline drift, but no
  longer lists `scripts/molmo_cleanup/molmospaces_worker_outputs.py`.

- 2026-06-25: Split overlong operator-console assertion helpers in
  `tests/unit/operator_console/test_scene_sampler_readiness_export.py` and
  `tests/unit/operator_console/test_static_assets.py` into same-file
  assertion vocabulary. This removed the remaining current quality-ratchet
  Ruff complexity rows while preserving the scene-sampler readiness and static
  overview/output UI contract assertions.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console/test_scene_sampler_readiness_export.py::test_scene_sampler_readiness_export_writes_artifacts tests/unit/operator_console/test_static_assets.py::test_static_app_uses_overview_workspace_and_outputs_copy -q
  .venv/bin/ruff check --select PLR0915 tests/unit/operator_console/test_scene_sampler_readiness_export.py tests/unit/operator_console/test_static_assets.py
  .venv/bin/ruff check tests/unit/operator_console/test_scene_sampler_readiness_export.py tests/unit/operator_console/test_static_assets.py
  .venv/bin/ruff format --check tests/unit/operator_console/test_scene_sampler_readiness_export.py tests/unit/operator_console/test_static_assets.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py
  git diff --check
  ```

  Note: the quality ratchet still fails on broader oversized-module baseline
  drift, but no current Ruff complexity rows remain.

- 2026-06-25: Replaced the MolmoSpaces map-preparation semantic category
  branch ladder with an ordered rule table owned by
  `roboclaws.maps.molmospaces_preparation`. This preserves the existing
  priority order and default category while removing the remaining direct Ruff
  C901 row. The focused contract test observes categories through
  `prepare_molmospaces_base_metric_map` instead of coupling to the private
  helper.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/contract/maps/test_generate_molmospaces_scene_bundles.py::test_molmospaces_room_category_rules_preserve_priority_and_fallback -q
  .venv/bin/ruff check --select C901 roboclaws/maps/molmospaces_preparation.py --output-format=concise
  .venv/bin/ruff check roboclaws/maps/molmospaces_preparation.py tests/contract/maps/test_generate_molmospaces_scene_bundles.py
  .venv/bin/ruff format --check roboclaws/maps/molmospaces_preparation.py tests/contract/maps/test_generate_molmospaces_scene_bundles.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py --summary --top 25
  git diff --check
  ```

  Note: the quality ratchet summary reports zero Ruff complexity violations;
  the full quality ratchet still fails on broader oversized-module baseline
  drift.

- 2026-06-25: Moved Codex live-run runner timing calculation, MCP trace timing
  reads, and first-MCP-request extraction out of
  `scripts/molmo_cleanup/run_live_codex_cleanup.py` and into the existing
  agent-layer `roboclaws.agents.live_timing` owner. This preserves the retired
  Codex runner script and its live timing output schema while reducing the
  oversized script from 1455 to 1393 lines and removing duplicate timing
  ownership next to the active OpenAI Agents timing implementation.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/molmo_cleanup/test_ci_live_reports.py::test_live_codex_timing_fails_aloud_on_malformed_trace_source tests/unit/molmo_cleanup/test_ci_live_reports.py::test_live_codex_timing_fails_aloud_on_malformed_run_result_source tests/unit/molmo_cleanup/test_ci_live_reports.py::test_live_codex_event_summary_fails_aloud_on_malformed_event_source tests/unit/molmo_cleanup/test_ci_live_reports.py::test_live_codex_provider_transient_failure_is_retryable -q
  ./scripts/dev/run_pytest_standalone.sh tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_timeline_partitions_runner_and_attribution tests/unit/agents/test_live_runtime.py::test_openai_agents_control_plane_metrics_parse_server_log tests/unit/agents/test_live_runtime.py::test_openai_agents_live_timing_fails_aloud_on_malformed_mcp_timing_source -q
  .venv/bin/ruff check roboclaws/agents/live_timing.py scripts/molmo_cleanup/run_live_codex_cleanup.py tests/unit/molmo_cleanup/test_ci_live_reports.py tests/unit/agents/test_live_runtime.py
  .venv/bin/ruff format --check roboclaws/agents/live_timing.py scripts/molmo_cleanup/run_live_codex_cleanup.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py --summary --top 40
  git diff --check
  ```

  Note: the quality ratchet summary still reports zero Ruff complexity
  violations. The full quality ratchet still fails on broader oversized-module
  baseline drift, but the Codex runner residual decreased from 1455 to 1393
  lines.

- 2026-06-25: Merged duplicate operator-message and operator-resume JSONL
  source-error formatting helpers inside
  `roboclaws.operator_console.interactions`. The interactions owner still
  exposes the same `operator_messages` / `operator_resume_requests` source
  labels and user-facing error messages, while `interactions.py` shrank from
  895 to 881 lines.

  Proof:

  ```bash
  ./scripts/dev/run_pytest_standalone.sh tests/unit/operator_console/test_interactions.py::test_operator_message_state_surfaces_malformed_source_errors tests/unit/operator_console/test_interactions.py::test_operator_message_state_surfaces_non_object_source_errors tests/unit/operator_console/test_interactions.py::test_operator_messages_keep_valid_rows_with_source_errors -q
  .venv/bin/ruff check roboclaws/operator_console/interactions.py tests/unit/operator_console/test_interactions.py
  .venv/bin/ruff format --check roboclaws/operator_console/interactions.py tests/unit/operator_console/test_interactions.py
  .venv/bin/python scripts/dev/check_python_quality_ratchet.py --summary --top 40
  git diff --check
  ```

  Note: the quality ratchet summary still reports zero Ruff complexity
  violations. The full quality ratchet still fails on broader oversized-module
  baseline drift, but `interactions.py` decreased from 895 to 881 lines.

## Parked Candidates

- Public MolmoSpaces `world=molmospaces/val_*` alias removal: current human
  docs still describe selected aliases as launchable. Removing or renaming that
  public surface needs an accepted public command migration. A safe internal
  slice may still rename implementation helpers if it preserves public world ids.
- `tests/contract/molmo_cleanup/test_molmospaces_realworld_cleanup.py`
  current artifact-shape failures: four tests still expect
  `agent_view.observed_objects`. Unblock by deciding whether those tests should
  migrate to Agent View v2 sections or whether the cleanup artifact producer
  should restore a documented compatibility field.
- Obsolete checker flag
  `--require-canonical-robot-view-camera-control`: the checker currently
  recognizes this public flag only to emit an actionable obsolete-flag error
  pointing at `--require-robot-head-camera-fpv`. Removing it would change a
  public checker error path to a generic argparse unknown-flag error. Unblock
  with an accepted public checker CLI migration decision.
