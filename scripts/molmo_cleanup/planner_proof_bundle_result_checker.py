from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_RESULT_SUMMARY_SCHEMA,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    validate_planner_proof_quality_evidence,
)
from roboclaws.household.planner_task_feasibility import grasp_feasibility_signature_counts


def assert_proof_result_summary(
    summary: dict[str, Any],
    commands: list[dict[str, Any]],
    base: Path,
    report_text: str,
    *,
    require_outputs: bool,
    require_quality: bool = False,
    planner_backed_min_steps: int | None = None,
) -> None:
    assert summary.get("schema") == PLANNER_PROOF_RESULT_SUMMARY_SCHEMA, summary
    assert int(summary.get("expected_count") or 0) == len(commands), summary
    results = summary.get("results") or []
    assert len(results) == len(commands), summary
    assert "Proof Probe Results" in report_text, report_text[:500]
    if require_outputs:
        assert int(summary.get("result_count") or 0) == len(commands), summary
    _assert_timeout_counts(summary, results, report_text)
    assert_grasp_signature_counts(summary, results, report_text)
    if require_quality or planner_backed_min_steps is not None:
        _assert_proof_quality_summary(
            summary,
            results,
            report_text,
            planner_backed_min_steps=planner_backed_min_steps,
        )
    for item in results:
        _assert_proof_result_item(item, base, report_text)


def assert_prior_proof_result_summary(
    summary: dict[str, Any],
    base: Path,
    report_text: str,
) -> None:
    schema = str(summary.get("schema") or "")
    assert schema, summary
    results = summary.get("results") or []
    assert isinstance(results, list), summary
    assert "Prior Proof Evidence" in report_text, report_text[:500]
    assert_grasp_signature_counts(summary, results, report_text)
    for item in results:
        assert isinstance(item, dict), summary
        for key in ("request_id", "status", "task_feasibility_status", "run_result", "report"):
            value = str(item.get(key) or "")
            if value:
                assert value in report_text, (key, report_text[:500])
        for view in item.get("views") or []:
            _assert_report_view_src(view, base, report_text)
        blocker_summary = str(item.get("task_feasibility_blocker_summary") or "")
        if blocker_summary:
            assert blocker_summary in report_text, (
                "task_feasibility_blocker_summary",
                report_text[:500],
            )
        blocker_kind = str(item.get("task_feasibility_blocker_kind") or "")
        if blocker_kind:
            assert blocker_kind in report_text, (
                "task_feasibility_blocker_kind",
                report_text[:500],
            )


def assert_grasp_signature_counts(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    report_text: str,
) -> None:
    grasp_signature_counts = summary.get("grasp_feasibility_signature_counts") or []
    if grasp_signature_counts:
        assert int(summary.get("grasp_feasibility_signature_count") or 0) == len(
            grasp_signature_counts
        ), summary
    else:
        grasp_signature_counts = grasp_feasibility_signature_counts(results)
    if not grasp_signature_counts:
        return
    assert "Grasp Feasibility Signature Matrix" in report_text, report_text[:500]
    assert "Effective removals" in report_text, report_text[:500]
    for signature in grasp_signature_counts:
        assert signature.get("pattern_key"), signature
        assert int(signature.get("count") or 0) > 0, signature
        for value in [
            signature.get("summary"),
            signature.get("subkind"),
            *(signature.get("request_ids") or []),
            *(signature.get("object_names") or []),
            *(signature.get("grasp_load_exception_asset_uids") or []),
            *(signature.get("grasp_load_exception_types") or []),
        ]:
            if value:
                assert str(value) in report_text, (signature, report_text[:500])


def _assert_timeout_counts(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    report_text: str,
) -> None:
    timeout_count = sum(1 for item in results if _has_blocker_code(item, "timeout"))
    assert int(summary.get("timeout_count") or 0) == timeout_count, summary
    if timeout_count:
        assert "Timeouts" in report_text, report_text[:500]
    rby1m_config_import_timeout_count = sum(
        1
        for item in results
        if _has_blocker_code(item, "timeout")
        and item.get("last_worker_stage") == "rby1m_config_import"
    )
    assert (
        int(summary.get("rby1m_config_import_timeout_count") or 0)
        == rby1m_config_import_timeout_count
    ), summary


