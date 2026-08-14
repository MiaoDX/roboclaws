# Agent Operating Runbook

This file holds repo-specific operating details that are too long for
`AGENTS.md` but useful to coding agents. Read only the sections relevant to the
current task.

## Environment Setup

Roboclaws uses one repo-local Python environment per checkout/worktree:
`.venv/`, managed by `uv` from `pyproject.toml` and `uv.lock`.

```bash
uv sync --extra dev
```

Use `uv sync` for declared project environments and `uv pip install` only for
explicit one-off local installs. Do not use plain `pip install` for repo setup.

The `dev` extra includes the standard MolmoSpaces/MuJoCo CPU runtime used by
local cleanup demos. Keep Isaac Lab isolated in `.venv-isaaclab/` and install
other optional extras only when a workflow explicitly needs them.

If PyPI downloads are slow or flaky, keep mirror selection machine-local:

```bash
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple \
  uv sync --extra dev
```

## Worktree Setup Hooks

This checkout uses project hooks from `.githooks/`; `core.hooksPath` should
point there. Install or repair it with:

```bash
git config core.hooksPath .githooks
```

`.githooks/post-checkout` auto-creates a worktree-local `.venv/`, a
`.venv-visual-grounding/`, copies gitignored local config such as `.env`, and
symlinks `.venv-isaaclab/` from the main checkout when it already exists.

Submodules under `vendors/` are mostly reference/vendor inputs. Inspect the main
checkout or `git submodule status --recursive` first; initialize a submodule in
the current worktree only when you need to modify it, run isolated verification,
or prove the exact checkout.

## Provider Keys And Network Guard

Local sessions keep provider keys in the repo-local `.env` file, which is
gitignored. Source it before any real VLM/provider call:

```bash
set -a && source .env && set +a
python -c "import os; assert os.environ.get('KIMI_API_KEY') or os.environ.get('CODEX_RESPONSES_API_KEY') or os.environ.get('MIMO_RESPONSES_API_KEY') or os.environ.get('MM_API_KEY'), 'No provider key set - did you source .env?'"
```

Current live product route:

- `agent_engine=openai-agents-sdk`
- `codex-responses` requires `CODEX_RESPONSES_BASE_URL`,
  `CODEX_RESPONSES_API_KEY`, and `CODEX_RESPONSES_MODEL`.
- `mimo-responses` requires `MIMO_RESPONSES_BASE_URL`,
  `MIMO_RESPONSES_API_KEY`, and `MIMO_RESPONSES_MODEL`.
- `minimax-responses` requires `MM_BASE_URL` and `MM_API_KEY`.
- `kimi-openai-chat` requires `KIMI_OPENAI_BASE_URL` and `KIMI_API_KEY`.

Every OpenAI Agents SDK launch selects one of these profiles explicitly. The
runtime never falls back between Responses and Chat Completions transports.

Before system-provider Claude Code workflows:

```bash
just dev::network-status
```

If it reports `network: work`, do not run those guarded routes. Model-only
overrides do not bypass the guard.

## Browser QA Sandbox Fallback

When using gstack `browse` / Playwright for local UI dogfooding, Ubuntu 24.04
hosts may fail Chromium startup with `No usable sandbox!`. Do not weaken system
AppArmor or sysctl settings. Use the per-command fallback:

```bash
GSTACK_CHROMIUM_NO_SANDBOX=1 browse goto http://127.0.0.1:<port>
```

## Test And Lint Workflow

Standard checks:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
```

Use the standalone pytest wrapper on hosts where ROS jazzy site-packages leak
into pytest collection and trigger a missing `lark` import.

For a focused loop:

```bash
./scripts/dev/run_pytest_standalone.sh tests/<target>.py -k <pattern> -q
```

## Public Command Routing

Translate natural-language demo requests to the public surface grammar:

```bash
just run::surface surface=<surface> agent_engine=<engine> [world=<world>] [backend=<backend>] [intent=<intent>] [provider_profile=<profile>] [key=value ...]
```

Examples:

- Map build:
  `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=map-build agent_engine=direct-runner evidence_lane=camera-grounded-labels camera_labeler=grounding-dino`
- SDK cleanup:
  `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco preset=cleanup agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat evidence_lane=world-public-labels`
- Open household goal:
  `just run::surface surface=household-world world=molmospaces/procthor-10k-val/0 backend=mujoco agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat prompt="我渴了，帮我找些解渴的东西"`
- Planner proof:
  `just run::surface surface=planner-proof world=planner-proof/default backend=mujoco intent=planner-proof agent_engine=direct-runner mode=dry-run`

Use `agent::*` for deeper maintainer control:

```bash
just agent::verify <target> [args ...]
just agent::harness <target> [args ...]
just agent::mcp up|down
```

Lower modules such as `molmo::*`, `harness::*`, `verify::*`, `mcp::*`, and
`dev::*` are private implementation
details. They remain runnable for debugging but should not be the first choice
for natural-language run requests.

For agent-facing changes, prefer the eval harness instead of hand-writing a
fixed gate list:

```bash
just agent::eval recommend plan=<path> budget=focused
just agent::eval execute since=<base> budget=focused
```

## Cloud vs Local Split

Cloud-style sessions are good for research, small mock-covered changes, CI/doc
edits, issue/PR work, and tasks whose proof is tests or deterministic mocks.

Local workstation sessions are required for real provider keys, simulator/GPU,
robot/backend services, screenshots/GIF evidence, and multi-round live debug
loops.

If a change's core claim depends on real hardware, real simulator rendering, or
real provider behavior, validate it locally or
state the missing validation explicitly. CI is continuous proof, not first
validation for local-only claims.

## Commit Hygiene Details

Before committing:

```bash
git status --short
git diff --cached
```

Stage only paths or hunks that belong to the current task. Avoid broad staging
commands in this shared checkout. If unrelated changes are present, leave them
alone and mention them if they affect verification or commit boundaries.
