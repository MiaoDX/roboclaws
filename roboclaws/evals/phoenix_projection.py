"""One-way projection of public eval identity and existing scores to Phoenix."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from roboclaws.core.json_sources import read_json_object
from roboclaws.evals.models import EvalResult, EvalSample, EvalSuite
from roboclaws.evals.suite_loading import REPO_ROOT, load_suite, path_token

MAPPING_SCHEMA = "roboclaws_phoenix_eval_projection_v3"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "evals" / "phoenix-projection"
MISSING_CONFIGURATION_VALUE = "missing"
CONFIGURATION_FIELDS = (
    "agent_engine",
    "provider_profile",
    "model",
    "skill_name",
    "prompt_source_git_sha",
    "prompt_skill_sha256",
)


class TaskDatasetContentMismatch(ValueError):
    """The task Dataset does not contain the requested immutable suite release."""


class ExactDatasetVersionNotFound(ValueError):
    """No Phoenix Dataset version has the expected public sample content."""


class TaskDatasetHistoryMismatch(ValueError):
    """A task Dataset has unsupported append history in Phoenix 11.20."""


def project_completed_eval_to_phoenix(
    *,
    suite_ref: str,
    eval_results_path: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Fail-open projection for one completed local or collected eval bundle."""
    output_path = eval_results_path.with_name("phoenix_projection.json")
    values = os.environ if environ is None else environ
    try:
        endpoint = _phoenix_api_origin(values.get("ROBOCLAWS_PHOENIX_OTLP_ENDPOINT", ""))
        return project_eval_to_phoenix(
            {
                "suite": suite_ref,
                "eval_results": str(eval_results_path),
                "endpoint": endpoint,
                "output": str(output_path),
            }
        )
    except Exception as exc:  # noqa: BLE001 - projection must not change the eval outcome
        suite, _samples, _public_samples, dataset_digest = _projection_inputs(suite_ref)
        mapping = _empty_mapping(suite, dataset_digest)
        mapping["state"] = "unavailable"
        mapping["reason"] = (
            "invalid_projection_configuration"
            if isinstance(exc, ValueError) and "endpoint" in str(exc).lower()
            else _failure_reason(exc)
        )
        _write_mapping(output_path, mapping)
        return _summary(output_path, mapping)


