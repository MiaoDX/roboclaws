# Retire OpenClaw And Local Docker Surfaces

**Status:** Implemented
**Created:** 2026-07-30
**Last reviewed:** 2026-07-30
**Current implementation contract:** Retire the validation-only OpenClaw
Gateway and remove repo-owned workstation-local Docker runtime, image-smoke,
and resource-management surfaces while preserving CloudML Dockerfiles, remote
image build/publish/runtime contracts, the two active agent engines, and all
current household, eval, simulator, and real-robot contracts.
**Related ADRs:** proposed
`docs/adr/0148-retire-openclaw-and-local-docker-runtime.md`

## Plan Ledger

- Status: DONE; implemented and verified through durable `$intuitive-flow`.
- Current slice: complete.
- Next action: human review of the completed retirement.
- Blocker: none.
- Completion owner: the executing root agent; workers may perform bounded
  read-only review or isolated test work but do not own final acceptance.

Final evidence: `uv sync --extra dev`, `uv lock --check`, repo-wide ruff and
format checks, focused launch/checker/dev-tools/operator-console tests, the
standalone full suite, exact current-surface searches, local operator-console
HTTP/inventory smoke, canonical direct-runner map-build and cleanup product
proofs, and an OpenAI Agents SDK launch-resolution trace all pass. CloudML and
remote-image files are unchanged.

## Decision Context

The current product has two agent engines: `direct-runner` and
`openai-agents-sdk`. `openclaw-gateway` is already rejected by public launch
validation and documented as a validation-required maintainer route. The team
does not plan to run OpenClaw tests in the near term.

Workstation-local Docker has no current public product role. Its remaining
repo-owned consumers are the OpenClaw Gateway, two local prebuilt-image smoke
scripts with no in-repo image build or CI caller, and generic operator-console
container cleanup left over from retired Docker-backed agent work. Keeping
these surfaces creates false maintenance and verification obligations.
CloudML Dockerfiles, remote image build/publish configuration, remote image
selection, and remote container runtime support are a separate maintained
platform contract and are outside this retirement.

## Preflight Contract

Preflight status: DRAFT

Task source: user request plus current-source audit.

Canonical source:
`docs/plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md`.

Route: `$intuitive-refactor` ratchet executed through durable
`$intuitive-flow`.

Goal: remove Docker from the maintained workstation-local execution and control
contract by formally retiring OpenClaw and deleting repo-owned local Docker
surfaces that no current product or repo-configured CI path consumes, without
changing any CloudML Docker or remote-image workflow.

Scope:

1. Record the retirement decision in a short ADR, mark its OpenClaw-only
   partial supersession of ADR-0137 and ADR-0138, update the ADR index, and
   update the active architecture contract to name only `direct-runner` and
   `openai-agents-sdk`.
2. Remove OpenClaw engine/provider metadata, explicit future-route rejection,
   provider-model aliases, intent runner declarations, MCP policy values, and
   OpenClaw-specific checker modes.
3. Remove the OpenClaw maintainer facade and runtime: `agent::gateway`, private
   Just modules, Gateway/chat recipes, bootstrap/config/transcript utilities,
   live and synthetic OpenClaw drivers, dogfood harnesses, household-server
   client hints, skill metadata, OpenClaw-only spikes, and their tests.
4. Remove repo-owned local Docker verification: the generic eval image smoke,
   Isaac image smoke, Docker requirement handling in the eval harness, and
   Docker bootstrap/pull behavior in the dev test workflow. Because OpenClaw
   currently owns the only two `integration`-marked tests, also remove or
   reshape the empty integration recipe, post-merge hook, marker, and docs so
   no maintained command exits 5 from collecting zero tests.
5. Remove operator-console Docker inventory, mount inspection, and container
   stop logic after proving no remaining in-repo launcher creates a
   Docker-backed attempt workspace.
6. Remove the `openclaw` optional dependency extra, lock metadata, root
   `.dockerignore` only if it is proven unrelated to CloudML image builds, and
   local-Docker-specific hook/config commentary. Preserve the
   `.openclaw-tmp/` and `.openclaw-token` ignore rules as credential/residual
   state safeguards even after their runtime owner is gone.
7. Remove current OpenClaw human/agent runbooks. Move the unique Docker/Tailscale
   incident document into `docs/retrospectives/`; preserve existing plans,
   archived ADRs, retrospectives, research report bodies, and immutable outputs
   as historical evidence. Update only active status capsules whose current or
   next-action claims are directly invalidated by ADR-0148; archive a capsule
   only when the repo's existing terminal-state rule applies.
8. Align `README.md`, `ARCHITECTURE.md`, `STATUS.md`, `just/README.md`,
   `AGENTS.md`, `docs/human/**`, `docs/agents/operating-runbook.md`,
   `docs/research/README.md`, `docs/adr/README.md`, `tests/README.md`,
   `skills/eval-harness/SKILL.md`, and `skills/household-world/SKILL.md` with
   the resulting local-runtime contract.
