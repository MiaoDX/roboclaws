# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: three distinct Stage A tasks have failed without platform retry. The first,
`t-20260724210310-e8v58`, exposed a legacy cleanup-manifest filename; its content-identity fix is
committed. The second, `t-20260724212407-tej6o`, reached the correct manifest and then failed because
the shared worker invoked a bare `uv` binary that the Isaac image does not expose. Review also found
that task generation overrode the image's valid `/isaac-sim/python.sh` runtime with a nonexistent
path. Those bootstrap defects are committed. The third, `t-20260724213659-xkdpj`, passed code
installation and the full CUDA/Isaac runtime preflight, then failed because the generic eval CLI
eagerly imported the unrelated session-live `mcp` dependency. That import is now lazy locally.
Stage B/C were not generated or submitted.

Last proof: the third task ran for 35 seconds after image pull on an approved guaranteed r49 host
with no preemption or platform retry. It proved RTX 4090, driver `570.124.06`, CUDA `12.8`, Isaac Sim
`6.0.0`, Isaac Lab `6.1.14`, Torch `2.10.0+cu128`, and durable EULA acceptance. Its failed marker
recorded `exit_code=1` with the expected image, code, contract, asset-group, and manifest identities.
It produced no row result or acceptance receipt because `mcp` was imported before the selected
Isaac smoke row started.

Next slice: verify and commit the lazy session-live import, create a fresh code archive and dry-run,
then submit a new distinct Stage A attempt and accept it before Stage B.

Stop condition: stop only on a material workspace/resource/cost/scope change or an external blocker
that cannot be repaired inside the frozen ladder. In-scope repair/retry attempts no longer require
per-attempt approval. NVIDIA EULA acceptance remains durable and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
