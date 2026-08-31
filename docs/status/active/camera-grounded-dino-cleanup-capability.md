# Camera-Grounded DINO Cleanup Capability

**Status:** ACTIVE
**Source plan:** `docs/plans/2026-08-31-camera-grounded-dino-cleanup-capability.md`
**Control plane:** root intuitive-flow goal
**Latest intent:** execute until DINO observations drive accepted cleanup

## Current Slice

Run and audit serial Codex and Kimi SDK proofs after the direct DINO capability
gate passed. Do not run physical robot motion.

## Last Proven Evidence

- `output/dino-cleanup-capability-direct-heading-20260831/0831_1652/seed-7`
  restored 5/5 with 100% sweep coverage, zero disturbances, and one successful
  authoritative `done`.
- The direct proof used real CUDA-backed Grounding DINO on an RTX 3090 with the
  unchanged box/text thresholds and no private target truth.
- Grouped public-taxonomy queries and canonical plus three bounded headings
  exposed all five target classes, including book and remote control.

## Next Proof

Provider readiness, then the same seed-7 camera-grounded DINO cleanup serially
with `codex-responses` and `kimi-openai-chat`, auditing each artifact before the
next run.

## Stop Condition

Codex and Kimi serial DINO cleanup runs each pass 4/5 restoration, 90% sweep,
at most two disturbances, and authoritative `done` with complete artifacts.

## No-Touch Scope

Physical robot motion, private scorer input, detector model/threshold changes,
provider expansion, and deployment-default migration.

## Parked Work

Real-robot deployment verification after the simulation/provider capability
gate passes and an operator authorizes motion.
