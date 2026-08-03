# TODOs

Deferred work that a future maintainer can pick up without rereading the whole
history. This is a parked-work list, not current project status. For current
focus, next action, and active source links, read [`STATUS.md`](STATUS.md).

One entry = one self-contained missing item. Shipped phases are tracked under
`docs/retrospectives/`, not here.

Each entry should answer:

- `Created`: when the item first became parked work.
- `Updated`: when this TODO entry was last materially rechecked or reshaped.
- `Status`: current state, not a promise that work is in progress.
- `Why`: the maintenance or product reason this still deserves to exist.
- `Next action`: the smallest useful action for the next maintainer.
- `Evidence`: current source links, artifacts, or files to start from.
- `Try now`: whether this is suitable for an ordinary coding-agent turn.

## Missing Work

- **Autonomous-nav decision reasoning in `report.html`**
  - Created: 2026-05-11.
  - Updated: 2026-06-11.
  - Status: Parked report UX enhancement.
  - Why: Autonomous navigation reports already have frame-by-frame controls,
    but they still do not show rich public decision reasoning comparable to VLM
    game reports. Better decision summaries reduce replay rediscovery during
    navigation debugging.
  - Next action: Render public per-step reason data when Gateway exposes it or
    when the agent emits a public reason tag. Do not expose hidden or encrypted
    chain-of-thought.
  - Evidence:
    `scripts/reports/render_autonomous_replay.py`;
    `scripts/templates/autonomous_report.html.j2`;
    `tests/contract/reports/test_render_autonomous_replay.py`.
  - Try now: Yes, if scoped to existing public trace fields. Broader Gateway
    changes need a separate design pass.

- **LeRobotDataset rollout export**
  - Created: 2026-05-11.
  - Updated: 2026-06-11.
  - Status: Parked optional data-format compatibility study.
  - Why: LeRobotDataset is a useful future interoperability target for robot
    rollout data, but current Roboclaws architecture does not depend on it.
  - Next action: Map current replay/run fields to LeRobotDataset concepts and
    list missing action, state, camera, and metadata fields before any exporter
    implementation.
  - Evidence:
    `docs/research-checkpoints/2026-04.md`;
    `docs/research-checkpoints/2026-05.md`;
    `roboclaws/core/run_artifacts.py`.
  - Try now: Yes for a spec or mapping document; exporter code should wait
    until the mapping is reviewed.

- **Multi-agent coding-agent harness expansion**
  - Created: 2026-05-11.
  - Updated: 2026-06-11.
  - Status: Parked architecture/research item.
  - Why: Multi-agent coding-agent runs could expose lock, context, state
    isolation, shared simulation, and scoring problems that single-agent live
    routes hide.
  - Next action: Write a small design packet that builds on the existing
    `LiveAgentRequest` / `LiveAgentResult` contract and future eval-suite
    repetition semantics instead of adding another launch path.
  - Evidence:
    `docs/plans/live-agent-runtime-sdk-spike.md`;
    `roboclaws/agents/live_runtime.py`;
    `docs/plans/2026-06-14-eval-driven-architecture.md`.
  - Try now: No for implementation. Start with planning or a bounded harness
    spike.

- **Async route perception during cleanup navigation**
  - Created: 2026-05-11.
  - Updated: 2026-05-31.
  - Status: Parked feature slice with research reference.
  - Why: Cleanup agents should eventually notice useful objects while moving
    between task locations without interrupting a held-object delivery, and
    reports need to distinguish route observations from deliberate waypoint
    observations.
  - Next action: Turn the Perception Producer reference into a bounded plan or
    simulator-first slice that updates the observed-handle worklist and report
    provenance.
  - Evidence:
    `docs/research/06-visual-grounding-perception-producer.md`;
    `docs/plans/molmospaces-waypoint-honest-cleanup-flow.md`;
    `roboclaws/household/realworld_mcp_server.py`.
  - Try now: Partially. Planning is ready; implementation needs a scoped
    feature contract.

- **Supported access to encrypted model reasoning**
  - Created: 2026-05-11.
  - Updated: 2026-06-11.
  - Status: Parked compliance/product research item.
  - Why: Local harness analysis would benefit from plaintext reasoning
    summaries, but Roboclaws must not implement decryption bypasses or expose
    hidden chain-of-thought.
  - Next action: Research first-party, user-consented reasoning-summary export
    paths and document only supported approaches.
  - Evidence:
    `roboclaws/agents/drivers/openai_agents_live.py`;
    `docs/plans/live-agent-runtime-sdk-spike.md`.
  - Try now: Yes for docs research only; no code bypass work is acceptable.

