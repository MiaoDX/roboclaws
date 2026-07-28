from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.artifact_report import (
    is_cleanup_run_result_artifact,
    load_cleanup_scenario_artifact,
    rerender_cleanup_report_from_artifact_path,
    rerender_cleanup_report_from_run_result,
    rerender_cleanup_reports_from_artifact_paths,
    rerender_cleanup_reports_from_run_results,
)
from roboclaws.household.report_visual_core import assert_cleanup_report_visual_core
from roboclaws.household.scenario import build_cleanup_scenario, write_scenario_bundle
from roboclaws.household.scoring import score_cleanup
from roboclaws.household.semantic_acceptability import (
    annotate_score_with_semantic_acceptability,
)
from roboclaws.household.semantic_timeline import semantic_substeps

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_regenerate_cleanup_report_script_wrapper_stays_removed() -> None:
    assert not (REPO_ROOT / "scripts" / "reports" / "regenerate_molmo_cleanup_report.py").exists()


def test_load_cleanup_scenario_artifact_uses_adjacent_private_manifest(tmp_path: Path) -> None:
    scenario = build_cleanup_scenario(seed=7)
    paths = write_scenario_bundle(tmp_path, scenario)

    loaded = load_cleanup_scenario_artifact(paths["scenario"])

    assert loaded.scenario_id == scenario.scenario_id
    assert loaded.private_manifest.success_threshold == scenario.private_manifest.success_threshold
    assert [target.object_id for target in loaded.private_manifest.targets] == [
        target.object_id for target in scenario.private_manifest.targets
    ]


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"cleanup report artifact source must contain valid JSON object: .*scenario\.json",
        ),
        (
            "[]\n",
            r"cleanup report artifact source must contain a JSON object: .*scenario\.json",
        ),
    ],
)
def test_load_cleanup_scenario_artifact_rejects_bad_scenario_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_cleanup_scenario_artifact(scenario_path)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"cleanup report artifact source must contain valid JSON object: "
            r".*private_manifest\.json",
        ),
        (
            "[]\n",
            r"cleanup report artifact source must contain a JSON object: "
            r".*private_manifest\.json",
        ),
    ],
)
def test_load_cleanup_scenario_artifact_rejects_bad_private_manifest_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    paths = write_scenario_bundle(tmp_path, scenario)
    paths["private_manifest"].write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_cleanup_scenario_artifact(paths["scenario"])


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"cleanup report artifact source must contain valid JSON object: "
            r".*run_result\.json",
        ),
        (
            "[]\n",
            r"cleanup report artifact source must contain a JSON object: "
            r".*run_result\.json",
        ),
    ],
)
def test_rerender_cleanup_report_from_run_result_rejects_bad_run_result_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    run_result_path = tmp_path / "run_result.json"
    run_result_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        rerender_cleanup_report_from_run_result(run_result_path)


