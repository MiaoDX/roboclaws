# ADR-0138: Use Detector-Only Visual Grounding Sidecar

Status: Accepted

Date: 2026-06-12

Partially superseded by [ADR-0148](0148-retire-openclaw-and-local-docker-runtime.md)
for its OpenClaw-only provider-routing carve-out.

## Context

ADR-0133 introduced the HTTP Visual Grounding Service and allowed hosted VLM
refiners and direct producers as comparison modes. That was useful while the
repo still explored many visual-labeling routes.

The current product shape is leaner: household-world and planner-proof are the
active surfaces, and visual grounding should provide camera-derived object
evidence without keeping hosted VLM direct/refiner paths alive as runtime
choices.

## Decision

Keep the HTTP visual-grounding sidecar boundary, but make the active current
contract detector-only.

Current visual-grounding runtime choices should be local detector labelers such
as Grounding DINO, YOLOE, YOLO-World, and OmDet-Turbo.

ADR-0143 later narrows this contract further: `sim-projected-labels`,
`fake-http`, and `contract-fake` are no longer active public/operator/product
camera labelers or current validation routes.

Retire hosted VLM visual-grounding camera labelers, refiner stages, and direct
producer stages from active code, command examples, tests, and benchmark
promotion logic. This includes any hosted VLM slot used as a
camera-labeler/refiner/direct-producer route.

Do not remove generic model/provider routing used by Codex, Claude Code,
OpenAI Agents SDK, OpenClaw text routes, model matrix flows, or future explicit
model experiments.

Gemini remains parked historical knowledge: it was strong for image/video
understanding and data labeling, and DINO plus Gemini improved one historical
cleanup result. Reintroducing Gemini should require a fresh explicit plan and
a bounded offline/on-demand labeling use case.

## Consequences

- The Visual Grounding Service remains a sidecar boundary, not an MCP tool.
- Current camera-grounded household runs should not expose hosted VLM
  direct/refiner camera labelers.
- Benchmarks should select among detector-only candidates, not direct VLM,
  proposer-plus-refiner promotions, sim projection, or fake transports as
  current validation proof.
- Historical plans, reports, and archived ADR-0133 may retain old VLM evidence,
  but current human docs and command surfaces must mark it retired or parked.
- The implementation plan is
  `docs/plans/2026-06-12-vlm-direct-sidecar-and-openclaw-status-cleanup.md`.

## Supersedes

- [ADR-0133](archive/superseded/0133-use-http-visual-grounding-service-for-real-camera-labels.md)
