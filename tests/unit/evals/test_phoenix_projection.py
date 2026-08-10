from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from roboclaws.evals import phoenix_projection
from roboclaws.evals.models import EvalResult, EvalTrial
from roboclaws.evals.suite_loading import load_suite

REAL_PHOENIX_HTTP = phoenix_projection.PhoenixHttp


class FakePhoenix:
    datasets: list[dict[str, Any]] = []
    examples: dict[str, list[dict[str, Any]]] = {}
    versions: dict[str, list[dict[str, Any]]] = {}
    experiments: dict[str, list[dict[str, Any]]] = {}
    runs: dict[str, list[dict[str, Any]]] = {}
    evaluations: dict[tuple[str, str], dict[str, Any]] = {}
    calls: list[tuple[str, str, Any]] = []

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    @classmethod
    def reset(cls) -> None:
        cls.datasets = []
        cls.examples = {}
        cls.versions = {}
        cls.experiments = {}
        cls.runs = {}
        cls.evaluations = {}
        cls.calls = []

    def upload_dataset(self, *, name: str, rows: list[dict[str, str]]) -> dict[str, Any]:
        self.calls.append(("POST", "/v1/datasets/upload?sync=true", rows))
        dataset = {"id": f"dataset-{len(self.datasets) + 1}", "name": name}
        self.datasets.append(dataset)
        self.examples[dataset["id"]] = [
            {"id": f"example-{index}", "input": row} for index, row in enumerate(rows, 1)
        ]
        self.versions[dataset["id"]] = [{"version_id": "version-1"}]
        return {"data": {"dataset_id": dataset["id"], "version_id": "version-1"}}

    def json(self, method: str, path: str, payload: object | None = None) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if method == "GET" and path.startswith("/v1/datasets?"):
            return {"data": self.datasets}
        if method == "GET" and "/versions?" in path:
            dataset_id = path.split("/")[3]
            return {"data": self.versions[dataset_id]}
        if method == "GET" and "/examples?" in path:
            dataset_id = path.split("/")[3]
            return {
                "data": {
                    "dataset_id": dataset_id,
                    "version_id": "version-1",
                    "examples": self.examples[dataset_id],
                }
            }
        if path.endswith("/experiments"):
            dataset_id = path.split("/")[3]
            if method == "GET":
                return {"data": self.experiments.get(dataset_id, [])}
            experiment = {
                "id": f"experiment-{len(self.experiments.get(dataset_id, [])) + 1}",
                "dataset_version_id": payload["version_id"],
                **payload,
            }
            self.experiments.setdefault(dataset_id, []).append(experiment)
            return {"data": experiment}
        if path.endswith("/runs"):
            experiment_id = path.split("/")[3]
            if method == "GET":
                return {"data": self.runs.get(experiment_id, [])}
            run = {
                "id": f"run-{len(self.runs.get(experiment_id, [])) + 1}",
                **payload,
            }
            self.runs.setdefault(experiment_id, []).append(run)
            return {"data": run}
        if path == "/v1/experiment_evaluations":
            key = (payload["experiment_run_id"], payload["name"])
            evaluation = self.evaluations.setdefault(
                key,
                {"id": f"evaluation-{len(self.evaluations) + 1}"},
            )
            return {"data": evaluation}
        raise AssertionError((method, path, payload))


@pytest.fixture(autouse=True)
def fake_phoenix(monkeypatch: pytest.MonkeyPatch) -> None:
    FakePhoenix.reset()
    monkeypatch.setattr(phoenix_projection, "PhoenixHttp", FakePhoenix)


def test_disabled_projection_writes_complete_mapping_without_network(tmp_path: Path) -> None:
    output = tmp_path / "mapping.json"

    summary = phoenix_projection.project_eval_to_phoenix(
        {"suite": "smoke_regression", "output": str(output)}
    )

    mapping = json.loads(output.read_text())
    assert summary["state"] == "disabled"
    assert mapping["state"] == "disabled"
    assert mapping["dataset"] is None
    assert mapping["experiments"] == []
    assert mapping["examples"] == []
    assert mapping["runs"] == []
    assert FakePhoenix.calls == []


def test_phoenix_http_upload_uses_documented_json_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Any] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"data":{"dataset_id":"dataset-1","version_id":"version-1"}}'

    def fake_urlopen(request: Any, *, timeout: float) -> Response:
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(phoenix_projection, "urlopen", fake_urlopen)
    payload = REAL_PHOENIX_HTTP("http://127.0.0.1:6006").upload_dataset(
        name="dataset-name",
        rows=[{"sample_id": "sample-1", "sample_version": "v1", "prompt_digest": "a" * 64}],
    )

    request, timeout = requests[0]
    assert request.full_url.endswith("/v1/datasets/upload?sync=true")
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data) == {
        "action": "create",
        "name": "dataset-name",
        "inputs": [{"sample_id": "sample-1", "sample_version": "v1", "prompt_digest": "a" * 64}],
    }
    assert timeout == 5.0
    assert payload["data"]["dataset_id"] == "dataset-1"


