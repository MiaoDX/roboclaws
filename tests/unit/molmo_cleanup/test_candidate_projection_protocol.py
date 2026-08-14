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
from roboclaws.household.household_mcp_projection import (
    _compact_cleanup_worklist_summary,
    _compact_declare_visual_candidates_response,
)


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


def test_baseline_projection_sanitizes_nested_visual_grounding_evidence() -> None:
    evidence = {
        "schema": "visual_grounding_evidence_v1",
        "candidate_state": "navigation_authorized",
        "private_truth_included": False,
    }
    projected = _compact_declare_visual_candidates_response(
        {
            "model_declared_observations": [{"visual_grounding_evidence": evidence}],
            "camera_model_candidates": [{"visual_grounding_evidence": evidence}],
        }
    )
    worklist = _compact_cleanup_worklist_summary(
        {"objects": [{"object_id": "observed_001", "visual_grounding_evidence": evidence}]}
    )

    validate_candidate_public_payload(projected)
    validate_candidate_public_payload(worklist)
    for item in (
        projected["model_declared_observations"][0],
        projected["camera_model_candidates"][0],
        worklist["objects"][0],
    ):
        assert item["visual_grounding_evidence"] == {
            "schema": "visual_grounding_evidence_v1",
            "candidate_state": "navigation_authorized",
        }


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