def _assert_proof_result_item(item: dict[str, Any], base: Path, report_text: str) -> None:
    for key in ("request_id", "status", "task_feasibility_status", "run_result", "report"):
        assert item.get(key), item
        assert str(item[key]) in report_text, (key, report_text[:500])
    assert item.get("task_feasibility_status") in {
        "not_run",
        "not_reached",
        "ready",
        "binding_not_promoted",
        "blocked",
        "unknown",
    }, item
    _assert_result_blockers(item, report_text)
    for view in item.get("views") or []:
        _assert_report_view_src(view, base, report_text)
    _assert_worker_artifacts(item, report_text)
    _assert_task_feasibility_blocker(item, report_text)
    _assert_result_quality(item, report_text)
    _assert_robot_placement_profile(item, report_text)
    _assert_sampler_adapter(item, report_text)
    _assert_cleanup_task_config(item, report_text)
    _assert_task_sampler_failure_diagnostics(item, report_text)
    _assert_worker_stage_events(item, report_text)


def _assert_result_blockers(item: dict[str, Any], report_text: str) -> None:
    for blocker in [
        *(item.get("blockers") or []),
        *(item.get("cleanup_binding_blockers") or []),
    ]:
        code = str(blocker.get("code") or "")
        if code:
            assert code in report_text, (code, report_text[:500])


def _assert_worker_artifacts(item: dict[str, Any], report_text: str) -> None:
    for key in ("last_worker_stage", "stdout", "stderr"):
        value = str(item.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])


def _assert_task_feasibility_blocker(item: dict[str, Any], report_text: str) -> None:
    blocker_kind = str(item.get("task_feasibility_blocker_kind") or "")
    if blocker_kind:
        assert "Task feasibility blocker" in report_text, report_text[:500]
        assert blocker_kind in report_text, ("task_feasibility_blocker_kind", report_text[:500])
    blocker_summary = str(item.get("task_feasibility_blocker_summary") or "")
    if blocker_summary:
        assert blocker_summary in report_text, (
            "task_feasibility_blocker_summary",
            report_text[:500],
        )


def _assert_result_quality(item: dict[str, Any], report_text: str) -> None:
    quality = item.get("proof_quality") or {}
    if quality:
        assert "Proof quality" in report_text, report_text[:500]
        assert str(quality.get("quality_tier") or "") in report_text, report_text[:500]


def _assert_robot_placement_profile(item: dict[str, Any], report_text: str) -> None:
    robot_placement_profile = item.get("task_sampler_robot_placement_profile") or {}
    if not robot_placement_profile:
        return
    assert "Robot placement profile" in report_text, report_text[:500]
    for key in ("profile",):
        value = str(robot_placement_profile.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])
    overrides = robot_placement_profile.get("place_robot_near_overrides") or {}
    max_tries = str(overrides.get("max_tries") or "")
    if max_tries:
        assert max_tries in report_text, ("place_robot_near_overrides", report_text[:500])


def _assert_sampler_adapter(item: dict[str, Any], report_text: str) -> None:
    sampler_adapter = item.get("cleanup_task_sampler_adapter") or {}
    if not sampler_adapter:
        return
    assert "Exact sampler adapter applied" in report_text, report_text[:500]
    for key in ("planner_object_id", "planner_target_receptacle_id", "task_sampler_class"):
        value = str(sampler_adapter.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])
    pickup_binding = sampler_adapter.get("exact_pickup_candidate_binding") or {}
    if pickup_binding:
        assert "Exact pickup candidate action" in report_text, report_text[:500]
        if pickup_binding.get("retry_budget") is not None:
            assert "Exact pickup retry budget" in report_text, report_text[:500]
        for key in ("planner_object_id", "action"):
            value = str(pickup_binding.get(key) or "")
            if value:
                assert value in report_text, (key, report_text[:500])


def _assert_cleanup_task_config(item: dict[str, Any], report_text: str) -> None:
    cleanup_task_config = item.get("cleanup_task_config") or {}
    config_blockers = cleanup_task_config.get("blockers") or []
    if not config_blockers:
        return
    assert "Exact task config blockers" in report_text, report_text[:500]
    for blocker in config_blockers:
        value = str(blocker.get("code") or "")
        if value:
            assert value in report_text, (value, report_text[:500])


def _assert_task_sampler_failure_diagnostics(item: dict[str, Any], report_text: str) -> None:
    task_sampler_failure = item.get("task_sampler_failure_diagnostics") or {}
    if not task_sampler_failure:
        return
    _assert_task_sampler_placement_failures(task_sampler_failure, report_text)
    _assert_task_sampler_grasp_failures(task_sampler_failure, report_text)
    _assert_grasp_collision_checks(task_sampler_failure, report_text)
    _assert_last_placement_scene_diagnostic(task_sampler_failure, report_text)
    last_failure = task_sampler_failure.get("last_robot_placement_failure") or {}
    value = str(last_failure.get("message") or "")
    if value:
        assert value in report_text, ("last_robot_placement_failure", report_text[:500])


