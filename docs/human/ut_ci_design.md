# UT And CI Design

This note defines how Roboclaws should split local unit-test feedback, required
CI gates, advisory smoke evidence, and local-only backend validation.

The goal is not to run every demo on every push. The goal is to keep a small
required gate that catches deterministic breakage, plus explicit slower gates
for real services and real simulator/backend evidence.

## Principles

1. CI is the arbiter, local checks are feedback.
2. Required CI should be deterministic, cheap, secret-free when possible, and
   fast enough to run on every PR.
3. Every public task or backend needs a minimum deterministic contract, but not
   every task/backend combination belongs in required CI.
4. Real model, external-service, GPU, simulator, and robot-backed runs are
   evidence gates. They should be `main`-only, advisory, opt-in, nightly, or
   local-only unless they are stable and cheap enough to block ordinary PRs.
5. GitHub-specific behavior such as artifact download, Pages assembly, and
   deploy permissions should have a local rehearsal path or a focused test that
   models the important constraint.

## Why CI Still Runs Lint And Format

Even if a developer runs unit tests before pushing, CI should still run lint,
format, and deterministic tests.

Local checks can be skipped, run against a dirty worktree, run with a different
environment, or run on the wrong branch. CI provides the auditable result for
the exact commit being reviewed or published.

Lint and format are cheap, deterministic checks. They should stay in required
CI. Removing them saves little and makes `main` depend on local discipline.

## Gate Levels

| Level | Trigger | Blocks? | What Belongs Here |
| --- | --- | --- | --- |
| Local feedback | before commit or push | no | focused standalone pytest, targeted reproduction |
| Required PR gate | every PR and push | yes | lint, format, deterministic pytest, mock reports, command routing contracts |
| Required main gate | push to `main` | yes, if stable | public report assembly, Pages artifact shape, stable real-model smoke if accepted |
| Advisory smoke | push to `main` or scheduled | no | provider or external-service runs that can timeout or depend on external services |
| Opt-in expensive gate | manual dispatch or commit tag | no by default | live model matrices, open-ended household tasks, broad backend comparisons |
| Local-only proof | developer workstation | no hosted CI | GPU, real robot, Isaac, Agibot GDK, full MolmoSpaces visual proof |
| Eval suite | scheduled, manual, or release gate | no by default until accepted | versioned samples, repeated trials, graders, aggregate metrics, and regression replay |

## Command Surface Policy

Use the existing command surfaces directly when they fit:

- `just run::surface ...` for user-facing surface/preset execution.
- `just agent::verify` for the full confidence gate.
- `just agent::eval ...` for versioned capability suites.
- `./scripts/dev/run_pytest_standalone.sh ...` for pytest marker slices.
- Package CLIs for maintainer debugging and specialist gates.

A dedicated `ci::*` namespace is optional. Add one only when the command is
truly job-shaped rather than task-shaped, such as local Pages assembly from
downloaded artifacts or a full "reproduce this exact GitHub job" wrapper.

Do not add a `ci::*` wrapper merely to rename an existing `run::surface` or
`agent::verify` command.

## Required Coverage For New Surfaces And Intents

When adding a public surface or intent such as
`surface=household-world preset=map-build` or
`surface=household-world preset=cleanup`, required CI should prove its public
contract with deterministic inputs:

- command routing accepts the documented `just run::surface` shape
- required profiles, drivers, and overrides are validated
- public artifacts are written with the expected names and schemas
- private evaluation data is not leaked into public agent inputs
- report generation succeeds on a tiny fixture or mock run
- rerun commands and output paths are stable

This required contract should use fake, fixture, direct, mock, or synthetic
backends when possible.

Real provider behavior is separate evidence. Do not block ordinary PRs on real
provider, GPU, or robot behavior unless the run is stable, cheap, and explicitly
accepted as a required gate.

## Required Coverage For New Backends

When adding a backend, required CI should cover the adapter boundary rather
than the full real backend:

- backend config is parsed and rejected clearly when invalid
- public task output shape is preserved
- backend-specific provenance is represented in artifacts
- failure modes produce useful diagnostics
- the checker can distinguish skipped, blocked, failed, and successful proof

The real backend run belongs in an advisory, manual, scheduled, or local-only
gate when it requires any of the following:

- paid model calls
- external service availability
- GPU or display
- downloaded simulator assets beyond normal mock reports
- private vendor resources
- robot hardware
- long-running autonomous agents

## Current CI Classification

| CI Job | Current Level | Local Equivalent |
| --- | --- | --- |
| `lint-and-mock` | required PR gate | `just agent::verify` |
| `household-route-contracts` | required PR gate, usually inside `lint-and-mock` | `./scripts/dev/run_pytest_standalone.sh -q tests/contract/dev_tools/test_task_agent_just_recipes.py tests/unit/operator_console` |
| `household-map-build` | required or advisory main gate depending on runtime cost | `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=map-build agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino ...` |
| `molmo-live-cleanup` | opt-in expensive gate | `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=cleanup agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=world-public-labels ...` or the live matrix script |
| `planner-proof` | local-only or manual expensive gate | `just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=direct-runner mode=dry-run` |

## Current Gaps

- `surface=household-world preset=map-build` should have deterministic
  required contract coverage for command routing and `runtime_metric_map.json`
  shape, independent of real Agibot, Isaac, or live-agent proof.
- New backends should not automatically expand required CI. Add a cheap adapter
  contract first, then decide whether real backend proof is advisory or local.

## Practical Pre-Push Command

For ordinary code changes, run:

```bash
uv sync --extra dev
just agent::verify
```

For a tighter edit/test loop before the final pre-push gate, run the smallest
relevant target through `./scripts/dev/run_pytest_standalone.sh`.

For changes touching CI report assembly or Pages scripts, also run the relevant
focused reproduction. For example, Pages helpers that must not depend on the
project environment should be exercised with `python -S`.

For changes whose claim depends on real simulator, model, GPU, or
robot behavior, run the matching local task or harness and record the command
and artifact path. CI keeps that proof continuously visible; it is not the
first validation for local-only claims.
