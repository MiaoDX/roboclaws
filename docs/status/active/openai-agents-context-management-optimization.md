# OpenAI Agents Context Management Optimization

Status: DONE

Source plan: `docs/plans/2026-07-02-openai-agents-context-management-optimization.md`

Latest intent: implement the approved plan through `intuitive-flow`.

Current slice: complete. The MolmoSpaces MapBuild product proof now finishes
with `run_result.json` while using the default `context_managed_v1` profile.

Completed batch summary:

- `context_managed_v1` is the default profile and `baseline` remains explicit.
- Managed camera-grounded MapBuild prompts use
  `observe_camera_grounded_candidates`.
- Raw-FPV budgets remain lane-specific and observe budget classification is
  lane-neutral.
- `RunConfig.call_model_input_filter` now runs budget checks before each SDK
  model call, even when compaction is disabled but budget limits are configured.
- Model-input compaction keeps the first full `metric_map` visible even when SDK
  call ids are opaque, and summarizes repeated maps only.
- Managed MapBuild prompt rendering aligns the one-observe-per-waypoint budget
  with scan-profile guidance and generic skill-context precedence.

Final deterministic proof:

```bash
./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents/test_live_runtime.py tests/unit/agents/test_household_cleanup_prompts.py tests/unit/agents/test_openai_agents_model_input_config.py tests/unit/agents/test_openai_agents_budget_sources.py tests/unit/operator_console/test_routes.py tests/unit/operator_console/test_launcher.py
.venv/bin/ruff check scripts/molmo_cleanup/openai_agents_perf_profile.py scripts/molmo_cleanup/openai_agents_budget.py scripts/molmo_cleanup/run_live_openai_agents_cleanup.py roboclaws/agents/drivers/openai_agents_budget.py roboclaws/agents/drivers/openai_agents_model_input.py roboclaws/agents/drivers/openai_agents_live.py roboclaws/agents/prompts/household_cleanup.py roboclaws/operator_console/routes.py tests/unit/agents/test_live_runtime.py tests/unit/agents/test_household_cleanup_prompts.py tests/unit/agents/test_openai_agents_model_input_config.py tests/unit/agents/test_openai_agents_budget_sources.py tests/unit/operator_console/test_routes.py tests/unit/operator_console/test_launcher.py
.venv/bin/ruff format --check scripts/molmo_cleanup/openai_agents_perf_profile.py scripts/molmo_cleanup/openai_agents_budget.py scripts/molmo_cleanup/run_live_openai_agents_cleanup.py roboclaws/agents/drivers/openai_agents_budget.py roboclaws/agents/drivers/openai_agents_model_input.py roboclaws/agents/drivers/openai_agents_live.py roboclaws/agents/prompts/household_cleanup.py roboclaws/operator_console/routes.py tests/unit/agents/test_live_runtime.py tests/unit/agents/test_household_cleanup_prompts.py tests/unit/agents/test_openai_agents_model_input_config.py tests/unit/agents/test_openai_agents_budget_sources.py tests/unit/operator_console/test_routes.py tests/unit/operator_console/test_launcher.py
```

Final product/live proof:

```bash
just dev::network-status
just run::surface surface=household-world world=molmospaces/val_0 backend=mujoco preset=map-build agent_engine=openai-agents-sdk provider_profile=codex-router-responses evidence_lane=camera-grounded-labels camera_labeler=grounding-dino scenario_setup=baseline seed=7
```

Evidence:

- `just dev::network-status` returned `network: work` with SDK live routes
  allowed through repo-local `CODEX_BASE_URL` / `CODEX_API_KEY`.
- Product run directory:
  `output/household/household-world/map-build/openai-agents-live-camera-grounded-labels/0702_2014/seed-7`.
- `live_status.json`: `phase=finished`, `exit_status=0`.
- `live_timing.json`: `profile_id=context_managed_v1`, `source=default`,
  deterministic compaction enabled, provider-native compaction `mode=off`,
  composite camera-grounded tool enabled, and no budget terminal failure.
- `trace.jsonl`: seven `observe_camera_grounded_candidates` responses and one
  underlying `observe` response per inspection waypoint.
- `run_result.json`, `runtime_metric_map.json`, `agent_view.json`, and
  `report.html` exist.

Stop condition: satisfied.

No-touch scope: unrelated eval/docs long-horizon changes already present in the
worktree remain out of this task.

Parked work: provider-native compaction remains off and requires separate proof.
