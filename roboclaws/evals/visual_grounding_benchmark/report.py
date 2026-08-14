from __future__ import annotations

import sys
from html import escape
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def _render_report(*, result: dict[str, Any], predictions: list[dict[str, Any]]) -> str:
    pipeline_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(row.get('benchmark_row_id', '')))}</td>"
        f"<td>{escape(str(row.get('pipeline_id', '')))}</td>"
        f"<td>{escape(str(row.get('model_family', '')))}</td>"
        f"<td>{escape(str(row.get('size_tier', '')))}</td>"
        f"<td>{escape(str(row.get('score', 0)))}</td>"
        f"<td>{escape(str(row.get('score_basis', '')))}</td>"
        f"<td>{escape(str(row.get('bbox_recall_at_iou', 0)))}</td>"
        f"<td>{escape(str(row.get('bbox_precision_at_iou', 0)))}</td>"
        f"<td>{escape(str(row.get('recall', 0)))}</td>"
        f"<td>{escape(str(row.get('precision', 0)))}</td>"
        f"<td>{escape(str(row.get('failure_rate', 0)))}</td>"
        f"<td>{escape(str(row.get('timeout_rate', 0)))}</td>"
        f"<td>{escape(str(row.get('mean_latency_ms', 0)))}</td>"
        f"<td>{escape(str(row.get('evidence_level', '')))}</td>"
        "</tr>"
        for row in result.get("ranking") or []
    )
    observation_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('pipeline_id', '')))}</td>"
        f"<td>{escape(str(item.get('observation_id', '')))}</td>"
        f"<td>{escape(str((item.get('pipeline') or {}).get('status', '')))}</td>"
        f"<td>{escape(str(item.get('candidate_count', 0)))}</td>"
        f'<td><a href="{escape(str(item.get("overlay_path", "")))}">overlay</a></td>'
        "</tr>"
        for item in predictions
    )
    stage_rows = "\n".join(
        _stage_report_rows(pipeline) for pipeline in result.get("pipelines") or []
    )
    destination_rows = "\n".join(
        _destination_report_rows(pipeline) for pipeline in result.get("pipelines") or []
    )
    telemetry_rows = "\n".join(
        _telemetry_report_rows(pipeline) for pipeline in result.get("pipelines") or []
    )
    detector_probe_rows = "\n".join(
        _detector_probe_report_rows(result.get("detector_probe_recommendation") or {})
    )
    family_rows = "\n".join(
        _family_sweep_report_rows(row) for row in result.get("family_sweep") or []
    )
    detector_probe = result.get("detector_probe_recommendation") or {}
    detector_probe_gate_text = (
        "Real stage provenance present: "
        f"{detector_probe.get('real_stage_provenance_present', False)}. "
        "Selected real-stage provenance complete: "
        f"{detector_probe.get('selected_real_stage_provenance_complete', False)}. "
        "Requires real detector-sidecar provenance before full cleanup probe: "
        f"{detector_probe.get('requires_real_stage_provenance_before_probe', True)}."
    )
    private_note = (
        "Per-item private label details included."
        if any("private_label_details" in pipeline for pipeline in result.get("pipelines") or [])
        else "Per-item private label details omitted; only aggregate private metrics are shown."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Visual Grounding Benchmark</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #202124; }}
    table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
    th, td {{ border: 1px solid #d0d7de; padding: 0.45rem 0.55rem; text-align: left; }}
    th {{ background: #f6f8fa; }}
    code {{ background: #f6f8fa; padding: 0.1rem 0.25rem; }}
  </style>
</head>
<body>
  <h1>Visual Grounding Benchmark</h1>
  <p>Corpus: <code>{escape(str((result.get("corpus") or {}).get("name", "")))}</code></p>
  <h2>Pipeline Ranking</h2>
  <table>
    <tr>
      <th>Row</th><th>Pipeline</th><th>Family</th><th>Size</th>
      <th>Score</th><th>Basis</th><th>Bbox recall</th><th>Bbox precision</th>
      <th>Recall</th><th>Precision</th>
      <th>Failure rate</th><th>Timeout rate</th><th>Mean latency ms</th>
      <th>Evidence level</th>
    </tr>
    {pipeline_rows}
  </table>
  <h2>Family Sweep Coverage</h2>
  <table>
    <tr>
      <th>Family</th><th>Rows tested</th><th>Size tiers</th>
      <th>Under-sampled</th><th>Reason</th>
    </tr>
    {family_rows}
  </table>
  <h2>End-To-End Probe Recommendation</h2>
  <p>
    The recommended full-cleanup probe set is capped to the sim control and one
    detector-only proposer pipeline.
  </p>
  <p>{escape(detector_probe_gate_text)}</p>
  <table>
    <tr><th>Slot</th><th>Pipeline</th><th>Evidence level</th><th>Reason</th></tr>
    {detector_probe_rows}
  </table>
  <h2>Visual Grounding Quality</h2>
  <p>{escape(private_note)}</p>
  <h2>Destination Hint Quality</h2>
  <p>
    Destination hints are recorded as producer evidence only. The cleanup runtime's
    destination hint resolver remains authoritative.
  </p>
  <table>
    <tr>
      <th>Pipeline</th><th>Hint rate</th><th>Known fixture rate</th>
      <th>Plausible hint rate</th><th>Actionability proxy rate</th>
    </tr>
    {destination_rows}
  </table>
  <h2>Cost And Resource Telemetry</h2>
  <table>
    <tr>
      <th>Pipeline</th><th>API cost available</th><th>Total USD</th>
      <th>Token usage available</th><th>Memory profile available</th><th>Peak MB</th>
    </tr>
    {telemetry_rows}
  </table>
  <h2>Stage Provenance</h2>
  <table>
    <tr>
      <th>Pipeline</th><th>Stage</th><th>Producer</th><th>Model</th>
      <th>Status</th><th>Latency avg ms</th><th>Device</th><th>Dtype</th><th>CUDA</th>
    </tr>
    {stage_rows}
  </table>
  <h2>Observation Overlays</h2>
  <table>
    <tr><th>Pipeline</th><th>Observation</th><th>Status</th><th>Candidates</th><th>Overlay</th></tr>
    {observation_rows}
  </table>
</body>
</html>
"""


def _stage_report_rows(pipeline: dict[str, Any]) -> str:
    rows = []
    pipeline_id = str(pipeline.get("pipeline_id") or "")
    for stage in pipeline.get("stage_summary") or []:
        runtime = stage.get("runtime") or {}
        rows.append(
            "<tr>"
            f"<td>{escape(pipeline_id)}</td>"
            f"<td>{escape(str(stage.get('stage', '')))}</td>"
            f"<td>{escape(str(stage.get('producer_id', '')))}</td>"
            f"<td>{escape(str(stage.get('model_id', '')))}</td>"
            f"<td>{escape(str(stage.get('status', '')))}</td>"
            f"<td>{escape(str(stage.get('latency_ms_avg', 0)))}</td>"
            f"<td>{escape(str(runtime.get('device', '')))}</td>"
            f"<td>{escape(str(runtime.get('dtype', '')))}</td>"
            f"<td>{escape(str(runtime.get('cuda_available', '')))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _destination_report_rows(pipeline: dict[str, Any]) -> str:
    metrics = pipeline.get("metrics") or {}
    return (
        "<tr>"
        f"<td>{escape(str(pipeline.get('pipeline_id') or ''))}</td>"
        f"<td>{escape(str(metrics.get('destination_hint_rate', 0)))}</td>"
        f"<td>{escape(str(metrics.get('destination_hint_known_fixture_rate', 0)))}</td>"
        f"<td>{escape(str(metrics.get('destination_hint_plausible_rate', 0)))}</td>"
        f"<td>{escape(str(metrics.get('actionability_proxy_rate', 0)))}</td>"
        "</tr>"
    )


def _telemetry_report_rows(pipeline: dict[str, Any]) -> str:
    api_cost = pipeline.get("api_cost") or {}
    memory = pipeline.get("memory_profile") or {}
    return (
        "<tr>"
        f"<td>{escape(str(pipeline.get('pipeline_id') or ''))}</td>"
        f"<td>{escape(str(api_cost.get('available', False)))}</td>"
        f"<td>{escape(str(api_cost.get('total_usd')))}</td>"
        f"<td>{escape(str(api_cost.get('token_usage_available', False)))}</td>"
        f"<td>{escape(str(memory.get('available', False)))}</td>"
        f"<td>{escape(str(memory.get('peak_mb')))}</td>"
        "</tr>"
    )


def _detector_probe_report_rows(detector_probe: dict[str, Any]) -> str:
    rows = []
    evidence_levels = detector_probe.get("evidence_levels") or {}
    for row in detector_probe.get("selected") or []:
        pipeline_id = str(row.get("pipeline_id") or "")
        evidence_level = (
            "control" if pipeline_id == "sim" else str(evidence_levels.get(pipeline_id) or "")
        )
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('slot') or ''))}</td>"
            f"<td>{escape(pipeline_id)}</td>"
            f"<td>{escape(evidence_level)}</td>"
            f"<td>{escape(str(row.get('reason') or ''))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _family_sweep_report_rows(row: dict[str, Any]) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(row.get('model_family') or ''))}</td>"
        f"<td>{escape(str(row.get('tested_config_count') or 0))}</td>"
        f"<td>{escape(', '.join(str(item) for item in row.get('size_tiers') or []))}</td>"
        f"<td>{escape(str(row.get('under_sampled', False)))}</td>"
        f"<td>{escape(str(row.get('under_sampled_reason') or ''))}</td>"
        "</tr>"
    )
