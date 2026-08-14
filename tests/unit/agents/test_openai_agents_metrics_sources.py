from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.agents.drivers.openai_agents_metric_sources import (
    read_openai_agents_jsonl_source,
)


def test_openai_agents_metrics_jsonl_source_preserves_valid_rows(tmp_path: Path) -> None:
    path = tmp_path / "openai-agents-events.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"event": "start"}),
                "",
                json.dumps({"event": "result"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert read_openai_agents_jsonl_source(path) == [
        {"event": "start"},
        {"event": "result"},
    ]


def test_openai_agents_metrics_jsonl_source_treats_missing_as_empty(
    tmp_path: Path,
) -> None:
    assert read_openai_agents_jsonl_source(tmp_path / "missing.jsonl") == []


def test_openai_agents_metrics_jsonl_source_fails_aloud_on_malformed_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "openai-agents-events.jsonl"
    path.write_text('{"event":"start"}\n{bad-json}\n', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain valid JSON object: "
        r".*openai-agents-events\.jsonl:2",
    ):
        read_openai_agents_jsonl_source(path)


def test_openai_agents_metrics_jsonl_source_fails_aloud_on_non_object_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "openai-agents-spans.jsonl"
    path.write_text(json.dumps(["not", "an", "event"]) + "\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents metrics source row must contain a JSON object: "
        r".*openai-agents-spans\.jsonl:1",
    ):
        read_openai_agents_jsonl_source(path)


def test_openai_agents_metrics_jsonl_source_preserves_live_source_label(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"OpenAI Agents live source row must contain a JSON object: "
        r".*trace\.jsonl:1",
    ):
        read_openai_agents_jsonl_source(path, source_label="OpenAI Agents live source")
