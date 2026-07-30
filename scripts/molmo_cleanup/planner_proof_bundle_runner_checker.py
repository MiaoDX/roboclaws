from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA,
    PLANNER_PROOF_EXECUTION_HORIZON_SCHEMA,
)
from scripts.molmo_cleanup.planner_proof_bundle_result_checker import (
    assert_prior_proof_result_summary,
    assert_proof_result_summary,
)
from scripts.molmo_cleanup.planner_proof_bundle_selection_checker import (
    assert_proof_request_selection,
    assert_selection_requirements,
    generated_fallback_request_count,
)


def assert_runner_result(
    data: dict[str, Any],
    base: Path,
    *,
    require_proof_outputs: bool = False,
    require_cleanup_rerun_output: bool = False,
    min_selected_requests: int | None = None,
    max_selected_requests: int | None = None,
    require_prior_covered_exclusion: bool = False,
    require_proof_execution_horizon: bool = False,
    require_proof_quality: bool = False,
    planner_backed_proof_min_steps: int | None = None,
) -> None:
    commands, report_text = _assert_runner_manifest_core(data, base)
    _assert_optional_proof_execution_horizon(
        data,
        report_text,
        require_proof_execution_horizon=require_proof_execution_horizon,
    )
    _assert_optional_local_runtime_preflight(data, report_text)
    _assert_optional_warmup(
        data,
        base,
        report_text,
        require_proof_outputs=require_proof_outputs,
    )
    generated_count = _assert_optional_proof_request_selection(
        data,
        commands,
        report_text,
        min_selected_requests=min_selected_requests,
        max_selected_requests=max_selected_requests,
        require_prior_covered_exclusion=require_prior_covered_exclusion,
    )
    assert int(data.get("ready_request_count") or 0) + generated_count >= len(commands), data
    _assert_optional_grasp_preflights(data, report_text)
    _assert_optional_proof_summaries(
        data,
        commands,
        base,
        report_text,
        require_proof_outputs=require_proof_outputs,
        require_proof_quality=require_proof_quality,
        planner_backed_proof_min_steps=planner_backed_proof_min_steps,
    )
    _assert_probe_commands(
        commands,
        base,
        report_text,
        require_proof_outputs=require_proof_outputs,
    )
    _assert_cleanup_command(data, report_text)
    _assert_optional_cleanup_rerun(
        data,
        base,
        report_text,
        require_cleanup_rerun_output=require_cleanup_rerun_output,
    )
    if data.get("status") == "local_runtime_blocked":
        preflight = data.get("local_runtime_preflight") or {}
        assert preflight.get("status") == "blocked", preflight


def _assert_runner_manifest_core(
    data: dict[str, Any],
    base: Path,
) -> tuple[list[dict[str, Any]], str]:
    assert data.get("schema") == PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA, data
    assert data.get("status") in {
        "dry_run",
        "probes_executed",
        "cleanup_rerun",
        "local_runtime_blocked",
    }, data
    assert int(data.get("proof_request_count") or 0) >= int(data.get("ready_request_count") or 0), (
        data
    )
    commands = data.get("commands") or []
    assert data.get("command_count") == len(commands), data
    assert data.get("cleanup_run_result"), data
    report = _resolve_path(base, str(data.get("report") or "report.html"))
    assert report.is_file(), report
    report_text = report.read_text(encoding="utf-8")
    _assert_runner_report(report_text)
    return commands, report_text


def _assert_optional_proof_execution_horizon(
    data: dict[str, Any],
    report_text: str,
    *,
    require_proof_execution_horizon: bool,
) -> None:
    horizon = data.get("proof_execution_horizon") or {}
    if horizon:
        _assert_proof_execution_horizon(horizon, report_text)
    elif require_proof_execution_horizon:
        raise AssertionError("proof_execution_horizon is required")


def _assert_optional_local_runtime_preflight(
    data: dict[str, Any],
    report_text: str,
) -> None:
    preflight = data.get("local_runtime_preflight") or {}
    if preflight:
        _assert_local_runtime_preflight(preflight, report_text)


def _assert_optional_warmup(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_proof_outputs: bool,
) -> None:
    warmup = data.get("warmup") or {}
    if warmup:
        _assert_warmup(
            warmup,
            base,
            report_text,
            require_outputs=require_proof_outputs,
        )


