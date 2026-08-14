from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from roboclaws.operator_console.prompt_preview import (
    PromptPreviewRequest,
    build_prompt_preview,
)
from roboclaws.operator_console.routes import (
    get_selection,
)
from roboclaws.operator_console.server import (
    _registered_preview_asset_names,
)
from roboclaws.operator_console.state import (
    derive_operator_state,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_CLEANUP,
    AGIBOT_SDK_MAP_BUILD,
    AGIBOT_SDK_OPEN_TASK,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_CLEANUP,
    B1_OPENAI_AGENTS_MAP_BUILD,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)
from tests.unit.operator_console.operator_console_support import (
    _assert_registered_scene_preview_assets,
    _assert_scene_preview_json_assets,
    _assert_scene_preview_png_assets,
    _assert_scene_preview_rejects_invalid_paths,
    _blocked_raw_operator_control_payload,
    _console_server,
    _write_running_operator_control_state,
)


def test_operator_console_prompt_preview_endpoint_renders_agent_kickoff_prompt(
    tmp_path: Path,
) -> None:
    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/prompt-preview",
            method="POST",
            data=json.dumps(
                {
                    "world_id": "molmospaces/procthor-objaverse-val/0",
                    "backend_id": "mujoco",
                    "intent_id": "open-ended",
                    "agent_engine_id": "openai-agents-sdk",
                    "provider_profile": "kimi-openai-chat",
                    "evidence_lane": "world-public-labels",
                    "scenario_setup": "baseline",
                    "prompt": "只收拾桌面上的杯子",
                    "overrides": {},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["operator_prompt"] == "只收拾桌面上的杯子"
    assert payload["source"] == "household-world"
    assert payload["intent"] == "open-ended"
    assert "prompt_mode" not in payload
    assert (
        "This run is surface=household-world intent=open-ended" in payload["agent_kickoff_prompt"]
    )
    assert "只收拾桌面上的杯子" in payload["agent_kickoff_prompt"]
    assert "household-world skill instructions" in payload["agent_kickoff_prompt"]
    assert payload["wrapper_notes"] == []


@pytest.mark.parametrize(
    ("request_fields", "expected_error"),
    [
        (
            {
                "agent_engine_id": "openai-agents-sdk",
                "evidence_lane": "camera-raw-fpv",
                "overrides": {},
                "env_overrides": {"ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "many"},
            },
            "raw_fpv_candidate_budget must be an integer",
        ),
        (
            {
                "agent_engine_id": "openai-agents-sdk",
                "evidence_lane": "world-public-labels",
                "overrides": {"relocation_count": "abc"},
            },
            "relocation_count must be an integer",
        ),
    ],
)
def test_operator_console_prompt_preview_endpoint_rejects_invalid_numeric_inputs(
    tmp_path: Path,
    request_fields: dict[str, object],
    expected_error: str,
) -> None:
    with _console_server(tmp_path) as (host, port):
        request = urllib.request.Request(
            f"http://{host}:{port}/api/prompt-preview",
            method="POST",
            data=json.dumps(
                {
                    "world_id": "molmospaces/procthor-objaverse-val/0",
                    "backend_id": "mujoco",
                    "intent_id": "cleanup",
                    "provider_profile": "kimi-openai-chat",
                    "scenario_setup": "relocate-cleanup-related-objects",
                    "prompt": "收拾杯子",
                    **request_fields,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(request)
        payload = json.loads(exc_info.value.read().decode("utf-8"))

    assert exc_info.value.code == 400
    assert expected_error in payload["error"]


@pytest.mark.parametrize(
    ("env_overrides", "expected_error"),
    [
        (
            {"ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "-1"},
            "max_observe_per_waypoint must be non-negative",
        ),
        (
            {"ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET": "-1"},
            "done_retry_budget must be non-negative",
        ),
    ],
)
def test_prompt_preview_rejects_invalid_openai_agents_numeric_env_values(
    env_overrides: dict[str, str],
    expected_error: str,
) -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )

    with pytest.raises(ValueError, match=expected_error):
        build_prompt_preview(
            route,
            PromptPreviewRequest(
                prompt="收拾杯子",
                env_overrides=env_overrides,
            ),
        )


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"relocation_count": "abc"}, "relocation_count must be an integer"),
        ({"relocation_count": "-3"}, "relocation_count must be non-negative"),
    ],
)
def test_prompt_preview_rejects_invalid_relocation_count(
    overrides: dict[str, str],
    expected_error: str,
) -> None:
    route = get_selection(MUJOCO_SDK_CLEANUP)

    with pytest.raises(ValueError, match=expected_error):
        build_prompt_preview(
            route,
            PromptPreviewRequest(
                prompt="收拾杯子",
                overrides={
                    "scenario_setup": "relocate-cleanup-related-objects",
                    **overrides,
                },
            ),
        )


def test_prompt_preview_uses_valid_openai_agents_numeric_env_overrides() -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )

    payload = build_prompt_preview(
        route,
        PromptPreviewRequest(
            prompt="收拾杯子",
            overrides={"relocation_count": "4"},
            env_overrides={
                "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "3",
                "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "2",
                "ROBOCLAWS_OPENAI_AGENTS_DONE_RETRY_BUDGET": "0",
            },
        ),
    )

    assert "Raw-FPV candidate-attempt budget=3" in payload["agent_kickoff_prompt"]
    assert "Per-waypoint observation budget=2" in payload["agent_kickoff_prompt"]
    assert "Done retry budget=0" in payload["agent_kickoff_prompt"]


def test_prompt_preview_keeps_existing_prompt_minimums_for_zero_budget_env() -> None:
    route = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::cleanup::openai-agents-sdk::camera-raw-fpv"
    )

    payload = build_prompt_preview(
        route,
        PromptPreviewRequest(
            prompt="收拾杯子",
            env_overrides={
                "ROBOCLAWS_OPENAI_AGENTS_RAW_FPV_CANDIDATE_BUDGET": "0",
                "ROBOCLAWS_OPENAI_AGENTS_MAX_OBSERVE_PER_WAYPOINT": "0",
            },
        ),
    )

    assert "Raw-FPV candidate-attempt budget=1" in payload["agent_kickoff_prompt"]
    assert "Per-waypoint observation budget=1" in payload["agent_kickoff_prompt"]


