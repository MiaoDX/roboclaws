from __future__ import annotations

import json
import sys

import pytest

from roboclaws.household.candidate_projection_protocol import (
    PROJECTION_WORKER_COMMAND_ENV,
    project_candidate_public_response,
    validate_candidate_public_payload,
)
from roboclaws.household.candidate_projection_worker import dispatch_candidate_projection


def test_projection_is_identity_when_no_candidate_worker_is_configured(monkeypatch) -> None:
    monkeypatch.delenv(PROJECTION_WORKER_COMMAND_ENV, raising=False)
    payload = {"status": "ok", "items": [{"object_id": "observed_001"}]}
    assert project_candidate_public_response("declare_visual_candidates", payload) is payload


def test_projection_worker_receives_scrubbed_environment(monkeypatch) -> None:
    code = (
        "import json,os,sys; "
        "request=json.loads(sys.stdin.readline()); "
        "assert 'OPENAI_API_KEY' not in os.environ; "
        "request['payload']['worker_env_safe']=True; "
        "print(json.dumps({'schema':'candidate_projection_result_v1',"
        "'operation':request['operation'],'payload':request['payload']}))"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-worker")
    monkeypatch.setenv(
        PROJECTION_WORKER_COMMAND_ENV,
        json.dumps([sys.executable, "-c", code]),
    )

    projected = project_candidate_public_response("declare_visual_candidates", {"status": "ok"})

    assert projected == {"status": "ok", "worker_env_safe": True}


def test_projection_rejects_private_input_before_worker(monkeypatch) -> None:
    monkeypatch.setenv(PROJECTION_WORKER_COMMAND_ENV, json.dumps(["false"]))
    with pytest.raises(ValueError, match="forbidden key"):
        project_candidate_public_response(
            "declare_visual_candidates", {"private_truth": "must-not-cross"}
        )


def test_candidate_worker_dispatches_only_declared_operations() -> None:
    result = dispatch_candidate_projection(
        {
            "schema": "candidate_projection_request_v1",
            "operation": "declare_visual_candidates",
            "payload": {
                "ok": True,
                "status": "ok",
                "model_declared_observations": [],
                "camera_model_candidates": [],
            },
        }
    )
    assert result["schema"] == "candidate_projection_result_v1"
    assert result["payload"]["status"] == "ok"
    with pytest.raises(ValueError, match="unsupported"):
        dispatch_candidate_projection(
            {
                "schema": "candidate_projection_request_v1",
                "operation": "shell",
                "payload": {},
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "value"},
        {"nested": {"holdout": "value"}},
        {"items": [{"grader_internal": "value"}]},
    ],
)
def test_public_payload_validator_rejects_private_keys(payload) -> None:
    with pytest.raises(ValueError, match="forbidden key"):
        validate_candidate_public_payload(payload)