- **Weekly coding-agent model/settings benchmark**
  - Created: 2026-05-11.
  - Updated: 2026-06-15.
  - Status: Parked eval-suite design.
  - Why: Coding-agent defaults drift as models, provider routes, and reasoning
    settings change. A stable weekly suite would make default recommendations
    evidence-based instead of anecdotal.
  - Next action: Fold this into the eval-suite architecture as a live-agent
    repetition slice with model/settings matrix, cost budget, `pass@k` /
    `pass^k`, and published report shape.
  - Evidence:
    `skills/agent-validation-matrix/SKILL.md`;
    `docs/plans/2026-06-11-agent-validation-matrix-skill.md`;
    `docs/plans/2026-06-14-eval-driven-architecture.md`;
    `just/README.md`.
  - Try now: Yes for benchmark design; recurring live execution needs provider
    budget and local-network constraints.

- **Cloud-backed eval harness execution scale-out**
  - Created: 2026-06-16.
  - Updated: 2026-06-16.
  - Status: Parked evaluation infrastructure design, awaiting cloud-machine
    access details.
  - Why: Local runs and one or two workstation-driven AI automation loops are
    too slow and narrow to give high confidence in agent-framework behavior.
    The Evaluation layer should be able to fan out eval harness jobs across
    cloud machines so local or physical validation can stay focused while the
    overall sample count, trial count, route coverage, and failure discovery
    scale become much larger.
  - Next action: After the cloud-machine usage contract is available, write a
    design packet for a remote eval-harness executor: worker lifecycle, queue or
    dispatch model, artifact upload/download, provider key and log redaction,
    quota/cost controls, deterministic seeds, simulator/runtime prerequisites,
    retry semantics, and aggregate `pass@k` / `pass^k` reporting.
  - Evidence:
    `docs/plans/2026-06-14-eval-driven-architecture.md`;
    `docs/adr/0140-use-eval-suites-as-first-class-architecture-layer.md`;
    `docs/adr/0141-use-eval-harness-as-maintainer-orchestration-facade.md`;
    `skills/eval-harness/SKILL.md`;
    `roboclaws/evals/runner.py`;
    `roboclaws/evals/live_runtime.py`;
    `just/README.md`.
  - Try now: No for implementation. Yes for design once the cloud-machine
    access model, credentials boundary, and expected worker environment are
    provided.

- **Real-task thinking / reasoning-effort comparison**
  - Created: 2026-06-16.
  - Updated: 2026-06-17.
  - Status: Parked live-provider comparison.
  - Why: Same-input live probes showed route-specific behavior: Kimi K2.7 Code
    needs the Claude Code user agent and works with Thinking On, MiniMax
    Responses works with medium reasoning, but `mimo-inside-openai-chat`
    Thinking On can explode into 200k+ token responses while disabled thinking
    completes. Defaults now use the smallest route-specific fix; a broader
    matrix is still needed before tuning other routes.
  - Next action: Turn the ad hoc runs into a bounded eval row on the same world,
    seed, evidence lane, prompt, and scenario setup. Keep Kimi and MiniMax as
    current-control rows, compare `mimo-inside-openai-chat` disabled vs enabled
    for regression proof, and only add other route/effort variants after a
    product run fails or is too slow.
  - Evidence:
    `roboclaws/agents/thinking_policy.py`;
    `docs/human/model-matrix.md`;
    `scripts/dev/check_model_providers.py`;
    `tests/unit/agents/test_thinking_policy.py`;
    `output/operator-console/runs/20260617-1513-mimo-inside-no-thinking-fruit/0617_1513/seed-7`;
    `output/household/household-world/open-ended/openai-agents-live-world-public-labels/0617_1545/seed-7`;
    `output/household/household-world/open-ended/openai-agents-live-world-public-labels/0617_1526/seed-7`.
  - Try now: Yes for one focused eval-row design or one same-prompt live A/B
    check. Broader cross-route matrices need provider budget and local runtime
    availability.

- **Periodic Docker-pinned coding-agent CLI updates**
  - Created: 2026-06-12.
  - Updated: 2026-06-12.
  - Status: Parked maintenance cadence.
  - Why: The Docker-backed coding-agent runtime pins Codex CLI and Claude Code
    exactly so live-agent demos are reproducible, but stale pins can miss
    provider, MCP, transport, and bug-fix changes. Version refreshes should be
    deliberate instead of accidental.
  - Next action: On a regular cadence, compare the pinned `@openai/codex` and
    `@anthropic-ai/claude-code` packages against npm latest, read relevant
    release notes, build a temporary image, and run focused MCP/provider smoke
    tests before changing the repo pin.
  - Evidence:
    `scripts/dev/coding_agent_toolchain.env`;
    `Dockerfile.coding-agents`;
    `scripts/dev/coding_agent_docker.sh`;
    `scripts/dev/coding_agent_env.sh`;
    `docs/human/model-route-verdicts.yaml`.
  - Try now: Yes for version audit and temporary-image smoke tests. Commit a
    pin bump only when the focused smokes show a net improvement or needed fix.

