# Camera-Grounded DINO Cleanup Capability

**Status:** ACTIVE
**Source plan:** `docs/plans/2026-08-31-camera-grounded-dino-cleanup-capability.md`
**Control plane:** root intuitive-flow goal
**Latest intent:** execute until DINO observations drive accepted cleanup

## Current Slice

Kimi v2 proof was rerun after fixing completion-action priority. The code and
deterministic gates pass; the remaining live acceptance is blocked by the Kimi
provider billing quota. Do not run physical robot motion.

## Last Proven Evidence

- `output/dino-cleanup-capability-direct-heading-20260831/0831_1652/seed-7`
  restored 5/5 with 100% sweep coverage, zero disturbances, and one successful
  authoritative `done`.
- The direct proof used real CUDA-backed Grounding DINO on an RTX 3090 with the
  unchanged box/text thresholds and no private target truth.
- Grouped public-taxonomy queries and canonical plus three bounded headings
  exposed all five target classes, including book and remote control.
- `output/dino-cleanup-capability-codex-heading-v4-20260831/0831_1801/seed-7`
  restored 4/5 with 100% coverage, zero disturbances, authoritative `done`,
  complete artifacts, and real CUDA Grounding DINO provenance.
- `output/dino-cleanup-capability-kimi-heading-v2-20260831/0831_1939/seed-7`
  reached 3 grounded chains and 6/7 sweep waypoints with 30 successful model
  calls, then terminated on one non-retryable `provider_quota_failure` with
  provider reason `billing_limit`; no `done` or terminal report was produced.

## Latest Failure Fingerprint

The first Kimi proof at
`output/dino-cleanup-capability-kimi-heading-v1-20260831/0831_1814/seed-7`
completed 3 grounded chains and the canonical 7/7 sweep, then repeatedly tried
stale non-recommended handles during heading recovery. The server rejected the
actions without disturbance. Its completion snapshot exposed both a concrete
heading action and an object-less grounded-chain action; the injected skill
also retained the older two-step declaration wording. The attempt was stopped
after 73 minutes with complete diagnostic trace and no provider failures.

## Next Proof

The single-action completion projection plus aligned skill/continuation guidance
is committed as `cef6b467`. Resume only the remaining `kimi-openai-chat`
seed-7 proof after the provider billing limit is restored, then audit its
terminal artifacts.

## External Blocker

The Kimi provider readiness probe passes, but the live route's billing limit was
exhausted during v2 at model call 30. A new Kimi proof requires the provider
quota/account state to change; do not expand provider scope or alter detector
configuration to work around it.

## Stop Condition

Codex and Kimi serial DINO cleanup runs each pass 4/5 restoration, 90% sweep,
at most two disturbances, and authoritative `done` with complete artifacts.

## No-Touch Scope

Physical robot motion, private scorer input, detector model/threshold changes,
provider expansion, and deployment-default migration.

## Parked Work

Real-robot deployment verification after the simulation/provider capability
gate passes and an operator authorizes motion.
