# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: the first Stage A task `t-20260724210310-e8v58` failed before GPU/runtime preflight.
The worker referenced the legacy cleanup-manifest filename while Isaac staging uploaded the
stage-specific manifest. The content-identity fix is implemented and focused tests pass. Stage B/C
were not generated or submitted.

Last proof: CloudML successfully pulled the published image on the approved guaranteed r49 host.
The task remained non-preemptible with `retryTimes=0`, ran for 31 seconds, and wrote a failed marker
with the expected image, code, contract, and asset identities. It produced no row result or
acceptance receipt. The prior network-disabled RTX 3090 image smoke remains accepted.

Next slice: create a fresh code archive and dry-run from the manifest-filename fix commit. Submit a
new Stage A attempt and accept it before Stage B.

Stop condition: stop only on a material workspace/resource/cost/scope change or an external blocker
that cannot be repaired inside the frozen ladder. In-scope repair/retry attempts no longer require
per-attempt approval. NVIDIA EULA acceptance remains durable and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
