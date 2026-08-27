"""Build privacy-filtered, self-contained Pages report bundles."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

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
