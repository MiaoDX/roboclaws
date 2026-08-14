# MapBuild Fixture-Focused Consumer Experiments

Status: DONE

Source plan: `docs/plans/2026-06-24-map-build-panorama-consumer-experiments.md`

Latest intent: refactor MapBuild to one fixture-focused contract, commit the
change, and run the actual root-env model/DINO proof.

Result:

- MapBuild now has one fixture-focused scan contract. `panorama` and `standard`
  are removed as runtime/eval scan-profile choices, and no public
  `scan_profile` launch axis was added.
- Direct MapBuild uses existing `navigate_to_relative_pose` body turns for the
  fixture-focused scan. No `rotate_360` composite tool was added.
- Direct runner and OpenAI Agents SDK remain comparison/eval dimensions, not
  user-facing scan strategy choices.
- Runtime Map Prior Snapshot consumers still treat movable priors as search
  hints only; current observation is required before acting.

Commits:

- `fa8ecf4c refactor: fix mapbuild scan contract`
- `1fa8fff3 docs: record root-env mapbuild evidence`

Final root-env proof:

- With `/home/mi/ws/gogo/roboclaws/.env` sourced,
  `just dev::model-provider-health all` passed all configured routes:
  `codex-router-responses`, `mimo-mify-responses`, `minimax-responses`,
  `mimo-tp-openai-chat`, `mimo-inside-openai-chat`, `kimi-openai-chat`, and
  `nvidia-chat`.
- Root-env focused execute:
  `just agent::eval execute plan=docs/plans/2026-06-24-map-build-panorama-consumer-experiments.md budget=focused output_dir=/tmp/happy-crab-eval-harness-execute-root-env-final`
  completed. Harness summary: 19 rows ran and exited 0; 6 rows were skipped as
  irrelevant by the selector.
- Deterministic direct `map_build_consumer` passed 5/5. The fixture-focused
  prior open-ended row improved from no-prior `observe=18`,
  `navigate_to_waypoint=13` to `observe=12`, `navigate_to_waypoint=7`.
  Cleanup prior passed as `no_regression` with `movable_hint_rechecked`.
- Direct world-public MapBuild product proof passed at
  `/tmp/happy-crab-eval-harness-execute-root-env-final/rows/direct-map-build-world-public/run/0625_0130/seed-7/run_result.json`
  with `final_status=map_build_complete`,
  `scan_profile_id=fixture-focused`, `navigate_to_relative_pose:request=28`,
  and `observe:request=35`.
- Direct world-public cleanup using that Runtime Metric Map prior passed at
  `/tmp/happy-crab-eval-harness-execute-root-env-final/rows/direct-cleanup-runtime-prior-consumer/run/0625_0130/seed-7/run_result.json`
  with `final_status=success`, `restored_count=5/5`, and
  `runtime_metric_map_prior.loaded=true`.
- Root-env Grounding DINO direct MapBuild passed at
  `/tmp/happy-crab-eval-harness-execute-root-env-final/rows/direct-map-build-grounding-dino/run/0625_0128/seed-7/run_result.json`
  with `visual_grounding_pipeline_id=grounding-dino`,
  `scan_profile_id=fixture-focused`,
  `navigate_to_relative_pose:request=28`,
  `declare_visual_candidates:request=35`, and `observe:request=35`.
- Root-env Grounding DINO direct cleanup completed at
  `/tmp/happy-crab-eval-harness-execute-root-env-final/rows/direct-camera-grounded-grounding-dino/run/0625_0127/seed-7/run_result.json`
  with `final_status=partial_success`, `restored_count=3/5`,
  `sweep_coverage_rate=1.0`, and
  `visual_grounding_pipeline_id=grounding-dino`.

Live OpenAI Agents SDK matrix:

- `codex-router-responses`: 3/5 passed, `pass_at_1=0.6`. Failures were two
  open-ended fridge rows, both `private_goal_not_satisfied`.
- `mimo-inside-openai-chat`: 2/5 passed, `pass_at_1=0.4`. Failures were two
  open-ended fridge rows with `private_goal_not_satisfied` plus one cleanup
  no-prior row classified as `harness_bug_unclassified` despite a
  `partial_success` product result.
- `kimi-openai-chat`: 3/5 passed, `pass_at_1=0.6`. Failures were two
  open-ended fridge rows, both `private_goal_not_satisfied`.
- `minimax-responses`: 3/5 passed, `pass_at_1=0.6`. Failures were two
  open-ended fridge rows, both `private_goal_not_satisfied`.
- Extra root-env live rows selected by the plan also passed:
  `openai-agents-sdk-open-task-live-eval` passed 3/3, and
  `openai-agents-sdk-cleanup-live-eval` passed 3/3 repetitions.

Residual findings:

- The live model routes were healthy enough to run; the recurring matrix
  failures are behavior failures around open-ended fridge search, not provider
  credential failures.
- The Mimo cleanup no-prior cell has an eval classification issue to inspect
  separately: the product run produced partial-success evidence while the eval
  row classified it as `harness_bug_unclassified`.
- Grounding DINO cleanup quality is not fully solved by this refactor; it
  reached partial success. The MapBuild DINO contract proof passed.

No-touch scope preserved:

- No private fixture/scorer truth was exposed to agents.
- No automatic latest-prior discovery was added.
- No default model route was promoted.
- No public scan strategy selector was added.
