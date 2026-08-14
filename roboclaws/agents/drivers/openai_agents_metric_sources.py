"""Strict JSONL source reader for OpenAI Agents metrics."""

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_jsonl_objects


def read_openai_agents_jsonl_source(
    path: Path, *, source_label: str = "OpenAI Agents metrics source"
) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    label = source_label.removesuffix(" source")
    return read_jsonl_objects(path, label=label)
