# OpenClaw image upgrade checklist

Use this checklist when bumping `OPENCLAW_IMAGE` (for example to `2026.4.26`).

## 1) Prepare and pin target image

- [ ] Set the candidate image in the repo default:
  - `scripts/openclaw/openclaw-defaults.env` → `OPENCLAW_IMAGE_DEFAULT="ghcr.io/openclaw/openclaw:2026.4.26"`
- [ ] If running CI manually, pass the candidate through env:
  - `OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:2026.4.26`
- [ ] Check `docs/human/openclaw/` and `docs/ai/openclaw/` for release-specific assumptions tied to the previous tag.

## 2) Pre-flight smoke (mandatory)

- [ ] Confirm Docker is clean on gateway ports:
  - `docker ps -a --format '{{.Names}}\t{{.Status}}' | grep -E 'openclaw-gateway' || true`
- [ ] Run bootstrap smoke command with the candidate image:
  - `OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:2026.4.26 IMAGE_MODEL=mimo_openai/mimo-v2.5 scripts/openclaw/openclaw-bootstrap.sh`
- [ ] Confirm startup succeeds and returns token.
- [ ] Confirm built-in probe returns `PONG` and prints a normal bootstrap summary.
- [ ] Confirm container cleanup state per local policy (`docker rm -f openclaw-gateway` after run).

## 3) MCP + tool profile validation

- [ ] Re-run MCP visibility check from `docs/human/openclaw/local.md` (initialize + `roboclaws__*` tool calls).
- [ ] Re-run tool-profile diff described in `docs/ai/openclaw/tool-profiles.md` against image artifacts.
- [ ] Verify `scripts/openclaw/openclaw-bootstrap.sh` still emits `tools.alsoAllow: ["bundle-mcp"]` for agents.
- [ ] Re-run plugin allowlist behavior probe from `docs/ai/openclaw/plugin-allowlist.md`.
- [ ] Validate startup logs with the new image:
  - plugin set matches expected allow-list
  - no provider/model fallback drift
  - no unexpected `/v1/chat/completions` probe regressions

## 4) Re-run behavior-dependent demos/tests

- [ ] Re-run OpenClaw smoke/demo path(s):
  - `just chat::run`
  - `just agent::run household-world openclaw-gateway world-public-labels task_intent=cleanup`
- [ ] Re-run relevant test entry points that assert OpenClaw startup/config invariants:
  - `pytest -q tests/contract/openclaw/test_openclaw_bootstrap.py`
- [ ] Record failures or behavior changes with exact image tag in checklist notes.

## 5) Documentation sync

- [ ] Update version references inside `docs/human/openclaw/*.md`, `docs/ai/openclaw/*.md`, and linked checklists.
- [ ] Update any measured values that change with the new image (startup latency, plugin count, profile assertions).
- [ ] Update release notes / planning notes if a behavior delta is blocking.

## 6) Merge gate

- [ ] New image proves healthy on at least one full local run.
- [ ] No changed plugin allow/block that removes required features.
- [ ] No unresolved references to `docs/openclaw-*.md` paths remain.
