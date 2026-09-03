from __future__ import annotations

from roboclaws.household.semantic_timeline import (
    CANONICAL_DISPLAY_SUBPHASES,
    CANONICAL_PLACE_DISPLAY_SUBPHASES,
)

VISUAL_CORE_BASE_SECTIONS = ("Before And After", "Object Moves", "Score")
VISUAL_CORE_SEMANTIC_SECTION = "Semantic Substeps"
VISUAL_CORE_ROBOT_SECTION = "Robot View Timeline"
VISUAL_CORE_AGENT_SECTION = "Agent View"
VISUAL_CORE_PRIVATE_SECTION = "Private Evaluation"
VISUAL_CORE_PLANNER_PROOF_REQUESTS_SECTION = "Planner Proof Requests"
PLANNER_DIAGNOSTIC_STYLE_MARKERS = (
    "diagnostic-view",
    "diagnostic-visual",
    "grasp-blocker-card",
    "decision-card",
)


def assert_cleanup_report_visual_core(
    report_text: str,
    *,
    require_semantic_subphases: bool = False,
    require_robot_timeline: bool = False,
    require_agent_view: bool = False,
    require_object_moves: bool = True,
    require_score: bool = True,
    require_private_evaluation: bool = False,
    require_planner_proof_requests: bool = False,
) -> None:
    """Assert the shared Cleanup Artifact Report visual core contract."""
    for marker in PLANNER_DIAGNOSTIC_STYLE_MARKERS:
        assert marker not in report_text, (marker, report_text[:500])

    _assert_visual_order(
        report_text,
        require_object_moves=require_object_moves,
        require_score=require_score,
        require_robot_timeline=require_robot_timeline,
        require_semantic_subphases=require_semantic_subphases,
    )

    if require_semantic_subphases:
        _assert_semantic_subphases(report_text)
    _assert_required_sections(
        report_text,
        require_robot_timeline=require_robot_timeline,
        require_agent_view=require_agent_view,
        require_private_evaluation=require_private_evaluation,
        require_planner_proof_requests=require_planner_proof_requests,
        require_score=require_score,
    )


def _assert_visual_order(
    report_text: str,
    *,
    require_object_moves: bool,
    require_score: bool,
    require_robot_timeline: bool,
    require_semantic_subphases: bool,
) -> None:
    ordered = [VISUAL_CORE_BASE_SECTIONS[0]]
    if require_object_moves:
        ordered.append(VISUAL_CORE_BASE_SECTIONS[1])
    _assert_sections_in_order(report_text, ordered)
    if require_score:
        _assert_after(report_text, VISUAL_CORE_BASE_SECTIONS[2], VISUAL_CORE_BASE_SECTIONS[1])
    if require_robot_timeline:
        anchor = (
            VISUAL_CORE_BASE_SECTIONS[1] if require_object_moves else VISUAL_CORE_BASE_SECTIONS[0]
        )
        if require_score and require_object_moves:
            _assert_between(
                report_text,
                VISUAL_CORE_ROBOT_SECTION,
                anchor,
                VISUAL_CORE_BASE_SECTIONS[2],
            )
        else:
            _assert_after(report_text, VISUAL_CORE_ROBOT_SECTION, anchor)
    if require_semantic_subphases:
        start = (
            VISUAL_CORE_BASE_SECTIONS[1] if require_object_moves else VISUAL_CORE_BASE_SECTIONS[0]
        )
        end = VISUAL_CORE_BASE_SECTIONS[2] if require_score else VISUAL_CORE_BASE_SECTIONS[0]
        _assert_between(report_text, VISUAL_CORE_SEMANTIC_SECTION, start, end)


def _assert_required_sections(
    report_text: str,
    *,
    require_robot_timeline: bool,
    require_agent_view: bool,
    require_private_evaluation: bool,
    require_planner_proof_requests: bool,
    require_score: bool,
) -> None:
    if require_robot_timeline:
        assert VISUAL_CORE_ROBOT_SECTION in report_text, report_text[:500]
    anchor = VISUAL_CORE_BASE_SECTIONS[2] if require_score else VISUAL_CORE_BASE_SECTIONS[0]
    if require_agent_view:
        assert VISUAL_CORE_AGENT_SECTION in report_text, report_text[:500]
        _assert_after(report_text, VISUAL_CORE_AGENT_SECTION, anchor)
    if require_private_evaluation:
        assert VISUAL_CORE_PRIVATE_SECTION in report_text, report_text[:500]
        _assert_after(report_text, VISUAL_CORE_PRIVATE_SECTION, anchor)
    if require_planner_proof_requests:
        assert VISUAL_CORE_PLANNER_PROOF_REQUESTS_SECTION in report_text, report_text[:500]
        _assert_after(report_text, VISUAL_CORE_PLANNER_PROOF_REQUESTS_SECTION, anchor)
        if require_agent_view:
            _assert_after(
                report_text,
                VISUAL_CORE_AGENT_SECTION,
                VISUAL_CORE_PLANNER_PROOF_REQUESTS_SECTION,
            )


def _assert_sections_in_order(report_text: str, sections: list[str]) -> None:
    previous_index = -1
    for section in sections:
        index = _section_index(report_text, section)
        assert index >= 0, (section, report_text[:500])
        assert index > previous_index, (sections, section, previous_index, index)
        previous_index = index


def _assert_semantic_subphases(report_text: str) -> None:
    assert "phase-rail" in report_text, report_text[:500]
    for label, detail in CANONICAL_DISPLAY_SUBPHASES:
        assert _has_subphase(report_text, label, detail), ((label, detail), report_text[:500])
    assert any(
        _has_subphase(report_text, label, detail)
        for label, detail in CANONICAL_PLACE_DISPLAY_SUBPHASES
    ), (
        CANONICAL_PLACE_DISPLAY_SUBPHASES,
        report_text[:500],
    )


def _assert_after(report_text: str, later: str, earlier: str) -> None:
    later_index = _section_index(report_text, later)
    earlier_index = _section_index(report_text, earlier)
    assert later_index >= 0 and earlier_index >= 0, (later, earlier, report_text[:500])
    assert later_index > earlier_index, (later, earlier, later_index, earlier_index)


def _assert_between(report_text: str, section: str, earlier: str, later: str) -> None:
    section_index = _section_index(report_text, section)
    earlier_index = _section_index(report_text, earlier)
    later_index = _section_index(report_text, later)
    assert section_index >= 0 and earlier_index >= 0 and later_index >= 0, (
        section,
        earlier,
        later,
        report_text[:500],
    )
    assert earlier_index < section_index < later_index, (
        section,
        earlier,
        later,
        section_index,
        earlier_index,
        later_index,
    )


def _section_index(report_text: str, section: str) -> int:
    heading = f"<h2>{section}</h2>"
    index = report_text.find(heading)
    if index >= 0:
        return index
    return report_text.find(section)


def _has_subphase(report_text: str, label: str, detail: str) -> bool:
    return f"<span>{label}</span><small>{detail}</small>" in report_text
