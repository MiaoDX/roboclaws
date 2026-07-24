# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: four distinct Stage A tasks have failed without platform retry. The first,
`t-20260724210310-e8v58`, exposed a legacy cleanup-manifest filename; its content-identity fix is
committed. The second, `t-20260724212407-tej6o`, reached the correct manifest and then failed because
the shared worker invoked a bare `uv` binary that the Isaac image does not expose. Review also found
that task generation overrode the image's valid `/isaac-sim/python.sh` runtime with a nonexistent
path. Those bootstrap defects are committed. The third, `t-20260724213659-xkdpj`, passed code
installation and the full CUDA/Isaac runtime preflight, then failed because the generic eval CLI
eagerly imported the unrelated session-live `mcp` dependency. That fix is committed. The fourth,
`t-20260724214533-lik6i`, reached the real RTX smoke and proved the remaining blocker is the CloudML
host driver. Stage B/C were not generated or submitted.

Last proof: the fourth task ran for 62 seconds on an approved guaranteed r49 host with no preemption
or platform retry. Code installation and runtime preflight passed on an RTX 4090 with driver
`570.124.06`, CUDA `12.8`, Isaac Sim `6.0.0`, Isaac Lab `6.1.14`, Torch `2.10.0+cu128`, and durable
EULA acceptance. The selected row then ran for 27.099 seconds and reached the real RTX renderer.
Isaac rejected driver `570.124.06` because Linux R570 versions in `[570.00, 570.158.01)` are
unsupported, then Warp reported CUDA illegal memory access 700 while loading the Isaac Lab sensor
kernel. Collection recovered the failed marker, row result, logs, generated USD, and init log; no
acceptance receipt was produced.

Next slice: CloudML must expose the approved r49 resource with a compatible NVIDIA driver, at least
`570.158.01` and preferably NVIDIA's recommended `580.95.05`. Recheck the driver through a fresh
Stage A attempt, accept Stage A, and only then generate Stage B.

Stop condition: the incompatible CloudML host driver is the current external blocker and cannot be
repaired inside the frozen repo/task ladder. In-scope repair/retry attempts no longer require
per-attempt approval once compatible r49 capacity is available. NVIDIA EULA acceptance remains
durable and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
