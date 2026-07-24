# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: two distinct Stage A tasks have failed before GPU/runtime preflight. The first,
`t-20260724210310-e8v58`, exposed a legacy cleanup-manifest filename; its content-identity fix is
committed. The second, `t-20260724212407-tej6o`, reached the correct manifest and then failed because
the shared worker invoked a bare `uv` binary that the Isaac image does not expose. Review also found
that task generation overrode the image's valid `/isaac-sim/python.sh` runtime with a nonexistent
path. Both bootstrap defects are now fixed locally with focused contract coverage. Stage B/C were
not generated or submitted.

Last proof: the second task ran for 32 seconds on an approved guaranteed r49 host with no preemption
or platform retry. Its failed marker recorded `exit_code=127` plus the expected image, code,
contract, asset-group, and manifest identities; history logs identify line 268's `uv: command not
found`. It produced no row result or acceptance receipt. The prior network-disabled RTX 3090 image
smoke remains accepted.

Next slice: verify and commit the Isaac bootstrap fix, create a fresh code archive and dry-run, then
submit a new distinct Stage A attempt and accept it before Stage B.

Stop condition: stop only on a material workspace/resource/cost/scope change or an external blocker
that cannot be repaired inside the frozen ladder. In-scope repair/retry attempts no longer require
per-attempt approval. NVIDIA EULA acceptance remains durable and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
