# CloudML Eval Execution Capsule

Capsule status: BLOCKED

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: execute the approved standard CloudML Eval Harness support
through `intuitive-flow`, committing coherent slices along the way.

Current slice: CPU and RTX 4090 lifecycle proof is complete; internal Router
live rows are paused at the provider-identity decision boundary.

Current blocker: CloudML CLI v1.3.25 and the exported custom-train schema have no
native environment-secret reference or workload-identity parameter. `--env`
stores plaintext `envConfigs`, while `--image_secret` only authenticates image
pulls. Provider keys cannot be placed in argv, YAML, image commands, or JuiceFS
artifacts.

Blocker fingerprint: `cloudml_secret_injection_missing`; the recommended
Router-side workload-identity exchange requires product/security review before
implementation.

Last proven evidence:

- Local bounded parallelism, dependency ordering, frozen manifests, per-row
  timing/provenance, resumable submission, status polling, collection, and
  normal JSON/Markdown/HTML reporting are implemented and covered.
- Published CPU/CUDA images passed offline smokes and resolve to OCI digests
  `sha256:e715abbd...faa7` and `sha256:d1d4c398...69a4`.
- CPU task `t-20260721202435-8sghy` passed and collected
  `route-trace-contract-tests` in 12.969 seconds with zero failed/missing rows.
- RTX 4090 task `t-20260721211104-0e8nh` passed and collected
  `direct-camera-grounded-grounding-dino` in 238.08 seconds. Readiness returned
  five DINO candidates; MuJoCo/MolmoSpaces cleanup completed offline.
- Grounding DINO must use `cuda`/`auto` with Transformers 4.57.6; whole-model
  float16 fails because internal text position embeddings remain float32.
- The cleanup archive now contains versioned scene and `droid_objaverse` cache
  metadata. Staging uses executor's `exe` entrypoint and active config.
- Executor CloudML readiness is `ready`, but `custom_train submit` exposes no
  secure provider secret reference or workload identity field.
- A no-credential task reached both internal Router `/models` endpoints and
  received HTTP 401. The remaining failure is authentication, not CloudML
  egress, model quota, GPU/runtime readiness, or harness placement.
- CLI help, binary schema, and a redacted exported task structure agree that
  CloudML currently exposes ordinary `envConfigs`, an image-pull secret, and
  JuiceFS-specific mount credentials, but no general runtime secret binding.

Completed slice batch: local parallel execution and the complete CloudML
CPU/RTX 4090 submit/status/collect path, including pinned images, code/assets,
run-owned mounts, offline DINO, and MolmoSpaces product execution.

Next hypothesis: a Router endpoint can validate a CloudML workload assertion
and issue a short-lived, route-scoped token without placing a long-lived
provider credential in CloudML task configuration.

Next proof: after security approval and Router support, run one bounded API
Router row and one bounded MiMo Router row from CloudML, then inspect generated
YAML, logs, and collected artifacts for secret leakage before running the hybrid
baseline.

Stop condition: stop before any plaintext secret workaround, provider identity
substitution, destructive retry, or new cross-repo executor API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: API Router/MiMo live rows and hybrid baseline proof wait on the
workload-identity decision and Router implementation; direct Kimi/MiniMax remain
ineligible on the internal-only worker pool; the repository quality ratchet has
unrelated pre-existing drift; FDS publication remains optional.
