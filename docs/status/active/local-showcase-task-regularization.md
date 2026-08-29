# Local Showcase Task Regularization

**Status:** COMPLETE
**Source plan:** `docs/plans/2026-08-29-local-showcase-task-regularization.md`
**Control plane:** root Codex intuitive-flow session
**Latest intent:** implement the accepted plan
**Current slice:** local Kimi acceptance complete; all required cleanup repetitions passed
**Last proven evidence:** focused implementation proofs; canonical deterministic
suite gates pass for smoke, map-build, and map-consumer-no-prior; open-ended is
2/3 because the synthetic drink sample correctly fails public exhaustion.
**Next proof:** none for this plan; cloud/provider promotion remains a separate
human decision
**Stop condition:** do not run Kimi until deterministic terminal, timeout, report,
asset-link, and privacy tests pass
**No-touch scope:** cloud concurrency/provider matrix, private-data boundary, public MCP surface
**Parked:** cloud promotion, cross-provider reliability, broad flag consolidation

**Latest live evidence:** map-build passed (251.742s), open-ended drink passed
(611.971s), and cleanup finalized with a complete diagnostic bundle but failed
capability honestly (`partial_success`, 3/5 restored, 1,559.268s, 116 tool
calls). Evidence/privacy status is ready; capability/time gate is not met.

The first cleanup-only retry was blocked before task execution because the
MolmoSpaces visual-backend slot was still legitimately held by an active
open-ended runner. It produced no run artifacts and is retained as a blocked
attempt; no process or slot was forcibly terminated.

On resume, the same slot remains active and its server log continues receiving
requests, so this is a live external-resource blocker rather than a stale lock.
The repaired contract was confirmed by three independent serial Kimi cleanup
attempts, each with complete evidence and successful capability outcome.

Focused cleanup contract, eval classification, and runner tests pass; Ruff check
and format checks pass. The source contract now carries all category-compatible
destination IDs in the private scorer while keeping public agent inputs
semantic-only. Fresh live evidence:
`output/local-showcase-kimi-final`, `output/local-showcase-kimi-repetitions`,
`output/local-showcase-kimi-repetition2`, and
`output/local-showcase-kimi-repetition3`; all report `success`, restoration
`1.0`, sweep `1.142857`, and disturbance count `0`.
