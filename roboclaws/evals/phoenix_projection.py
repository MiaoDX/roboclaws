"""One-way projection of public eval identity and existing scores to Phoenix."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.models import EvalResult
from roboclaws.evals.suite_loading import REPO_ROOT, load_suite, path_token

MAPPING_SCHEMA = "roboclaws_phoenix_eval_projection_v1"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "evals" / "phoenix-projection"


def project_eval_to_phoenix(overrides: dict[str, str]) -> dict[str, object]:
    """Project a suite and optional existing results without executing any eval work."""
    values = dict(overrides)
    suite_ref = values.pop("suite", "smoke_regression")
    results_ref = values.pop("eval_results", "")
    endpoint = values.pop("endpoint", "").rstrip("/")
    output_ref = values.pop("output", "")
    if values:
        raise ValueError(f"unsupported phoenix-project override(s): {', '.join(sorted(values))}")

    suite, samples = load_suite(suite_ref)
    public_samples = [
        {
            "sample_id": sample.sample_id,
            "sample_version": sample.version,
            "prompt_digest": _digest_text(sample.prompt),
        }
        for sample in samples
    ]
    dataset_digest = _digest_json(
        {
            "suite_id": suite.suite_id,
            "suite_version": suite.version,
            "samples": public_samples,
        }
    )
    output_path = (
        Path(output_ref)
        if output_ref
        else DEFAULT_OUTPUT_ROOT / f"{path_token(suite.suite_id)}-{dataset_digest[:12]}.json"
    )
    mapping: dict[str, Any] = {
        "schema": MAPPING_SCHEMA,
        "state": "disabled" if not endpoint else "unavailable",
        "reason": "endpoint_not_configured" if not endpoint else "projection_not_completed",
        "suite": {
            "suite_id": suite.suite_id,
            "suite_version": suite.version,
            "dataset_digest": dataset_digest,
        },
        "dataset": None,
        "experiment": None,
        "examples": [],
        "runs": [],
        "evaluations": [],
    }
    if not endpoint:
        _write_mapping(output_path, mapping)
        return _summary(output_path, mapping)

    _validate_loopback_endpoint(endpoint)
    results, projection_time = (
        _load_results(Path(results_ref), suite.suite_id) if results_ref else ([], "")
    )
    public_results = [(result, _public_result_identity(result)) for result in results]
    try:
        mapping.update(
            _project(
                PhoenixHttp(endpoint),
                suite_id=suite.suite_id,
                suite_version=suite.version,
                required_graders=suite.required_graders,
                public_samples=public_samples,
                dataset_digest=dataset_digest,
                results=public_results,
                projection_time=projection_time,
            )
        )
        mapping["state"] = "ready"
        mapping["reason"] = "projected"
    except (HTTPError, KeyError, OSError, TimeoutError, URLError, ValueError) as exc:
        mapping["state"] = "unavailable"
        mapping["reason"] = _failure_reason(exc)
    _write_mapping(output_path, mapping)
    return _summary(output_path, mapping)


class PhoenixHttp:
    """Small Phoenix 11.20 HTTP surface used by the projection command."""

    def __init__(self, endpoint: str, *, timeout_s: float = 5.0) -> None:
        self.endpoint = endpoint
        self.timeout_s = timeout_s

    def json(self, method: str, path: str, payload: object | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            f"{self.endpoint}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        with urlopen(request, timeout=self.timeout_s) as response:  # noqa: S310
            return json.loads(response.read() or b"{}")

    def upload_dataset(self, *, name: str, rows: list[dict[str, str]]) -> Any:
        return self.json(
            "POST",
            "/v1/datasets/upload?sync=true",
            {"action": "create", "name": name, "inputs": rows},
        )


def _project(
    http: PhoenixHttp,
    *,
    suite_id: str,
    suite_version: str,
    required_graders: tuple[str, ...],
    public_samples: list[dict[str, str]],
    dataset_digest: str,
    results: list[tuple[EvalResult, dict[str, str]]],
    projection_time: str,
) -> dict[str, object]:
    dataset_name = f"roboclaws-{path_token(suite_id)}-{dataset_digest[:16]}"
    dataset_query = urlencode({"name": dataset_name, "limit": 100})
    dataset = _find_named(_data(http.json("GET", f"/v1/datasets?{dataset_query}")), dataset_name)
    if dataset is None:
        uploaded = _mapping(_data(http.upload_dataset(name=dataset_name, rows=public_samples)))
        dataset = {"id": uploaded.get("dataset_id"), "name": dataset_name}
    dataset_id = _id(dataset, "dataset")
    examples_payload = _mapping(_data(http.json("GET", f"/v1/datasets/{dataset_id}/examples")))
    examples = _list_of_mappings(examples_payload.get("examples"), "dataset examples")
    example_by_sample = {
        str(_mapping(item.get("input")).get("sample_id") or ""): item for item in examples
    }
    example_mappings = [
        _example_mapping(http.endpoint, dataset_id, row, example_by_sample)
        for row in public_samples
    ]
    projection: dict[str, object] = {
        "dataset": {
            "name": dataset_name,
            "phoenix_id": dataset_id,
            "url": f"{http.endpoint}/datasets/{dataset_id}",
        },
        "examples": example_mappings,
        "experiment": None,
        "runs": [],
        "evaluations": [],
    }
    if not results:
        return projection

    experiment_digest = _digest_json([identity for _result, identity in results])
    experiment_name = f"roboclaws-{suite_version}-{experiment_digest[:16]}"
    experiments = _data(http.json("GET", f"/v1/datasets/{dataset_id}/experiments"))
    experiment = _find_by_digest(experiments, experiment_digest)
    if experiment is None:
        experiment = _data(
            http.json(
                "POST",
                f"/v1/datasets/{dataset_id}/experiments",
                {"name": experiment_name, "metadata": {"projection_digest": experiment_digest}},
            )
        )
    experiment_id = _id(experiment, "experiment")
    projection["experiment"] = {
        "name": experiment_name,
        "digest": experiment_digest,
        "phoenix_id": experiment_id,
        "url": f"{http.endpoint}/experiments/{experiment_id}",
    }
    existing_runs = _list_of_mappings(
        _data(http.json("GET", f"/v1/experiments/{experiment_id}/runs")), "experiment runs"
    )
    run_by_identity = {
        (str(item.get("dataset_example_id") or ""), int(item.get("repetition_number") or 0)): item
        for item in existing_runs
    }
    evaluations: list[dict[str, str | None]] = []
    run_mappings: list[dict[str, str]] = []
    for result, identity in results:
        run_digest = _digest_json(identity)
        example_id = _id(example_by_sample[identity["sample_id"]], "example")
        repetition_number = int(identity["repetition_index"])
        run = run_by_identity.get((example_id, repetition_number))
        if run is None:
            run = _data(
                http.json(
                    "POST",
                    f"/v1/experiments/{experiment_id}/runs",
                    {
                        "dataset_example_id": example_id,
                        "output": {"status": result.status, "identity": identity},
                        "repetition_number": repetition_number,
                        "start_time": projection_time,
                        "end_time": projection_time,
                        "trace_id": identity.get("trace_id") or None,
                    },
                )
            )
        run_id = _id(run, "experiment run")
        run_mappings.append(
            {
                "trial_id": identity["trial_id"],
                "digest": run_digest,
                "phoenix_id": run_id,
                "url": f"{http.endpoint}/experiments/{experiment_id}/runs/{run_id}",
            }
        )
        for grader in required_graders:
            status = _grader_status(result, grader)
            if status is None:
                continue
            evaluation_name = f"{grader}.status"
            evaluation_digest = _digest_json([run_digest, evaluation_name, status])
            evaluation = _mapping(
                _data(
                    http.json(
                        "POST",
                        "/v1/experiment_evaluations",
                        {
                            "experiment_run_id": run_id,
                            "name": evaluation_name,
                            "annotator_kind": "CODE",
                            "start_time": projection_time,
                            "end_time": projection_time,
                            "result": {"label": status},
                            "metadata": {"projection_digest": evaluation_digest},
                            "trace_id": identity.get("trace_id") or None,
                        },
                    )
                )
            )
            evaluation_id = evaluation.get("id")
            evaluations.append(
                {
                    "trial_id": identity["trial_id"],
                    "name": evaluation_name,
                    "label": status,
                    "digest": evaluation_digest,
                    "phoenix_id": str(evaluation_id) if evaluation_id else None,
                    "url": (
                        f"{http.endpoint}/experiments/{experiment_id}/runs/{run_id}"
                        if run_id
                        else None
                    ),
                }
            )
    projection["runs"] = run_mappings
    projection["evaluations"] = evaluations
    return projection


def _public_result_identity(result: EvalResult) -> dict[str, str]:
    identity = result.identity
    allowed = (
        "suite_id",
        "suite_version",
        "sample_id",
        "sample_version",
        "trial_id",
        "agent_engine",
        "provider_profile",
        "model",
        "skill_name",
        "prompt_source_git_sha",
        "prompt_skill_sha256",
        "prompt_rendered_sha256",
        "trace_id",
    )
    public = {key: str(identity[key]) for key in allowed if identity.get(key) not in {None, ""}}
    public["repetition_index"] = str(identity["repetition_index"])
    public.update(_run_artifact_identity(result))
    return public


def _run_artifact_identity(result: EvalResult) -> dict[str, str]:
    run_dir_value = result.artifacts.get("run_dir")
    if not isinstance(run_dir_value, str) or not run_dir_value:
        return {}
    run_dir = Path(run_dir_value)
    if not run_dir.is_absolute():
        run_dir = REPO_ROOT / run_dir
    projection: dict[str, str] = {}
    prompt_path = run_dir / "prompt-identity.json"
    if prompt_path.is_file():
        prompt = read_json_object(prompt_path, label="prompt identity")
        for key in (
            "prompt_source_git_sha",
            "prompt_skill_sha256",
            "prompt_rendered_sha256",
        ):
            value = prompt.get(key)
            if isinstance(value, str) and value:
                projection[key] = value
    timing_path = run_dir / "live_timing.json"
    if timing_path.is_file():
        timing = read_json_object(timing_path, label="live timing")
        trace_id = timing.get("trace_id")
        if isinstance(trace_id, str) and trace_id:
            projection["trace_id"] = trace_id
    return projection


def _example_mapping(
    endpoint: str,
    dataset_id: str,
    row: dict[str, str],
    example_by_sample: dict[str, Any],
) -> dict[str, str]:
    example_id = _id(example_by_sample[row["sample_id"]], "example")
    return {
        "sample_id": row["sample_id"],
        "sample_digest": _digest_json(row),
        "phoenix_example_id": example_id,
        "url": f"{endpoint}/datasets/{dataset_id}/examples/{example_id}",
    }


def _grader_status(result: EvalResult, grader: str) -> str | None:
    output = result.grader_outputs.get(grader)
    if not isinstance(output, dict):
        return None
    status = output.get("status")
    return status if isinstance(status, str) and status else None


def _load_results(path: Path, suite_id: str) -> tuple[list[EvalResult], str]:
    resolved = path if path.is_absolute() else REPO_ROOT / path
    payload = read_json_object(resolved, label="eval results")
    suite = _mapping(payload.get("suite"))
    if suite.get("suite_id") != suite_id:
        raise ValueError("eval_results suite_id does not match the projected suite")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("eval_results must contain a results list")
    projection_time = datetime.fromtimestamp(resolved.stat().st_mtime, timezone.utc).isoformat()
    return [EvalResult.from_mapping(_mapping(row)) for row in rows], projection_time


def _validate_loopback_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Phoenix endpoint must be loopback HTTP")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Phoenix endpoint must contain only loopback origin and optional port")


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"phoenix_http_{exc.code}"
    if isinstance(exc, ValueError):
        return "invalid_projection_input_or_response"
    if isinstance(exc, TimeoutError):
        return "phoenix_timeout"
    return "phoenix_connection_failed"


def _data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _find_named(items: Any, name: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        raise ValueError("Phoenix list response must contain a list")
    return next(
        (item for item in items if isinstance(item, dict) and item.get("name") == name), None
    )


def _find_by_digest(items: Any, digest: str) -> dict[str, Any] | None:
    rows = _list_of_mappings(items, "Phoenix experiments")
    return next(
        (
            item
            for item in rows
            if _mapping(item.get("metadata")).get("projection_digest") == digest
        ),
        None,
    )


def _list_of_mappings(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Phoenix {label} response must contain a list of objects")
    return value


def _id(payload: Any, kind: str) -> str:
    value = _mapping(payload).get("id")
    if not isinstance(value, str) or not value:
        raise ValueError(f"Phoenix {kind} response has no id")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return value


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest_json(value: object) -> str:
    return _digest_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _write_mapping(path: Path, mapping: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summary(path: Path, mapping: dict[str, Any]) -> dict[str, object]:
    return {"mapping": str(path), "state": mapping["state"], "reason": mapping["reason"]}
