# Phase 4 Live Blocker Receipt

- Timestamp: `2026-09-02T05:04:00Z` (Asia/Shanghai execution date 2026-09-02)
- RESULT_STATUS: `BLOCKED_NEEDS_LOCAL_VALIDATION`
- BLOCKER_KIND: `grounding-dino`
- BLOCKED_COMMAND: `.venv/bin/python -m roboclaws.household.visual_grounding_sidecar.readiness --pipeline grounding-dino`
- Exit code: `1`
- Sanitized output: `visual grounding sidecar is not ready for product runs: connection_error; loopback connection refused`

The preceding `scripts/dev/network_status.sh` probe exited 0 and reported that
repo-local OpenAI Agents SDK provider routes are allowed. The required
camera-grounded MapBuild command was not run because the DINO prerequisite did
not pass. No simulator-label, provider, baseline, or launch-axis substitution
was made.
