# CloudML Eval Execution Capsule

Capsule status: ACTIVE

Source plan: `docs/plans/2026-06-18-cloudml-juicefs-eval.md`

Control plane: root Codex session, scope `cloudml-eval-execution`

Project-status writer: unassigned; return a status delta unless ownership is
made explicit.

Latest user intent: execute the approved standard CloudML Eval Harness support
through `intuitive-flow`, committing coherent slices along the way.

Current slice: CPU and RTX 4090 lifecycle proof is complete; the next boundary
is secure provider injection for internal Router live rows.

Current blocker: executor `custom_train submit` has no native secret reference,
environment-secret reference, or workload identity parameter. Provider keys
cannot be placed in argv, YAML, image commands, or JuiceFS artifacts.

Blocker fingerprint: `cloudml_secret_injection_missing`; security-sensitive
executor API expansion requires review before implementation.

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

Completed slice batch: local parallel execution and the complete CloudML
CPU/RTX 4090 submit/status/collect path, including pinned images, code/assets,
run-owned mounts, offline DINO, and MolmoSpaces product execution.

Next hypothesis: a native CloudML secret-reference or workload-identity field
can make internal API Router and MiMo rows runnable without exposing provider
keys.

Next proof:

```bash
cd /home/mi/executor
./exe compute cloudml custom_train submit -h
```

Stop condition: stop before any plaintext secret workaround, provider identity
substitution, destructive retry, or new cross-repo executor API change.

No-touch scope: product task strategy, MCP semantics, grader policy, physical
robot backends, unrelated plans, and direct-provider identity aliases.

Parked work: API Router/MiMo live rows and hybrid baseline proof wait on secure
provider injection; direct Kimi/MiniMax remain ineligible on the internal-only
worker pool; the repository quality ratchet has unrelated pre-existing drift;
FDS publication remains optional.
