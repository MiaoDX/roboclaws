# 0134. Use Public Done Readiness Gates

Date: 2026-06-05

## Status

Superseded by the terminal completion lifecycle below

## Context

ADR-0003 separates the Cleanup Agent's public view from private evaluation
truth. ADR-0006 exposes the cleanup contract through bounded MCP tools, including
`done`, while ADR-0011 already makes invalid cleanup order an executable public
contract instead of a prompt-only convention. ADR-0132 keeps cleanup memory
skill-first but makes contract-derived facts authoritative for `done` gates,
reports, and checkers.

Recent RAW_FPV live runs showed another form of false completion: an agent could
call `done` after inspecting visual candidates without completing enough
grounded cleanup chains. Prompt guidance helped but was not authoritative, and
embedding RAW_FPV-specific checks directly in the MCP server risks turning the
server orchestration layer into a growing collection of task/profile branches.

## Superseding Decision (2026-08-03)

`done` is terminal-only. Every invocation writes terminal artifacts exactly once
and ends the Robot Run. If readiness is blocked, the terminal outcome is
`terminal_incomplete`; the checker rejects it and the Agent receives no further
recovery turn.

Agent View readiness is the sole pre-terminal completion authority. After every
nonterminal atomic MCP response, including recoverable errors, the runtime
computes one `household_completion_snapshot_v1` under `readiness.completion` and
projects that exact snapshot and digest onto the response and public trace. Its
monotonic response identity names the source tool. Blockers and executable next
actions derive only from the existing public cleanup worklist and public runtime
evidence. Source and generated inspection waypoint identities remain attached to
actionable candidates.

SDK continuation carries the latest canonical snapshot and digest. Missing,
malformed, or stale state fails closed as terminal-incomplete; continuation does
not reconstruct cleanup strategy from trace history or rejected `done` calls.
No additional readiness or cleanup-query MCP tool is added.

The public-only evidence boundary below remains in force.

## Prior Decision

Roboclaws will treat task/profile-specific completion readiness as a server-side
Done Readiness Gate. A `done` call remains the public lifecycle tool, but before
finalization the runtime may evaluate one or more readiness policies derived
from public run state.

Done Readiness Gates must use only public/runtime evidence available through the
cleanup contract boundary:

- Agent View state;
- public MCP tool requests and responses;
- public cleanup worklists or semantic substeps derived from traces;
- public run acceptance configuration such as the requested run size or profile.

The first run-size-derived grounded-cleanup-chain policy is scoped to
`camera-raw` / RAW_FPV runs. Structured `world-labels` lanes may still opt into
an explicit grounded-chain requirement, but they must use world-label recovery
tooling such as `navigate_to_object`, not RAW_FPV-only visual-candidate recovery.

They must not use or expose private generated mess membership, acceptable
destination sets, hidden target lists, private manifests, hidden target
receptacles, `is_misplaced`, or scorer object truth.

Historically, rejected `done` calls returned an additive public blocker structure while
preserving existing top-level recovery fields during migration:

```json
{
  "ok": false,
  "tool": "done",
  "status": "blocked",
  "error_reason": "insufficient_grounded_cleanup_chains",
  "required_tool": "navigate_to_visual_candidate",
  "completion": {
    "status": "blocked",
    "blockers": [
      {
        "type": "insufficient_grounded_cleanup_chains",
        "current": 3,
        "required": 4,
        "required_tool": "navigate_to_visual_candidate"
      }
    ]
  }
}
```

Numeric blocker fields may expose public progress and the minimum public
acceptance requirement for the run, but they must not label that value as a
private target count or reveal private target identities. This recovery behavior
is superseded: Skills consume the completion snapshot before terminal `done` and
never retry `done`.

The MCP tool surface should not grow a separate default `cleanup_worklist` or
`check_done_ready` tool solely for this purpose. The authoritative completion
check belongs on `done`; optional helper scripts or skill scratchpads may use
the same public tool results, but they are not the source of truth.

## Considered Options

- Keep this in prompts and skills only. This keeps MCP small, but it cannot
  guarantee completion correctness because live agents can ignore instructions,
  lose count, or loop on visual candidates.
- Add a new MCP readiness tool. This gives agents a proactive query path, but it
  expands the public surface and still lets an agent skip the query and call
  `done`.
- Put every profile-specific completion rule directly into the MCP server. This
  is quick for one bug, but it grows server orchestration around task/profile
  branches and makes future readiness rules harder to test in isolation.
- Use a Done Readiness Gate evaluated by `done`. This keeps the MCP surface
  stable, makes completion enforcement authoritative, and lets profile-specific
  policies be tested as explicit runtime strategies.

## Consequences

- `done` blockers become part of the public response contract, not just ad hoc
  recovery text.
- Skills can be simpler and more extensible: they react to public blockers
  instead of carrying private or profile-specific completion truth.
- Completion policies need focused tests for public/private boundary safety,
  blocker shape, and trace-derived progress.
- The first implementation can keep existing top-level `error_reason` and
  `required_tool` fields while adding `completion.blockers` for forward
  compatibility.