def _assert_task_sampler_placement_failures(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    placement_failure_keys = ("robot_placement_failure_count", "asset_failure_count")
    if any(_positive_int(task_sampler_failure.get(key)) for key in placement_failure_keys):
        assert "Task sampler placement failures" in report_text, report_text[:500]
        for key in placement_failure_keys:
            value = str(task_sampler_failure.get(key) or "")
            if value and value != "0":
                assert value in report_text, (key, report_text[:500])
    for key in ("robot_placement_attempt_count",):
        value = str(task_sampler_failure.get(key) or "")
        if value and value != "0":
            assert value in report_text, (key, report_text[:500])


def _assert_task_sampler_grasp_failures(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    grasp_failures = task_sampler_failure.get("grasp_failures") or []
    if not grasp_failures:
        return
    assert "Post-placement grasp failures" in report_text, report_text[:500]
    assert "Post-Placement Rejection Views" in report_text, report_text[:500]
    if "candidate_effective_removal_count" in task_sampler_failure:
        assert "Post-placement effective removals" in report_text, report_text[:500]
    if "candidate_name_miss_count" in task_sampler_failure:
        assert "Post-placement candidate name misses" in report_text, report_text[:500]
    value = str(task_sampler_failure.get("grasp_failure_count") or "")
    if value:
        assert value in report_text, ("grasp_failure_count", report_text[:500])


def _assert_grasp_collision_checks(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    if not (
        task_sampler_failure.get("grasp_load_attempts")
        or task_sampler_failure.get("grasp_collision_checks")
    ):
        return
    assert "Grasp collision checks" in report_text, report_text[:500]
    last_check = task_sampler_failure.get("last_grasp_collision_check") or {}
    last_load = task_sampler_failure.get("last_grasp_load_attempt") or {}
    for key in ("asset_uid", "noncolliding_grasp_count", "cached_grasp_count"):
        value = str(last_check.get(key) or last_load.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])


def _assert_last_placement_scene_diagnostic(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    last_scene = task_sampler_failure.get("last_placement_scene_diagnostic") or {}
    if not last_scene:
        return
    assert "Placement free-space fraction" in report_text, report_text[:500]
    value = str(last_scene.get("valid_neighborhood_fraction") or "")
    if value:
        assert value in report_text, (
            "last_placement_scene_diagnostic",
            report_text[:500],
        )


def _assert_worker_stage_events(item: dict[str, Any], report_text: str) -> None:
    worker_stage_events = item.get("worker_stage_events") or []
    assert int(item.get("worker_stage_event_count") or 0) == len(worker_stage_events), item
    for event in worker_stage_events:
        assert isinstance(event, dict), item
        for key in ("event", "stage"):
            value = str(event.get(key) or "")
            if value:
                assert value in report_text, (event, report_text[:500])


def _assert_proof_quality_summary(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    report_text: str,
    *,
    planner_backed_min_steps: int | None,
) -> None:
    proof_quality_summary = summary.get("proof_quality_summary") or {}
    assert proof_quality_summary.get("schema") == "planner_proof_quality_summary_v1", summary
    assert "Planner Proof Quality" in report_text, report_text[:500]
    assert "Proof Quality" in report_text, report_text[:500]
    for item in results:
        if not item.get("run_result_exists"):
            continue
        quality = planner_proof_quality_evidence(item)
        assert quality.get("schema") == "planner_proof_quality_v1", item
        if planner_backed_min_steps is not None and item.get("planner_backed"):
            validate_planner_proof_quality_evidence(
                quality,
                min_steps_executed=planner_backed_min_steps,
            )


def _assert_report_view_src(view: dict[str, Any], base: Path, report_text: str) -> None:
    path_text = str(view.get("path") or "")
    assert path_text, view
    src = _report_asset_src(path_text, base)
    expected = f'src="{html.escape(src)}"'
    assert expected in report_text, (expected, report_text[:500])
    if _resolve_path(base, path_text).exists():
        assert _resolve_path(base, src).is_file(), src


def _report_asset_src(path_text: str, base: Path) -> str:
    if path_text.startswith(("http://", "https://", "data:")):
        return path_text
    candidate = Path(path_text)
    try:
        if candidate.is_absolute():
            asset_path = candidate
        elif candidate.exists():
            asset_path = candidate.resolve()
        elif (base / candidate).exists():
            asset_path = (base / candidate).resolve()
        else:
            return path_text
        return Path(os.path.relpath(asset_path, base.resolve())).as_posix()
    except OSError:
        return path_text


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    return base / path


def _has_blocker_code(item: dict[str, Any], code: str) -> bool:
    blockers = [*(item.get("blockers") or []), *(item.get("cleanup_binding_blockers") or [])]
    return any(
        isinstance(blocker, dict) and str(blocker.get("code") or "") == code for blocker in blockers
    )


def _positive_int(value: Any) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False
