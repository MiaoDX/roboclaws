---
name: eval-evolution
description: Prepare, run, review, and explicitly promote bounded Skill or existing-MCP Eval Evolution campaigns through the canonical eval facade.
---

# Eval Evolution

Use this Skill for maintainer-owned optimization campaigns driven by frozen eval
evidence. `roboclaws.evals` remains the control plane. The optimizer and robot
trials are distinct OpenAI Agents SDK agents; a provider profile selects their
models and never changes the agent engine.

## Prepare

Freeze an `eval_evolution_campaign_v1` JSON manifest before the first optimizer
call. Bind one target kind and target, the baseline commit and target digest,
mutable paths, optimizer and robot provider/model identities, paired training
suites, the orchestrator-only sealed confirmation reference, quality and
minimum-improvement policy, runtime identity, and explicit turn/trial/token/
cost/time/retry ceilings.
The budget block also declares positive `optimizer_call_tokens`,
`optimizer_call_cost_usd`, `robot_attempt_tokens`, and
`robot_attempt_cost_usd` reservations. Each reservation is a frozen maximum for
one optimizer run or one robot attempt, not a post-hoc usage target.

Skill campaigns target exactly one `skills/<name>/SKILL.md`. Keep
`static-full` as the baseline. `no-skill` is a non-promotable negative control.
Do not mix Skill and MCP changes.

## Run

Inspect the blocked preflight without provider execution:

```bash
just agent::eval evolve campaign=<campaign.json>
```

Run the frozen campaign only after provider/runtime readiness is established:

```bash
just agent::eval evolve campaign=<campaign.json> live_execution=run
```

The optimizer can only read the declared target, read sanitized feedback, and
submit one hypothesis plus patch. It has no shell, filesystem, git, network,
eval-launch, commit, or publication tool. Host-owned validation creates one
content-addressed full baseline snapshot and runs deterministic gates before
paired robot trials.

## Review

Reject missing or mismatched identity, incomplete paired evidence, privacy or
checker failures, trajectory/terminal violations, quality regressions, neutral
rewrites, and `no-skill`. Efficiency ranks only candidates that meet the frozen
quality and minimum-improvement rule. At most one training winner reaches one
sealed confirmation. Its evidence never returns to the optimizer.

The orchestrator reserves the full optimizer-run or robot-attempt token and cost
maximum before provider execution and passes that limit into the Agents SDK
model settings. Insufficient remaining campaign capacity is `inconclusive`
without starting the provider. A model without catalog output pricing is also
blocked before execution because its cost ceiling cannot be derived safely.
Behavior/provider failures do not retry.
A separately recorded classified infrastructure attempt is allowed only when
the frozen campaign permits one retry.

## Promote

Promotion requires an accepted selection report and a digest-bound
`eval_evolution_promotion_manifest_v1` with `maintainer_approved=true`:

```bash
just agent::eval evolve-promote \
  report=<selection-report.json> \
  manifest=<maintainer-approved.json> \
  live_execution=run
```

Stop before creating that approval unless a maintainer has reviewed the exact
candidate, paired training, sealed confirmation, limitations, and digests.
Promotion applies only the reviewed patch. It does not commit, change defaults,
or publish a baseline/catalog artifact.

MCP description candidates additionally require the Phase 2 structural
text-only proof. Never run MCP behavior candidates live until the Phase 3
malicious isolation proof has passed on the selected placement.
