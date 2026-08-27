"""Eval result bundle and artifact persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.evals.models import EvalResult, EvalSuite
from roboclaws.evals.reports import render_eval_report, results_bundle


def persist_results(
    *,
    suite: EvalSuite,
    results: list[EvalResult],
    output_dir: Path,
    budget: str,
    selection: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    bundle = results_bundle(suite=suite, results=results, output_dir=output_dir, budget=budget)
    if selection:
        bundle["selection"] = selection
    results_path = output_dir / "eval_results.json"
    report_path = output_dir / "eval_report.html"
    write_json(results_path, bundle)
    report_path.write_text(render_eval_report(bundle), encoding="utf-8")
    bundle["artifacts"]["eval_results"] = str(results_path)
    bundle["artifacts"]["eval_report"] = str(report_path)
    write_json(results_path, bundle)
    return bundle, results_path, report_path


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
