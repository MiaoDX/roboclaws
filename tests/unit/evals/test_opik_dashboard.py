from __future__ import annotations

from typing import Any

from roboclaws.evals.opik_projection.dashboard import reconcile_dashboard


class _DashboardTransport:
    endpoint = "http://127.0.0.1:5174"

    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.calls: list[tuple[str, str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        expected: frozenset[int] = frozenset({200}),
    ) -> tuple[int, Any, dict[str, str]]:
        self.calls.append((method, path, payload))
        if method == "GET":
            return 200, {"content": self.existing}, {}
        if method == "POST":
            body = {"id": "dashboard-1", **payload}
            self.existing.append(body)
            return 201, body, {}
        return 200, {"id": "dashboard-1", **payload}, {}


def test_dashboard_reconciliation_is_idempotent_and_honest() -> None:
    transport = _DashboardTransport()
    first = reconcile_dashboard(transport, dataset_url="http://127.0.0.1:5174/datasets/dataset-1")
    second = reconcile_dashboard(transport, dataset_url="http://127.0.0.1:5174/datasets/dataset-1")

    assert first == {"id": "dashboard-1", "created": True, "schema": "roboclaws_opik_dashboard_v1"}
    assert second["created"] is False
    assert [call[:2] for call in transport.calls] == [
        ("GET", "/v1/private/insights-views?size=100"),
        ("POST", "/v1/private/insights-views"),
        ("GET", "/v1/private/insights-views?size=100"),
        ("PATCH", "/v1/private/insights-views/dashboard-1"),
    ]
    content = transport.calls[1][2]["config"]["sections"][1]["widgets"][0]["config"]["content"]
    assert "25 native Experiment/trace rows; 40 Dataset-only rows" in content

    sections = transport.calls[1][2]["config"]["sections"]
    assert [section["id"] for section in sections] == [
        "roboclaws_scope",
        "roboclaws_coverage",
        "roboclaws_provider",
        "roboclaws_outcome",
    ]
    assert [section["title"] for section in sections] == [
        "Review scope",
        "Trace fidelity coverage",
        "Native trace volume by provider",
        "Native trace volume by recorded outcome",
    ]
    metrics = {section["id"]: section["widgets"][0] for section in sections[2:]}
    assert metrics["roboclaws_provider"]["title"] == "Native trace volume by provider"
    assert metrics["roboclaws_provider"]["config"]["breakdown"]["metadataKey"] == "provider_profile"
    assert metrics["roboclaws_outcome"]["title"] == "Native trace volume by recorded outcome"
    assert metrics["roboclaws_outcome"]["config"]["breakdown"]["metadataKey"] == "outcome"
    assert "roboclaws_trace" not in {section["id"] for section in sections}
    assert all(
        widget["config"].get("breakdown", {}).get("metadataKey")
        not in {"failure_class", "trace_fidelity"}
        for section in sections
        for widget in section["widgets"]
    )


def test_dashboard_duplicate_closed_name_fails() -> None:
    transport = _DashboardTransport(
        [{"id": "a", "name": "Roboclaws eval review"}, {"id": "b", "name": "Roboclaws eval review"}]
    )

    try:
        reconcile_dashboard(transport, dataset_url="http://127.0.0.1:5174/datasets/dataset-1")
    except ValueError as exc:
        assert "multiple" in str(exc)
    else:
        raise AssertionError("duplicate Dashboard names must fail closed")
