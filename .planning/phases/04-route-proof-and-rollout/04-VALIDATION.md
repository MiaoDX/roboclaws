# Phase 4 Validation Ledger

This ledger is the Nyquist gate for the route-proof plans. It is an execution
checklist, not product implementation.

| Wave | Proof | Required command or flow | Evidence / blocker rule |
|---|---|---|---|
| 1 | Route, budget, baseline, privacy, digest invariants | `./scripts/dev/run_pytest_standalone.sh -q tests -k 'context or baseline or mapbuild or cleanup or open_ended or privacy or digest or artifact'` | Fail on missing unmanaged `baseline`, budget overflow/replay, privacy leak, or digest drift. |
| 2 | Camera/DINO integration | `./scripts/dev/run_pytest_standalone.sh -q tests -k 'camera or dino or grounding'` | Preserve scoped evidence and content digests. |
| 2 | Operator-console and Agibot metadata | focused tests, then `just console::run` dry-run/manual checkpoint | No physical movement; missing runtime emits guarded blocker. |
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
| Route/context deterministic selection | FAIL | Two continuation-contract failures named in `04-01-SUMMARY.md` |
| Privacy/digest/artifact selection | PASS | Focused standalone pytest exited 0 |
| Camera/DINO/operator/Agibot selection | PASS | Focused standalone pytest exited 0 |
| Operator-console manual flow | NOT RUN | Blocking human inspection remains unproven |
| Focused eval recommendation | PASS | `output/eval-harness/20260902T045438Z/`; JSON digest `3bb18c5706d6c3f98ef0839761932cf31deec13be60074cc55b3fedd59899678` |
| Focused eval execution | FAIL | Stalled ten minutes in local row executor; stopped once, no retry |
| Network readiness | PASS | Repo-local provider routes allowed |
| Camera-grounded live proof | BLOCKED_NEEDS_LOCAL_VALIDATION | `04-LIVE-BLOCKER.md`; Grounding DINO loopback connection refused |

`REQ-route-proof-and-rollout` is not satisfied. Explicit managed-versus-baseline
results, the operator-console checkpoint, and the required available live proof
were not completed. No durable baseline was published.
