# CloudML Isaac Digital-Twin Proof

Status: BLOCKED

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

Next slice: after explicit NVIDIA EULA authorization, implement and offline-prove the pinned Isaac
image. Image publication and each paid r49 stage require their own later approvals. The CloudML
capacity query is also pending because `cml` is not installed on this host.

Blocker fingerprint: `external_approval:nvidia_eula`; Phase 1 image acquisition/build and runtime
smoke require an explicit EULA decision that the implementation-contract approval did not grant.

Stop condition: do not acquire/build the NVIDIA image without explicit EULA authorization; do not
publish an image or submit any paid r49 task without separately scoped approval.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, retries,
repeat Stage C, preemptible placement, and maintained-product promotion.
