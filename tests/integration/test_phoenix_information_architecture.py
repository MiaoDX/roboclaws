from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from roboclaws.evals.models import EvalResult, EvalTrial
from roboclaws.evals.phoenix_projection import PhoenixHttp, project_eval_to_phoenix
from roboclaws.evals.suite_loading import load_suite

ENDPOINT = os.environ.get("ROBOCLAWS_PHOENIX_INTEGRATION_ENDPOINT", "").rstrip("/")
pytestmark = pytest.mark.skipif(not ENDPOINT, reason="disposable Phoenix endpoint not configured")


def test_pinned_phoenix_exact_versions_and_projector_contract(tmp_path: Path) -> None:
    http = PhoenixHttp(ENDPOINT)
    openapi = http.json("GET", "/openapi.json")
    upload_schema = openapi["paths"]["/v1/datasets/upload"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert upload_schema["properties"]["action"]["enum"] == ["create", "append"]
    assert not any("examples/{" in path for path in openapi["paths"])

    first_upload = _ensure_version_proof(http)
    version_query = urlencode({"version_id": first_upload["version_id"]})
    old_version = http.json(
        "GET",
        f"/v1/datasets/{first_upload['dataset_id']}/examples?{version_query}",
    )["data"]
    assert old_version["version_id"] == first_upload["version_id"]
    assert [item["input"]["sample_id"] for item in old_version["examples"]] == ["one"]

    results_path = _write_heterogeneous_results(tmp_path / "eval_results.json")
    overrides = {
        "suite": "smoke_regression",
        "eval_results": str(results_path),
        "endpoint": ENDPOINT,
    }
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    assert project_eval_to_phoenix(overrides | {"output": str(first_path)})["state"] == "ready"
    assert project_eval_to_phoenix(overrides | {"output": str(second_path)})["state"] == "ready"
    first = _read_json(first_path)
    second = _read_json(second_path)

    assert first == second
    assert len(first["experiments"]) == 2
    assert len(first["runs"]) == 2
    assert len({run["experiment_id"] for run in first["runs"]}) == 2
    assert all(
        experiment["dataset_version_id"] == first["dataset"]["version_id"]
        for experiment in first["experiments"]
    )
    remote_experiments = http.json(
        "GET", f"/v1/datasets/{first['dataset']['phoenix_id']}/experiments"
    )["data"]
    remote_by_id = {item["id"]: item for item in remote_experiments}
    assert all(
        remote_by_id[item["phoenix_id"]]["dataset_version_id"] == first["dataset"]["version_id"]
        for item in first["experiments"]
    )

    corrected = _read_json(results_path)
    corrected["results"][0]["grader_outputs"]["privacy"]["status"] = "failed"
    results_path.write_text(json.dumps(corrected), encoding="utf-8")
    corrected_path = tmp_path / "corrected.json"
    assert project_eval_to_phoenix(overrides | {"output": str(corrected_path)})["state"] == "ready"
    corrected_mapping = _read_json(corrected_path)
    first_by_provider = {
        item["configuration"]["provider_profile"]: item for item in first["experiments"]
    }
    corrected_by_provider = {
        item["configuration"]["provider_profile"]: item for item in corrected_mapping["experiments"]
    }
    assert (
        first_by_provider["not_applicable"]["phoenix_id"]
        != corrected_by_provider["not_applicable"]["phoenix_id"]
    )
    assert (
        first_by_provider["kimi-openai-chat"]["phoenix_id"]
        != corrected_by_provider["kimi-openai-chat"]["phoenix_id"]
    )


def _ensure_version_proof(http: PhoenixHttp) -> dict[str, str]:
    name = "roboclaws-ia-version-proof"
    datasets = http.json("GET", f"/v1/datasets?{urlencode({'name': name, 'limit': 10})}")["data"]
    if not datasets:
        created = http.upload_dataset(
            name=name,
            rows=[{"sample_id": "one", "value": "v1"}],
        )["data"]
        http.json(
            "POST",
            "/v1/datasets/upload?sync=true",
            {
                "action": "append",
                "name": name,
                "inputs": [{"sample_id": "two", "value": "v1"}],
            },
        )
        return created
    assert len(datasets) == 1
    dataset_id = datasets[0]["id"]
    versions = http.json("GET", f"/v1/datasets/{dataset_id}/versions?limit=100")["data"]
    matches: list[str] = []
    for version in versions:
        version_id = version["version_id"]
        query = urlencode({"version_id": version_id})
        examples = http.json("GET", f"/v1/datasets/{dataset_id}/examples?{query}")["data"][
            "examples"
        ]
        if [item["input"] for item in examples] == [{"sample_id": "one", "value": "v1"}]:
            matches.append(version_id)
    assert len(matches) == 1
    return {"dataset_id": dataset_id, "version_id": matches[0]}


def _write_heterogeneous_results(path: Path) -> Path:
    suite, samples = load_suite("smoke_regression")
    trial = EvalTrial.from_sample(
        samples[0],
        suite=suite,
        trial_id="ia-proof-direct",
        repetition_index=0,
        agent_engine="direct-runner",
        runner_class="deterministic",
        provider_profile="not_applicable",
        model="not_applicable",
        skill_name="household-world",
    )
    result = EvalResult.from_trial(
        trial,
        status="passed",
        grader_outputs={grader: {"status": "passed"} for grader in suite.required_graders},
    ).to_dict()
    second: dict[str, Any] = json.loads(json.dumps(result))
    second["identity"].update(
        {
            "trial_id": "ia-proof-kimi",
            "provider_profile": "kimi-openai-chat",
            "model": "kimi-k2.7-code",
        }
    )
    path.write_text(
        json.dumps(
            {
                "schema": "roboclaws_eval_results_bundle_v1",
                "suite": suite.to_dict(),
                "results": [result, second],
            }
        ),
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
