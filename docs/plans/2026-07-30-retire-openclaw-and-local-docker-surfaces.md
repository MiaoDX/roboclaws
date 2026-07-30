# Retire OpenClaw And Local Docker Surfaces

**Status:** Proposed
**Created:** 2026-07-30
**Last reviewed:** 2026-07-30
**Current implementation contract:** Retire the validation-only OpenClaw
Gateway and remove repo-owned local Docker runtime, image-smoke, and resource
management surfaces while preserving the two active agent engines and all
current household, eval, simulator, and real-robot contracts.
**Related ADRs:** proposed
`docs/adr/0148-retire-openclaw-and-local-docker-runtime.md`

## Plan Ledger

- Status: PROPOSED; implementation is not approved by this document alone.
- Current slice: none.
- Next action: human approval, then execute through `$intuitive-refactor` and
  durable `$intuitive-flow`.
- Blocker: none at planning time.
- Completion owner: the executing root agent; workers may perform bounded
  read-only review or isolated test work but do not own final acceptance.

## Decision Context

The current product has two agent engines: `direct-runner` and
`openai-agents-sdk`. `openclaw-gateway` is already rejected by public launch
validation and documented as a validation-required maintainer route. The team
does not plan to run OpenClaw tests in the near term.

Docker has no current public product role. Its remaining repo-owned consumers
are the OpenClaw Gateway, two prebuilt-image smoke scripts with no in-repo image
build or CI caller, and generic operator-console container cleanup left over
from retired Docker-backed agent work. Keeping these surfaces creates false
maintenance and verification obligations.

## Preflight Contract

Preflight status: DRAFT

Task source: user request plus current-source audit.

Canonical source:
`docs/plans/2026-07-30-retire-openclaw-and-local-docker-surfaces.md`.

Route: `$intuitive-refactor` ratchet executed through durable
`$intuitive-flow`.

Goal: make the repository's maintained runtime contract Docker-free by
formally retiring OpenClaw and deleting every repo-owned local Docker execution
surface that no current product or CI path consumes.

Scope:

1. Record the retirement decision in a short ADR and update the active
   architecture contract to name only `direct-runner` and
   `openai-agents-sdk`.
2. Remove OpenClaw engine/provider metadata, explicit future-route rejection,
   provider-model aliases, intent runner declarations, MCP policy values, and
   OpenClaw-specific checker modes.
3. Remove the OpenClaw maintainer facade and runtime: `agent::gateway`, private
   Just modules, Gateway/chat recipes, bootstrap/config/transcript utilities,
   live and synthetic OpenClaw drivers, dogfood harnesses, and their tests.
4. Remove repo-owned local Docker verification: the generic eval image smoke,
   Isaac image smoke, Docker requirement handling in the eval harness, and
   Docker bootstrap/pull behavior in the dev test workflow.
5. Remove operator-console Docker inventory, mount inspection, and container
   stop logic after proving no remaining in-repo launcher creates a
   Docker-backed attempt workspace.
6. Remove the `openclaw` optional dependency extra, lock metadata, root
   `.dockerignore`, stale `.gitignore` entries, and Docker-specific hook
   commentary.
7. Remove current OpenClaw human/agent runbooks. Move the unique Docker/Tailscale
   incident document into `docs/retrospectives/`; preserve existing plans,
   archived ADRs, retrospectives, and immutable outputs as historical evidence.
8. Align `README.md`, `ARCHITECTURE.md`, `STATUS.md`, `just/README.md`,
   `docs/human/**`, and `docs/agents/operating-runbook.md` with the resulting
   Docker-free maintained surface.

Non-goals:

- Do not delete, stop, prune, or mutate host Docker containers, images,
  volumes, daemon configuration, or ignored local data.
- Do not remove CloudML or other remote-platform image fields; remote job image
  selection is not a local Docker runtime contract.
- Do not edit vendor/submodule Docker metadata.
- Do not rewrite historical plans, archived ADRs, retrospectives, published
  reports, or immutable candidate artifacts.
- Do not remove MCP, `mcp[cli]`, OpenAI Agents SDK providers, MuJoCo, the host
  Isaac Lab runtime, Agibot GDK, or current eval suites.
- Do not add a replacement gateway, container abstraction, compatibility alias,
  migration shim, or deprecated-command tombstone.
- Do not run paid providers, accept the Omniverse EULA, or exercise physical
  robot movement as part of this cleanup.

Entity budget:

