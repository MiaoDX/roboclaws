# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: NVIDIA EULA acceptance is explicit and durable; continue without asking again.

Current slice: the dedicated `cloudml-r49-isaac` capability, immutable image variable, opt-in
Stage A/B/C rows, non-preemptible placement, durable EULA acceptance, Isaac worker readiness, and
prior-stage acceptance-receipt validation are implemented. The Phase 0 proof contract freezes
runtime versions/revision, measured local byte inputs, minimum resource/headroom budgets, stage
commands and acceptance thresholds, asset groups, and maximum cost envelopes. Phase 1 local image
implementation and offline proof are complete.

Last proof: local image
`sha256:a5dab3a2bd7350334d644e1cea70cadf96203da01a64b754abfb98de5e58217e`
(`22042441547` bytes) passed the network-disabled GPU smoke on an RTX 3090. Exact Isaac Sim 6.0.0,
Isaac Lab 6.1.14, Torch 2.10.0+cu128, and CUDA 12.8 identities matched; RTX rendering loaded and
indexed the generated USD; the strict checker passed; and all four robot views were nonblank and
manually inspected. Focused image, runtime, eval, and backend tests pass.

Next slice: after separate publication approval, publish the proven image and record its registry
digest. Then request a separately bounded paid r49 Stage A approval. The CloudML capacity query is
also pending because `cml` is not installed on this host.

Stop condition: do not publish an image or submit any paid r49 task without separately scoped
approval. NVIDIA EULA acceptance is already authorized and must not be requested again.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, retries,
repeat Stage C, preemptible placement, and maintained-product promotion.
