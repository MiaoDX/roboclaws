# Forward-Only Post-Review Cleanup

Status: DONE

Source plan: `docs/plans/2026-07-28-forward-only-post-review-cleanup.md`

## Outcome

The repository now expresses one forward-only product architecture. Current
callers use source-aware MolmoSpaces IDs, a typed launch executor, package-owned
OpenAI Agents SDK runtime, a product-owned Runtime Prior catalog, one household
Skill strategy owner, and direct household projection owners.

The cleanup removed retired direct-provider implementations and tests,
product-to-eval imports, installable eval CLI aliases, legacy world aliases,
positional launch lowering, active script-library runtime identities, duplicate
generic prompt/MCP strategy, and private-symbol projection facades. Relative to
the approved plan commit, the tracked tree is net more than 3,700 lines smaller
without growing the Python quality baseline or adding compatibility shims.

## Proof

- Ruff, format, the Python quality ratchet, the full standalone suite, and
  `just agent::verify mock` pass.
- Smoke regression, open-ended goals, map-build quality, and no-prior consumer
  deterministic eval suites pass.
- Direct camera-grounded map-build and world-public cleanup product routes pass.
- All four provider health probes and fixed-prior consumer rows pass; the Kimi
  open-task and cleanup smoke rows pass.
- The accepted six-row live matrix contains zero provider failures, privacy
  leaks, and trajectory violations. Kimi fixed-prior and cleanup each used the
  one permitted repaired rerun.
- The supported operator-console route finished with passed checker state and
  exposed report, run result, trace, Runtime Map, preview, launch log, and
  operator state artifacts.

Live evidence is rooted at
`output/eval-harness/20260729T041434Z/final/eval_harness.json`. The final
source-derived recommendation is
`output/eval-harness/20260729T080334Z/eval_harness.json`.

## Candidate

The refreshed immutable candidate is
`output/public-candidate/20260729T082627Z/`, built from source commit
`5092fdd257d0b386415a4643cf350f750413216c`.

- Candidate commit: `172eaf904088fa2dcf704729b8452497fa02ceeb`
- Membership digest:
  `09feb969817b89ea732bd64c13f6d42ea84518a167ec00e80f69b4bbee844b16`
- Wheel SHA-256:
  `3b2add7aa8b6f0dfe0e671bb5044e8a073d292ceaa441f9511230ad3ee3aa0c7`
- Sdist SHA-256:
  `6d4f6030fdf16c225959c02d7d67bc9d46f716c722958901c5a6518f0aba6791`

The first candidate attempt exposed a stale secret baseline after intentional
provider deletion. The baseline was refreshed with the CI-pinned scanner and a
new candidate was built. In the clean room, the exact camera-grounded product
gate also proved that the declared `visual-grounding-dino` extra is required in
addition to `dev`; installing that existing extra allowed the unchanged gate to
pass.

The wheel and sdist contain the product runtime owners and omit
`roboclaws.evals`, eval definitions, and the eval-harness skill. Both artifacts
install in isolation, import the live household runtime with the declared
OpenAI Agents extra, resolve a typed product plan, and reject the retired eval
CLI alias.

Publication was not performed. The candidate is ready for a separate human
publication decision.

## Parked Work

None inside this plan. Repository-wide unrelated work remains in `TODOS.md` and
`THOUGHTS.md`.
