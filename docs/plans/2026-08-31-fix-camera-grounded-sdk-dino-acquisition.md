# Fix Camera-Grounded SDK DINO Acquisition

**Status:** DRAFT - planning-loop recommendation
**Created:** 2026-08-31
**Owner:** Household World maintainers

## Goal

Restore the existing camera-grounded acquisition contract for both OpenAI
Agents SDK provider routes (`codex-responses` and `kimi-openai-chat`): every
successful camera-grounded observation must use the registered
`observe_camera_grounded_candidates` composite, send the FPV frame to the real
Grounding DINO sidecar, and register the resulting public observed handles.

This is an acquisition-path repair. It does not claim that cleanup capability
has passed until the existing 4/5 cleanup proof is rerun.

## Evidence And Root Cause

- The 2026-08-31 Codex proof used real Grounding DINO, but recorded 8 `observe`
  calls, 1 `declare_visual_candidates` call, and 0 composite calls. Only one
  waypoint's candidates entered registration; cleanup restored 1/5.
- `camera_grounded_composite_tools` is enabled by the resolved context-managed
  SDK profile, and lifecycle startup receives the flag, but
  `register_household_mcp_tools()` does not invoke the existing composite
  registrar. The profile/prompt and actual MCP tool surface can therefore
  disagree.
- The composite tool predates this regression (`663dc9d3`, 2026-06-12).
  Historical dogfood evidence records a Codex DINO camera-label run with 4/5
  restored and semantic 5/5, so this is a wiring regression candidate rather
  than evidence that DINO has always failed cleanup.

## Scope

1. Wire `register_agent_sdk_camera_grounded_composite_tools()` into the shared
   household MCP registration path when the resolved SDK entitlement is true
   and the run is camera-grounded.
2. Make prompt rendering, server startup arguments, and actual MCP registration
   derive from the same resolved profile value; remove any ad-hoc environment
   disagreement in the launch command path.
3. Keep registration idempotent and preserve the underlying `observe` and
   `declare_visual_candidates` trace events in the composite response.
4. Add focused regression tests for Codex/Kimi-equivalent SDK profiles:
   composite present when enabled, absent for explicit baseline/world-label
   profiles, stale two-step prompts rewritten, and no silent two-step fallback.
5. Capture resolved profile, composite entitlement, and registered tool names in
   live timing/run artifacts before any paid provider proof.
6. Run one real serial DINO cleanup proof with `codex-responses`, then one with
   `kimi-openai-chat`, using the same scene and existing acceptance thresholds.

## Non-Goals

- No Grounding DINO model, threshold, training, or detector bakeoff changes.
- No cleanup destination or candidate-actionability redesign in this plan.
- No public default migration, Raw-FPV retirement, provider expansion, or
  compatibility alias.
- No physical robot motion, cloud promotion, or additional provider
  concurrency.

## Acceptance

### Deterministic contract gate

- Enabled camera-grounded SDK profile exposes exactly one composite tool in the
  actual MCP tool list and the kickoff/continuation prompt names it.
- Explicit baseline or world-label profile does not expose the camera-grounded
  composite.
- A fixture with N successful camera-grounded observations produces N composite
  calls, N declaration events (allowing zero candidates on a valid frame), and
  no duplicate declaration for one source observation.
- Missing composite registration fails closed before a live provider run; it
  must not silently revert to model-requested `observe` plus declaration.
- Existing world-label and direct-runner contracts remain unchanged.

### Real provider gates

For each of Codex and Kimi, the serial run must show:

- requested/effective lane `camera-grounded-labels` and labeler
  `grounding-dino`;
- composite calls covering every successful inspected waypoint;
- external Grounding DINO provenance, CUDA/runtime readiness, nonzero candidate
  and observed-handle events, and complete privacy/report assets;
- candidates entering the normal cleanup worklist and the existing local-drain
  trace;
- existing cleanup capability threshold: at least 4/5 restored, at least 90%
  sweep coverage, at most two disturbances, authoritative terminal `done`.

If acquisition passes but the existing cleanup threshold still fails, record
actionability/destination quality as a separate follow-up; do not broaden this
plan.

## Verification

1. Focused MCP registration, profile-resolution, prompt, continuation, and
   trace-cardinality tests via
   `./scripts/dev/run_pytest_standalone.sh`.
2. `ruff check .` and `ruff format --check .` for changed Python files.
3. Real serial Codex DINO proof, artifact audit, then real serial Kimi DINO
   proof and artifact audit.
4. Re-run the existing cleanup checker/eval contract suite after both proofs.

## Stop Gates

- Stop before live providers if the resolved profile, prompt, and registered
  MCP tool list disagree.
- Stop before default migration if either provider lacks complete acquisition
  coverage or fails the existing cleanup threshold.
- Stop and report if the fix requires detector-specific destination logic,
  threshold search, new credentials, physical motion, or scope expansion.

## Alternatives Considered

- **Auto-declare inside plain `observe`:** rejected for this plan because it
  changes the existing public two-step semantics, risks duplicate declarations,
  and obscures trace ownership. Use the existing composite seam instead.
- **Prompt-only repair:** rejected because the observed Codex failure is model
  non-compliance with the two-step instruction; the actual MCP entitlement must
  be deterministic.