- **Re-review MiniMax Responses with Codex MCP routing**
  - Created: 2026-06-12.
  - Updated: 2026-06-12.
  - Status: Parked provider compatibility review.
  - Why: MiniMax `MiniMax-M3` and `MiniMax-M2.7-highspeed` work through the
    OpenAI Agents SDK Responses route for structured cleanup, but Codex CLI
    currently rejects MiniMax-emitted MCP tool calls as `unsupported call`
    because the provider emits flattened tool names such as
    `mcp__cleanup__metric_map` or `cleanup__ping_tool` instead of the routed
    Codex MCP server/tool shape.
  - Next action: After a relevant Codex CLI release, MiniMax token-plan release,
    or router/tool-call compatibility note, rebuild a temporary coding-agent
    image and rerun the focused MiniMax MCP smoke plus one household cleanup
    attempt for `MiniMax-M3` and `MiniMax-M2.7-highspeed`.
  - Evidence:
    `docs/human/model-route-verdicts.yaml`;
    `docs/human/model-matrix.md`;
    `.tmp/minimax-mcp-text-smoke/20260612_155910-codex139-m3`;
    `.tmp/minimax-mcp-text-smoke/20260612_155910-codex139-m27`;
    `.tmp/minimax-mcp-text-smoke/20260612_160421-codex139-feature-m3`;
    `.tmp/minimax-mcp-text-smoke/20260612_160421-codex139-feature-m27`.
  - Try now: No for another blind rerun. Yes when a provider or Codex-side
    change gives a concrete reason to expect the tool-call shape changed.

- **Audit coding-agent runner parity across Codex and OpenAI Agents SDK**
  - Created: 2026-06-22.
  - Updated: 2026-06-22.
  - Status: Parked runner-semantics audit.
  - Why: The operator handoff bug showed that `codex-cli` and
    `openai-agents-sdk` had different lifecycle semantics for the same user
    intent: Codex preserved an explicit "wait / do not call done" handoff, while
    the SDK runner treated no `done` as a failure and cleaned up the MCP server.
    Other route-specific differences may still exist around continuation,
    timeout, pause/resume, failure status, artifact writing, and operator stop.
  - Next action: Build a small parity checklist for shared live-agent semantics,
    then compare `run_live_codex_cleanup.py` and
    `run_live_openai_agents_cleanup.py` against it. Convert any discovered
    divergence into focused regression tests before changing runner behavior.
  - Evidence:
    `scripts/molmo_cleanup/run_live_codex_cleanup.py`;
    `scripts/molmo_cleanup/run_live_openai_agents_cleanup.py`;
    `tests/unit/molmo_cleanup/test_ci_live_reports.py`;
    `tests/unit/operator_console/test_state.py`;
    `tests/unit/operator_console/test_operator_console.py`;
    commit `3213fc4c` (`fix: preserve OpenAI Agents handoff pause`).
  - Try now: Yes for audit and test-plan work. Apply behavior changes only as
    narrow fixes with parity tests.

- **Physically delete retired coding-agent implementation**
  - Created: 2026-06-24.
  - Updated: 2026-06-24.
  - Status: Parked removal cleanup after SDK-only live-agent routing.
  - Why: The SDK-only migration removed Codex CLI and Claude Code from current
    public/operator/eval launch surfaces, but the lower-level coding-agent
    Docker tooling, Codex/Claude runner scripts, and supporting tests remain as
    manual-debug or historical surfaces. Keeping those sources around continues
    maintenance drag and makes the code reduction look smaller than the
    architectural retirement.
  - Next action: Decide whether manual debugging support is still worth
    preserving. If not, delete the retired implementation files and migrate or
    remove callers/tests that still reference them.
  - Evidence:
    `Dockerfile.coding-agents`;
    `scripts/dev/coding_agent_docker.sh`;
    `scripts/dev/coding_agent_env.sh`;
    `scripts/dev/coding_agent_toolchain.env`;
    `scripts/molmo_cleanup/run_live_codex_cleanup.py`;
    `scripts/molmo_cleanup/run_live_claude_cleanup.py`;
    `scripts/molmo_cleanup/run_live_codex_agibot_map_build.py`;
    `just/code.just`;
    `tests/contract/dev_tools/test_code_just_recipes.py`;
    `tests/contract/dev_tools/test_coding_agent_env_helpers.py`;
    `tests/unit/molmo_cleanup/test_ci_live_reports.py`;
    `tests/unit/molmo_cleanup/test_live_codex_agibot_map_build.py`.
  - Try now: Yes for a deletion plan or focused removal PR. Do not remove
    OpenClaw or the `codex-router-responses` SDK provider profile as part of
    this cleanup.

_If this list empties, next work should come from a new plan or issue._