def test_rerender_cleanup_report_from_run_result_uses_shared_visual_core(
    tmp_path: Path,
) -> None:
    scenario = build_cleanup_scenario(seed=7)
    write_scenario_bundle(tmp_path, scenario)
    receptacle_by_id = {item.receptacle_id: item.to_public_dict() for item in scenario.receptacles}
    target = scenario.private_manifest.targets[0]
    obj = next(item for item in scenario.objects if item.object_id == target.object_id)
    target_receptacle_id = target.valid_receptacle_ids[0]
    trace_events = _semantic_trace(
        object_id=obj.object_id,
        source_receptacle_id=obj.location_id,
        target_receptacle_id=target_receptacle_id,
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in trace_events) + "\n",
        encoding="utf-8",
    )
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    final_locations = scenario.object_locations()
    final_locations[obj.object_id] = target_receptacle_id
    score = annotate_score_with_semantic_acceptability(
        score_cleanup(final_locations, scenario.private_manifest).to_dict(),
        scenario,
    )
    run_result = {
        "backend": "test",
        "cleanup_status": "success",
        "contract": "realworld_cleanup_v1",
        "agent_driven": True,
        "mcp_server": "household_world",
        "policy": "codex_agent",
        "primitive_provenance": "api_semantic",
        "scenario_id": scenario.scenario_id,
        "semantic_substeps": semantic_substeps(trace_events, receptacle_by_id),
        "score": score,
        "robot_view_steps": [
            {
                "action": f"navigate_to_object {obj.object_id}",
                "semantic_phase": "navigate_to_object",
                "robot_pose": {},
                "views": {"fpv": "robot_views/nav.fpv.png"},
                "focus": {},
            },
            {
                "action": f"place {obj.object_id}",
                "semantic_phase": "place",
                "robot_pose": {},
                "views": {"fpv": "robot_views/place.fpv.png"},
                "focus": {},
            },
        ],
        "artifacts": {
            "scenario": "scenario.json",
            "trace": "trace.jsonl",
            "before_snapshot": "before.png",
            "after_snapshot": "after.png",
            "report": str(tmp_path / "report.html"),
        },
    }
    run_result_path = tmp_path / "run_result.json"
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")
    (tmp_path / "report.html").write_text("<h2>Semantic Substeps</h2>raw</table>", encoding="utf-8")

    report_path = rerender_cleanup_report_from_run_result(run_result_path)

    report_text = report_path.read_text(encoding="utf-8")
    assert report_path == tmp_path / "report.html"
    assert_cleanup_report_visual_core(
        report_text,
        require_semantic_subphases=True,
        require_robot_timeline=True,
    )
    assert "<span>nav</span><small>object</small>" in report_text
    assert "<span>pick</span><small>object</small>" in report_text
    assert "navigate_to_object -&gt; pick" not in report_text


def test_rerender_cleanup_report_from_run_result_handles_missing_scenario_artifact(
    tmp_path: Path,
) -> None:
    trace_events = _semantic_trace(
        object_id="observed_001",
        source_receptacle_id="table_01",
        target_receptacle_id="sink_01",
    )
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in trace_events) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "before.png").write_bytes(b"before")
    (tmp_path / "after.png").write_bytes(b"after")
    run_result = {
        "backend": "molmospaces_subprocess",
        "cleanup_status": "success",
        "contract": "realworld_cleanup_v1",
        "agent_driven": True,
        "policy": "camera_model_policy_baseline",
        "primitive_provenance": "api_semantic",
        "scenario_id": "scenario_from_run_result",
        "seed": 9,
        "score": {
            "status": "success",
            "restored_count": 1,
            "total_targets": 1,
            "success_threshold": 1,
            "restored_object_ids": ["observed_001"],
            "missed_object_ids": [],
            "object_results": [
                {
                    "object_id": "observed_001",
                    "actual_location_id": "sink_01",
                    "restored": True,
                    "semantic_acceptability": "preferred",
                    "semantic_reason": "exact",
                }
            ],
        },
        "semantic_substeps": [
            {
                "object_id": "observed_001",
                "source_receptacle_id": "table_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {"phase": "navigate_to_object"},
                    {"phase": "pick"},
                    {"phase": "navigate_to_receptacle"},
                    {"phase": "place", "location_id": "sink_01"},
                ],
            }
        ],
        "agent_view": _minimal_agent_view(),
        "private_evaluation": {
            "schema_version": "private_evaluation_v1",
            "generated_mess_set": ["observed_001"],
            "object_results": [
                {
                    "object_id": "observed_001",
                    "restored": True,
                    "actual_location_id": "sink_01",
                }
            ],
        },
        "robot_view_steps": [
            {
                "action": "navigate_to_object observed_001",
                "semantic_phase": "navigate_to_object",
                "robot_pose": {},
                "views": {"fpv": "robot_views/nav.fpv.png"},
                "focus": {},
            }
        ],
        "artifacts": {
            "trace": "trace.jsonl",
            "before_snapshot": "before.png",
            "after_snapshot": "after.png",
        },
    }
    run_result_path = tmp_path / "run_result.json"
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")

    report_path = rerender_cleanup_report_from_run_result(run_result_path)

    report_text = report_path.read_text(encoding="utf-8")
    assert "scenario_from_run_result" in report_text
    assert_cleanup_report_visual_core(
        report_text,
        require_semantic_subphases=True,
        require_robot_timeline=True,
        require_agent_view=True,
        require_private_evaluation=True,
    )
    assert "<span>nav</span><small>object</small>" in report_text
    assert "Subphase: <strong>nav</strong>" in report_text
    assert "nav/object" not in report_text


