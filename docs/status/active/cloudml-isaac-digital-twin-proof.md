# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: the dedicated `cloudml-r49-isaac` capability, immutable image variable, opt-in
Stage A/B/C rows, non-preemptible placement, durable EULA acceptance, Isaac worker readiness, and
prior-stage acceptance-receipt validation are implemented. The pinned image is published by
digest. Queue `11759` currently exposes the approved guaranteed r49 shape, and generated tasks now
record disabled auto-retry plus the frozen stage timeout and collector allowance.

Last proof: local and published image
`sha256:ce373d74339b1fd8687954a4d0585b531e37c0c80e6b80cd0ddb692267dd1831`
(`22042441664` bytes) passed the network-disabled GPU smoke on an RTX 3090. Exact Isaac Sim 6.0.0,
Isaac Lab 6.1.14, Torch 2.10.0+cu128, and CUDA 12.8 identities matched; RTX rendering loaded and
indexed the generated USD; the strict checker passed; and all four robot views were nonblank and
manually inspected. Registry publication completed under the immutable `roboclaws-eval-isaac-
e7e78a1e-20260724` tag. Focused image, runtime, eval, and backend tests pass.

Next slice: generate and inspect Stage A from a committed code archive and the generated-smoke
asset group, then submit one guaranteed, non-preemptible r49 task. Collect and strictly accept it
before preparing Stage B.

Stop condition: stop on any failed stage, capacity/registry/JuiceFS/runtime mismatch, retry need, or
material scope/resource/cost change. The approved ladder permits no automatic or manual retry.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, retries,
repeat Stage C, preemptible placement, and maintained-product promotion.
