# Real-Model Smoke Validation

Date: 2026-04-14

This report records the outcome of the local-dev validation task from issue #50:
"validate #46 100-step smoke effect on real AI2-THOR + real Kimi."

## Scope

Validate the post-#46 `main` branch smoke behavior against the issue #50 acceptance
criteria:

- Territory should terminate before 100 steps, and not via `max_steps`
- Coverage should reach at least 95% before 100 steps
- The combined Kimi spend should stay around 10 cents or less

## Method

- Verified the local `.env` Kimi key with `python scripts/check_kimi_key.py`
- Confirmed the repo environment locally: editable install, `ai2thor 5.0.0`,
  `ruff`, and `pytest`
- Began a local `xvfb-run` replay on the workstation
- Stopped the duplicate local rerun once the latest `main` Actions run on the
  same commit finished and published real-model artifacts

Using the published artifact was the right call. It exercised real Unity rendering
plus the real Kimi path on the exact target commit without spending extra Kimi
budget on a slow software-rendered local rerun.

## Validated Target

- Commit: `eb588409cb42ebfe56cb0759dcdadcd133582e41`
- GitHub Actions run: `24402133146`
- Relevant job: `real-model-smoke`

## Results

| Game | Termination | Steps | Score | Kimi cost |
|---|---|---:|---:|---:|
| Territory | `stale` | 26 | `19 / 234` claimed | `$0.016257` |
| Coverage | `max_steps` | 100 | `21 / 234` covered, `8.97%` | `$0.084300` |

Combined Kimi spend: `$0.100557`

## Findings

### What passed

- Territory did terminate before the 100-step budget.
- Territory did not end via `max_steps`.
- Real AI2-THOR and real Kimi were exercised on `main`.

### What failed

- Coverage never reached the `95%` target.
- Coverage ran the full 100-step budget and ended via `max_steps`.
- Combined spend landed slightly above the documented "about 10 cents" target.

## Likely Cause Of Failure

The current repo behavior does not match the intended design in two important ways:

1. `roboclaws/games/territory.py` and `roboclaws/games/coverage.py` currently call
   `provider.get_action(images=[], state=game_state)`, so the real-model smoke is
   state-only. The provider supports image payloads, but the game loops do not send
   any first-person or overhead frames yet.
2. `roboclaws/games/coverage.py` currently treats coverage as "visited cells" rather
   than "cells seen in the field of view," while `docs/technical-design.md` still
   describes field-of-view-based coverage with a 95% target.

With only visited-cell accounting, `21 / 234` after 100 individual steps is poor,
but not surprising enough to treat as a random one-off. The smoke expectation and
the actual implementation are misaligned.

## Outcome

Issue #50 was completed as a validation task, not a fix. The validation result is:

- The 100-step budget from #46 is not the problem by itself
- There is still a real gameplay or metric mismatch in coverage

That follow-up work is tracked in issue #52.

## Follow-Up

Issue #52 should decide and implement one coherent story:

- Either coverage is field-of-view based, in which case the game loop needs to feed
  images and the coverage accounting must reflect seen cells
- Or coverage is visited-cell based, in which case the docs and smoke expectations
  need to be revised to match the real game

Until that is resolved, the current `README.md` and `docs/technical-design.md`
overstate what the real-model smoke on `main` actually proves.

---

## RESOLVED (2026-04-15)

Both "Likely Cause" items were fixed the day after this report was
written. This section is now a historical validation snapshot, not a
description of current behavior.

- **Images flow through the game loops.** Commit `ddfb523`
  ("feat: improve multi-agent VLM game decisions", 2026-04-15 10:55)
  wired `images=prompt_images` through `game.decide()` in both
  `examples/territory_game.py:316` and `examples/coverage_game.py:357`.
  The provider call now receives a non-empty image list per step.
- **Coverage semantics are field-of-view.** `roboclaws/games/coverage.py:185-211`
  computes visible cells via yaw + half-FOV angle math and distance cap,
  then `_mark_covered` (line 213+) marks that set. Not visited-cells.
- **Issue #52 closed 2026-04-15T05:13:18Z.**

> **Note for future ingests:** this report's body describes the state
> at 2026-04-14. When consumed by `/gsd-ingest-docs` on 2026-04-20, the
> doc-synthesizer initially treated the "Likely Cause" section as
> current-state findings (producing two stale ingest warnings). Both warnings
> were verified stale against git log + live code and marked RESOLVED before
> the old ingest scratch files were removed from `.planning/`. The lesson —
> always cross-check "current broken state" claims in dated validation
> reports — is captured as a feedback memory.
