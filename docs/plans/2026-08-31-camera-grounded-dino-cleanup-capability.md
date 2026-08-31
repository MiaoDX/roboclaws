# Camera-Grounded DINO Cleanup Capability

**Status:** ACTIVE
**Created:** 2026-08-31
**Owner:** Household World maintainers
**Parent:** `docs/plans/2026-08-31-fix-camera-grounded-sdk-dino-acquisition.md`

## Goal

Make real Grounding DINO observations drive the complete household cleanup
loop, not only candidate acquisition. An SDK cleanup run must discover enough
misplaced objects from public FPV evidence, expose actionable public handles
and destinations, execute their semantic cleanup chains, and satisfy the
existing cleanup threshold before terminal `done`.

## Root-Cause Evidence

- The repaired Codex and Kimi acquisition runs both produced 7/7 composite
  observations and 33 candidates, but only one `cleanup_recommended` handle and
  one completed chain.
- Offline review of the same FPV frames shows visible generated targets for
  plate, pillow, and potato. Plate was detected and restored. Exact-category
  probes detect pillow at 0.41 and potato at 0.52 without changing model or
  thresholds; the current generic-label/global-top-k request loses them.
- Two generated targets were absent from canonical FPV frames, so one fixed
  camera view per waypoint is insufficient for the accepted whole-room task.
- Camera-model cleanup currently derives no grounded-chain requirement from
  `requested_run_size`, allowing authoritative `done` after only one chain.

## Scope

1. Query Grounding DINO with concrete categories grouped by the existing public
   cleanup taxonomy and deduplicate bounded results without private target data.
2. Apply the existing public success threshold to camera-grounded cleanup and
   fail closed before `done` when too few grounded cleanup chains completed.
3. Require a bounded multi-heading composite sweep when canonical views do not
   produce enough cleanup chains.
4. Preserve public-only target/destination policy and the existing semantic
   manipulation loop.
5. Verify the same seed/scene serially with `codex-responses` and
   `kimi-openai-chat`.

## Non-Goals

- No private generated-mess membership or exact destination exposure.
- No detector model, threshold, training, or benchmark bakeoff.
- No physical robot motion or deployment-default migration.
- No world-label or direct-runner behavior change beyond shared public helpers
  explicitly covered by regression tests.

## Acceptance

- DINO input is the source of every acted-on observed handle.
- Public completion state requires at least 4 grounded cleanup chains for a
  five-object cleanup run and cannot accept an early `done`.
- Codex and Kimi each restore at least 4/5 objects in the same seed-7 scene,
  achieve at least 90% sweep coverage, cause at most two disturbances, and
  terminate through authoritative `done`.
- Both runs retain real external Grounding DINO CUDA provenance, complete
  privacy/report assets, and one declaration per composite observation.

## Verification

1. Focused category-query, candidate-cardinality, completion-gate, continuation,
   prompt, MCP, and cleanup checker tests.
2. `ruff check .`, `ruff format --check .`, and `just agent::verify`.
3. One deterministic/direct camera-grounded cleanup proof.
4. Serial live Codex proof and artifact audit, then serial live Kimi proof and
   artifact audit.

## Current Evidence

- The seed-7 direct proof at
  `output/dino-cleanup-capability-direct-heading-20260831/0831_1652/seed-7`
  restored 5/5 targets with 100% sweep coverage, zero disturbances, and one
  authoritative successful `done`.
- The proof used real `IDEA-Research/grounding-dino-base` inference on CUDA
  (`NVIDIA GeForce RTX 3090`) with the existing box/text thresholds and no
  private target truth.
- Public-taxonomy grouped queries plus canonical and three bounded 90-degree
  body headings recovered all five target classes, including the previously
  absent book and remote control.
- The deterministic stop gate is satisfied. Remaining acceptance is the serial
  Codex and Kimi SDK proof and artifact audit.
- The first Kimi SDK proof reached only 3 grounded chains because the model
  followed conflicting completion actions and retried stale handles. Commit
  `cef6b467` now publishes one prioritized executable action and aligns the
  composite DINO recovery guidance.
- Kimi v2 then reached 3 grounded chains and 6/7 sweep waypoints before a
  non-retryable provider `billing_limit` quota failure at model call 30. The
  remaining Kimi acceptance is external-provider blocked; no terminal report
  or `done` was produced.

## Stop Gates

- Stop before live providers if deterministic DINO evidence does not expose at
  least four public cleanup-recommended handles in the seed-7 scene.
- Stop before physical robot motion or default migration.
- Stop for user direction before changing detector thresholds/models, exposing
  private truth, or expanding provider/resource scope.
