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

Last proof: commit `1e1c7cd303214ffaf7f70c63309f1fe15a4ddf9d` generated a fresh Stage A
identity with code archive SHA `9e6f4126e89d3dfce68ed20888b21b261cd3706c7592e28abdf5da375fc366fc`
and proof-contract SHA `4d59a8b4fb43543413bec3754fd7eb04b9a244c3ccb82892da33e45133739c96`.
The dry-run retained one guaranteed r49 GPU, `preemptible=false`, `enableRetry=false`, and the
required 580-series gate. Twenty-eight one-GPU tasks then sampled `slave564` (10), `slave565` (12),
and `slave574` (6). One eight-GPU diagnostic sampled `slave589`; two four-GPU diagnostics sampled
`slave565`. All 31 tasks were non-preemptible with `retryTimes=0`, reported exact driver
`570.124.06`, selected native graphics libraries, and stopped before Isaac because the required
series was 580. No task reached the overlay branch, no Stage A receipt was produced, and the
diagnostic multi-GPU tasks are not acceptance evidence. Run inputs and one-GPU plan artifacts live
under `/tmp/roboclaws-cloudml-isaac-vulkan580-proof/`. Representative task IDs are one-GPU
`t-20260725003836-df1h0`, eight-GPU `t-20260725005104-rxnzc`, and four-GPU
`t-20260725005314-y1pox` / `t-20260725005455-ay4e4`.

Next slice: when the scheduler exposes the known `580.105.08` r49 group, rerun the normal one-GPU
Stage A with the pinned image and require the log to show `mode=overlay`, both explicit Vulkan ICD
variables, successful RTX startup, and accepted nonblank artifacts. Accept Stage A before
generating Stage B.

Stop condition: the remaining blocker is external CloudML placement availability. The
custom-train schema exposes no hostname affinity, and bounded 1/4/8-GPU placement shapes did not
reach a 580 host in the current scheduling window. In-scope retry attempts do not require
per-attempt approval once compatible capacity is available. NVIDIA EULA acceptance remains durable
and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
