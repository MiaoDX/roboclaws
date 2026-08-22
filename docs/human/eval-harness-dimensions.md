# Eval Harness Dimensions

This page summarizes the maintained eval axes. Exact rows and profile
membership belong to machine-readable sources, so this page does not duplicate
counts that drift when the catalog changes.

Terminal reports project these axes into the quality-first observability
decision views documented in [evaluation.md](evaluation.md#observability-decision-report).
The dimension catalog remains the membership owner; the report does not define
a second catalog.

Sources of truth:

- Rows and profile membership: `skills/eval-harness/catalog/rows.json`
- Engines and providers: `roboclaws/launch/agent_engines.py` and
  `roboclaws/agents/provider_registry.py`
- Suites: `evals/household_world/suites/*.json`
- Scope decision: `docs/adr/0145-scope-eval-harness-profiles-to-purposeful-baselines.md`

## Baseline Profiles

| Profile | Intended use |
| --- | --- |
| `baseline-core` | Normal local refresh: deterministic gates, suites, direct product rows, and selected detector rows. |
| `baseline-live-default` | Core plus the normal explicit Kimi live-agent rows. |
| `baseline-refresh` | Release or nightly refresh including the explicit four-profile provider comparison. |

Provider-backed rows run only when their preflight is ready. Otherwise they
record blocked evidence; they are never silently replaced by a different
provider or wire API.

## Agent Engines

| Engine | Role | Provider selection |
| --- | --- | --- |
| `direct-runner` | Deterministic product and suite baseline. | None. |
| `openai-agents-sdk` | Maintained live-agent engine. | One explicit SDK profile is required. |
Retired coding-agent engines are rejected by launch validation and are not
preserved as compatibility aliases.

## SDK Provider Profiles

| Profile | Default model | Wire API | Current role |
| --- | --- | --- | --- |
| `codex-responses` | Environment-supplied opaque model, public label `codex` | Responses | Independent Codex cell with passing fixed-prior live proof. |
| `mimo-responses` | Environment-supplied opaque model, public label `mimo` | Responses | Independent MiMo cell with passing fixed-prior live proof. |
| `minimax-responses` | `MiniMax-M3` | Responses | Named public comparison route. |
| `kimi-openai-chat` | `kimi-k2.7-code` | Chat Completions | Only Chat Completions route and normal live default selection. |

No endpoint/model default or transport fallback exists. Codex's thin HTTP
compatibility adapter is profile-scoped; commands, packets, and console
launches serialize the selected profile explicitly.

## Capability Axes

| Axis | Maintained values |
| --- | --- |
| Intent | `open-ended`, `cleanup`, `map-build`, `planner-proof`, `route-trace`, `eval-harness`, `eval-suite` |
| Preset | no preset/open-ended, `cleanup`, `map-build` |
| Evidence lane | `world-public-labels`, `camera-grounded-labels`, `camera-raw-fpv` |
| Camera labeler | `grounding-dino` and other cataloged comparison labelers for camera-grounded rows |
| Public backend | `mujoco` for the default MolmoSpaces simulation route |
| Optional validation backends | Agibot GDK and Isaac Lab, selected explicitly and omitted from default discovery |
| Scenario setup | `baseline`, `relocate-cleanup-related-objects` |
| Runtime prior | no prior or one explicit read-only Runtime Map Prior Snapshot |

RAW-FPV direct-runner evaluation remains available. No final SDK provider has
verified image transport, so SDK RAW-FPV is not a maintained live baseline row.

## Suites

The household suite set covers smoke regression, cleanup capability, MapBuild
quality and consumption, open-ended goals, scene sampling, and long-horizon
tasks. Read each suite JSON for exact samples and graders.

Provider health is useful availability evidence, not robot capability proof.
Keep provider comparisons explicit and keep deterministic, simulator, detector,
hardware, and provider failures classified separately.