def project_eval_to_phoenix(overrides: dict[str, str]) -> dict[str, object]:
    """Project a suite and optional existing results without executing any eval work."""
    values = dict(overrides)
    suite_ref = values.pop("suite", "smoke_regression")
    results_ref = values.pop("eval_results", "")
    endpoint = values.pop("endpoint", "").rstrip("/")
    output_ref = values.pop("output", "")
    if values:
        raise ValueError(f"unsupported phoenix-project override(s): {', '.join(sorted(values))}")

    suite, samples, public_samples, dataset_digest = _projection_inputs(suite_ref)
    output_path = (
        Path(output_ref)
        if output_ref
        else DEFAULT_OUTPUT_ROOT / f"{path_token(suite.suite_id)}-{dataset_digest[:12]}.json"
    )
    mapping = _empty_mapping(suite, dataset_digest, endpoint_configured=bool(endpoint))
    if not endpoint:
        _write_mapping(output_path, mapping)
        return _summary(output_path, mapping)

    _validate_loopback_endpoint(endpoint)
    results, projection_time = (
        _load_results(Path(results_ref), suite=suite, samples=samples) if results_ref else ([], "")
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
    dataset_name = _dataset_name(suite_id)
    dataset_query = urlencode({"name": dataset_name, "limit": 100})
    dataset = _find_named(_data(http.json("GET", f"/v1/datasets?{dataset_query}")), dataset_name)
    if dataset is None:
        uploaded = _mapping(_data(http.upload_dataset(name=dataset_name, rows=public_samples)))
        dataset = {"id": uploaded.get("dataset_id"), "name": dataset_name}
    dataset_id = _id(dataset, "dataset")
    examples_digest = _public_examples_digest(public_samples)
    try:
        dataset_version_id, examples_payload = _resolve_dataset_version(
            http,
            dataset_id=dataset_id,
            expected_examples_digest=examples_digest,
        )
    except ExactDatasetVersionNotFound as exc:
        raise TaskDatasetContentMismatch(
            f"task Dataset {dataset_name!r} does not contain eval suite version "
            f"{suite_version!r}; bump the suite version, rebuild the local Phoenix data, "
            "and reproject canonical artifacts"
        ) from exc
    examples = _list_of_mappings(examples_payload.get("examples"), "dataset examples")
    example_by_sample = _examples_by_sample(examples)
    example_mappings = [
        _example_mapping(http.endpoint, dataset_id, row, example_by_sample)
        for row in public_samples
    ]
    projection: dict[str, object] = {
        "dataset": {
            "name": dataset_name,
            "digest": dataset_digest,
            "examples_digest": examples_digest,
            "phoenix_id": dataset_id,
            "version_id": dataset_version_id,
            "url": f"{http.endpoint}/datasets/{dataset_id}",
        },
        "examples": example_mappings,
        "experiments": [],
        "runs": [],
        "evaluations": [],
    }
    if not results:
        return projection
    existing_experiments = _list_of_mappings(
        _data(http.json("GET", f"/v1/datasets/{dataset_id}/experiments")),
        "experiments",
    )
    experiment_mappings: list[dict[str, Any]] = []
    evaluations: list[dict[str, str | None]] = []
    run_mappings: list[dict[str, str]] = []
    for configuration, partition in _partition_results(results):
        source_bundle_digest = _source_bundle_digest(partition, required_graders)
        experiment_digest = _experiment_projection_digest(
            dataset_version_id=dataset_version_id,
            source_bundle_digest=source_bundle_digest,
            configuration=configuration,
            results=partition,
            required_graders=required_graders,
        )
        experiment_name = _experiment_name(
            suite_id=suite_id,
            suite_version=suite_version,
            configuration=configuration,
            digest=experiment_digest,
        )
        matches = _find_all_by_digest(existing_experiments, experiment_digest)
        if len(matches) > 1:
            raise ValueError("Phoenix contains ambiguous experiments for one projection digest")
        experiment = matches[0] if matches else None
        if experiment is None:
            experiment = _mapping(
                _data(
                    http.json(
                        "POST",
                        f"/v1/datasets/{dataset_id}/experiments",
                        {
                            "name": experiment_name,
                            "version_id": dataset_version_id,
                            "metadata": {
                                "projection_schema": MAPPING_SCHEMA,
                                "dataset_version_id": dataset_version_id,
                                "tested_configuration": configuration,
                                "tested_configuration_digest": _digest_json(configuration),
                                "source_bundle_digest": source_bundle_digest,
                                "experiment_projection_digest": experiment_digest,
                            },
                        },
                    )
                )
            )
        if experiment.get("dataset_version_id") != dataset_version_id:
            raise ValueError("Phoenix Experiment resolved to the wrong Dataset version")
        experiment_id = _id(experiment, "experiment")
        experiment_mappings.append(
            {
                "name": experiment_name,
                "digest": experiment_digest,
                "source_bundle_digest": source_bundle_digest,
                "configuration": configuration,
                "phoenix_id": experiment_id,
                "dataset_version_id": dataset_version_id,
                "url": f"{http.endpoint}/experiments/{experiment_id}",
            }
        )
        partition_runs, partition_evaluations = _project_experiment_runs(
            http,
            experiment_id=experiment_id,
            partition=partition,
            example_by_sample=example_by_sample,
            required_graders=required_graders,
            projection_time=projection_time,
        )
        run_mappings.extend(partition_runs)
        evaluations.extend(partition_evaluations)
    projection["experiments"] = experiment_mappings
    projection["runs"] = run_mappings
    projection["evaluations"] = evaluations
    return projection


def _resolve_dataset_version(
    http: PhoenixHttp,
    *,
    dataset_id: str,
    expected_examples_digest: str,
) -> tuple[str, dict[str, Any]]:
    versions = _list_of_mappings(
        _data(http.json("GET", f"/v1/datasets/{dataset_id}/versions?limit=100")),
        "dataset versions",
    )
    if len(versions) != 1:
        raise TaskDatasetHistoryMismatch(
            "a task Dataset must contain exactly one immutable Phoenix version; rebuild the "
            "local Phoenix data and reproject canonical artifacts"
        )
    matches: list[tuple[str, dict[str, Any]]] = []
    for version in versions:
        version_id = str(version.get("version_id") or "")
        if not version_id:
            raise ValueError("Phoenix Dataset version response has no version_id")
        query = urlencode({"version_id": version_id})
        payload = _mapping(_data(http.json("GET", f"/v1/datasets/{dataset_id}/examples?{query}")))
        if payload.get("version_id") != version_id:
            raise ValueError("Phoenix returned examples for the wrong Dataset version")
        examples = _list_of_mappings(payload.get("examples"), "dataset examples")
        public_rows = [_mapping(item.get("input")) for item in examples]
        if _public_examples_digest(public_rows) == expected_examples_digest:
            matches.append((version_id, payload))
    if not matches:
        raise ExactDatasetVersionNotFound(
            "Phoenix could not resolve an exact Dataset version by public content"
        )
    if len(matches) > 1:
        raise ValueError("Phoenix resolved multiple Dataset versions with the same public content")
    return matches[0]


def _public_examples_digest(rows: list[dict[str, Any]]) -> str:
    return _digest_json(sorted(rows, key=lambda row: str(row.get("sample_id") or "")))


def _dataset_name(suite_id: str) -> str:
    return f"roboclaws-{path_token(suite_id)}"


def _examples_by_sample(examples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in examples:
        sample_id = str(_mapping(item.get("input")).get("sample_id") or "")
        if not sample_id or sample_id in result:
            raise ValueError("Phoenix Dataset version has missing or duplicate sample identity")
        result[sample_id] = item
    return result


def _configuration_key(identity: dict[str, str]) -> dict[str, str]:
    return {
        field: str(identity.get(field) or MISSING_CONFIGURATION_VALUE)
        for field in CONFIGURATION_FIELDS
    }


def _partition_results(
    results: list[tuple[EvalResult, dict[str, str]]],
) -> list[tuple[dict[str, str], list[tuple[EvalResult, dict[str, str]]]]]:
    partitions: dict[str, tuple[dict[str, str], list[tuple[EvalResult, dict[str, str]]]]] = {}
    for result, identity in results:
        configuration = _configuration_key(identity)
        digest = _digest_json(configuration)
        partitions.setdefault(digest, (configuration, []))[1].append((result, identity))
    return [partitions[digest] for digest in sorted(partitions)]


def _grader_labels(result: EvalResult, required_graders: tuple[str, ...]) -> dict[str, str]:
    return {
        grader: status
        for grader in required_graders
        if (status := _grader_status(result, grader)) is not None
    }


def _source_bundle_digest(
    results: list[tuple[EvalResult, dict[str, str]]], required_graders: tuple[str, ...]
) -> str:
    return _digest_json(
        sorted(
            (
                {
                    "identity": identity,
                    "status": result.status,
                    "grader_labels": _grader_labels(result, required_graders),
                }
                for result, identity in results
            ),
            key=lambda item: (
                str(item["identity"].get("trial_id") or ""),
                str(item["identity"].get("repetition_index") or ""),
            ),
        )
    )


def _experiment_projection_digest(
    *,
    dataset_version_id: str,
    source_bundle_digest: str,
    configuration: dict[str, str],
    results: list[tuple[EvalResult, dict[str, str]]],
    required_graders: tuple[str, ...],
) -> str:
    return _digest_json(
        {
            "projection_schema": MAPPING_SCHEMA,
            "dataset_version_id": dataset_version_id,
            "source_bundle_digest": source_bundle_digest,
            "tested_configuration": configuration,
            "grader_contract": list(required_graders),
            "results": [
                {
                    "identity": identity,
                    "status": result.status,
                    "grader_labels": _grader_labels(result, required_graders),
                }
                for result, identity in sorted(
                    results,
                    key=lambda item: (
                        item[1].get("trial_id", ""),
                        item[1].get("repetition_index", ""),
                    ),
                )
            ],
        }
    )


def _experiment_name(
    *,
    suite_id: str,
    suite_version: str,
    configuration: dict[str, str],
    digest: str,
) -> str:
    fields = (
        path_token(suite_id),
        path_token(suite_version),
        path_token(configuration["agent_engine"]),
        path_token(configuration["provider_profile"]),
        path_token(configuration["model"]),
        path_token(configuration["skill_name"]),
    )
    readable = "-".join(field[:32] for field in fields)
    return f"roboclaws-{readable}-{digest[:8]}"


def _project_experiment_runs(
    http: PhoenixHttp,
    *,
    experiment_id: str,
    partition: list[tuple[EvalResult, dict[str, str]]],
    example_by_sample: dict[str, dict[str, Any]],
    required_graders: tuple[str, ...],
    projection_time: str,
) -> tuple[list[dict[str, str]], list[dict[str, str | None]]]:
    existing_runs = _list_of_mappings(
        _data(http.json("GET", f"/v1/experiments/{experiment_id}/runs")),
        "experiment runs",
    )
    runs_by_digest: dict[str, list[dict[str, Any]]] = {}
    for run in existing_runs:
        output = _mapping(run.get("output"))
        digest = str(output.get("projection_digest") or "")
        if digest:
            runs_by_digest.setdefault(digest, []).append(run)
    run_mappings: list[dict[str, str]] = []
    evaluations: list[dict[str, str | None]] = []
    for result, identity in partition:
        grader_labels = _grader_labels(result, required_graders)
        run_digest = _digest_json(
            {"identity": identity, "status": result.status, "grader_labels": grader_labels}
        )
        matches = runs_by_digest.get(run_digest, [])
        if len(matches) > 1:
            raise ValueError("Phoenix contains ambiguous runs for one projection digest")
        example_id = _id(example_by_sample[identity["sample_id"]], "example")
        repetition_number = int(identity["repetition_index"])
        run = matches[0] if matches else None
        if run is None:
            run = _mapping(
                _data(
                    http.json(
                        "POST",
                        f"/v1/experiments/{experiment_id}/runs",
                        {
                            "dataset_example_id": example_id,
                            "output": {
                                "status": result.status,
                                "identity": identity,
                                "projection_digest": run_digest,
                            },
                            "repetition_number": repetition_number,
                            "start_time": projection_time,
                            "end_time": projection_time,
                            "trace_id": identity.get("trace_id") or None,
                        },
                    )
                )
            )
            runs_by_digest[run_digest] = [run]
        run_id = _id(run, "experiment run")
        run_url = f"{http.endpoint}/experiments/{experiment_id}/runs/{run_id}"
        run_mappings.append(
            {
                "trial_id": identity["trial_id"],
                "digest": run_digest,
                "experiment_id": experiment_id,
                "phoenix_id": run_id,
                "url": run_url,
            }
        )
        for grader, status in grader_labels.items():
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
                    "url": run_url,
                }
            )
    return run_mappings, evaluations


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


