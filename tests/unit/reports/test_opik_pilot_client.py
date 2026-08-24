from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).parents[3] / "scripts/reports/opik_pilot_client.py"
SPEC = importlib.util.spec_from_file_location("opik_pilot_client", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PartialBundleTransport:
    endpoint = "http://127.0.0.1:5174"

    def __init__(self, trace_id: str, existing_span_id: str, experiment_item_id: str) -> None:
        self.trace_id = trace_id
        self.existing_span_id = existing_span_id
        self.experiment_item_id = experiment_item_id
        self.writes: list[tuple[str, str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        expected: frozenset[int] = frozenset({200}),
    ) -> tuple[int, Any, dict[str, str]]:
        if method == "GET" and path == f"/v1/private/traces/{self.trace_id}":
            return (
                200,
                {
                    "id": self.trace_id,
                    "feedback_scores": [{"name": "roboclaws.passed", "value": 1, "source": "sdk"}],
                },
                {},
            )
        if method == "GET" and path.startswith("/v1/private/spans?"):
            content = [{"id": self.existing_span_id}]
            return 200, {"content": content, "size": 1, "total": 1}, {}
        if method == "GET" and path == (f"/v1/private/experiments/items/{self.experiment_item_id}"):
            return 404, {"message": "not found"}, {}
        self.writes.append((method, path, payload))
        return 204, None, {}


def _bundle() -> tuple[dict[str, Any], dict[str, Any]]:
    trace = {
        "projection_key": "trace-key",
        "spans": [
            {
                "span_id": "span-1",
                "trace_id": "source-trace",
                "span_type": "agent",
                "started_at": "2026-08-17T00:00:00+00:00",
                "ended_at": "2026-08-17T00:00:01+00:00",
            },
            {
                "span_id": "span-2",
                "trace_id": "source-trace",
                "parent_id": "span-1",
                "span_type": "tool",
                "started_at": "2026-08-17T00:00:00.100000+00:00",
                "ended_at": "2026-08-17T00:00:00.900000+00:00",
            },
        ],
    }
    item = {
        "projection_key": "item-key",
        "metadata": {"row_id": "row-1", "trial_id": "trial-1"},
        "scores": {"roboclaws.passed": 1, "roboclaws.tool_call_count": 2},
    }
    return trace, item


def test_timestamped_stable_uuid_is_deterministic_uuid7() -> None:
    timestamp = "2026-08-17T00:00:00+00:00"
    first = MODULE.stable_uuid_at("trace-key", timestamp)
    second = MODULE.stable_uuid_at("trace-key", timestamp)
    parsed = uuid.UUID(first)

    assert first == second
    assert parsed.version == 7
    assert int.from_bytes(parsed.bytes[:6]) == int(
        datetime.fromisoformat(timestamp).astimezone(timezone.utc).timestamp() * 1000
    )
    assert MODULE.stable_uuid_at("other-key", timestamp) != first


def test_partial_bundle_replay_only_writes_missing_resources() -> None:
    trace, item = _bundle()
    trace_id = MODULE.stable_uuid_at(trace["projection_key"], trace["spans"][0]["started_at"])
    span_ids, _ = MODULE._span_payloads(trace, trace_id, "pilot-project")
    experiment_item_id = MODULE.stable_uuid("experiment-item:" + item["projection_key"])
    transport = PartialBundleTransport(trace_id, span_ids[0], experiment_item_id)

    result = MODULE._create_trace_bundle(transport, trace, item, "pilot-project", "experiment-id")

    assert result[4] == {"traces": 0, "spans": 1, "experiment_items": 1, "scores": 1}
    assert [call[:2] for call in transport.writes] == [
        ("POST", "/v1/private/spans/batch"),
        ("POST", "/v1/private/experiments/items"),
        ("PUT", f"/v1/private/traces/{trace_id}/feedback-scores"),
    ]
    assert transport.writes[-1][2]["name"] == "roboclaws.tool_call_count"


def test_receipt_preserves_first_and_second_pass_proof(tmp_path: Path) -> None:
    snapshot = {
        "schema": "projection-v1",
        "projection_purpose": "historical_candidate_projection",
        "candidate_status": "unaccepted",
        "source_manifest_sha256": "source-digest",
        "snapshot_sha256": "snapshot-digest",
        "trace_coverage": {"native_span_trace": 1, "experiment_only": 1},
        "privacy_scan": {"state": "passed", "finding_count": 0},
        "source_files": [],
    }
    result = {
        "project_id": "project-id",
        "dataset_id": "dataset-id",
        "experiment_id": "experiment-id",
        "dataset_item_ids": ["dataset-item-1", "dataset-item-2"],
        "experiment_item_ids": ["experiment-item-1"],
        "trace_ids": ["trace-1"],
        "span_ids": ["span-1"],
        "score_count": 1,
        "server_counts": {
            "dataset_items": 2,
            "experiment_items": 1,
            "traces": 1,
            "spans": 1,
            "scores": 1,
            "dashboards": 0,
        },
        "created": {
            "experiment": 1,
            "traces": 1,
            "spans": 1,
            "experiment_items": 1,
            "scores": 1,
        },
        "limitations": [],
    }

    path = MODULE.write_receipt(snapshot, result, "http://127.0.0.1:5174", tmp_path)
    result["created"] = {key: 0 for key in result["created"]}
    MODULE.write_receipt(snapshot, result, "http://127.0.0.1:5174", tmp_path)
    receipt = json.loads(path.read_text())

    assert receipt["passes"]["first"]["created"]["traces"] == 1
    assert receipt["passes"]["second"]["created"] == result["created"]
    assert (
        receipt["passes"]["first"]["identity_sha256"]
        == receipt["passes"]["second"]["identity_sha256"]
    )
