# Operator Session Long Interaction

Status: ACTIVE

Source plan: approved chat contract, 2026-06-28.

Latest intent: implement formal Operator Session chaining, without making a
single persistent agent process.

Current slice: sanitized next-goal context injection into live SDK kickoff
prompts, session-live eval harness row, wind-down-safe Next Goal autostart, and
focused tests are implemented in the working tree.

No-touch scope: unrelated active file `docs/status/active/live-rerun-20260628.md`.

Latest proof:

```bash
ruff check .
ruff format --check .
git diff --check
./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals/test_session_live_eval.py tests/unit/evals/test_eval_harness_selector.py tests/contract/dev_tools/test_eval_just_recipe.py tests/unit/agents/test_household_cleanup_prompts.py tests/unit/operator_console/test_launcher.py tests/unit/operator_console/test_operator_console.py tests/unit/operator_console/test_interactions.py tests/contract/dev_tools/test_task_agent_just_recipes.py::test_surface_launch_exports_operator_session_context_to_lower_recipe_environment tests/contract/dev_tools/test_task_agent_just_recipes.py::test_molmo_cleanup_recipe_passes_goal_contract_to_all_household_runners
```

Latest true live proof:

```bash
just dev::network-status
just agent::eval session-live budget=smoke agent_engine=openai-agents-sdk provider_profile=codex-router-responses live_execution=run live_timeout_s=900
```

Result: passed.

Artifacts:

- `output/evals/operator_session_live/20260629-012238/eval_results.json`
- `output/evals/operator_session_live/20260629-012238/eval_report.html`

Live checks passed: parent started, Steer Current Run was consumed through
`check_operator_messages`, Next Goal started a linked child run, the child
prompt received sanitized Operator Session context, and the child reached
terminal state.
