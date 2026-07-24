# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: implement the approved plan while preserving its external approval gates.

Current slice: the dedicated `cloudml-r49-isaac` capability, immutable image variable, opt-in
Stage A/B/C rows, non-preemptible placement, explicit EULA gate, Isaac worker readiness, and
prior-stage acceptance-receipt validation are implemented. The Phase 0 proof contract freezes
runtime versions/revision, measured local byte inputs, minimum resource/headroom budgets, stage
commands and acceptance thresholds, asset groups, and maximum cost envelopes. Existing CPU MuJoCo
and r49 DINO placement changes in the shared worktree are preserved.

Last proof: repo-wide ruff and all plan-named deterministic pytest gates pass. Isaac rows cannot
match the CPU or generic DINO pools, never inherit preemptible submission, reject a generic or
stage-mismatched content manifest, carry the frozen-contract digest, and B/C reject absent or
invalid receipts.

Next slice: implement the deterministic Isaac asset-packaging helper, including portable USD
closure/path validation and per-file/archive hashes, then generate the three dry-run fixtures. The
CloudML capacity query is still pending because `cml` is not installed on this host.

Stop condition: do not acquire/build the NVIDIA image without explicit EULA authorization; do not
publish an image or submit any paid r49 task without separately scoped approval.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, retries,
repeat Stage C, preemptible placement, and maintained-product promotion.
