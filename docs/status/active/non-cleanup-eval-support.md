# Non-Cleanup Eval Support

Current blocker: none; implementation is complete for
`docs/plans/2026-06-15-non-cleanup-eval-support.md`.

Blocker fingerprint:

- blocker_kind: none
- root_cause_classification: not blocked
- last_decision_delta: live Codex and OpenAI Agents SDK open-ended evals now
  produce graded passing results against current `world-public-labels`
  artifacts.

Last proven evidence:

- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/evals tests/contract/dev_tools/test_eval_just_recipe.py`
  passed with 64 tests.
- Final deterministic suites passed:
  `flow-final-open-ended-goals`, `flow-final-map-build-consumer`, and
  `flow-final-scene-sampler-stress`.
- Final recommendations selected expected open-ended, map-build, and
  planner-proof rows under `output/eval-harness/flow-final-recommend-*`.
- Planner-proof dry run passed under
  `output/eval-harness/flow-final-planner-proof-dry-run`.
- Required live proof passed:
  `output/evals/household_world_open_ended_goals/flow-open-ended-codex-live-retry3/eval_results.json`.
- Additional OpenAI Agents SDK live proof passed with MiniMax:
  `output/evals/household_world_open_ended_goals/flow-open-ended-agent-sdk-minimax-live-20260616-rerun2/eval_results.json`.
  Aggregate: 1/1 passed, 0 blocked, 0 failed. The underlying live command
  returned `exit_status=0`; MCP timing recorded 87.635s, 32 tool calls, and
  64 tool events. The earlier `openai-agents-sdk` / `codex-env` live attempt
  reached the SDK runtime but was blocked by an upstream 502 provider response.

Next command/artifact: none for this task; ready for commit/closeout.

Stop condition: met.

No-touch scope at completion: system-provider Claude Code, public run
surface names, private scorer truth, and unrelated scene-sampler candidate
profile edits. OpenClaw was retired later by ADR-0148.

Parked work: expand open-ended sample coverage and authoritative semantic
predicates only after the first suite is proven; add a planner-proof eval suite
only when repeated versioned planner-proof samples exist; add live map-build rows
after the selected engine's artifact behavior is proven.