def _load_results(
    path: Path, *, suite: EvalSuite, samples: list[EvalSample]
) -> tuple[list[EvalResult], str]:
    resolved = path if path.is_absolute() else REPO_ROOT / path
    payload = read_json_object(resolved, label="eval results")
    result_suite = _mapping(payload.get("suite"))
    if result_suite.get("suite_id") != suite.suite_id:
        raise ValueError("eval_results suite_id does not match the projected suite")
    if result_suite != suite.to_dict():
        raise ValueError("eval_results suite does not match the exact projected suite release")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("eval_results must contain a results list")
    results = [EvalResult.from_mapping(_mapping(row)) for row in rows]
    sample_by_id = {sample.sample_id: sample for sample in samples}
    for result in results:
        _validate_result_identity(result, suite=suite, sample_by_id=sample_by_id)
    projection_time = datetime.fromtimestamp(resolved.stat().st_mtime, timezone.utc).isoformat()
    return results, projection_time


def _validate_result_identity(
    result: EvalResult, *, suite: EvalSuite, sample_by_id: dict[str, EvalSample]
) -> None:
    identity = result.identity
    if identity.get("suite_id") != suite.suite_id or identity.get("suite_version") != suite.version:
        raise ValueError("eval result does not match the exact projected suite release")
    sample_id = str(identity.get("sample_id") or "")
    sample = sample_by_id.get(sample_id)
    if sample is None:
        raise ValueError("eval result sample_id is not part of the projected suite")
    expected = {
        "sample_version": sample.version,
        "surface": sample.surface,
        "intent": sample.intent,
        "preset": sample.preset,
        "world": sample.world,
        "backend": sample.backend,
        "evidence_lane": sample.evidence_lane,
        "camera_labeler": sample.camera_labeler,
        "scenario_setup": sample.scenario_setup,
        "seed": sample.seed,
        "prompt": sample.prompt,
        "goal_contract_hash": sample.goal_contract_hash,
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ValueError("eval result does not match the exact projected sample release")


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


def _phoenix_api_origin(otlp_endpoint: str) -> str:
    endpoint = str(otlp_endpoint or "").strip()
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.path != "/v1/traces" or parsed.query or parsed.fragment:
        raise ValueError("Phoenix OTLP endpoint must use the exact /v1/traces path")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    _validate_loopback_endpoint(origin)
    return origin


def _projection_inputs(
    suite_ref: str,
) -> tuple[EvalSuite, list[EvalSample], list[dict[str, str]], str]:
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
    return suite, samples, public_samples, dataset_digest


def _empty_mapping(
    suite: EvalSuite,
    dataset_digest: str,
    *,
    endpoint_configured: bool = False,
) -> dict[str, Any]:
    return {
        "schema": MAPPING_SCHEMA,
        "state": "unavailable" if endpoint_configured else "disabled",
        "reason": "projection_not_completed" if endpoint_configured else "endpoint_not_configured",
        "suite": {
            "suite_id": suite.suite_id,
            "suite_version": suite.version,
            "dataset_digest": dataset_digest,
        },
        "dataset": None,
        "experiments": [],
        "examples": [],
        "runs": [],
        "evaluations": [],
    }


def _failure_reason(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"phoenix_http_{exc.code}"
    if isinstance(exc, TaskDatasetHistoryMismatch):
        return "task_dataset_history_unsupported"
    if isinstance(exc, TaskDatasetContentMismatch):
        return "task_dataset_content_mismatch"
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


def _find_all_by_digest(items: Any, digest: str) -> list[dict[str, Any]]:
    rows = _list_of_mappings(items, "Phoenix experiments")
    return [
        item
        for item in rows
        if isinstance(item.get("metadata"), dict)
        and item["metadata"].get("experiment_projection_digest") == digest
    ]


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
