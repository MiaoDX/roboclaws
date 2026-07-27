# Restore Codex And MiMo Responses Cells

Status: BLOCKED

Source plan: `docs/plans/2026-07-27-restore-codex-mimo-responses-cells.md`

Control plane: current main-session intuitive-flow run

Latest intent: execute the approved dual-profile correction with task-scoped commits and required
live provider proof.

Current slice: deterministic implementation, current-doc alignment, local configuration migration,
and MiMo live proof are complete. Codex live proof is externally blocked.

Last proof: Ruff, format, the full standalone pytest suite, pre-commit scoped tests, and final
eval-selector cleanup tests pass; baseline-refresh selects four cells. MiMo health and its
fixed-prior suite pass 2/2. Exact endpoint/key/request-model scans are clear across tracked files
and the new output. Codex health returns HTTP 403 across two explicit request-model attempts.

Blocker fingerprint: `provider_entitlement_or_config/codex-responses/http-403`.

Next action: a human/provider owner resolves Codex entitlement or supplies a verified standard
Responses configuration, then rerun Codex health and its fixed-prior row.

Next proof: Codex provider health, then the Codex fixed-prior row from the same frozen Runtime Map
Prior. No additional model/header guessing is authorized.

Stop condition: stop on provider-specific transport needs, ambiguous local credential mapping,
overlapping owned-file edits, publication, or material external cost/resource expansion.

No-touch scope: MiniMax/Kimi semantics, CloudML, simulator scoring, physical movement, public push,
history rewriting, `.env` contents in logs/artifacts, and `job_config_template.yaml`.

Parked work: none.