9. When removing `--require-openclaw-minimum`, retain current SDK coverage for
   its still-valid artifact, public MCP tool-trace, agent-driven, and
   `scene_objects` privacy invariants instead of deleting those assertions with
   the OpenClaw-specific aggregation mode.

Non-goals:

- Do not delete, stop, prune, or mutate host Docker containers, images,
  volumes, daemon configuration, or ignored local data.
- Do not remove or edit CloudML Dockerfiles, image build/publish configuration,
  remote-platform image fields, registry contracts, or remote container
  runtime support. Remote job images are not a workstation-local Docker
  contract.
- Preserve `scripts/dev/configure_nvidia_vulkan_runtime.sh`; it supports the
  CloudML Isaac digital-twin environment and does not invoke local Docker.
- Do not edit vendor/submodule Docker metadata.
- Do not rewrite historical plans, archived ADRs, retrospective bodies,
  research report bodies, published reports, inactive `.planning/**` evidence,
  or immutable candidate artifacts.
- Do not remove MCP, `mcp[cli]`, OpenAI Agents SDK providers, MuJoCo, the host
  Isaac Lab runtime, Agibot GDK, or current eval suites.
- Do not add a replacement gateway, container abstraction, compatibility alias,
  migration shim, or deprecated-command tombstone.
- Do not run paid providers, accept the Omniverse EULA, or exercise physical
  robot movement as part of this cleanup.

Entity budget:

- reuse: active launch catalog, provider registry, MCP server, eval facade,
  direct-runner product proofs, existing human-doc surface, and the remaining
  useful unit/contract test taxonomy.
- remove/merge: OpenClaw engine/runtime/checker/docs/tests; two local
  image-smoke scripts; Docker eval requirement; the now-empty integration test
  lane; operator-console Docker resource owner; stale dependency and
  hook/config surfaces.
- move: `docs/troubleshooting/docker-tailscale-mtu.md` to a dated retrospective
  so unique incident evidence leaves the current troubleshooting surface
  without being rewritten.
- new: one ADR, required by the repo's durable architecture-decision policy.
- expansion triggers: a current external caller, CI job, published artifact
  regeneration contract, or non-OpenClaw product route is proven to depend on a
  deletion target; stop and request re-approval.

Context:

- must-read: `STATUS.md`, `ARCHITECTURE.md`, this plan,
  `AGENTS.md`, `docs/agents/operating-runbook.md`, `justfile`,
  `just/agent.just`, `just/dev.just`, `just/molmo.just`,
  `roboclaws/launch/agent_engines.py`, `roboclaws/agents/provider_registry.py`,
  `roboclaws/cli/household_agent_server.py`,
  `roboclaws/operator_console/launch_support.py`, and
  `roboclaws/operator_console/runtime_inventory.py`, plus
  `scripts/dev/network_status.sh`, `.githooks/post-merge`,
  `spike/gateway_transcript_probe.py`, and `spike/mcp_image_probe.py`.
- useful: OpenClaw tests and scripts, current provider/launch tests, eval
  catalog requirements, and git history for the affected paths.
- avoid-unless-needed: historical plans, archived ADRs, retrospectives,
  generated output, immutable candidates, and vendor trees.

Acceptance:

- SUCCESS: no current launch, provider, MCP, checker, Just, hook, test, or
  operator-console owner retains OpenClaw behavior or invokes
  workstation-local Docker; the active two-engine product shape, CloudML
  Docker/image contracts, and current artifact/privacy contracts pass
  deterministic and product-run gates.
- BLOCKED_NEEDS_DECISION: a current external/CI consumer is proven, a current
  artifact must still be regenerated through OpenClaw, or cleanup requires a
  replacement runtime or compatibility layer.
- BLOCKED_NEEDS_LOCAL_VALIDATION: a required direct-runner product proof or
  local operator-console smoke cannot run for a concrete environment reason.
- INTERMEDIATE_ONLY: none.
- No regressions: preserve `just run::surface`, remaining `just agent::*`, four
  OpenAI Agents SDK provider profiles, MCP capability contracts, eval suites,
  map-build/cleanup/open-task behavior, operator-console host process control,
  CloudML Docker/image workflows, MuJoCo, host and CloudML Isaac Lab, and
  Agibot GDK.

Verification:

- deterministic: `uv sync --extra dev`, `uv lock --check`, `ruff check .`,
  `ruff format --check .`, focused launch/provider/MCP/checker/eval/dev-tools/
  operator-console tests, and `./scripts/dev/run_pytest_standalone.sh -q`.
- integration: collect the integration marker before mutation, then retire the
  lane if OpenClaw removal leaves it empty; prove no maintained hook or
  `just dev::test` branch invokes an empty pytest selection, inspects local
  Docker, or pulls images. Live provider calls are not required because
  provider transport is unchanged.
- product-run: run canonical direct-runner map-build and cleanup commands with
  explicit world/backend/seed/setup and require their built-in checkers to
  pass; trace one canonical `openai-agents-sdk` launch resolution without
  calling a provider.
- local-live-manual: add a subprocess spy or PATH sentinel that fails on any
  `argv[0] == "docker"` while exercising runtime inventory and host-attempt
  stop, then start the local operator console and smoke its HTTP/UI inventory
  and normal host-process stop behavior. No Docker daemon, provider, GPU
  container, or hardware proof is required.
