# Contributing to Roboclaws

## Development Setup

```bash
git clone https://github.com/MiaoDX/roboclaws.git
cd roboclaws
uv sync --extra dev
```

Run the fast gate before ordinary commits:

```bash
ruff check .
ruff format --check .
./scripts/dev/run_pytest_standalone.sh -q
```

Use the standalone pytest wrapper on hosts where ROS site-packages leak into
pytest collection.

## Dev Tooling

| Tool | What it does | Why we use it |
| --- | --- | --- |
| `uv` | project environment manager | Builds the repo-local `.venv/` from `pyproject.toml` and `uv.lock`, including the standard MolmoSpaces/MuJoCo CPU runtime. |
| `just` | command runner | Exposes the small public `run::surface` and `agent::*` facade while keeping implementation modules private. |

Install with the upstream single-binary installers if your package manager has
an older `just`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \
  | bash -s -- --to ~/.local/bin
```

Discover commands:

```bash
just
just --summary
just --list run
just --list agent
```

Current public examples:

```bash
just run::surface surface=household-world agent_engine=direct-runner preset=map-build evidence_lane=camera-grounded-labels camera_labeler=grounding-dino
just run::surface surface=household-world agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat preset=cleanup evidence_lane=world-public-labels
just run::surface surface=household-world agent_engine=openai-agents-sdk provider_profile=kimi-openai-chat prompt="find something useful to drink"
just agent::verify
```

## Development Topology

Day-to-day work is split between cloud-style and local sessions.

| | Cloud session | Local session |
| --- | --- | --- |
| Provider/API keys | usually no | yes, from repo-local `.env` |
| Simulator/GPU/display resources | no | yes, when configured locally |
| Backend services | no | yes |
| Good tasks | docs, CI, mock-covered refactors, issue work | real-provider validation, GPU/backend runs, long debug loops |
| Validation ceiling | lint, unit, contract, mock gates | real provider + simulator/backend evidence |

The first validation of a real-provider, GPU, robot, or backend-specific claim
happens locally. CI keeps accepted proof continuously visible; it should not be
the first place a local-only claim is exercised.

## CI Overview

| Job | Trigger | Purpose |
| --- | --- | --- |
| `lint-and-mock` | every push and PR | `just agent::verify`: ruff, format check, deterministic pytest, and active household report contracts. |

Required CI must stay deterministic and secret-light. Real provider, GPU,
Isaac, Agibot, and robot-backed runs belong in advisory, manual, scheduled,
or local-only gates unless explicitly promoted.

## Secrets

Repo-local `.env` is the normal local route and is ignored by git. Common keys:

```bash
KIMI_API_KEY=
KIMI_OPENAI_BASE_URL=
MM_API_KEY=
MM_BASE_URL=
CODEX_RESPONSES_API_KEY=
CODEX_RESPONSES_BASE_URL=
CODEX_RESPONSES_MODEL=
MIMO_RESPONSES_API_KEY=
MIMO_RESPONSES_BASE_URL=
MIMO_RESPONSES_MODEL=
```

GitHub secrets are needed only for workflows that run live provider profiles.
Do not paste secrets into logs, PR descriptions, reports, or planning files.

## Git Workflow

- Branch from `main`.
- Keep commits scoped.
- Use `type: description` commit messages such as `fix: tighten cleanup gate`.
- Push to a feature branch and open a PR targeting `main`.