def _assert_optional_proof_request_selection(
    data: dict[str, Any],
    commands: list[dict[str, Any]],
    report_text: str,
    *,
    min_selected_requests: int | None,
    max_selected_requests: int | None,
    require_prior_covered_exclusion: bool,
) -> int:
    selection = data.get("proof_request_selection") or {}
    if not selection:
        assert not require_prior_covered_exclusion, data
        assert min_selected_requests in {None, 0}, data
        return 0
    assert_proof_request_selection(selection, commands, report_text)
    assert_selection_requirements(
        selection,
        report_text,
        min_selected_requests=min_selected_requests,
        max_selected_requests=max_selected_requests,
        require_prior_covered_exclusion=require_prior_covered_exclusion,
    )
    return generated_fallback_request_count(selection)


def _assert_optional_grasp_preflights(data: dict[str, Any], report_text: str) -> None:
    decision = data.get("grasp_feasibility_mitigation_decision") or {}
    if decision:
        _assert_grasp_mitigation_decision(decision, report_text)
    availability_preflight = data.get("grasp_cache_availability_preflight") or {}
    if availability_preflight:
        _assert_grasp_cache_availability_preflight(availability_preflight, report_text)
    generation_preflight = data.get("grasp_cache_generation_preflight") or {}
    if generation_preflight:
        _assert_grasp_cache_generation_preflight(generation_preflight, report_text)


def _assert_optional_proof_summaries(
    data: dict[str, Any],
    commands: list[dict[str, Any]],
    base: Path,
    report_text: str,
    *,
    require_proof_outputs: bool,
    require_proof_quality: bool,
    planner_backed_proof_min_steps: int | None,
) -> None:
    prior_summary = data.get("prior_proof_result_summary") or {}
    if prior_summary:
        assert_prior_proof_result_summary(prior_summary, base, report_text)
    proof_summary = data.get("proof_result_summary") or {}
    if proof_summary:
        assert_proof_result_summary(
            proof_summary,
            commands,
            base,
            report_text,
            require_outputs=require_proof_outputs,
            require_quality=require_proof_quality,
            planner_backed_min_steps=planner_backed_proof_min_steps,
        )
    elif require_proof_outputs:
        raise AssertionError("proof_result_summary is required with --require-proof-outputs")


def _assert_probe_commands(
    commands: list[dict[str, Any]],
    base: Path,
    report_text: str,
    *,
    require_proof_outputs: bool,
) -> None:
    for item in commands:
        _assert_command(item, base, report_text, require_proof_outputs=require_proof_outputs)


def _assert_cleanup_command(data: dict[str, Any], report_text: str) -> None:
    cleanup_command = data.get("cleanup_command") or []
    if not cleanup_command:
        return
    command_text = " ".join(str(part) for part in cleanup_command)
    assert command_text in report_text, command_text


def _assert_optional_cleanup_rerun(
    data: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_cleanup_rerun_output: bool,
) -> None:
    cleanup_rerun = data.get("cleanup_rerun") or {}
    requires_rerun = (
        data.get("status") == "cleanup_rerun" or cleanup_rerun or require_cleanup_rerun_output
    )
    if not requires_rerun:
        return
    _assert_cleanup_rerun(
        cleanup_rerun,
        base,
        report_text,
        require_outputs=require_cleanup_rerun_output or data.get("status") == "cleanup_rerun",
    )


def _assert_runner_report(report_text: str) -> None:
    for heading in (
        "Planner Proof Bundle Runner",
        "Source Cleanup Artifact",
        "Proof Probe Commands",
        "Cleanup Rerun Command",
    ):
        assert heading in report_text, (heading, report_text[:500])


