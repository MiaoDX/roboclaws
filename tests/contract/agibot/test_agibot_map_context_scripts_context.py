from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from tests.contract.agibot.agibot_map_context_scripts_support import (
    CAPTURE_PATH,
    GENERATOR_PATH,
    SIX_CAMERA_CAPTURE_PATH,
    VERIFY_PATH,
    _base_metric_map_context,
    _capture_manifest,
    _completed_context,
    _FakeAgibotGDK,
    _FakeCameraFactory,
    _load_module,
    _require_agibot_sdk_runner,
    _require_six_camera_capture,
    _run_sdk,
    _run_sdk_allowing_failure,
    _TimeoutPnc,
)


def test_generate_metric_map_from_completed_agibot_context(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_from_context")
    context_path = tmp_path / "agibot_map_context.completed.json"
    output_dir = tmp_path / "generated"
    context_path.write_text(json.dumps(_completed_context()), encoding="utf-8")

    generator.main([str(context_path), "--output-dir", str(output_dir)])

    metric_map = json.loads((output_dir / "metric_map.json").read_text(encoding="utf-8"))
    static_fixture_projection = json.loads(
        (output_dir / "static_fixture_projection.json").read_text(encoding="utf-8")
    )
    agent_view = json.loads((output_dir / "agent_view.json").read_text(encoding="utf-8"))

    assert metric_map["schema"] == "real_robot_map_bundle_v1"
    assert "map_source" not in metric_map
    assert "map_bundle" not in metric_map
    assert metric_map["occupancy_grid_artifact"] is None
    assert metric_map["map_preview_artifact"] == "semantic_preview.png"
    assert metric_map["inspection_waypoints"][0]["waypoint_source"] == "operator_recorded_pose"
    assert metric_map["inspection_waypoints"][0]["reachability_status"] == "verified"
    assert "verification" not in metric_map["inspection_waypoints"][0]
    assert metric_map["robot_pose"]["pose_source"] == "operator_recorded_pose"
    assert static_fixture_projection["schema"] == "static_fixture_projection_v1"
    assert (
        static_fixture_projection["static_fixture_projection_mode"]
        == "operator_authored_static_projection"
    )
    assert static_fixture_projection["contains_runtime_observations"] is False
    assert "map_source" not in json.dumps(agent_view)
    assert "verification" not in json.dumps(agent_view)
    assert (output_dir / "semantic_preview.png").is_file()


def test_generate_metric_map_from_base_metric_agibot_context(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_from_base_metric_context")
    context_path = tmp_path / "agibot_map_context.base_metric.json"
    output_dir = tmp_path / "generated"
    context_path.write_text(json.dumps(_base_metric_map_context()), encoding="utf-8")

    generator.main([str(context_path), "--output-dir", str(output_dir)])

    metric_map = json.loads((output_dir / "metric_map.json").read_text(encoding="utf-8"))
    static_fixture_projection = json.loads(
        (output_dir / "static_fixture_projection.json").read_text(encoding="utf-8")
    )
    agent_view = json.loads((output_dir / "agent_view.json").read_text(encoding="utf-8"))
    first_waypoint = metric_map["inspection_waypoints"][0]
    payload_text = json.dumps(agent_view).lower()

    assert metric_map["schema"] == "real_robot_map_bundle_v1"
    assert "mode" not in metric_map
    assert metric_map["rooms"][0]["room_label"] == "Open office"
    assert metric_map["room_category_hints"][0]["room_label"] == "Open office"
    assert metric_map["base_metric_map"]["source_rooms_hidden"] is False
    assert metric_map["base_metric_map"]["source_room_labels_visible"] is True
    assert metric_map["base_metric_map"]["source_fixtures_hidden"] is True
    assert metric_map["base_metric_map"]["generated_candidate_count"] == 3
    assert metric_map["safety_bounds"]["polygon"]
    assert len(metric_map["inspection_waypoints"]) == 3
    assert len(metric_map["generated_exploration_candidates"]) == 3
    assert first_waypoint["waypoint_id"] == "generated_exploration_001"
    assert first_waypoint["waypoint_source"] == "generated_exploration_candidate"
    assert first_waypoint["purpose"] == "base_metric_map_exploration"
    assert first_waypoint["reachability_status"] == "verified"
    assert first_waypoint["candidate_provenance"]["source"] == "public_free_space_sample"
    assert first_waypoint["room_label"] == "Open office"
    assert "verification" not in first_waypoint
    assert "mode" not in static_fixture_projection
    assert (
        static_fixture_projection["static_fixture_projection_mode"] == "base_metric_map_no_fixtures"
    )
    assert static_fixture_projection["rooms"] == []
    assert "agibot_gdk" not in payload_text
    assert "map_source" not in payload_text
    assert "verification" not in payload_text
    assert "pnc" not in payload_text
    assert (output_dir / "semantic_preview.png").is_file()


def test_generate_metric_map_rejects_missing_context_source(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_missing_context_source")
    missing = tmp_path / "missing_context.json"

    with pytest.raises(
        SystemExit, match=r"Agibot map context source is missing: .*missing_context\.json"
    ):
        generator.main([str(missing), "--output-dir", str(tmp_path / "generated")])


def test_generate_metric_map_rejects_malformed_context_source(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_malformed_context_source")
    context_path = tmp_path / "agibot_map_context.invalid.json"
    context_path.write_text("{bad json\n", encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match=r"Agibot map context source must contain valid JSON object: .*invalid\.json",
    ):
        generator.main([str(context_path), "--output-dir", str(tmp_path / "generated")])


def test_generate_metric_map_rejects_non_object_context_source(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_non_object_context_source")
    context_path = tmp_path / "agibot_map_context.array.json"
    context_path.write_text("[]", encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match=r"Agibot map context source must contain a JSON object: .*array\.json",
    ):
        generator.main([str(context_path), "--output-dir", str(tmp_path / "generated")])


def test_generate_metric_map_rejects_todo_context(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_from_context_todo")
    context = _completed_context()
    context["rooms"][0]["room_label"] = "TODO: room label"

    errors = generator.validate_context(context)

    assert "rooms[0].room_label is required" in errors


def test_capture_context_upsert_records_multiple_waypoints(tmp_path: Path) -> None:
    capture = _load_module(CAPTURE_PATH, "capture_map_context_views")
    context_path = tmp_path / "agibot_map_context.todo.json"
    context = {
        "schema": "agibot_gdk_map_context_authoring_v1",
        "map_source": {"type": "agibot_gdk_map_context", "map_id": 3, "map_name": "office"},
        "rooms": [],
        "fixtures": [],
        "inspection_waypoints": [],
        "waypoint_captures": [],
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")

    loaded = json.loads(context_path.read_text(encoding="utf-8"))
    capture._upsert_capture_into_context(
        loaded,
        manifest=_capture_manifest("wp_sofa_front", x=1.0, y=2.0),
        manifest_path=tmp_path / "captures" / "wp_sofa_front" / "capture_manifest.json",
        context_dir=tmp_path,
        room_id="living_room",
        room_label="Living room",
        fixture_id="sofa",
        fixture_label="Sofa",
        fixture_category="sofa",
        waypoint_id="wp_sofa_front",
        waypoint_label="Sofa front",
    )
    capture._upsert_capture_into_context(
        loaded,
        manifest=_capture_manifest("wp_table_front", x=2.0, y=3.0),
        manifest_path=tmp_path / "captures" / "wp_table_front" / "capture_manifest.json",
        context_dir=tmp_path,
        room_id="living_room",
        room_label="Living room",
        fixture_id="table",
        fixture_label="Table",
        fixture_category="table",
        waypoint_id="wp_table_front",
        waypoint_label="Table front",
    )

    assert [item["waypoint_id"] for item in loaded["inspection_waypoints"]] == [
        "wp_sofa_front",
        "wp_table_front",
    ]
    assert {item["fixture_id"] for item in loaded["fixtures"]} == {"sofa", "table"}
    assert len(loaded["rooms"]) == 1
    assert loaded["inspection_waypoints"][0]["capture"]["manifest_path"] == (
        "captures/wp_sofa_front/capture_manifest.json"
    )


def test_capture_context_loader_rejects_invalid_context_sources(tmp_path: Path) -> None:
    capture = _load_module(CAPTURE_PATH, "capture_map_context_views_source_errors")
    missing = tmp_path / "missing_context.json"
    malformed = tmp_path / "malformed_context.json"
    non_object = tmp_path / "array_context.json"
    malformed.write_text("{bad json\n", encoding="utf-8")
    non_object.write_text("[]", encoding="utf-8")

    with pytest.raises(
        SystemExit, match=r"Agibot map context source is missing: .*missing_context\.json"
    ):
        capture._load_context(missing)
    with pytest.raises(
        SystemExit,
        match=(
            r"Agibot map context source must contain valid JSON object: "
            r".*malformed_context\.json"
        ),
    ):
        capture._load_context(malformed)
    with pytest.raises(
        SystemExit,
        match=r"Agibot map context source must contain a JSON object: .*array_context\.json",
    ):
        capture._load_context(non_object)


def test_verify_helpers_select_map_check_and_record_status() -> None:
    verifier = _load_module(VERIFY_PATH, "verify_waypoints_with_pnc")
    context = _completed_context()
    context["inspection_waypoints"].append(
        {
            "waypoint_id": "wp_table_front",
            "room_id": "living_room",
            "fixture_id": "sofa",
            "label": "Table front",
            "x": 2.0,
            "y": 2.0,
            "yaw": 0.0,
        }
    )

    selected = verifier.select_waypoints(
        context,
        all_waypoints=False,
        waypoint_ids=["wp_table_front"],
    )
    map_check = verifier.compare_current_map(
        context,
        {"id": 3, "name": "office_floor_1", "is_curr_map": True},
    )
    result = {
        "reachability_status": verifier.VERIFIED,
        "navigation_backend": "agibot_gdk",
        "primitive_provenance": "agibot_gdk_normal_navi",
    }
    verifier.record_waypoint_verification(selected[0], result)

    assert len(selected) == 1
    assert map_check["ok"] is True
    assert selected[0]["reachability_status"] == "verified"
    assert selected[0]["verification"]["primitive_provenance"] == "agibot_gdk_normal_navi"


def test_verify_context_loader_rejects_invalid_context_sources(tmp_path: Path) -> None:
    verifier = _load_module(VERIFY_PATH, "verify_waypoints_with_pnc_source_errors")
    missing = tmp_path / "missing_context.json"
    malformed = tmp_path / "malformed_context.json"
    non_object = tmp_path / "array_context.json"
    wrong_schema = tmp_path / "wrong_schema_context.json"
    malformed.write_text("{bad json\n", encoding="utf-8")
    non_object.write_text("[]", encoding="utf-8")
    wrong_schema.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")

    with pytest.raises(
        SystemExit, match=r"Agibot map context source is missing: .*missing_context\.json"
    ):
        verifier._load_context(missing)
    with pytest.raises(
        SystemExit,
        match=(
            r"Agibot map context source must contain valid JSON object: "
            r".*malformed_context\.json"
        ),
    ):
        verifier._load_context(malformed)
    with pytest.raises(
        SystemExit,
        match=r"Agibot map context source must contain a JSON object: .*array_context\.json",
    ):
        verifier._load_context(non_object)
    with pytest.raises(SystemExit, match="context schema must be"):
        verifier._load_context(wrong_schema)


def test_verify_waypoint_timeout_records_cancel_evidence(monkeypatch) -> None:
    verifier = _load_module(VERIFY_PATH, "verify_waypoints_with_pnc_timeout")
    waypoint = _completed_context()["inspection_waypoints"][0]
    pnc = _TimeoutPnc()

    monkeypatch.setattr(verifier.time, "sleep", lambda seconds: None)

    result = verifier.verify_waypoint(
        gdk=_FakeAgibotGDK(),
        pnc=pnc,
        waypoint=waypoint,
        timeout_s=0.0,
        poll_s=0.0,
        map_check={"ok": True},
    )

    assert result["reachability_status"] == "timeout"
    assert result["navigation_backend"] == "agibot_gdk"
    assert result["cancel_attempted"] is True
    assert result["cancel_task_id"] == 42
    assert result["cancel_requested"] is True
    assert result["cancel_error"] == ""
    assert result["final_task_before_cancel"]["state_name"] == "running"
    assert result["final_task_after_cancel"]["state_name"] == "canceled"
    assert result["final_task"]["state_name"] == "canceled"
    assert pnc.cancel_task_calls == [42]


def test_vendor_sdk_runner_exports_base_metric_context_generated_candidates(
    tmp_path: Path,
) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.minimal.json"
    context_path.write_text(json.dumps(_base_metric_map_context()), encoding="utf-8")
    root = tmp_path / "sdk-runner"
    agent_view_dir = root / "01-agent-view"
    navigate_dir = root / "03-navigate"

    _run_sdk(
        "agent-view",
        "--context-json",
        str(context_path),
        "--output-dir",
        str(agent_view_dir),
    )
    _run_sdk(
        "navigate-waypoint",
        "--agent-view-json",
        str(agent_view_dir / "agent_view.json"),
        "--output-dir",
        str(navigate_dir),
        "--waypoint-id",
        "generated_exploration_001",
    )

    agent_view = json.loads((agent_view_dir / "agent_view.json").read_text(encoding="utf-8"))
    run_result = json.loads((agent_view_dir / "run_result.json").read_text(encoding="utf-8"))
    navigate_result = json.loads((navigate_dir / "run_result.json").read_text(encoding="utf-8"))
    payload_text = json.dumps(agent_view).lower()
    metric_map = agent_view["metric_map"]
    static_fixture_projection = agent_view["static_fixture_projection"]
    waypoint = metric_map["inspection_waypoints"][0]

    assert agent_view.get("schema") != agent_view_module.AGENT_VIEW_SCHEMA
    assert metric_map["base_metric_map"]["enabled"] is True
    assert metric_map["rooms"][0]["room_label"] == "Open office"
    assert metric_map["room_category_hints"][0]["room_label"] == "Open office"
    assert waypoint["waypoint_source"] == "generated_exploration_candidate"
    assert waypoint["room_label"] == "Open office"
    assert waypoint["reachability_status"] == "verified"
    assert static_fixture_projection["static_fixture_projection_mode"] == (
        "base_metric_map_no_fixtures"
    )
    assert run_result["summary"]["generated_exploration_candidates"] == 3
    assert run_result["privacy_check"]["ok"] is True
    assert "map_source" not in payload_text
    assert "verification" not in payload_text
    assert navigate_result["tool_response"]["navigation_status"] == "dry_run_not_executed"
    assert navigate_result["tool_response"]["waypoint_id"] == "generated_exploration_001"


def test_sdk_runner_context_json_source_rejects_malformed_json(tmp_path: Path) -> None:
    _require_agibot_sdk_runner()
    context_path = tmp_path / "agibot_map_context.malformed.json"
    context_path.write_text("{bad json\n", encoding="utf-8")

    proc = _run_sdk_allowing_failure(
        "agent-view",
        "--context-json",
        str(context_path),
        "--output-dir",
        str(tmp_path / "agent-view"),
    )

    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert "Agibot SDK context JSON source must contain valid JSON object" in proc.stderr
    assert str(context_path) in proc.stderr


def test_six_camera_capture_writes_all_default_views_and_no_motion(
    monkeypatch, tmp_path: Path
) -> None:
    _require_six_camera_capture()
    capture = _load_module(SIX_CAMERA_CAPTURE_PATH, "capture_six_camera_views_mocked_success")
    fake_gdk = _FakeAgibotGDK(camera_factory=_FakeCameraFactory())

    monkeypatch.setitem(sys.modules, "agibot_gdk", fake_gdk)
    monkeypatch.setattr(capture, "require_robot_discovery", lambda robot_host: None)
    monkeypatch.setattr(capture, "ensure_runtime", lambda robot_host, script_path: None)
    monkeypatch.setattr(capture.time, "sleep", lambda seconds: None)

    rc = capture.main_from_args(
        [
            "--robot-host",
            "127.0.0.1",
            "--output-dir",
            str(tmp_path),
            "--no-contact-sheet",
        ]
    )

    status = json.loads((tmp_path / "six_view_status.json").read_text(encoding="utf-8"))
    cameras = [item["camera"] for item in status["captures"]]
    assert rc == 0
    assert status["read_only"] is True
    assert status["navigation_submission"] is False
    assert status["motion_or_write_calls_used"] == []
    assert cameras == [
        "head_color",
        "head_stereo_left",
        "head_stereo_right",
        "head_depth",
        "hand_left_color",
        "hand_right_color",
    ]
    for item in status["captures"]:
        assert item["ok"] is True
        assert item["shape"] == [640, 400]
        assert item["image_path"].endswith(f"{item['camera']}.jpg")
        assert (tmp_path / f"{item['camera']}.jpg").read_bytes().startswith(b"\xff\xd8")
    assert fake_gdk.gdk_release_calls == 1