- reuse: active launch catalog, provider registry, MCP server, eval facade,
  direct-runner product proofs, existing human-doc surface, and current test
  markers.
- remove/merge: OpenClaw engine/runtime/checker/docs/tests; two image-smoke
  scripts; Docker eval requirement; operator-console Docker resource owner;
  stale dependency and hook/config surfaces.
- move: `docs/troubleshooting/docker-tailscale-mtu.md` to a dated retrospective
  so unique incident evidence leaves the current troubleshooting surface
  without being rewritten.
- new: one ADR, required by the repo's durable architecture-decision policy.
- expansion triggers: a current external caller, CI job, published artifact
  regeneration contract, or non-OpenClaw product route is proven to depend on a
  deletion target; stop and request re-approval.

Context:

- must-read: `STATUS.md`, `ARCHITECTURE.md`, this plan,
  `docs/agents/operating-runbook.md`, `justfile`, `just/agent.just`,
  `just/dev.just`, `just/molmo.just`, `roboclaws/launch/agent_engines.py`,
  `roboclaws/agents/provider_registry.py`,
  `roboclaws/operator_console/launch_support.py`, and
  `roboclaws/operator_console/runtime_inventory.py`.
- useful: OpenClaw tests and scripts, current provider/launch tests, eval
  catalog requirements, and git history for the affected paths.
- avoid-unless-needed: historical plans, archived ADRs, retrospectives,
  generated output, immutable candidates, and vendor trees.

Acceptance:

- SUCCESS: no current launch, provider, MCP, checker, Just, hook, test, or
  operator-console owner retains OpenClaw behavior or invokes local Docker; the
  active two-engine product shape and current artifact/privacy contracts pass
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
  MuJoCo, host Isaac Lab, and Agibot GDK.

Verification:

- deterministic: `uv sync --extra dev`, `uv lock --check`, `ruff check .`,
  `ruff format --check .`, focused launch/provider/MCP/checker/eval/dev-tools/
  operator-console tests, and `./scripts/dev/run_pytest_standalone.sh -q`.
- integration: prove the dev integration/all recipes no longer inspect or pull
  Docker images; run their deterministic recipe contracts. Live provider calls
  are not required because provider transport is unchanged.
- product-run: run canonical direct-runner map-build and cleanup commands with
  explicit world/backend/seed/setup and require their built-in checkers to
  pass; trace one canonical `openai-agents-sdk` launch resolution without
  calling a provider.
- local-live-manual: start the local operator console, load runtime inventory,
  stop a normal host-backed attempt, and verify no Docker executable is probed.
  No Docker daemon, provider, GPU container, or hardware proof is required.
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
| 1. Decision and active metadata | ADR, launch catalog, agent engines, provider registry, intents | `openclaw-gateway` becomes an ordinary unsupported value; no OpenClaw provider/model metadata remains |
| 2. Runtime and evidence removal | Just modules, `scripts/openclaw`, Molmo drivers, MCP policy, checker, harnesses | No Gateway/chat/OpenClaw smoke or special artifact acceptance path remains |
| 3. Local Docker infrastructure removal | image-smoke scripts, eval requirements, dev workflow, operator console, hooks/config | Maintained tests and runtime inventory never invoke Docker |
| 4. Dependencies and docs | `pyproject.toml`, `uv.lock`, root/human/agent docs, troubleshooting | No OpenClaw extra or current Docker maintenance instructions remain; history stays historical |
| 5. Final convergence | exact searches, full gates, product proofs, review | Clean worktree, no required gate skipped, no compatibility surface reintroduced |

## Stop Gates

1. Before deletion, inspect tracked and external CI callers for every command,
   script, optional extra, and image-smoke entrypoint.
2. Before removing `.gitignore` entries, verify `.openclaw-tmp/` and
   `.openclaw-token` are absent. If present, do not delete them; stop for a
   human-owned cleanup decision.
3. Before removing operator-console Docker logic, prove no current launcher
   creates `agent-docker-workspace` or another container-backed run resource.
4. If a current public or external consumer exists, stop rather than preserve
   a silent shim.
5. Do not claim completion if canonical product commands, full tests, or the
   operator-console no-Docker smoke cannot run.

## Expected Documentation Result

- Root and human docs describe only the two active agent engines and host-based
  runtime paths.
- OpenClaw implementation guides leave `docs/human/**` and `docs/ai/**`.
- The Docker/Tailscale incident remains available only as shipped history.
- Existing OpenClaw plans, ADR archives, and retrospectives remain untouched
  and are not treated as current instructions.
