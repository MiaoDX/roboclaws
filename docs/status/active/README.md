# Active Standalone Work

Use this directory for parallel terminal or agent work and durable initiative
capsules. A named initiative keeps one stable owner file for its full lifetime;
GSD state may link to that capsule but must not create a competing initiative
status record. Short-lived standalone task files may still be deleted or
archived at closeout.

One standalone task owns one file:

```text
docs/status/active/<task-slug>.md
```

Keep each file short. Initiative capsules remain at their stable path after
completion or parking with a terminal conclusion, evidence links and resume
conditions. Do not use these files as substitutes for GSD phase plans,
`docs/plans/`, issues, or verification artifacts.

## Template

```md
# <Task Name>

Owner/session: <terminal or agent>
Started: YYYY-MM-DD HH:MM
State: active | blocked | done | parked

## Scope

One short paragraph.

## Source Of Truth

- Plan/phase/issue: <link>

## Next Action

One concrete step.

## Touched Areas

- <path or module>

## Notes

Only details needed by another terminal to avoid conflicts.
```
