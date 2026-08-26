"""Explicit idempotent reconciliation for the pinned Opik review Dashboard."""

from __future__ import annotations

from typing import Any

from roboclaws.evals.opik_projection.client import OpikClientError, Transport

DASHBOARD_NAME = "Roboclaws eval review"
DASHBOARD_SLUG = "roboclaws-eval-review"
DASHBOARD_SCHEMA = "roboclaws_opik_dashboard_v1"


def reconcile_dashboard(
    client: Transport, *, dataset_url: str, project_name: str = "roboclaws-eval"
) -> dict[str, Any]:
    """Create or update the single supported review Dashboard."""
    existing = _find_dashboard(client)
    payload = _dashboard_payload(dataset_url=dataset_url, project_name=project_name)
    if existing is None:
        status, body, _ = client.request(
            "POST",
            "/v1/private/insights-views",
            payload,
            expected=frozenset({201}),
        )
        del status
        if not isinstance(body, dict) or not body.get("id"):
            raise OpikClientError("Opik Dashboard create response omitted identity")
        return {"id": body["id"], "created": True, "schema": DASHBOARD_SCHEMA}
    dashboard_id = existing.get("id")
    if not isinstance(dashboard_id, str) or not dashboard_id:
        raise OpikClientError("Opik Dashboard identity is malformed")
    _, body, _ = client.request(
        "PATCH",
        f"/v1/private/insights-views/{dashboard_id}",
        payload,
        expected=frozenset({200}),
    )
    if not isinstance(body, dict) or body.get("id") != dashboard_id:
        raise OpikClientError("Opik Dashboard update changed deterministic identity")
    return {"id": dashboard_id, "created": False, "schema": DASHBOARD_SCHEMA}


def _find_dashboard(client: Transport) -> dict[str, Any] | None:
    _, page, _ = client.request("GET", "/v1/private/insights-views?size=100")
    if not isinstance(page, dict) or not isinstance(page.get("content"), list):
        raise OpikClientError("Opik Dashboard list response is malformed")
    matches = [item for item in page["content"] if item.get("name") == DASHBOARD_NAME]
    if len(matches) > 1:
        raise OpikClientError("multiple Opik review Dashboards have the closed name")
    return matches[0] if matches else None


def _dashboard_payload(*, dataset_url: str, project_name: str) -> dict[str, Any]:
    return {
        "name": DASHBOARD_NAME,
        "slug": DASHBOARD_SLUG,
        "type": "multi_project",
        "scope": "insights",
        "description": "Canonical local evidence remains authoritative; Opik is diagnostic.",
        "config": {
            "version": 4,
            "sections": [
                {
                    "id": "roboclaws_scope",
                    "title": "Review scope",
                    "layout": [{"h": 4, "i": "roboclaws_scope_note", "w": 6, "x": 0, "y": 0}],
                    "widgets": [
                        {
                            "id": "roboclaws_scope_note",
                            "type": "text_markdown",
                            "title": "Canonical review boundary",
                            "config": {
                                "content": (
                                    f"**Project:** `{project_name}`. Canonical JSON/Markdown and "
                                    "human decisions remain authoritative. "
                                    f"[Open all Dataset rows]({dataset_url})."
                                )
                            },
                            "subtitle": "",
                            "generatedTitle": "Text",
                        }
                    ],
                },
                {
                    "id": "roboclaws_coverage",
                    "title": "Trace fidelity coverage",
                    "layout": [{"h": 4, "i": "roboclaws_coverage_note", "w": 6, "x": 0, "y": 0}],
                    "widgets": [
                        {
                            "id": "roboclaws_coverage_note",
                            "type": "text_markdown",
                            "title": "Native versus Dataset-only rows",
                            "config": {
                                "content": (
                                    "**25 native Experiment/trace rows; 40 Dataset-only rows.** "
                                    "Dataset coverage is 65 rows; no trace is invented for "
                                    "experiment-only evidence."
                                )
                            },
                            "subtitle": "",
                            "generatedTitle": "Text",
                        }
                    ],
                },
                _metrics_section(
                    "roboclaws_provider", "Native trace volume by provider", "provider_profile"
                ),
                _metrics_section(
                    "roboclaws_outcome",
                    "Native trace volume by recorded outcome",
                    "outcome",
                ),
            ],
        },
    }


def _metrics_section(section_id: str, title: str, metadata_key: str) -> dict[str, Any]:
    widget_id = f"{section_id}_metric"
    return {
        "id": section_id,
        "title": title,
        "layout": [{"h": 4, "i": widget_id, "w": 6, "x": 0, "y": 0}],
        "widgets": [
            {
                "id": widget_id,
                "type": "project_metrics",
                "title": title,
                "config": {
                    "breakdown": {
                        "field": "metadata",
                        "metadataKey": metadata_key,
                        "aggregateTotal": True,
                    },
                    "chartType": "bar",
                    "metricType": "TRACE_COUNT",
                },
                "subtitle": "",
                "generatedTitle": "Number of traces",
            }
        ],
    }
