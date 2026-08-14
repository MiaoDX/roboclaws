---
name: visual-result-showcase
description: Create blog, README, social, or demo-review visual showcases from completed Roboclaws run artifacts, especially chaptered GIFs/contact sheets for household cleanup runs. Use when asked to turn report output, robot_views, traces, or run_result.json into polished visual result evidence without rerunning the robot task.
---

# Visual Result Showcase

Use this skill when a completed Roboclaws run needs to become a publishable
visual artifact: blog GIF, README demo strip, release note contact sheet, or
operator-facing result montage.

## Boundary

This is post-run artifact work. By default, use only:

- `run_result.json`
- `trace.jsonl`
- `agent_view.json`
- `robot_views/*`
- public report images such as `before.png`, `after.png`, and map previews

Do not run a new robot task, call a VLM, inspect private manifests, or imply
that report-only views were agent inputs. If a score is shown, label it as
post-run evaluation.

## Household Cleanup GIF

For cleanup result showcases, prefer the whole-task story:

1. task and before state;
2. observe sweep progress;
3. every object cleanup chain, preserving the visible tool order;
4. final state and post-run evaluation.

Use the bundled renderer:

```bash
python skills/visual-result-showcase/scripts/render_household_cleanup_showcase.py \
  --run-dir output/household/household-world/cleanup/direct-world-public-labels/seed-7 \
  --out-dir docs/blog/assets/household-cleanup-showcase
```

The script writes:

- `showcase.gif`
- `contact_sheet.png`
- `frames/*.png`
- `manifest.json`

## Visual Rules

- Make FPV the main panel. Prefer `.fpv.bbox.png` when available.
- Label FPV as the agent-facing view.
- Label chase/RPV and verification/map views as report-only evidence.
- Include an MCP tool trace bar so the viewer sees `observe`, navigation,
  `pick`, `place`, receptacle open/close, and `done`.
- Keep claims honest: "Codex agent drives bounded MCP cleanup tools" is fine;
  "visual-only", "real robot", or "fully solved cleanup" is not unless the
  source run proves that exact claim.
- For WeChat/blog publication, keep a GIF plus source frames. Use the contact
  sheet for quick human review before embedding.