def _minimal_agent_view() -> dict[str, object]:
    return agent_view_module.build_agent_view(
        contract="realworld_cleanup_v1",
        perception_mode="visible_object_detections",
        detection_exposure_policy="public_runtime_map",
        structured_detections_available=True,
        base_metric_map={"schema": "real_robot_map_bundle_v1", "map_bundle": {}},
        runtime_metric_map={"schema": "runtime_metric_map_v1", "static_map": {}},
        observed_objects=[
            {
                "object_id": "observed_001",
                "category": "Plate",
                "state": "placed",
            }
        ],
        raw_fpv_observations=[],
        camera_model_policy_evidence={},
        model_declared_observations=[],
        model_declared_observation_evidence={},
        policy_view={},
        cleanup_worklist={},
        observed_waypoint_ids=[],
        public_tool_names=[],
        forbidden_keys=frozenset(),
    )


def test_rerender_cleanup_report_from_run_result_resolves_declared_paths_under_run_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_result_path = _write_minimal_run_result(run_dir)
    nested = run_dir / "artifacts"
    nested.mkdir()
    (nested / "trace.jsonl").write_text(
        (run_dir / "trace.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    cwd = tmp_path / "cwd"
    (cwd / "artifacts").mkdir(parents=True)
    (cwd / "artifacts" / "trace.jsonl").write_text("{not json}\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    run_result = json.loads(run_result_path.read_text(encoding="utf-8"))
    run_result["artifacts"]["trace"] = "artifacts/trace.jsonl"
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")

    report_path = rerender_cleanup_report_from_run_result(run_result_path)

    assert report_path == run_dir / "report.html"
    assert_cleanup_report_visual_core(
        report_path.read_text(encoding="utf-8"),
        require_semantic_subphases=True,
    )


def test_rerender_cleanup_report_from_run_result_rejects_missing_declared_trace(
    tmp_path: Path,
) -> None:
    run_result_path = _write_minimal_run_result(tmp_path / "run")
    run_result = json.loads(run_result_path.read_text(encoding="utf-8"))
    run_result["artifacts"]["trace"] = "missing/trace.jsonl"
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="trace.*missing/trace.jsonl"):
        rerender_cleanup_report_from_run_result(run_result_path)


def test_rerender_cleanup_report_from_run_result_rejects_empty_declared_trace(
    tmp_path: Path,
) -> None:
    run_result_path = _write_minimal_run_result(tmp_path / "run")
    run_result = json.loads(run_result_path.read_text(encoding="utf-8"))
    run_result["artifacts"]["trace"] = ""
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="declared trace artifact is empty"):
        rerender_cleanup_report_from_run_result(run_result_path)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            '{"event": "response", "tool": "observe", "response": {}}\n{not-json\n',
            r"cleanup report trace source row must contain valid JSON object: "
            r".*trace\.jsonl:2",
        ),
        (
            '{"event": "response", "tool": "observe", "response": {}}\n[]\n',
            r"cleanup report trace source row must contain a JSON object: "
            r".*trace\.jsonl:2",
        ),
    ],
)
def test_rerender_cleanup_report_from_run_result_rejects_bad_trace_rows(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    run_result_path = _write_minimal_run_result(tmp_path / "run")
    (run_result_path.parent / "trace.jsonl").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        rerender_cleanup_report_from_run_result(run_result_path)


def test_rerender_cleanup_report_from_run_result_rejects_missing_declared_scenario(
    tmp_path: Path,
) -> None:
    run_result_path = _write_minimal_run_result(tmp_path / "run")
    run_result = json.loads(run_result_path.read_text(encoding="utf-8"))
    run_result["artifacts"]["scenario"] = "missing/scenario.json"
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="scenario.*missing/scenario.json"):
        rerender_cleanup_report_from_run_result(run_result_path)


