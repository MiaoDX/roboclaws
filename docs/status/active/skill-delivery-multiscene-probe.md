# Skill Delivery Multi-Scene Probe

Status: complete; reviewed; inconclusive

The completed campaign is a reviewed, paired `no-skill` versus `static-full`
cleanup comparison across MolmoSpaces scenes 0, 10, and 12. It uses
`kimi-openai-chat` / `kimi-k2.7-code`, seed 7, `world-public-labels`, five
relocated objects, local serial execution, and zero automatic live retries.

The frozen run-local identity is under
`output/eval-probes/20260805-skill-delivery-multiscene/experiment.json`.
This probe cannot change the default or publish a durable baseline/catalog;
the reviewed result did not justify either action.

## Result

Both cells completed all three local live trials with the same Kimi model,
scene set, seed, tool surface, and zero automatic retries. The authoritative
eval result is `0/3` for both cells:

| Scene | `static-full` | `no-skill` |
| --- | --- | --- |
| 0 | eval failed; restoration 0.0 | eval failed; restoration 0.0 |
| 10 | eval failed; run restoration 0.8, incomplete semantic sequence | eval failed; restoration 0.0 |
| 12 | eval failed; restoration 0.0 | eval failed; run restoration 0.8, incomplete semantic sequence |

All six trials reached the product checker. No provider, network, runtime, or
privacy failure was observed, and no automatic retry ran. The two successful
`run_result` outcomes are not eval passes because the checker rejected the
corresponding semantic evidence. This is an inconclusive quality comparison,
not a promotion result. Keep the product default unchanged and do not publish
a baseline or catalog artifact.

Evidence:

- `output/eval-probes/20260805-skill-delivery-multiscene/results/probe_skill_delivery_multiscene_20260805/static-full/eval_results.json`
- `output/eval-probes/20260805-skill-delivery-multiscene/results/probe_skill_delivery_multiscene_20260805/no-skill/eval_results.json`