def test_operator_state_derives_public_fields_and_artifact_links(tmp_path: Path) -> None:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / "run-a"
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "phase": "running",
                "backend_lock": "molmospaces_mujoco",
                "started_at_epoch": 1,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "tool_name": "navigate_to_object",
                "ok": True,
                "reasoning": "public reason",
                "observation_summary": "mug visible",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "run_result.json").write_text(
        json.dumps(
            {
                "task": "household-cleanup",
                "backend": "molmospaces_subprocess",
                "cleanup_success": True,
                "private_manifest": {"must_not": "surface"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")

    state = derive_operator_state(tmp_path, run_dir, get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK))

    assert state["run_id"] == "run-a"
    assert state["latest_tool_call"]["name"] == "navigate_to_object"
    assert state["latest_public_decision_evidence"]["observation_summary"] == "mug visible"
    assert state["checker_status"]["status"] == "passed"
    assert "private_manifest" not in state["public_run_result"]
    assert any(item["label"] == "Report" for item in state["artifact_paths"])
    report_link = next(item for item in state["artifact_paths"] if item["label"] == "Report")
    assert report_link["href"].startswith("/artifacts/")
    assert "?v=" in report_link["href"]


def test_operator_console_serves_only_operator_output_artifacts(tmp_path: Path) -> None:
    output_artifact = (
        tmp_path / "output" / "operator-console" / "runs" / "run-a" / "console-launch.log"
    )
    output_artifact.parent.mkdir(parents=True)
    output_artifact.write_text("Authorization: Bearer live-token\nvisible tail\n", encoding="utf-8")
    repo_file = tmp_path / "README.md"
    repo_file.write_text("repo source should not be an artifact\n", encoding="utf-8")

    output_rel = output_artifact.relative_to(tmp_path).as_posix()
    repo_rel = repo_file.relative_to(tmp_path).as_posix()

    with _console_server(tmp_path) as (host, port):
        artifact_url = f"http://{host}:{port}/artifacts/{urllib.parse.quote(output_rel)}"
        with urllib.request.urlopen(artifact_url) as response:
            assert response.read().decode("utf-8") == output_artifact.read_text(encoding="utf-8")

        raw_url = f"http://{host}:{port}/api/raw/{urllib.parse.quote(output_rel)}"
        with urllib.request.urlopen(raw_url) as response:
            redacted = response.read().decode("utf-8")

        repo_url = f"http://{host}:{port}/artifacts/{urllib.parse.quote(repo_rel)}"
        with pytest.raises(urllib.error.HTTPError) as repo_error:
            urllib.request.urlopen(repo_url)
        raw_repo_url = f"http://{host}:{port}/api/raw/{urllib.parse.quote(repo_rel)}"
        with pytest.raises(urllib.error.HTTPError) as raw_repo_error:
            urllib.request.urlopen(raw_repo_url)

        escape_url = (
            f"http://{host}:{port}/artifacts/"
            f"{urllib.parse.quote('output/operator-console/../README.md')}"
        )
        with pytest.raises(urllib.error.HTTPError) as escape_error:
            urllib.request.urlopen(escape_url)
        raw_escape_url = (
            f"http://{host}:{port}/api/raw/"
            f"{urllib.parse.quote('output/operator-console/../README.md')}"
        )
        with pytest.raises(urllib.error.HTTPError) as raw_escape_error:
            urllib.request.urlopen(raw_escape_url)

    assert "live-token" not in redacted
    assert "visible tail" in redacted
    assert repo_error.value.code == 404
    assert raw_repo_error.value.code == 404
    assert escape_error.value.code == 404
    assert raw_escape_error.value.code == 404


def test_operator_console_static_assets_are_not_cached(tmp_path: Path) -> None:
    with _console_server(tmp_path) as (host, port):
        for asset in ("styles.css", "app.js", "state.js", "workflow-view.js"):
            with urllib.request.urlopen(f"http://{host}:{port}/{asset}") as response:
                assert response.headers["Cache-Control"] == "no-store, max-age=0"
                assert response.headers["Content-Type"].endswith("charset=utf-8")


def test_operator_console_serves_scene_preview_assets(tmp_path: Path) -> None:
    registered_previews = _registered_preview_asset_names()
    _assert_registered_scene_preview_assets(registered_previews)

    with _console_server(tmp_path) as (host, port):
        base_url = f"http://{host}:{port}"
        _assert_scene_preview_png_assets(base_url)
        _assert_scene_preview_json_assets(base_url)
        _assert_scene_preview_rejects_invalid_paths(base_url)


def test_operator_console_latest_run_endpoint_returns_artifact_backed_history(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "latest-run"
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps({"run_id": run_id, "route": route.to_payload(), "phase": "finished"}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html>ok</html>", encoding="utf-8")

    with _console_server(tmp_path) as (host, port):
        with urllib.request.urlopen(f"http://{host}:{port}/api/runs/latest") as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["run_id"] == run_id
    assert payload["selection_id"] == route.id
    assert payload["run_dir"] == str(run_dir.resolve())


def test_operator_console_control_endpoint_rejects_malformed_request_body(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "malformed-control-body-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_raw_operator_control_payload(host, port, run_id, "{not-json")

    assert (
        payload["error"] == "operator console request body source must contain valid JSON object: "
        "POST /api/runs/malformed-control-body-run/control"
    )
    assert not (run_dir / "operator_control.jsonl").exists()


def test_operator_console_control_endpoint_rejects_non_object_request_body(
    tmp_path: Path,
) -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    run_id = "non-object-control-body-run"
    run_dir = _write_running_operator_control_state(tmp_path, route, run_id)

    with _console_server(tmp_path) as (host, port):
        payload = _blocked_raw_operator_control_payload(host, port, run_id, "[]")

    assert (
        payload["error"] == "operator console request body source must contain a JSON object: "
        "POST /api/runs/non-object-control-body-run/control"
    )
    assert not (run_dir / "operator_control.jsonl").exists()
