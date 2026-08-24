from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

ENDPOINT = os.environ.get("ROBOCLAWS_OPIK_INTEGRATION_ENDPOINT", "").rstrip("/")
MANIFEST = Path("output/eval-harness/20260817T072338Z/eval_harness.json")


def _json(path: str) -> dict[str, Any]:
    request = Request(ENDPOINT + "/api" + path, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


pytestmark = pytest.mark.skipif(not ENDPOINT, reason="disposable Opik endpoint not configured")


def _receipt() -> dict[str, Any]:
    manifest_digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    path = Path("output/opik-poc") / manifest_digest / "projection_receipt.json"
    assert path.is_file(), "run the Opik pilot projection twice before this integration gate"
    return json.loads(path.read_text())


def test_live_opik_projection_matches_receipt_and_trace_contract() -> None:
    receipt = _receipt()
    assert receipt["endpoint_origin"] == ENDPOINT
    assert receipt["candidate_status"] == "unaccepted"
    assert receipt["opik_release"] == "2.2.36"
    assert receipt["trace_coverage"] == {
        "native_span_trace": 25,
        "experiment_only": 40,
    }
    assert receipt["counts"] == {
        "dataset_items": 65,
        "experiment_items": 25,
        "traces": 25,
        "spans": 4994,
        "scores": 56,
        "dashboards": 0,
    }
    assert receipt["server_counts"] == receipt["counts"]
    assert receipt["passes"]["first"]["server_counts"] == receipt["counts"]
    assert receipt["passes"]["second"]["server_counts"] == receipt["counts"]
    assert receipt["passes"]["second"]["created"] == {
        "experiment": 0,
        "experiment_items": 0,
        "scores": 0,
        "spans": 0,
        "traces": 0,
    }
    assert (
        receipt["passes"]["first"]["identity_sha256"]
        == receipt["passes"]["second"]["identity_sha256"]
    )

    ids = receipt["ids"]
    dataset = _json(f"/v1/private/datasets/{ids['dataset_id']}")
    experiment = _json(f"/v1/private/experiments/{ids['experiment_id']}")
    assert dataset["project_id"] == ids["project_id"]
    assert experiment["dataset_id"] == ids["dataset_id"]

    dataset_page = _json(
        f"/v1/private/datasets/{ids['dataset_id']}/items?" + urlencode({"size": 100})
    )
    assert dataset_page["total"] == 65
    assert {item["id"] for item in dataset_page["content"]} == set(ids["dataset_item_ids"])

    experiment_items = [
        _json(f"/v1/private/experiments/items/{item_id}") for item_id in ids["experiment_item_ids"]
    ]
    assert all(item["experiment_id"] == ids["experiment_id"] for item in experiment_items)
    assert {item["trace_id"] for item in experiment_items} == set(ids["trace_ids"])

    traces = [_json(f"/v1/private/traces/{trace_id}") for trace_id in ids["trace_ids"]]
    assert all(trace["project_id"] == ids["project_id"] for trace in traces)
    assert all(trace["metadata"]["trace_fidelity"] == "native_span_trace" for trace in traces)
    assert sum(len(trace.get("feedback_scores") or []) for trace in traces) == 56

    remote_span_ids: set[str] = set()
    for trace_id in ids["trace_ids"]:
        page = _json(
            "/v1/private/spans?"
            + urlencode(
                {
                    "project_id": ids["project_id"],
                    "trace_id": trace_id,
                    "size": 1000,
                    "truncate": "true",
                    "strip_attachments": "true",
                }
            )
        )
        assert page["size"] == page["total"]
        trace_spans = page["content"]
        trace_span_ids = {span["id"] for span in trace_spans}
        assert all(
            span.get("parent_span_id") is None or span["parent_span_id"] in trace_span_ids
            for span in trace_spans
        )
        remote_span_ids.update(trace_span_ids)
    assert remote_span_ids == set(ids["span_ids"])