def test_rerender_cleanup_reports_from_run_results_reuses_single_adapter(
    tmp_path: Path,
) -> None:
    first = _write_minimal_run_result(tmp_path / "first")
    second = _write_minimal_run_result(tmp_path / "second")

    report_paths = rerender_cleanup_reports_from_run_results([first, second])

    assert report_paths == [first.parent / "report.html", second.parent / "report.html"]
    for report_path in report_paths:
        assert_cleanup_report_visual_core(
            report_path.read_text(encoding="utf-8"),
            require_semantic_subphases=True,
        )


def test_rerender_cleanup_report_from_artifact_path_accepts_run_directory(
    tmp_path: Path,
) -> None:
    run_result = _write_minimal_run_result(tmp_path / "run")

    assert is_cleanup_run_result_artifact(run_result.parent)

    report_path = rerender_cleanup_report_from_artifact_path(run_result.parent)

    assert report_path == run_result.parent / "report.html"
    assert_cleanup_report_visual_core(
        report_path.read_text(encoding="utf-8"),
        require_semantic_subphases=True,
    )


def test_rerender_cleanup_reports_from_artifact_paths_reuses_directory_adapter(
    tmp_path: Path,
) -> None:
    first = _write_minimal_run_result(tmp_path / "first")
    second = _write_minimal_run_result(tmp_path / "second")

    report_paths = rerender_cleanup_reports_from_artifact_paths([first.parent, second])

    assert report_paths == [first.parent / "report.html", second.parent / "report.html"]


def _write_minimal_run_result(run_dir: Path) -> Path:
    run_dir.mkdir()
    trace_events = _semantic_trace(
        object_id="observed_001",
        source_receptacle_id="table_01",
        target_receptacle_id="sink_01",
    )
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in trace_events) + "\n",
        encoding="utf-8",
    )
    (run_dir / "before.png").write_bytes(b"before")
    (run_dir / "after.png").write_bytes(b"after")
    run_result = {
        "backend": "test",
        "cleanup_status": "success",
        "contract": "realworld_cleanup_v1",
        "primitive_provenance": "api_semantic",
        "scenario_id": "scenario_from_run_result",
        "score": {
            "status": "success",
            "restored_count": 1,
            "total_targets": 1,
            "success_threshold": 1,
            "restored_object_ids": ["observed_001"],
            "missed_object_ids": [],
            "object_results": [],
        },
        "semantic_substeps": [
            {
                "object_id": "observed_001",
                "source_receptacle_id": "table_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {"phase": "navigate_to_object"},
                    {"phase": "pick"},
                    {"phase": "navigate_to_receptacle"},
                    {"phase": "place", "location_id": "sink_01"},
                ],
            }
        ],
        "artifacts": {
            "trace": "trace.jsonl",
            "before_snapshot": "before.png",
            "after_snapshot": "after.png",
        },
    }
    run_result_path = run_dir / "run_result.json"
    run_result_path.write_text(json.dumps(run_result, indent=2, sort_keys=True), encoding="utf-8")
    return run_result_path


def _semantic_trace(
    *,
    object_id: str,
    source_receptacle_id: str,
    target_receptacle_id: str,
) -> list[dict[str, object]]:
    responses = [
        {
            "tool": "navigate_to_object",
            "ok": True,
            "object_id": object_id,
            "location_id": source_receptacle_id,
            "source_receptacle_id": source_receptacle_id,
            "primitive_provenance": "api_semantic",
        },
        {
            "tool": "pick",
            "ok": True,
            "object_id": object_id,
            "location_id": "held_by_agent",
            "source_receptacle_id": source_receptacle_id,
            "primitive_provenance": "api_semantic",
        },
        {
            "tool": "navigate_to_receptacle",
            "ok": True,
            "object_id": object_id,
            "receptacle_id": target_receptacle_id,
            "primitive_provenance": "api_semantic",
        },
        {
            "tool": "place",
            "ok": True,
            "object_id": object_id,
            "receptacle_id": target_receptacle_id,
            "location_id": target_receptacle_id,
            "location_relation": "on",
            "primitive_provenance": "api_semantic",
        },
    ]
    events: list[dict[str, object]] = []
    for response in responses:
        events.append({"event": "response", "tool": response["tool"], "response": response})
    return events
