---
name: report-performance-analysis
description: Use this skill whenever the user asks whether a Roboclaws live-agent report run is faster, wants to compare Agent SDK/Codex/Claude cleanup reports, asks about model-call work, residual latency, speedup validity, or report performance under provider/network variance. The skill extracts sanitized JSON metrics first and answers only from generated metric/comparison artifacts, not from report.html scraping or raw prompts.
---

# Report Performance Analysis

Use this skill to analyze Roboclaws live-agent report performance honestly under
unstable provider and network conditions.

## Workflow

1. Read `references/metric-contract.md`.
2. Identify the run directory or comparison manifest.
3. Run fixed scripts before answering:
   - One run: `../../scripts/reports/extract_live_report_metrics.py <run_dir>`
   - Two runs or manifest: `../../scripts/reports/compare_live_report_metrics.py ...`
   - Calibration data: `../../scripts/reports/calibrate_model_latency.py ...`
4. Answer from generated JSON packets. Do not scrape `report.html`, raw prompt
   text, model text, full tool payloads, private evaluator truth, or compact
   continuation state.

## Interpretation Rules

- Lead with quality and effect before wall time.
- Treat single-run output as diagnostic unless an explicit baseline or manifest
  is supplied.
- Missing token, duration, image, or calibration fields are unavailable, not
  zero.
- A faster candidate is not a speed win when quality regressed unless the
  comparison packet records an explicit waiver.
- Call out apples-to-oranges baselines, missing telemetry, uncalibrated
  normalized model time, and high model/SDK residual latency.

## Common Commands

Extract one run:

```bash
.venv/bin/python scripts/reports/extract_live_report_metrics.py \
  output/path/to/seed-7 \
  --output output/report-performance-analysis/metrics.json \
  --write-model-call-metrics
```

Compare two runs:

```bash
.venv/bin/python scripts/reports/compare_live_report_metrics.py \
  --baseline-run-dir output/baseline/seed-7 \
  --candidate-run-dir output/candidate/seed-7 \
  --output output/report-performance-analysis/comparison.json
```

Compare with explicit normalized timing:

```bash
.venv/bin/python scripts/reports/calibrate_model_latency.py \
  --output output/report-performance-analysis/calibration.json \
  output/baseline/seed-7/model_call_metrics.jsonl \
  output/candidate/seed-7/model_call_metrics.jsonl

.venv/bin/python scripts/reports/compare_live_report_metrics.py \
  --baseline-run-dir output/baseline/seed-7 \
  --candidate-run-dir output/candidate/seed-7 \
  --calibration output/report-performance-analysis/calibration.json \
  --output output/report-performance-analysis/normalized-comparison.json
```

Compare a manifest:

```bash
.venv/bin/python scripts/reports/compare_live_report_metrics.py \
  --manifest skills/report-performance-analysis/templates/comparison-manifest.json \
  --output output/report-performance-analysis/comparison.json
```

## Answer Shape

Use a compact answer:

```text
Verdict: <accepted speed win | diagnostic only | rejected | blocked>
Quality: <same/better/regressed and why>
Work: <model calls, tool calls, uncached/output/reasoning tokens>
Timing: <wall time, model API time, estimated model work availability, residual>
Limitations: <missing telemetry/calibration/apples-to-oranges/live gate>
Evidence: <metric JSON path or comparison JSON path>
```
