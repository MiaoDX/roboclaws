# Household Runner Eval Unification

Status: DONE

Source plan: `docs/plans/2026-07-03-household-runner-eval-unification.md`

Latest user intent: implement the whole plan via intuitive-flow.

Current slice: implementation and verification completed. Household task
identity now routes through one `household-world` skill, one private
`household-world` dispatch target, and one task-neutral household-world direct
episode path. Long Horizon remains an eval suite/grader that runs through the
normal product launch path.

Last proven evidence:

- `ruff check .`
- `ruff format --check .`
- `./scripts/dev/run_pytest_standalone.sh -q`
- `just run::surface surface=household-world agent_engine=direct-runner preset=map-build evidence_lane=world-public-labels`
- `just run::surface surface=household-world agent_engine=direct-runner preset=cleanup evidence_lane=world-public-labels`
- `just agent::eval suite=smoke_regression budget=smoke`
- `just agent::eval suite=open_ended_goals budget=smoke`
- `just agent::eval suite=cleanup_capability budget=smoke`
- `just agent::eval suite=map_build_consumer budget=smoke`
- `just agent::eval suite=long_horizon_tasks budget=smoke` completed through
  the product path and graded 0/2 with `private_goal_not_satisfied`, exposing
  product capability gaps now that the scripted substitute is gone.
- `just agent::eval suite=scene_sampler_stress budget=smoke`
- `just agent::eval recommend plan=docs/plans/2026-07-03-household-runner-eval-unification.md budget=focused`
- `just dev::network-status` reported `network: work`; OpenClaw and
  system-provider manual-debug routes remain guarded on this network.
- Selected live row:
  `just agent::eval suite=map_build_consumer budget=focused output_dir=output/eval-harness/20260703T010549Z/evals stamp=map-build-consumer-openai-agents-sdk-codex-router-responses agent_engine=openai-agents-sdk provider_profile=codex-router-responses live_execution=run`
  completed with provider/runtime availability proven, 1/5 samples passed
  (`map_build.fixture_focused_seed7`), and 4/5 consumer/open-ended samples
  failed before grading as product behavior/runtime-budget failures.

Stale-name proof:

`rg -n "molmo-realworld-cleanup|household-open-task|household-long-horizon|run_scripted_long_horizon|eval_scenario" roboclaws skills docs/human evals tests`
returned no active references. The remaining
`household-world.cleanup|map-build` hits are deliberate rejection tests only.

Next action: none for this implementation capsule.

Next proof: none required unless a follow-up specifically targets the live
MapBuild consumer behavior failures.

Stop condition: stop if a private setup value would need to enter Agent View or
MCP responses, if public ADR-0139 command shape would change, or if eval can
only pass through an oracle/scripted product-run substitute.

No-touch scope: historical `.planning/` phase records and unrelated active
status files.

Parked work: investigate the live `map_build_consumer` SDK failures separately
if product behavior improvement is the next objective. This migration did not
attempt to tune live-agent policy behavior.