- exact searches: use scoped tokens and call sites such as `openclaw-gateway`,
  `openclaw_agent`, `host.docker.internal`, `docker run|pull|ps|inspect|stop`,
  and the removed script/recipe names across current code, skills, hooks, tests,
  and current docs. Do not use generic `container` or remote `image` words as a
  zero-hit gate; explicitly allow CloudML, vendor, historical evidence, and the
  two residual-state safety rules in `.gitignore`.
- optional: compare package/import size and report net deleted files/lines.

Execution:

- main: root agent owns dependency ordering, selective commits, final exact
  searches, doc alignment, and completion judgment.
- worker: optional bounded read-only changed-code and current-doc reviews after
  implementation; no worker may mutate overlapping files.
- worker-goal: independently find remaining current OpenClaw/local-Docker
  consumers and regression risks, excluding history/vendor/output.

To execute: `/goal execute docs/plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md with intuitive-flow`

Optional tracking: none.

Approval: `LGTM`, `approve`, or `go ahead` approves; edits request revision.

## Proposed Slices

| Slice | Primary owners | Required outcome |
| --- | --- | --- |
| 1. Decision and active metadata | ADR/index, launch catalog, agent engines, provider registry, intents | `openclaw-gateway` becomes an ordinary unsupported value; ADR-0148 supersedes only prior OpenClaw carve-outs |
| 2. Runtime and evidence removal | Just modules, `scripts/openclaw`, Molmo drivers, MCP policy, checker, CLI hints, skills, spikes, harnesses | No Gateway/chat/OpenClaw smoke or special artifact acceptance path remains; shared SDK privacy/trace assertions survive |
| 3. Local Docker infrastructure removal | local image-smoke scripts, eval requirements, empty integration lane, dev workflow, operator console, hooks/config | Maintained local tests and runtime inventory never invoke Docker; CloudML Docker/image paths remain untouched |
| 4. Dependencies and docs | `pyproject.toml`, `uv.lock`, root/human/agent/index docs, active capsules, troubleshooting | No OpenClaw extra or current local-Docker instructions remain; safety ignores and history stay intact |
| 5. Final convergence | exact searches, full gates, product proofs, review | Clean worktree, no required gate skipped, no compatibility surface reintroduced |

## Stop Gates

1. Before deletion, inspect tracked callers and repo-configured CI for every
   command, script, optional extra, and image-smoke entrypoint. Record any
   visibility limit; do not claim to prove unobservable external callers. Stop
   only when a concrete current external consumer is found.
2. Preserve `.openclaw-tmp/` and `.openclaw-token` ignore rules. Do not inspect,
   delete, or expose any matching local residual state.
3. Before removing operator-console Docker logic, prove no current launcher
   creates `agent-docker-workspace` or another container-backed run resource.
4. Before deleting root `.dockerignore` or any Dockerfile/build configuration,
   prove it is unrelated to CloudML. Any CloudML Docker/image impact is a scope
   violation and stop condition.
5. Before deleting the OpenClaw checker helper, map every assertion to either a
   current SDK contract test or an explicitly retired OpenClaw-only rule.
6. If a current public or external consumer exists, stop rather than preserve
   a silent shim.
7. Do not claim completion if canonical product commands, full tests, or the
   operator-console no-Docker smoke cannot run.

## Expected Documentation Result

- Root and human docs describe only the two active agent engines and distinguish
  host-based product runtime from preserved CloudML Docker/image workflows.
- OpenClaw implementation guides leave `docs/human/**` and `docs/ai/**`.
- The Docker/Tailscale incident remains available only as shipped history.
- Existing OpenClaw plans, ADR archives, and retrospectives remain untouched
  and are not treated as current instructions.

## Planning Loop Review

Round 1 used independent plan-entropy, document-grill, and skeptic scouts. The
main-session judgment kept the full plan as the recommended execution unit and
merged these material corrections:

- preserve CloudML Docker/image contracts and the NVIDIA Vulkan helper;
- preserve OpenClaw residual-state ignore rules as a security boundary;
- retire the empty integration lane created by deleting its only OpenClaw
  tests;
- retain shared SDK artifact, tool-trace, and privacy assertions when removing
  the OpenClaw checker mode;
- prove the operator console's no-Docker behavior with a deterministic command
  sentinel rather than visual inspection alone;
- make tracked/repo-configured callers, current status capsules, skill/CLI
  side entrances, and ADR partial supersession explicit.

Parked: broader dependency pruning, MCP, generic network-status capability,
CloudML remote images, host/CloudML Isaac, MuJoCo, Agibot GDK, historical
evidence, and unrelated test-taxonomy redesign.

Rejected: a second planning round, a replacement gateway, compatibility shims,
and generic zero-hit searches for `container`, `image`, or `Docker` that would
misclassify preserved CloudML and historical surfaces.

Planning-loop saturation: one round was sufficient. No unresolved product,
contract, safety, cost, or infrastructure decision remains; later findings are
implementation defaults unless a stop gate above fires.