def test_projection_is_idempotent_and_exports_only_closed_public_fields(tmp_path: Path) -> None:
    results = _write_results(tmp_path / "eval_results.json")
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"
    overrides = {
        "suite": "smoke_regression",
        "eval_results": str(results),
        "endpoint": "http://127.0.0.1:6006",
    }

    phoenix_projection.project_eval_to_phoenix(overrides | {"output": str(first_output)})
    first_creates = [
        call
        for call in FakePhoenix.calls
        if call[0] == "POST" and call[1] != "/v1/experiment_evaluations"
    ]
    phoenix_projection.project_eval_to_phoenix(overrides | {"output": str(second_output)})
    all_creates = [
        call
        for call in FakePhoenix.calls
        if call[0] == "POST" and call[1] != "/v1/experiment_evaluations"
    ]

    assert len(all_creates) == len(first_creates)
    first = json.loads(first_output.read_text())
    second = json.loads(second_output.read_text())
    assert first["suite"] == second["suite"]
    assert first["dataset"] == second["dataset"]
    assert first["dataset"]["version_id"] == "version-1"
    assert first["experiments"] == second["experiments"]
    assert first["runs"] == second["runs"]
    assert first["evaluations"] == second["evaluations"]
    exported = json.dumps(FakePhoenix.calls)
    assert "prompt_digest" in exported
    assert "top secret prompt" not in exported
    assert "private_goal_reference" not in exported
    assert "acceptable_destinations" not in exported
    assert "generated_mess" not in exported
    assert "grader_config" not in exported
    assert "raw-secret-artifact" not in exported
    assert "unexpected_private_metric" not in exported
    run_posts = [
        payload
        for method, path, payload in FakePhoenix.calls
        if method == "POST" and path.endswith("/runs")
    ]
    assert run_posts[0]["output"]["identity"]["prompt_source_git_sha"] == "a" * 40
    assert run_posts[0]["output"]["identity"]["prompt_skill_sha256"] == "b" * 64
    assert run_posts[0]["trace_id"] == "trace-1"
    assert {
        "dataset_example_id",
        "output",
        "repetition_number",
        "start_time",
        "end_time",
        "trace_id",
    } <= run_posts[0].keys()
    evaluation_posts = [
        payload
        for method, path, payload in FakePhoenix.calls
        if method == "POST" and path == "/v1/experiment_evaluations"
    ]
    assert evaluation_posts[0]["annotator_kind"] == "CODE"
    assert evaluation_posts[0]["result"] == {"label": "passed"}
    assert {row["name"] for row in first["evaluations"]} == {
        "artifacts.status",
        "privacy.status",
        "trajectory.status",
    }
    version_reads = [path for method, path, _payload in FakePhoenix.calls if method == "GET"]
    assert any(path.endswith("/versions?limit=100") for path in version_reads)
    assert any(path.endswith("/examples?version_id=version-1") for path in version_reads)


def test_heterogeneous_bundle_partitions_configuration_without_run_collisions(
    tmp_path: Path,
) -> None:
    results = _write_results(tmp_path / "eval_results.json")
    payload = json.loads(results.read_text())
    second = json.loads(json.dumps(payload["results"][0]))
    second["identity"].update(
        {
            "trial_id": "trial-2",
            "provider_profile": "kimi-openai-chat",
            "model": "kimi-k2.7-code",
        }
    )
    payload["results"].append(second)
    results.write_text(json.dumps(payload))
    output = tmp_path / "mapping.json"

    phoenix_projection.project_eval_to_phoenix(
        {
            "suite": "smoke_regression",
            "eval_results": str(results),
            "endpoint": "http://127.0.0.1:6006",
            "output": str(output),
        }
    )

    mapping = json.loads(output.read_text())
    assert len(mapping["experiments"]) == 2
    assert {row["configuration"]["provider_profile"] for row in mapping["experiments"]} == {
        "not_applicable",
        "kimi-openai-chat",
    }
    assert len(mapping["runs"]) == 2
    assert len({row["experiment_id"] for row in mapping["runs"]}) == 2
    run_posts = [
        payload
        for method, path, payload in FakePhoenix.calls
        if method == "POST" and path.endswith("/runs")
    ]
    assert {row["repetition_number"] for row in run_posts} == {0}
    assert {row["dataset_example_id"] for row in run_posts} == {"example-1"}


