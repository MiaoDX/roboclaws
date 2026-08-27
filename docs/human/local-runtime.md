# Local Runtime Reference

Normal users configure provider keys; observability is optional and fail-open.

## Optional Local Opik

Opik 2.2.36 is the supported local observability backend. It never gates a
product run, eval outcome, collection, or promotion. The base deployment is
loopback-only and stores retained data under `output/opik/`.

```bash
bash scripts/dev/validate_opik_deployment.sh
docker compose -p roboclaws-opik -f deploy/opik/compose.yaml up -d --wait
```

The explicit LAN overlay exposes only the web frontend for human review:

```bash
OPIK_LAN_BIND_HOST=192.0.2.60 \
OPIK_LAN_HTTP_PORT=5174 \
docker compose -p roboclaws-opik -f deploy/opik/compose.yaml \
  -f deploy/opik/compose.lan.yaml up -d
```

Set one loopback base origin for automatic runtime and eval projection:

```bash
export ROBOCLAWS_OPIK_ENDPOINT=http://127.0.0.1:5174
```

Roboclaws routes traces to exactly `roboclaws-runtime` and `roboclaws-eval`.
Eval projection writes adjacent `opik_projection.json` receipts and is bounded,
atomic, idempotent, and fail-open. `opik-project` repairs one named result;
`opik-dashboard` is the explicit Dashboard reconciliation command.

Opik receives only sanitized public identity, allowlisted metrics, and span
metadata. It never receives prompts, tool bodies, images, maps, secrets,
private evaluator truth, or provider endpoints. Local JSON, Markdown, run
artifacts, graders, and promotion decisions remain canonical.

## Provider Keys

Copy `.env.example` to `.env`, then fill only the keys you have:

```bash
KIMI_OPENAI_BASE_URL=
KIMI_API_KEY=
MM_BASE_URL=
MM_API_KEY=
CODEX_RESPONSES_BASE_URL=
CODEX_RESPONSES_API_KEY=
CODEX_RESPONSES_MODEL=
MIMO_RESPONSES_BASE_URL=
MIMO_RESPONSES_API_KEY=
MIMO_RESPONSES_MODEL=
```

Every OpenAI Agents SDK launch selects a provider profile explicitly.

## Local Report Artifacts

Eval Harness terminal publication contains only `eval_harness.json`,
`eval_harness.md`, `eval_harness.completed.json`, and adjacent Opik receipts.
Domain-specific HTML reports remain available where their owning surface needs
them; the retired Eval Harness HTML companion and report server are gone.

The hosted capability showcase uploads any adjacent `opik_projection.json`
receipt with its canonical suite bundle, but never sends it to Opik. A trusted
maintainer may later project a retained result with `just agent::eval
opik-project suite=<suite> eval_results=<path>` from a loopback-capable host.