def _assert_proof_execution_horizon(horizon: dict[str, Any], report_text: str) -> None:
    assert horizon.get("schema") == PLANNER_PROOF_EXECUTION_HORIZON_SCHEMA, horizon
    assert horizon.get("status") in {"aligned", "command_steps_below_coverage_horizon"}, horizon
    assert int(horizon.get("command_steps") or 0) >= 0, horizon
    assert int(horizon.get("prior_covered_min_proof_steps") or 0) >= 1, horizon
    assert str(horizon.get("command_quality_target") or "") in {
        "unknown",
        "one_step_motion",
        "multi_step_motion",
    }, horizon
    assert str(horizon.get("prior_covered_quality_floor") or "") in {
        "one_step_motion",
        "multi_step_motion",
    }, horizon
    assert "Proof Execution Horizon" in report_text, report_text[:500]
    for value in (
        horizon.get("status"),
        horizon.get("command_quality_target"),
        horizon.get("prior_covered_quality_floor"),
    ):
        _assert_report_contains(str(value), report_text)
    for blocker in horizon.get("blockers") or []:
        if not isinstance(blocker, dict):
            continue
        _assert_report_contains(str(blocker.get("code") or ""), report_text)
        _assert_report_contains(str(blocker.get("message") or ""), report_text)


def _assert_local_runtime_preflight(preflight: dict[str, Any], report_text: str) -> None:
    assert preflight.get("schema") == "planner_proof_bundle_local_runtime_preflight_v1", preflight
    assert preflight.get("status") in {"ready", "blocked", "not_checked"}, preflight
    assert "Local Runtime Preflight" in report_text, report_text[:500]
    assert str(preflight.get("status") or "") in report_text, report_text[:500]
    _assert_report_contains_if_present(preflight.get("python_executable"), report_text)
    for check in preflight.get("checks") or []:
        assert isinstance(check, dict), preflight
        _assert_report_values_for_keys(check, ("name", "status"), report_text)
        command = " ".join(str(part) for part in check.get("command") or [])
        _assert_report_contains_if_present(command, report_text)
    for blocker in preflight.get("blockers") or []:
        assert isinstance(blocker, dict), preflight
        _assert_report_values_for_keys(blocker, ("code", "message"), report_text)


def _assert_report_contains(value: str, report_text: str, context: Any = "") -> None:
    assert value in report_text or html.escape(value) in report_text, (
        context or value,
        report_text[:500],
    )


def _assert_report_contains_if_present(value: Any, report_text: str, context: Any = "") -> None:
    text = str(value or "")
    if text:
        _assert_report_contains(text, report_text, context or text)


def _assert_report_values_for_keys(
    payload: dict[str, Any],
    keys: tuple[str, ...],
    report_text: str,
) -> None:
    for key in keys:
        _assert_report_contains_if_present(payload.get(key), report_text, key)


def _assert_warmup(
    warmup: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_outputs: bool,
) -> None:
    for key in ("output_dir", "run_result", "report", "command"):
        assert warmup.get(key), warmup
    command = warmup.get("command") or []
    assert isinstance(command, list) and command, warmup
    assert "--output-dir" in command, command
    assert "--probe-mode" in command, command
    assert "config_import" in command, command
    assert "--torch-extensions-dir" in command, command
    command_text = " ".join(str(part) for part in command)
    assert "RBY1M/CuRobo Warmup" in report_text, report_text[:500]
    assert command_text in report_text, command_text
    for key in ("output_dir", "run_result", "report"):
        assert str(warmup[key]) in report_text, (key, report_text[:500])
    if require_outputs:
        run_result = _resolve_path(base, str(warmup["run_result"]))
        proof_report = _resolve_path(base, str(warmup["report"]))
        assert run_result.is_file(), run_result
        assert proof_report.is_file(), proof_report


def _assert_command(
    item: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_proof_outputs: bool,
) -> None:
    for key in (
        "request_id",
        "object_id",
        "target_receptacle_id",
        "output_dir",
        "run_result",
        "report",
    ):
        assert item.get(key), item
    command = item.get("command") or []
    assert isinstance(command, list) and command, item
    command_text = " ".join(str(part) for part in command)
    assert "--output-dir" in command, command
    assert "--cleanup-object-id" in command, command
    _assert_semantic_subphases(item, report_text)
    for value in (
        item["request_id"],
        item["object_id"],
        item["target_receptacle_id"],
        item["run_result"],
        item["report"],
    ):
        assert str(value) in report_text, (value, report_text[:500])
    assert command_text in report_text, command_text
    if require_proof_outputs:
        run_result = _resolve_path(base, str(item["run_result"]))
        proof_report = _resolve_path(base, str(item["report"]))
        assert run_result.is_file(), run_result
        assert proof_report.is_file(), proof_report


