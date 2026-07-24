# CloudML Isaac Digital-Twin Proof

Status: ACTIVE

Source plan: `docs/plans/2026-07-24-cloudml-isaac-digital-twin-proof.md`

Control plane: root intuitive-flow session

Latest intent: continue the bounded CloudML A/B/C proof. NVIDIA EULA acceptance is explicit and
durable; continue without asking again.

Current slice: driver-series sampling and graphics-runtime diagnosis are complete. Three bounded
waves created 25 independent Stage A tasks across five physical r49 host groups, all
non-preemptible and all with `retryTimes=0`. Placement was: 16 tasks on `slave574`, three on
`slave560`, and two each on `slave564`, `slave589`, and `slave590`. The worker now supports an
optional `580` series gate and records the graphics devices, libraries, and Vulkan ICDs before RTX
startup. Stage B/C were not generated or submitted.

Last proof: tasks `t-20260724232052-keaui`, `t-20260724234002-lz8aa`, and
`t-20260724234002-uuccz` reached RTX 4090 host `slave560` with driver `580.105.08`. All three passed
CUDA/Isaac runtime preflight with CUDA `12.8`, Isaac Sim `6.0.0`, Isaac Lab `6.1.14`, Torch
`2.10.0+cu128`, and durable EULA acceptance. The host exposes `nvidia-modeset`, the NVIDIA Vulkan
ICD, and `NVIDIA_DRIVER_CAPABILITIES=all`, but its container runtime does not inject
`libGLX_nvidia.so.0` or `libnvidia-glvkspirv.so.580.105.08`; only `libvulkan.so.1` is visible.
Isaac therefore fails at `vkCreateInstance` with `ERROR_INCOMPATIBLE_DRIVER`, then Warp reports
CUDA error 700 while loading `isaaclab.sensors.kernels`. In contrast, sampled `570.124.06` hosts
inject both NVIDIA graphics libraries correctly but are inside Isaac Sim 6.0's rejected R570
range. Collected evidence for `t-20260724234002-lz8aa` lives under
`/tmp/roboclaws-cloudml-isaac-driver580-wave3/run-3/cloudml/collected/`; no acceptance receipt was
produced.

Next slice: CloudML must repair the NVIDIA container-runtime graphics-library injection on the
`580.105.08` r49 group, or expose another r49 group with both driver `>=570.158.01` and complete
Vulkan driver libraries. Re-run one full Stage A after that platform change, accept it, and only
then generate Stage B.

Stop condition: the remaining blocker is external CloudML host/container-runtime configuration and
cannot be repaired through the custom-train schema, which exposes no hostname affinity, hostPath,
or privileged runtime control. In-scope repair/retry attempts do not require per-attempt approval
once compatible capacity is available. NVIDIA EULA acceptance remains durable and is not a blocker.

No-touch scope: MolmoSpaces+Isaac, digital-twin cleanup, Agibot hardware, physical movement,
provider selection, eval scoring policy, and unrelated CloudML hybrid work.

Parked work: alternate GPU classes, typed asset schema expansion, sidecar expansion, repeat Stage C,
preemptible placement, and maintained-product promotion.
