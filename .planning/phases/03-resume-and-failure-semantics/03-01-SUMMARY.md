---
phase: 03-resume-and-failure-semantics
plan: 01
subsystem: agents
tags: [checkpoint, continuation, failure-semantics]
requires: [phase-01, phase-02]
provides: [bounded-checkpoint-resumability]
affects: [household-live-lifecycle]
tech-stack:
  added: []
  patterns: [fail-closed-classification]
key-files:
  created: []
  modified: [roboclaws/agents/household_live_continuation.py, roboclaws/agents/household_live_lifecycle.py, tests/unit/agents/test_live_runtime_continuation.py]
decisions: [resume only validated checkpointed overflow from reconstructed public state]
metrics:
  duration: 00:03
  completed: 2026-09-02
---

# Phase 3 Plan 1: Bounded Checkpoint Continuation Summary

Added explicit checkpoint resumability classification for household SDK runs. Context overflow resumes only with a valid checkpoint and canonical completion snapshot; terminal, missing, corrupt, non-context, and exhausted cases fail closed with actionable reason codes. Lifecycle telemetry records the classification for each attempt.

## Deviations from Plan

None - plan executed as written.

## Verification

- `./scripts/dev/run_pytest_standalone.sh -q tests/unit/agents/test_live_runtime_continuation.py` (10 passed)
- `ruff check roboclaws/agents/household_live_continuation.py roboclaws/agents/household_live_lifecycle.py tests/unit/agents/test_live_runtime_continuation.py` (passed)

## Self-Check: PASSED

- Commit `89077e75` exists.
- Modified source and test files exist.