def _assert_semantic_subphases(item: dict[str, Any], report_text: str) -> None:
    semantic_subphases = item.get("semantic_subphases") or []
    if not semantic_subphases:
        return
    assert "Semantic subphases" in report_text, report_text[:500]
    for subphase in semantic_subphases:
        if not isinstance(subphase, dict):
            continue
        _assert_report_values_for_keys(subphase, ("phase", "label", "detail"), report_text)


def _assert_grasp_mitigation_decision(
    decision: dict[str, Any],
    report_text: str,
) -> None:
    assert decision.get("schema") == "planner_grasp_feasibility_mitigation_decision_v1", decision
    assert decision.get("status") in {"not_applicable", "action_required"}, decision
    assert decision.get("primary_route"), decision
    assert decision.get("recommendation"), decision
    assert "Grasp Feasibility Mitigation Decision" in report_text, report_text[:500]
    _assert_report_contains_for_values(
        [
            decision.get("status"),
            decision.get("primary_route"),
            decision.get("recommendation"),
            decision.get("source_rotation_state"),
            *(decision.get("missing_grasp_asset_uids") or []),
            *(decision.get("grasp_load_exception_types") or []),
        ],
        report_text,
        context=decision,
    )
    for item in decision.get("signature_groups") or []:
        assert isinstance(item, dict), decision
        _assert_report_contains_for_values(
            [
                item.get("source"),
                item.get("subkind"),
                item.get("summary"),
                *(item.get("request_ids") or []),
                *(item.get("object_names") or []),
                *(item.get("grasp_load_exception_asset_uids") or []),
            ],
            report_text,
            context=item,
        )


def _assert_report_contains_for_values(
    values: list[Any],
    report_text: str,
    *,
    context: Any,
) -> None:
    for value in values:
        if value:
            _assert_report_contains(str(value), report_text, context)


def _assert_grasp_cache_availability_preflight(
    preflight: dict[str, Any],
    report_text: str,
) -> None:
    assert preflight.get("schema") == "planner_grasp_cache_availability_preflight_v1", preflight
    assert preflight.get("status") in {"ready", "missing_cache", "not_applicable"}, preflight
    assert "Grasp Cache Availability Preflight" in report_text, report_text[:500]
    _assert_availability_preflight_values(preflight, report_text)
    assets = preflight.get("assets") or []
    _assert_availability_asset_counts(preflight, assets)
    for asset in assets:
        _assert_grasp_cache_asset(asset, report_text, context=preflight)


def _assert_availability_preflight_values(preflight: dict[str, Any], report_text: str) -> None:
    _assert_report_contains_for_values(
        [
            preflight.get("status"),
            preflight.get("assets_dir"),
            preflight.get("assets_dir_resolved"),
            preflight.get("assets_dir_source"),
            preflight.get("upstream_loader"),
            preflight.get("mitigation_recommendation"),
            *(preflight.get("missing_grasp_asset_uids") or []),
            *(preflight.get("cache_ready_asset_uids") or []),
            *(preflight.get("cache_missing_asset_uids") or []),
        ],
        report_text,
        context=preflight,
    )


def _assert_availability_asset_counts(
    preflight: dict[str, Any],
    assets: list[dict[str, Any]],
) -> None:
    assert int(preflight.get("asset_count") or 0) == len(assets), preflight
    ready_count = sum(1 for item in assets if str(item.get("status") or "") == "ready")
    missing_count = sum(1 for item in assets if str(item.get("status") or "") == "missing_cache")
    assert int(preflight.get("ready_asset_count") or 0) == ready_count, preflight
    assert int(preflight.get("missing_cache_asset_count") or 0) == missing_count, preflight


