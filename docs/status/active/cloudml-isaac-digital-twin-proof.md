# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: the driver-matched Vulkan runtime is implemented and locally proven. Image
`roboclaws-eval-isaac-vulkan580-4b483e4e-20260725` is pinned at
`sha256:6f6c1f9b4a0af8e2725e6842c3906d8ce31b0bb43f221bdd158c13157f7ab3ce`; it copies the
TheLastFoot-proven exact `580.105.08` userspace overlay and leaves exact `570.124.06` on native
CloudML-injected libraries. Unknown or mixed driver sets fail closed. The local offline image smoke
passed on RTX 3090 driver `570.211.01` with real Vulkan rendering and all required nonblank images.
Stage B/C were not generated or submitted.

Last proof: commit `e9824f25abd37c41b384d95344bee3935a6fd1ac` generated a current Stage A
identity with manifest SHA `202d926e672a177308b6b656a950c2a5adecf729782f6b8106cc5d88d5c29575`,
code archive SHA `9be279fb8e03f87085ee9f7ff8468e870aad85804ee005d1c7f3a4faa352d205`, and
proof-contract SHA `4d59a8b4fb43543413bec3754fd7eb04b9a244c3ccb82892da33e45133739c96`.
The task envelope retained one guaranteed r49 GPU, `preemptible=false`, `enableRetry=false`, and the
required 580-series gate. Eight sequential tasks followed by six same-second waves of eight tasks
added 56 one-GPU attempts: `slave559` (2), `slave563` (2), `slave564` (21), `slave574` (12),
`slave580` (13), and `slave589` (6). All were terminal with `retryTimes=0`, reported exact driver
`570.124.06`, selected native graphics libraries, and stopped before Isaac. Representative IDs are
`t-20260725114930-tjbej` (`slave574`), `t-20260725115948-vd1xo` (`slave559`),
`t-20260725115949-pcymd` (`slave563`), `t-20260725120554-5bsav` (`slave564`),
`t-20260725120554-m2czj` (`slave580`), and `t-20260725115948-nom12` (`slave589`).
Representative `run-85` lifecycle status was terminal/failed; collection recovered an identity-
complete marker with `exit_code=3` and correctly rejected acceptance because no row result existed.

Across both sampling windows there are now 84 normal one-GPU tasks, plus one eight-GPU and two
four-GPU placement diagnostics. No current task reached the overlay branch, no Stage A receipt was
produced, and the diagnostic multi-GPU tasks are not acceptance evidence. Run inputs and one-GPU
plan artifacts live under `/tmp/roboclaws-cloudml-isaac-vulkan580-proof/`; the current Stage A input
lives under `/tmp/roboclaws-cloudml-isaac-stage-a-e9824f25/`.

Next slice: when the scheduler exposes the known `580.105.08` r49 group, rerun the normal one-GPU
Stage A with the pinned image and require the log to show `mode=overlay`, both explicit Vulkan ICD
variables, successful RTX startup, and accepted nonblank artifacts. Accept Stage A before
generating Stage B.

Stop condition: the remaining blocker is external CloudML placement availability. The
custom-train schema exposes no hostname affinity, and bounded sequential, concurrent, 4-GPU, and
8-GPU placement shapes did not reach a 580 host in the current scheduling window. In-scope retry
attempts do not require per-attempt approval once compatible capacity is available. NVIDIA EULA
acceptance remains durable and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