def test_regraded_bundle_creates_new_immutable_experiment_and_then_reuses_it(
    tmp_path: Path,
) -> None:
    results = _write_results(tmp_path / "eval_results.json")
    overrides = {
        "suite": "smoke_regression",
        "eval_results": str(results),
        "endpoint": "http://127.0.0.1:6006",
    }
    phoenix_projection.project_eval_to_phoenix(overrides | {"output": str(tmp_path / "first.json")})
    payload = json.loads(results.read_text())
    payload["results"][0]["grader_outputs"]["privacy"]["status"] = "failed"
    results.write_text(json.dumps(payload))

    phoenix_projection.project_eval_to_phoenix(
        overrides | {"output": str(tmp_path / "second.json")}
    )
    creates_after_correction = [
        call for call in FakePhoenix.calls if call[0] == "POST" and call[1].endswith("/experiments")
    ]
    phoenix_projection.project_eval_to_phoenix(overrides | {"output": str(tmp_path / "third.json")})
    all_creates = [
        call for call in FakePhoenix.calls if call[0] == "POST" and call[1].endswith("/experiments")
    ]

    assert len(creates_after_correction) == 2
    assert len(all_creates) == 2
    first = json.loads((tmp_path / "first.json").read_text())
    second = json.loads((tmp_path / "second.json").read_text())
    third = json.loads((tmp_path / "third.json").read_text())
    assert first["experiments"][0]["phoenix_id"] != second["experiments"][0]["phoenix_id"]
    assert (
        first["experiments"][0]["source_bundle_digest"]
        != second["experiments"][0]["source_bundle_digest"]
    )
    assert second["experiments"] == third["experiments"]
    assert second["runs"] == third["runs"]


def test_server_failure_is_fail_open_with_unavailable_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingPhoenix(FakePhoenix):
        def json(self, method: str, path: str, payload: object | None = None) -> Any:
            raise OSError("server returned 503 with a secret body")

    monkeypatch.setattr(phoenix_projection, "PhoenixHttp", FailingPhoenix)
    output = tmp_path / "mapping.json"

    summary = phoenix_projection.project_eval_to_phoenix(
        {
            "suite": "smoke_regression",
            "endpoint": "http://localhost:6006",
            "output": str(output),
        }
    )

    mapping = json.loads(output.read_text())
    assert summary["state"] == "unavailable"
    assert mapping["state"] == "unavailable"
    assert mapping["reason"] == "phoenix_connection_failed"
    assert "secret body" not in output.read_text()
    assert mapping["dataset"] is None
    assert mapping["runs"] == []


@pytest.mark.parametrize(
    "endpoint",
    ["https://127.0.0.1:6006", "http://phoenix.example:6006", "http://0.0.0.0:6006"],
)
def test_non_loopback_or_non_http_endpoint_is_rejected(tmp_path: Path, endpoint: str) -> None:
    output = tmp_path / "mapping.json"
    with pytest.raises(ValueError, match="loopback HTTP"):
        phoenix_projection.project_eval_to_phoenix(
            {"suite": "smoke_regression", "endpoint": endpoint, "output": str(output)}
        )
    assert not output.exists()
    assert FakePhoenix.calls == []


def test_malformed_local_results_fail_before_network_or_mapping(tmp_path: Path) -> None:
    results = tmp_path / "eval_results.json"
    results.write_text(json.dumps({"suite": {"suite_id": "wrong"}, "results": []}))
    output = tmp_path / "mapping.json"

    with pytest.raises(ValueError, match="suite_id does not match"):
        phoenix_projection.project_eval_to_phoenix(
            {
                "suite": "smoke_regression",
                "eval_results": str(results),
                "endpoint": "http://127.0.0.1:6006",
                "output": str(output),
            }
        )

    assert not output.exists()
    assert FakePhoenix.calls == []


def test_dispatcher_never_invokes_suite_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from roboclaws.evals import runner

    def forbidden_execution(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("suite execution must not be called")

    monkeypatch.setattr(runner, "run_eval_suite", forbidden_execution)
    payload = runner.run_cli_tool(
        "phoenix-project",
        {"suite": "smoke_regression", "output": str(tmp_path / "mapping.json")},
    )

    assert payload["state"] == "disabled"


def _write_results(path: Path) -> Path:
    suite, samples = load_suite("smoke_regression")
    sample = samples[0]
    trial = EvalTrial.from_sample(
        sample,
        suite=suite,
        trial_id="trial-1",
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
        grader_outputs={
            "artifacts": {"status": "passed", "details": "raw-secret-artifact"},
            "privacy": {"status": "passed", "private_goal_reference": "secret"},
            "trajectory": {"status": "passed", "acceptable_destinations": "secret"},
        },
        artifacts={"trace": "/tmp/raw-secret-artifact"},
        metrics={"unexpected_private_metric": 42},
    )
    identity = dict(result.identity)
    identity["prompt"] = "top secret prompt"
    run_dir = path.parent / "run"
    run_dir.mkdir()
    (run_dir / "prompt-identity.json").write_text(
        json.dumps(
            {
                "schema": "roboclaws_prompt_identity_v1",
                "prompt_source_git_sha": "a" * 40,
                "prompt_skill_sha256": "b" * 64,
                "prompt_rendered_sha256": "c" * 64,
            }
        )
    )
    (run_dir / "live_timing.json").write_text(
        json.dumps({"trace_id": "trace-1", "private_goal_reference": "secret"})
    )
    payload = {
        "schema": "roboclaws_eval_results_bundle_v1",
        "suite": suite.to_dict(),
        "results": [
            result.to_dict()
            | {"identity": identity, "artifacts": result.artifacts | {"run_dir": str(run_dir)}}
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