def _assert_grasp_cache_asset(
    asset: dict[str, Any],
    report_text: str,
    *,
    context: Any,
) -> None:
    assert isinstance(asset, dict), context
    assert asset.get("status") in {"ready", "missing_cache"}, asset
    _assert_report_contains_for_values(
        [
            asset.get("asset_uid"),
            asset.get("status"),
            asset.get("loader_file_status"),
            asset.get("object_asset_status"),
        ],
        report_text,
        context=asset,
    )
    candidate_files = asset.get("candidate_grasp_files") or []
    assert len(candidate_files) == 3, asset
    for probe in [*candidate_files, *(asset.get("folder_probe_files") or [])]:
        _assert_grasp_cache_probe(probe, report_text, context=asset)
    for object_file in asset.get("object_asset_files") or []:
        assert isinstance(object_file, dict), asset
        _assert_report_values_for_keys(
            object_file, ("kind", "relative_path", "resolved_path"), report_text
        )


def _assert_grasp_cache_probe(
    probe: dict[str, Any],
    report_text: str,
    *,
    context: Any,
) -> None:
    assert isinstance(probe, dict), context
    _assert_report_values_for_keys(
        probe,
        (
            "source",
            "loader_role",
            "relative_path",
            "resolved_path",
            "validation_status",
            "transform_count",
        ),
        report_text,
    )


def _assert_grasp_cache_generation_preflight(
    preflight: dict[str, Any],
    report_text: str,
) -> None:
    assert preflight.get("schema") == "planner_grasp_cache_generation_preflight_v1", preflight
    assert preflight.get("status") in {"ready", "blocked", "not_applicable"}, preflight
    if preflight.get("status") == "not_applicable":
        return
    assert "Grasp Cache Generation Preflight" in report_text, report_text[:500]
    _assert_generation_preflight_values(preflight, report_text)
    assets = preflight.get("assets") or []
    assert int(preflight.get("asset_count") or 0) == len(assets), preflight
    for asset in assets:
        _assert_generation_asset(asset, report_text, context=preflight)
    _assert_generation_checks(preflight, report_text)
    _assert_generation_blockers(preflight, report_text)


def _assert_generation_preflight_values(preflight: dict[str, Any], report_text: str) -> None:
    _assert_report_contains_for_values(
        [
            preflight.get("status"),
            preflight.get("molmospaces_python"),
            preflight.get("molmospaces_root"),
            preflight.get("assets_dir"),
            preflight.get("objects_list_path"),
            preflight.get("working_dir"),
            preflight.get("mitigation_recommendation"),
        ],
        report_text,
        context=preflight,
    )


def _assert_generation_asset(
    asset: dict[str, Any],
    report_text: str,
    *,
    context: Any,
) -> None:
    assert isinstance(asset, dict), context
    _assert_report_values_for_keys(
        asset,
        (
            "asset_uid",
            "object_xml",
            "generated_npz_path",
            "cache_target_resolved_path",
        ),
        report_text,
    )


def _assert_generation_checks(preflight: dict[str, Any], report_text: str) -> None:
    for check in preflight.get("checks") or []:
        assert isinstance(check, dict), preflight
        _assert_report_values_for_keys(check, ("name", "status", "code", "message"), report_text)
        path_value = str(check.get("path") or check.get("resolved_path") or "")
        _assert_report_contains_if_present(path_value, report_text, check)


def _assert_generation_blockers(preflight: dict[str, Any], report_text: str) -> None:
    blockers = preflight.get("blockers") or []
    assert int(preflight.get("blocker_count") or 0) == len(blockers), preflight
    if preflight.get("status") == "blocked":
        assert blockers, preflight
    for blocker in blockers:
        assert isinstance(blocker, dict), preflight
        _assert_report_values_for_keys(blocker, ("code", "name", "message"), report_text)


def _assert_cleanup_rerun(
    cleanup_rerun: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_outputs: bool,
) -> None:
    for key in ("output_dir", "run_result", "report"):
        assert cleanup_rerun.get(key), cleanup_rerun
        assert str(cleanup_rerun[key]) in report_text, (key, report_text[:500])
    assert "Cleanup Rerun Artifact" in report_text, report_text[:500]
    if require_outputs:
        output_dir = _resolve_path(base, str(cleanup_rerun["output_dir"]))
        run_result = _resolve_path(base, str(cleanup_rerun["run_result"]))
        report = _resolve_path(base, str(cleanup_rerun["report"]))
        assert output_dir.is_dir(), output_dir
        assert run_result.is_file(), run_result
        assert report.is_file(), report


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    return base / path
