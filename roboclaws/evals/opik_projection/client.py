"""Bounded dependency-free REST client for the pinned Opik projection contract."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class OpikClientError(ValueError):
    """Raised when Opik cannot satisfy the closed projection contract."""


class Transport(Protocol):
    endpoint: str

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        expected: frozenset[int] = frozenset({200}),
    ) -> tuple[int, Any, dict[str, str]]: ...


def _remaining_s(client: Transport) -> float | None:
    remaining = getattr(client, "remaining_s", None)
    return float(remaining()) if callable(remaining) else None


def _bounded_sleep(client: Transport, seconds: float) -> None:
    remaining = _remaining_s(client)
    time.sleep(seconds if remaining is None else min(seconds, remaining))


class OpikHttp:
    def __init__(self, endpoint: str, *, deadline_s: float = 60.0) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise OpikClientError("Opik endpoint must be loopback HTTP")
        if parsed.username or parsed.password or parsed.path not in {"", "/"}:
            raise OpikClientError("Opik endpoint must be a base origin without credentials")
        if parsed.query or parsed.fragment:
            raise OpikClientError("Opik endpoint must not contain a query or fragment")
        if not 0 < deadline_s <= 300:
            raise OpikClientError("Opik projection deadline must be between 0 and 300 seconds")
        self.endpoint = endpoint.rstrip("/")
        self._deadline = time.monotonic() + deadline_s

    def remaining_s(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise OpikClientError("Opik projection deadline expired")
        return remaining

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        expected: frozenset[int] = frozenset({200}),
    ) -> tuple[int, Any, dict[str, str]]:
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            self.endpoint + "/api" + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=min(5.0, self.remaining_s())) as response:
                raw = response.read()
                status = response.status
                headers = dict(response.headers.items())
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
            headers = dict(exc.headers.items())
        if status not in expected:
            detail = raw.decode(errors="replace")[:500]
            raise OpikClientError(f"Opik {method} {path} returned {status}: {detail}")
        return status, json.loads(raw) if raw else None, headers


def stable_uuid(projection_key: str) -> str:
    value = bytearray(hashlib.sha256(projection_key.encode()).digest()[:16])
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(value)))


def stable_uuid_at(projection_key: str, timestamp: str) -> str:
    instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    milliseconds = int(instant.timestamp() * 1000)
    if not 0 <= milliseconds < 1 << 48:
        raise OpikClientError(f"timestamp is outside the UUIDv7 range: {timestamp}")
    value = bytearray(hashlib.sha256(projection_key.encode()).digest()[:16])
    value[:6] = milliseconds.to_bytes(6)
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(value)))


def _location_id(headers: dict[str, str]) -> str:
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise OpikClientError("Opik create response omitted Location identity")
    return location.rstrip("/").rsplit("/", 1)[-1]


def _find_exact(client: Transport, resource: str, name: str) -> dict[str, Any] | None:
    _, page, _ = client.request(
        "GET", f"/v1/private/{resource}?" + urlencode({"name": name, "size": 100})
    )
    matches = [entry for entry in page["content"] if entry["name"] == name]
    if len(matches) > 1:
        raise OpikClientError(f"multiple Opik {resource} objects named {name!r}")
    return matches[0] if matches else None


def _ensure_project(client: Transport, snapshot: dict[str, Any]) -> str:
    name = snapshot["project"]["name"]
    existing = _find_exact(client, "projects", name)
    if existing:
        return existing["id"]
    _, _, headers = client.request(
        "POST",
        "/v1/private/projects",
        {
            "name": name,
            "visibility": "private",
            "description": "One-way projection only; canonical evidence remains local.",
        },
        expected=frozenset({201}),
    )
    return _location_id(headers)


def _ensure_dataset(client: Transport, snapshot: dict[str, Any], project_id: str) -> str:
    name = snapshot["dataset"]["name"]
    dataset_id = stable_uuid(snapshot["dataset"]["projection_key"])
    status, by_id, _ = client.request(
        "GET",
        f"/v1/private/datasets/{dataset_id}",
        expected=frozenset({200, 404}),
    )
    if status == 200:
        if by_id.get("name") != name or by_id.get("project_id") != project_id:
            raise OpikClientError(
                "existing deterministic Dataset identity has different closed name or Project"
            )
        return dataset_id
    existing = _find_exact(client, "datasets", name)
    if existing:
        if existing.get("id") != dataset_id or existing.get("project_id") != project_id:
            raise OpikClientError("existing Dataset name has different closed identity or Project")
        return dataset_id
    _, _, headers = client.request(
        "POST",
        "/v1/private/datasets",
        {
            "id": dataset_id,
            "name": name,
            "project_id": project_id,
            "type": "evaluation_suite",
            "visibility": "private",
            "tags": ["roboclaws", "canonical-local-evidence"],
            "description": "Canonical public rows; experiment-only means no trace was invented.",
        },
        expected=frozenset({201}),
    )
    returned_id = _location_id(headers)
    if returned_id != dataset_id:
        raise OpikClientError("Opik did not preserve the deterministic Dataset ID")
    return dataset_id


def _upsert_dataset_items(
    client: Transport, snapshot: dict[str, Any], project_id: str, dataset_id: str
) -> list[str]:
    ids = [stable_uuid(item["projection_key"]) for item in snapshot["items"]]
    payload = {
        "dataset_id": dataset_id,
        "project_id": project_id,
        "items": [
            {
                "id": item_id,
                "source": "sdk",
                "data": item["metadata"],
                "description": "Canonical Eval Harness triage projection; diagnostic only.",
                "tags": [item["metadata"]["trace_fidelity"], item["metadata"]["outcome"]],
            }
            for item_id, item in zip(ids, snapshot["items"], strict=True)
        ],
    }
    client.request("PUT", "/v1/private/datasets/items", payload, expected=frozenset({204}))
    return ids


def _ensure_experiment(
    client: Transport, snapshot: dict[str, Any], project_id: str
) -> tuple[str, bool]:
    experiment_id = stable_uuid(snapshot["experiment"]["projection_key"])
    status, _, _ = client.request(
        "GET",
        f"/v1/private/experiments/{experiment_id}",
        expected=frozenset({200, 404}),
    )
    if status == 200:
        return experiment_id, False
    client.request(
        "POST",
        "/v1/private/experiments",
        {
            "id": experiment_id,
            "dataset_name": snapshot["dataset"]["name"],
            "project_id": project_id,
            "name": snapshot["experiment"]["name"],
            "metadata": {
                "candidate_status": snapshot["candidate_status"],
                "policy_owner": snapshot["schema"],
                "trace_limitation": "experiment_only rows remain dataset-only",
            },
            "tags": ["roboclaws", "canonical-local-evidence"],
        },
        expected=frozenset({201}),
    )
    return experiment_id, True


def _span_type(source_type: str) -> str:
    if source_type in {"generation", "response", "llm"}:
        return "llm"
    if source_type in {"function", "tool", "mcp_tools"}:
        return "tool"
    return "general"


def _span_payloads(
    trace: dict[str, Any], trace_id: str, project_name: str
) -> tuple[list[str], list[dict[str, Any]]]:
    spans = trace["spans"]
    id_map = {
        span["span_id"]: stable_uuid_at(
            trace["projection_key"] + ":" + span["span_id"], span["started_at"]
        )
        for span in spans
    }
    payloads = []
    for span in spans:
        payloads.append(
            {
                "id": id_map[span["span_id"]],
                "project_name": project_name,
                "trace_id": trace_id,
                "parent_span_id": id_map.get(span.get("parent_id")),
                "name": span.get("span_name") or span["span_type"],
                "type": _span_type(span["span_type"]),
                "start_time": span["started_at"],
                "end_time": span.get("ended_at"),
                "metadata": {
                    "source_span_id": span["span_id"],
                    "source_span_type": span["span_type"],
                    "source_status": span.get("status", "unavailable"),
                },
                "model": span.get("model"),
                "provider": span.get("provider_profile"),
                "source": "sdk",
                "environment": "roboclaws-opik",
            }
        )
    return list(id_map.values()), payloads


def _wait_for_resource(client: Transport, path: str, description: str) -> dict[str, Any]:
    for _ in range(20):
        status, resource, _ = client.request("GET", path, expected=frozenset({200, 404}))
        if status == 200:
            return resource
        _bounded_sleep(client, 0.25)
    raise OpikClientError(f"created {description} did not become readable")


def _existing_span_ids(client: Transport, project_name: str, trace_id: str) -> set[str]:
    _, page, _ = client.request(
        "GET",
        "/v1/private/spans?"
        + urlencode(
            {
                "project_name": project_name,
                "trace_id": trace_id,
                "size": 1000,
                "truncate": "true",
                "strip_attachments": "true",
            }
        ),
    )
    if page["size"] != len(page["content"]) or page["total"] != page["size"]:
        raise OpikClientError("trace exceeds the single-page span reconciliation bound")
    return {span["id"] for span in page["content"]}


def _score_values(trace_resource: dict[str, Any]) -> dict[str, int | float]:
    return {
        score["name"]: score["value"]
        for score in trace_resource.get("feedback_scores") or []
        if score.get("source") == "sdk"
    }


def _expected_counts(result: dict[str, Any]) -> dict[str, int]:
    return {
        "dataset_items": len(result["dataset_item_ids"]),
        "experiment_items": len(result["experiment_item_ids"]),
        "traces": len(result["trace_ids"]),
        "spans": len(result["span_ids"]),
        "scores": result["score_count"],
        "dashboards": 0,
    }


def _read_server_counts(client: Transport, result: dict[str, Any]) -> dict[str, int]:
    _, dataset_items, _ = client.request(
        "GET",
        f"/v1/private/datasets/{result['dataset_id']}/items?" + urlencode({"size": 1000}),
    )
    experiment_items = []
    for experiment_item_id in result["experiment_item_ids"]:
        _, experiment_item, _ = client.request(
            "GET", f"/v1/private/experiments/items/{experiment_item_id}"
        )
        experiment_items.append(experiment_item)
    _, traces, _ = client.request(
        "GET",
        "/v1/private/traces?"
        + urlencode(
            {
                "project_id": result["project_id"],
                "size": 1000,
                "truncate": "true",
                "strip_attachments": "true",
            }
        ),
    )
    _, spans, _ = client.request(
        "GET",
        "/v1/private/spans?"
        + urlencode(
            {
                "project_id": result["project_id"],
                "size": 10000,
                "truncate": "true",
                "strip_attachments": "true",
            }
        ),
    )
    return {
        "dataset_items": dataset_items["total"],
        "experiment_items": len(experiment_items),
        "traces": traces["total"],
        "spans": spans["total"],
        "scores": sum(len(trace.get("feedback_scores") or []) for trace in traces["content"]),
        "dashboards": 0,
    }


def _wait_for_server_counts(client: Transport, result: dict[str, Any]) -> dict[str, int]:
    expected = _expected_counts(result)
    observed: dict[str, int] = {}
    for _ in range(40):
        observed = _read_server_counts(client, result)
        if observed == expected:
            return observed
        _bounded_sleep(client, 0.25)
    raise OpikClientError(
        f"Opik projection counts did not converge: expected {expected}, observed {observed}"
    )


def _create_trace_bundle(
    client: Transport,
    trace: dict[str, Any],
    item: dict[str, Any],
    project_name: str,
    experiment_id: str,
) -> tuple[str, list[str], str, int, dict[str, int]]:
    trace_id = stable_uuid_at(
        trace["projection_key"], min(span["started_at"] for span in trace["spans"])
    )
    experiment_item_id = stable_uuid("experiment-item:" + item["projection_key"])
    span_ids, spans = _span_payloads(trace, trace_id, project_name)
    status, trace_resource, _ = client.request(
        "GET", f"/v1/private/traces/{trace_id}", expected=frozenset({200, 404})
    )
    created = {"traces": 0, "spans": 0, "experiment_items": 0, "scores": 0}
    if status == 404:
        starts = [span["started_at"] for span in trace["spans"]]
        ends = [span.get("ended_at", span["started_at"]) for span in trace["spans"]]
        client.request(
            "POST",
            "/v1/private/traces",
            {
                "id": trace_id,
                "project_name": project_name,
                "name": f"{item['metadata']['row_id']} / {item['metadata']['trial_id']}",
                "start_time": min(starts),
                "end_time": max(ends),
                "metadata": item["metadata"],
                "tags": ["native-span-trace", "historical-candidate"],
                "source": "sdk",
                "environment": "roboclaws-opik",
            },
            expected=frozenset({201}),
        )
        created["traces"] = 1
        trace_resource = _wait_for_resource(
            client, f"/v1/private/traces/{trace_id}", f"trace {trace_id}"
        )

    existing_span_ids = _existing_span_ids(client, project_name, trace_id)
    missing_spans = [span for span in spans if span["id"] not in existing_span_ids]
    for offset in range(0, len(missing_spans), 100):
        client.request(
            "POST",
            "/v1/private/spans/batch",
            {"spans": missing_spans[offset : offset + 100]},
            expected=frozenset({204}),
        )
    created["spans"] = len(missing_spans)

    experiment_item_status, _, _ = client.request(
        "GET",
        f"/v1/private/experiments/items/{experiment_item_id}",
        expected=frozenset({200, 404}),
    )
    if experiment_item_status == 404:
        client.request(
            "POST",
            "/v1/private/experiments/items",
            {
                "experiment_items": [
                    {
                        "id": experiment_item_id,
                        "experiment_id": experiment_id,
                        "dataset_item_id": stable_uuid(item["projection_key"]),
                        "trace_id": trace_id,
                        "project_name": project_name,
                    }
                ]
            },
            expected=frozenset({204}),
        )
        created["experiment_items"] = 1

    existing_scores = _score_values(trace_resource)
    for name, value in item["scores"].items():
        if existing_scores.get(name) == value:
            continue
        client.request(
            "PUT",
            f"/v1/private/traces/{trace_id}/feedback-scores",
            {"name": name, "value": value, "source": "sdk"},
            expected=frozenset({204}),
        )
        created["scores"] += 1
    return trace_id, span_ids, experiment_item_id, len(item["scores"]), created


def project_snapshot(snapshot: dict[str, Any], client: Transport) -> dict[str, Any]:
    project_id = _ensure_project(client, snapshot)
    dataset_id = _ensure_dataset(client, snapshot, project_id)
    dataset_item_ids = _upsert_dataset_items(client, snapshot, project_id, dataset_id)
    experiment_id, experiment_created = _ensure_experiment(client, snapshot, project_id)
    items = {item["projection_key"]: item for item in snapshot["items"]}
    bundles = [
        _create_trace_bundle(
            client,
            trace,
            items[trace["item_projection_key"]],
            snapshot["project"]["name"],
            experiment_id,
        )
        for trace in snapshot["traces"]
    ]
    client.request(
        "POST",
        "/v1/private/experiments/finish",
        {"ids": [experiment_id]},
        expected=frozenset({204}),
    )
    result = {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "experiment_id": experiment_id,
        "dataset_item_ids": dataset_item_ids,
        "experiment_item_ids": [bundle[2] for bundle in bundles],
        "trace_ids": [bundle[0] for bundle in bundles],
        "span_ids": [span_id for bundle in bundles for span_id in bundle[1]],
        "score_count": sum(bundle[3] for bundle in bundles),
        "created": {
            "experiment": int(experiment_created),
            **{
                key: sum(bundle[4][key] for bundle in bundles)
                for key in ("traces", "spans", "experiment_items", "scores")
            },
        },
        "limitations": [
            "Opik 2.2.36 requires Experiment items to reference traces; "
            "40 experiment_only rows remain Dataset items to avoid invented traces.",
            "Experiment and trace drilldown cover native-span rows only; Dataset rows retain "
            "the complete review population.",
        ],
    }
    result["server_counts"] = _wait_for_server_counts(client, result)
    return result


def write_receipt(
    snapshot: dict[str, Any], result: dict[str, Any], endpoint: str, output_root: Path
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "opik_projection.json"
    counts = _expected_counts(result)
    identity_digest = hashlib.sha256(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key.endswith("_id") or key.endswith("_ids")
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    pass_record = {
        "created": result["created"],
        "identity_sha256": identity_digest,
        "projected_counts": counts,
        "server_counts": result["server_counts"],
    }
    passes = {"first": pass_record}
    if path.is_file():
        previous = json.loads(path.read_text())
        if previous.get("snapshot_sha256") != snapshot["snapshot_sha256"] or previous.get(
            "endpoint_origin"
        ) != endpoint.rstrip("/"):
            raise OpikClientError("existing receipt belongs to a different snapshot or endpoint")
        passes = {"first": previous["passes"]["first"], "second": pass_record}
        if passes["first"]["identity_sha256"] != identity_digest:
            raise OpikClientError("Opik identities changed between projection passes")

    receipt = {
        "schema": snapshot["schema"],
        "state": "ready",
        "reason": "projected",
        "projection_purpose": snapshot["projection_purpose"],
        "candidate_status": snapshot["candidate_status"],
        "source_manifest_sha256": snapshot["source_manifest_sha256"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "endpoint_origin": endpoint.rstrip("/"),
        "opik_release": "2.2.36",
        "counts": counts,
        "ids": {
            key: value
            for key, value in result.items()
            if key.endswith("_id") or key.endswith("_ids")
        },
        "created": result["created"],
        "server_counts": result["server_counts"],
        "passes": passes,
        "trace_coverage": snapshot["trace_coverage"],
        "privacy_scan": snapshot["privacy_scan"],
        "source_files": snapshot["source_files"],
        "limitations": result["limitations"],
        "urls": {
            "project": endpoint.rstrip("/") + "/projects/" + result["project_id"],
            "experiments": endpoint.rstrip("/") + "/experiments",
            "dataset": endpoint.rstrip("/") + "/datasets/" + result["dataset_id"],
        },
    }
    _atomic_write_json(path, receipt)
    return path


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
