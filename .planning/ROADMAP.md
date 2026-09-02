# Roadmap: State-First Context Manager

## Phases

- [x] **Phase 1: State And Checkpoint Schema** - Project authoritative typed task state into atomic checkpoints. (completed 2026-09-02)
- [ ] **Phase 2: Pre-Call Context Assembler** - Reconstruct bounded model input before provider calls.
- [ ] **Phase 3: Resume And Failure Semantics** - Resume valid checkpointed overflow and fail closed otherwise.
- [ ] **Phase 4: Route Proof And Rollout** - Prove the contract across household routes and evidence lanes.

## Phase Details

### Phase 1: State And Checkpoint Schema
**Goal**: Runs have an authoritative, privacy-bounded typed snapshot that can be restored from an atomic checkpoint.
**Depends on**: Nothing (first phase)
**Requirements**: REQ-state-and-checkpoint-schema
**Success Criteria** (what must be TRUE):
  1. A snapshot round-trips with task/intent, pose, waypoint, object freshness/provenance, action outcomes, safety gates, completion, evidence digests, and monotonic revision intact.
  2. Checkpoints are written atomically at meaningful tool/action and context-interruption boundaries.
  3. Model-facing state and telemetry contain no private scoring truth, credentials, raw prompts, or full tool payloads.
  4. Existing complete traces and run artifacts remain unchanged and readable.
**Plans**: TBD

### Phase 2: Pre-Call Context Assembler
**Goal**: Every SDK model call receives a reconstructed, bounded context with reserved output capacity before the hard provider limit.
**Depends on**: Phase 1
**Requirements**: REQ-pre-call-context-assembler
**Success Criteria** (what must be TRUE):
  1. Context reconstruction triggers at the proactive soft watermark, before hard-limit failure.
  2. Estimated input, expected output, and safety reserve are accounted for in every pre-call decision.
  3. Optional retrieval and older raw overlap are evicted before action-critical snapshot fields.
  4. Synthetic growth remains below the hard limit; residual overflow checkpoints once and does not retry the same payload.
**Plans**: TBD

### Phase 3: Resume And Failure Semantics
**Goal**: A checkpointed context-budget interruption resumes safely, while invalid or terminal states fail closed with actionable evidence.
**Depends on**: Phase 2
**Requirements**: REQ-resume-and-failure-semantics
**Success Criteria** (what must be TRUE):
  1. A valid checkpointed provider overflow starts the next SDK invocation from reconstructed state without duplicating the over-limit payload.
  2. Missing or corrupt checkpoints produce an actionable non-resumable status.
  3. Terminal completion is never resumed and still requires MCP `done` plus `run_result.json`.
  4. Continuation counts remain bounded and recoverable versus unrecoverable failures are distinguishable in status/artifacts.
**Plans**: TBD

### Phase 4: Route Proof And Rollout
**Goal**: The shared context contract is proven across supported household routes and preserves reviewable evidence.
**Depends on**: Phase 3
**Requirements**: REQ-route-proof-and-rollout
**Success Criteria** (what must be TRUE):
  1. Cleanup, MapBuild, and no-preset open-ended SDK paths pass focused deterministic and eval gates with explicit unmanaged `baseline` comparison.
  2. Camera-grounded/DINO, operator-console, and Agibot resolver metadata paths use the same context contract without new launch axes.
  3. Managed workloads stay within budget and complete traces, reports, and DINO artifacts remain content-addressed and reviewable.
  4. Private data does not cross model-input or telemetry boundaries; unavailable live prerequisites are recorded with guarded blocker output.
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. State And Checkpoint Schema | 3/3 | Complete   | 2026-09-02 |
| 2. Pre-Call Context Assembler | 0/TBD | Not started | - |
| 3. Resume And Failure Semantics | 0/TBD | Not started | - |
| 4. Route Proof And Rollout | 0/TBD | Not started | - |
