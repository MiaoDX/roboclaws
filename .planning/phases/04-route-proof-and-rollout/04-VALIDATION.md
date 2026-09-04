# Phase 4 Validation Ledger

This ledger is the Nyquist gate for the route-proof plans. It is an execution
checklist, not product implementation.

| Wave | Proof | Required command or flow | Evidence / blocker rule |
|---|---|---|---|
| 1 | Route, budget, baseline, privacy, digest invariants | `./scripts/dev/run_pytest_standalone.sh -q tests -k 'context or baseline or mapbuild or cleanup or open_ended or privacy or digest or artifact'` | Fail on missing unmanaged `baseline`, budget overflow/replay, privacy leak, or digest drift. |
| 2 | Camera/DINO integration | `./scripts/dev/run_pytest_standalone.sh -q tests -k 'camera or dino or grounding'` | Preserve scoped evidence and content digests. |
| 2 | Operator-console and Agibot metadata | focused tests, then automated browser QA against `just console::run` | No physical movement; assert route metadata, readiness, assets, console/network errors, and responsive layout. |
| 3 | Focused eval matrix | `just agent::eval recommend ... budget=focused` then approved `execute` | Packet must include cleanup, MapBuild, open-ended SDK, DINO, operator, Agibot, and explicit baseline rows. |
| 3 | Conditional live product proof | `scripts/dev/network_status.sh`, provider/DINO readiness probes, then documented `just run::surface ...` command | Capture command/output/timestamp; unavailable prerequisites produce `BLOCKED_NEEDS_LOCAL_VALIDATION`, never fallback. |

## Completion Gate

Run `ruff check .`, `ruff format --check .`, and
`./scripts/dev/run_pytest_standalone.sh -q` after focused checks. Phase proof is
complete only when deterministic and eval gates pass and live gates either pass
or have a concrete guarded blocker receipt. No code, launch axis, public
contract, or durable baseline publication is authorized by this ledger.

## Execution Record: 2026-09-02

| Gate | Result | Evidence |
|---|---|---|
| Ruff | PASS | `ruff check .` |
| Format | PASS | `ruff format --check .` (`1007 files already formatted`) |
| Full standalone pytest | PASS | Full standalone pytest passes after aligning active Kimi fixtures and the model-matrix route with canonical `k3`; only existing deprecation warnings remain |
| Route/context deterministic selection | PASS | Continuation regressions fixed in `b3199b6d`; broad selector passed on rerun |
| Privacy/digest/artifact selection | PASS | Focused standalone pytest exited 0 |
| Camera/DINO/operator/Agibot selection | PASS | Focused standalone pytest exited 0 |
| Operator-console product flow | PASS | Automated browser QA selected Build Map, verified canonical route/readiness/safety metadata, loaded all assets, found no console/network errors or horizontal overflow, and captured desktop/mobile screenshots in `output/state-first-context-manager/` |
| Focused eval recommendation | PASS | `output/eval-harness/20260902T045438Z/`; JSON digest `3bb18c5706d6c3f98ef0839761932cf31deec13be60074cc55b3fedd59899678` |
| Focused eval execution | PARTIAL | The current 30-row `baseline-refresh` completed with 25 passed rows and 5 Kimi cleanup comparison rows blocked by the provider's 5-hour quota; no rows failed and no provider substitution occurred. |
| Network readiness | PASS | Repo-local provider routes allowed |
| Camera-grounded live proof | PASS | `04-LIVE-PROOF.md`; real Grounding DINO sidecar readiness passed and the camera-grounded MapBuild product route completed with 35 detector events, 238 candidates, zero failures, and privacy-bounded artifacts |

The state-first implementation, DINO live proof, operator-console browser proof,
and scoped route contracts are supported by passing evidence. However,
`REQ-route-proof-and-rollout` remains partial because the canonical focused eval
command does not have an all-passing result. Its two failures are a missing
historical eval fixture and one existing direct-runner
`private_goal_not_satisfied` row; neither was introduced or changed by this
plan. No durable baseline was published.
