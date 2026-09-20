"""Build privacy-filtered, self-contained Pages report bundles."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

PUBLIC_SUFFIXES = {".html", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
PRIVATE_NAMES = {
    "private_evaluation.json",
    "prompt-identity.json",
    "agent_scratchpad.json",
    "trace.jsonl",
    "openai-agents-trace.json",
    "openai-agents-events.jsonl",
    "model_call_metrics.jsonl",
    "openai-agents-server.log",
}


def published_visual_report_href(execution_path: Path, bundle: Any) -> str | None:
    """Link a single trial's existing run report; keep multi-trial entry at the summary."""
    if not isinstance(bundle, dict):
        return None
    results = bundle.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        return None
    artifacts = results[0].get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    report_path = str(artifacts.get("report") or "")
    if not Path(report_path).is_file():
        return None
    return _published_visual_report_href(execution_path, report_path)


def _published_visual_report_href(execution_path: Path, report_path: str) -> str | None:
    try:
        relative_report = Path(report_path).relative_to(execution_path.parent)
    except (TypeError, ValueError):
        return None
    if (
        not relative_report.parts
        or relative_report.parts[0] != "evals"
        or ".." in relative_report.parts
    ):
        return None
    if relative_report.name != "report.html":
        return None
    return (Path("reports") / execution_path.parent.name / relative_report).as_posix()


def sanitize_report_html(source: str) -> str:
    """Remove evaluator truth and prompt/rerun controls from a public report."""
    source = re.sub(
        r"<section\b[^>]*\bprivate-evaluation\b[^>]*>.*?</section>",
        "",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source = re.sub(
        r"<details\b[^>]*\bsummary-metadata\b[^>]*>.*?</details>",
        "",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source = re.sub(
        r"<(?:section|div)\b[^>]*\brerun-panel\b[^>]*>.*?</(?:section|div)>",
        "",
        source,
        flags=re.I | re.S,
    )
    # JSON/JSONL links are internal evidence and are not part of the Pages bundle.
    source = re.sub(
        r'<a\b([^>]*?)\bhref=["\'][^"\']+\.(?:json|jsonl)(?:#[^"\']*)?["\']([^>]*)>(.*?)</a>',
        r"\3",
        source,
        flags=re.I | re.S,
    )
    return source


def publish_report_bundle(source_root: Path, destination_root: Path) -> int:
    """Copy public HTML and image assets while excluding private artifacts."""
    copied = 0
    for source in source_root.rglob("*"):
        if not source.is_file() or source.name in PRIVATE_NAMES:
            continue
        if source.suffix.lower() not in PUBLIC_SUFFIXES:
            continue
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() == ".html":
            destination.write_text(
                sanitize_report_html(source.read_text(encoding="utf-8")), encoding="utf-8"
            )
        else:
            shutil.copy2(source, destination)
        copied += 1
    return copied
