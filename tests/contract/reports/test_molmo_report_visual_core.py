from __future__ import annotations

import pytest

from roboclaws.household.report_visual_core import assert_cleanup_report_visual_core
from roboclaws.household.semantic_camera_timeline import robot_view_capture_for_tool


def test_visual_core_contract_accepts_canonical_cleanup_order() -> None:
    report = """
    <h2>Before And After</h2>
    <h2>Object Moves</h2>
    <section><h2>Robot View Timeline</h2></section>
    <section><h2>Semantic Substeps</h2><ol class="phase-rail">
      <li><span>nav</span><small>object</small></li>
      <li><span>pick</span><small>object</small></li>
      <li><span>nav</span><small>target</small></li>
      <li><span>place</span><small>surface</small></li>
    </ol></section>
    <h2>Score</h2>
    <h2>Agent View</h2>
    <h2>Private Evaluation</h2>
    """

    assert_cleanup_report_visual_core(
        report,
        require_semantic_subphases=True,
        require_robot_timeline=True,
        require_agent_view=True,
        require_private_evaluation=True,
    )


def test_visual_core_contract_accepts_legacy_semantic_before_robot_order() -> None:
    report = """
    <h2>Before And After</h2>
    <h2>Object Moves</h2>
    <section><h2>Semantic Substeps</h2><ol class="phase-rail">
      <li><span>nav</span><small>object</small></li>
      <li><span>pick</span><small>object</small></li>
      <li><span>nav</span><small>target</small></li>
      <li><span>place</span><small>surface</small></li>
    </ol></section>
    <section><h2>Robot View Timeline</h2></section>
    <h2>Score</h2>
    """

    assert_cleanup_report_visual_core(
        report,
        require_semantic_subphases=True,
        require_robot_timeline=True,
    )


def test_visual_core_contract_rejects_raw_semantic_table() -> None:
    report = """
    <h2>Before And After</h2>
    <h2>Object Moves</h2>
    <h2>Semantic Substeps</h2>
    <table><tr><td>navigate_to_object -> pick -> navigate_to_receptacle</td></tr></table>
    <h2>Score</h2>
    """

    with pytest.raises(AssertionError):
        assert_cleanup_report_visual_core(report, require_semantic_subphases=True)


def test_visual_core_contract_rejects_planner_diagnostic_style_drift() -> None:
    report = """
    <style>.diagnostic-view { background: #fff; }</style>
    <h2>Before And After</h2>
    <h2>Object Moves</h2>
    <section><h2>Semantic Substeps</h2><ol class="phase-rail">
      <li><span>nav</span><small>object</small></li>
      <li><span>pick</span><small>object</small></li>
      <li><span>nav</span><small>target</small></li>
      <li><span>place</span><small>surface</small></li>
    </ol></section>
    <h2>Score</h2>
    """

    with pytest.raises(AssertionError):
        assert_cleanup_report_visual_core(report, require_semantic_subphases=True)


def test_robot_view_capture_for_tool_reuses_fixture_ids() -> None:
    capture = robot_view_capture_for_tool(
        "navigate_to_receptacle",
        {"fixture_id": "sink_01"},
        {"ok": True, "object_id": "observed_001", "fixture_id": "sink_01"},
        object_id_transform=lambda value: f"internal:{value}" if value else None,
    )

    assert capture == {
        "action": "navigate_to_receptacle sink_01",
        "label_suffix": "navigate_receptacle_sink_01",
        "focus_object_id": "internal:observed_001",
        "focus_receptacle_id": "sink_01",
        "semantic_phase": "navigate_to_receptacle",
    }
