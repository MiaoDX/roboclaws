# ADR-0142: Bound Eval Evolution To Agents SDK And Sealed Evidence

Status: Accepted

Date: 2026-08-05

## Context

Roboclaws needs a bounded way to improve Skill text and existing MCP capability
behavior from eval evidence. The optimizer is an untrusted proposal source: if
it can inspect private truth, rewrite graders, choose thresholds, or mutate the
main checkout, measured improvement is not credible. The historical
self-improvement loop also depended on Codex CLI and a TUI-oriented harness that
are outside the current product architecture.

## Decision

Eval Evolution is owned by `roboclaws.evals` and exposed only through
`just agent::eval evolve|evolve-promote`. The optimizer and robot under test are
distinct OpenAI Agents SDK agents. A Codex-family provider profile may select a
model, but Codex CLI is neither an engine nor an execution dependency.

The trusted orchestrator gives the optimizer only a versioned sanitized
feedback packet and narrow read-target, read-feedback, and submit-candidate
tools. Raw eval samples, private truth, graders/checkers, provider secrets,
sealed holdout identity, host paths, and promotion policy remain inaccessible.
The same privacy validator gates optimizer calls and persisted optimizer-visible
artifacts.

Campaign policy and candidate identity freeze before paid trials. Deterministic
gates precede live trials; authoritative quality, privacy, checker, trajectory,
and terminal-evidence gates precede efficiency ranking. Exactly one eligible
training winner may reach one sealed holdout, and holdout evidence never returns
to the optimizer. Budget exhaustion is inconclusive.

Candidate generation and evaluation cannot mutate the main checkout. Promotion
requires a digest-bound, explicit maintainer approval and applies only the
reviewed patch. It does not commit, change defaults, or publish baselines or
catalog artifacts.

Skill text is the first live slice. MCP description changes require a proven
text-only structural delta. Optimizer-authored MCP behavior cannot run live
until a credential-scrubbed, private-data-isolated candidate boundary passes
the malicious local and selected-placement proof in Phase 3.

## Consequences

- There is one eval control plane and one report lineage.
- `agent_engine=openai-agents-sdk` is invariant for both live roles.
- Failed, blocked, neutral, or inconclusive candidates cannot reach promotion.
- The isolation gate may leave MCP behavior evolution blocked while Skill and
  MCP-description evolution remain usable.
- Human review remains mandatory before applying any accepted candidate.

## Rejected Alternatives

- Restore the historical Codex CLI/tmux/TUI harness.
- Let the optimizer launch evals, use a shell, inspect the repository, or define
  its own graders and thresholds.
- Treat a path allowlist as sufficient isolation for optimizer-authored Python.
- Feed holdout failures back into another adaptive optimizer turn.
