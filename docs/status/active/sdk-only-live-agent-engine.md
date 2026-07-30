# SDK-Only Live Agent Engine Cleanup

- Source plan: `docs/plans/2026-06-23-sdk-only-live-agent-engine.md`
- Latest user intent: continue and finish the persisted `intuitive-flow` implementation goal.
- Current slice: implementation and deterministic verification complete.
- Next action: review and commit the SDK-only migration when ready.
- Blocker fingerprint: none.
- Last proven evidence:
  - `./scripts/dev/run_pytest_standalone.sh -q tests/unit/providers/test_provider_catalog.py tests/unit/evals tests/unit/operator_console`
  - `./scripts/dev/run_pytest_standalone.sh -q tests/contract/dev_tools/test_task_agent_just_recipes.py tests/contract/dev_tools/test_eval_just_recipe.py tests/contract/dev_tools/test_backend_catalog_just_recipes.py tests/contract/dev_tools/test_verify_just_recipes.py`
  - `ruff check .`
  - `ruff format --check .`
- Completed slice summary: active docs, launch catalog, provider registry, eval identity/runtime, eval harness, operator console, Molmo/agent just recipes, Agibot SDK map-build route, and focused tests now use active engines `direct-runner` and `openai-agents-sdk`; `codex-cli` / `claude-code` are rejected through the retired-engine contract; dead detached live eval polling was removed; operator-console active phases use SDK naming.
- Remaining reference classification: remaining Codex/Claude strings in the searched active surface are retired-engine error text, negative assertions, historical/manual-debug coding-agent helper tests, or provider/profile compatibility names such as `codex-router-responses`.
- Stop condition: satisfied for deterministic proof. No active public/operator/eval route requires a retired engine; Agibot map-build has an SDK route.
- No-touch scope honored at completion; the later ADR-0148 retirement separately removed OpenClaw. `codex-router-responses` remained an SDK provider profile and no compatibility alias was added for retired engines.
- Parked work: optional real live SDK eval remains dependent on provider/runtime health and was not run in this deterministic closeout.
