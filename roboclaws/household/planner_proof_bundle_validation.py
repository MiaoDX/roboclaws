from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.planner_proof_contracts import (
    PLANNER_PROOF_BUNDLE_RUN_MANIFEST_SCHEMA,
    PLANNER_PROOF_EXECUTION_HORIZON_SCHEMA,
)
from roboclaws.household.planner_proof_result_validation import (
    assert_prior_proof_result_summary,
    assert_proof_result_summary,
)
from roboclaws.household.planner_proof_selection_validation import (
    assert_proof_request_selection,
    assert_selection_requirements,
    generated_fallback_request_count,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate planner proof bundle runner artifacts.")
    parser.add_argument("path", type=Path, help="proof_bundle_run_manifest.json or output dir")
    parser.add_argument("--require-proof-outputs", action="store_true")
    parser.add_argument("--require-cleanup-rerun-output", action="store_true")
    parser.add_argument("--min-selected-requests", type=int)
    parser.add_argument("--max-selected-requests", type=int)
    parser.add_argument("--require-prior-covered-exclusion", action="store_true")
    parser.add_argument("--require-proof-execution-horizon", action="store_true")
    parser.add_argument("--require-proof-quality", action="store_true")
    parser.add_argument("--require-planner-backed-proof-min-steps", type=int, default=None)
    return parser.parse_args(argv)


def validate_bundle_path(
    path: Path,
    *,
    require_proof_outputs: bool = False,
    require_cleanup_rerun_output: bool = False,
    min_selected_requests: int | None = None,
    max_selected_requests: int | None = None,
    require_prior_covered_exclusion: bool = False,
    require_proof_execution_horizon: bool = False,
    require_proof_quality: bool = False,
    planner_backed_proof_min_steps: int | None = None,
) -> Path:
    manifest_path = path / "proof_bundle_run_manifest.json" if path.is_dir() else path
    data = read_json_object(manifest_path, label="planner proof bundle runner manifest")
    assert_runner_result(
        data,
        manifest_path.parent,
        require_proof_outputs=require_proof_outputs,
        require_cleanup_rerun_output=require_cleanup_rerun_output,
        min_selected_requests=min_selected_requests,
        max_selected_requests=max_selected_requests,
        require_prior_covered_exclusion=require_prior_covered_exclusion,
        require_proof_execution_horizon=require_proof_execution_horizon,
        require_proof_quality=require_proof_quality,
        planner_backed_proof_min_steps=planner_backed_proof_min_steps,
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = validate_bundle_path(
        args.path,
        require_proof_outputs=args.require_proof_outputs,
        require_cleanup_rerun_output=args.require_cleanup_rerun_output,
        min_selected_requests=args.min_selected_requests,
        max_selected_requests=args.max_selected_requests,
        require_prior_covered_exclusion=args.require_prior_covered_exclusion,
        require_proof_execution_horizon=args.require_proof_execution_horizon,
        require_proof_quality=args.require_proof_quality,
        planner_backed_proof_min_steps=args.require_planner_backed_proof_min_steps,
    )
    print(f"planner-proof-bundle ok: {manifest_path}")
    return 0


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
    commands = _assert_runner_manifest_core(data, base)
    _assert_optional_proof_execution_horizon(
        data,
        require_proof_execution_horizon=require_proof_execution_horizon,
    )
    _assert_optional_local_runtime_preflight(data)
    _assert_optional_warmup(
        data,
        base,
        require_proof_outputs=require_proof_outputs,
    )
    generated_count = _assert_optional_proof_request_selection(
        data,
        commands,
        min_selected_requests=min_selected_requests,
        max_selected_requests=max_selected_requests,
        require_prior_covered_exclusion=require_prior_covered_exclusion,
    )
    assert int(data.get("ready_request_count") or 0) + generated_count >= len(commands), data
    _assert_optional_grasp_preflights(data)
    _assert_optional_proof_summaries(
        data,
        commands,
        base,
        require_proof_outputs=require_proof_outputs,
        require_proof_quality=require_proof_quality,
        planner_backed_proof_min_steps=planner_backed_proof_min_steps,
    )
    _assert_probe_commands(
        commands,
        base,
        require_proof_outputs=require_proof_outputs,
    )
    _assert_optional_cleanup_rerun(
        data,
        base,
        require_cleanup_rerun_output=require_cleanup_rerun_output,
    )
    if data.get("status") == "local_runtime_blocked":
        preflight = data.get("local_runtime_preflight") or {}
        assert preflight.get("status") == "blocked", preflight


def _assert_runner_manifest_core(
    data: dict[str, Any],
    base: Path,
) -> list[dict[str, Any]]:
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
    return commands


def _assert_optional_proof_execution_horizon(
    data: dict[str, Any],
    *,
    require_proof_execution_horizon: bool,
) -> None:
    horizon = data.get("proof_execution_horizon") or {}
    if horizon:
        _assert_proof_execution_horizon(horizon)
    elif require_proof_execution_horizon:
        raise AssertionError("proof_execution_horizon is required")


def _assert_optional_local_runtime_preflight(data: dict[str, Any]) -> None:
    preflight = data.get("local_runtime_preflight") or {}
    if preflight:
        _assert_local_runtime_preflight(preflight)


def _assert_optional_warmup(
    data: dict[str, Any],
    base: Path,
    *,
    require_proof_outputs: bool,
) -> None:
    warmup = data.get("warmup") or {}
    if warmup:
        _assert_warmup(
            warmup,
            base,
            require_outputs=require_proof_outputs,
        )


def _assert_optional_proof_request_selection(
    data: dict[str, Any],
    commands: list[dict[str, Any]],
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
    assert_proof_request_selection(selection, commands)
    assert_selection_requirements(
        selection,
        min_selected_requests=min_selected_requests,
        max_selected_requests=max_selected_requests,
        require_prior_covered_exclusion=require_prior_covered_exclusion,
    )
    return generated_fallback_request_count(selection)


def _assert_optional_grasp_preflights(data: dict[str, Any]) -> None:
    decision = data.get("grasp_feasibility_mitigation_decision") or {}
    if decision:
        _assert_grasp_mitigation_decision(decision)
    availability_preflight = data.get("grasp_cache_availability_preflight") or {}
    if availability_preflight:
        _assert_grasp_cache_availability_preflight(availability_preflight)
    generation_preflight = data.get("grasp_cache_generation_preflight") or {}
    if generation_preflight:
        _assert_grasp_cache_generation_preflight(generation_preflight)


def _assert_optional_proof_summaries(
    data: dict[str, Any],
    commands: list[dict[str, Any]],
    base: Path,
    *,
    require_proof_outputs: bool,
    require_proof_quality: bool,
    planner_backed_proof_min_steps: int | None,
) -> None:
    prior_summary = data.get("prior_proof_result_summary") or {}
    if prior_summary:
        assert_prior_proof_result_summary(prior_summary, base)
    proof_summary = data.get("proof_result_summary") or {}
    if proof_summary:
        assert_proof_result_summary(
            proof_summary,
            commands,
            base,
            require_outputs=require_proof_outputs,
            require_quality=require_proof_quality,
            planner_backed_min_steps=planner_backed_proof_min_steps,
        )
    elif require_proof_outputs:
        raise AssertionError("proof_result_summary is required with --require-proof-outputs")


def _assert_probe_commands(
    commands: list[dict[str, Any]],
    base: Path,
    *,
    require_proof_outputs: bool,
) -> None:
    for item in commands:
        _assert_command(item, base, require_proof_outputs=require_proof_outputs)


def _assert_optional_cleanup_rerun(
    data: dict[str, Any],
    base: Path,
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
        require_outputs=require_cleanup_rerun_output or data.get("status") == "cleanup_rerun",
    )


def _assert_runner_report(report_text: str) -> None:
    assert report_text.strip(), "planner proof bundle report is empty"
    marker = "Planner Proof Bundle Runner"
    assert marker in report_text, (marker, report_text[:500])


def _assert_proof_execution_horizon(horizon: dict[str, Any]) -> None:
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
    for blocker in horizon.get("blockers") or []:
        assert isinstance(blocker, dict), horizon


def _assert_local_runtime_preflight(preflight: dict[str, Any]) -> None:
    assert preflight.get("schema") == "planner_proof_bundle_local_runtime_preflight_v1", preflight
    assert preflight.get("status") in {"ready", "blocked", "not_checked"}, preflight
    for check in preflight.get("checks") or []:
        assert isinstance(check, dict), preflight
    for blocker in preflight.get("blockers") or []:
        assert isinstance(blocker, dict), preflight


def _assert_warmup(
    warmup: dict[str, Any],
    base: Path,
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
    if require_outputs:
        run_result = _resolve_path(base, str(warmup["run_result"]))
        proof_report = _resolve_path(base, str(warmup["report"]))
        assert run_result.is_file(), run_result
        assert proof_report.is_file(), proof_report


def _assert_command(
    item: dict[str, Any],
    base: Path,
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
    assert "--output-dir" in command, command
    assert "--cleanup-object-id" in command, command
    if require_proof_outputs:
        run_result = _resolve_path(base, str(item["run_result"]))
        proof_report = _resolve_path(base, str(item["report"]))
        assert run_result.is_file(), run_result
        assert proof_report.is_file(), proof_report


def _assert_grasp_mitigation_decision(decision: dict[str, Any]) -> None:
    assert decision.get("schema") == "planner_grasp_feasibility_mitigation_decision_v1", decision
    assert decision.get("status") in {"not_applicable", "action_required"}, decision
    assert decision.get("primary_route"), decision
    assert decision.get("recommendation"), decision
    for item in decision.get("signature_groups") or []:
        assert isinstance(item, dict), decision


def _assert_grasp_cache_availability_preflight(preflight: dict[str, Any]) -> None:
    assert preflight.get("schema") == "planner_grasp_cache_availability_preflight_v1", preflight
    assert preflight.get("status") in {"ready", "missing_cache", "not_applicable"}, preflight
    assets = preflight.get("assets") or []
    _assert_availability_asset_counts(preflight, assets)
    for asset in assets:
        _assert_grasp_cache_asset(asset, context=preflight)


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
    *,
    context: Any,
) -> None:
    assert isinstance(asset, dict), context
    assert asset.get("status") in {"ready", "missing_cache"}, asset
    candidate_files = asset.get("candidate_grasp_files") or []
    assert len(candidate_files) == 3, asset
    for probe in [*candidate_files, *(asset.get("folder_probe_files") or [])]:
        _assert_grasp_cache_probe(probe, context=asset)
    for object_file in asset.get("object_asset_files") or []:
        assert isinstance(object_file, dict), asset


def _assert_grasp_cache_probe(
    probe: dict[str, Any],
    *,
    context: Any,
) -> None:
    assert isinstance(probe, dict), context


def _assert_grasp_cache_generation_preflight(preflight: dict[str, Any]) -> None:
    assert preflight.get("schema") == "planner_grasp_cache_generation_preflight_v1", preflight
    assert preflight.get("status") in {"ready", "blocked", "not_applicable"}, preflight
    if preflight.get("status") == "not_applicable":
        return
    assets = preflight.get("assets") or []
    assert int(preflight.get("asset_count") or 0) == len(assets), preflight
    for asset in assets:
        _assert_generation_asset(asset, context=preflight)
    _assert_generation_checks(preflight)
    _assert_generation_blockers(preflight)


def _assert_generation_asset(
    asset: dict[str, Any],
    *,
    context: Any,
) -> None:
    assert isinstance(asset, dict), context


def _assert_generation_checks(preflight: dict[str, Any]) -> None:
    for check in preflight.get("checks") or []:
        assert isinstance(check, dict), preflight


def _assert_generation_blockers(preflight: dict[str, Any]) -> None:
    blockers = preflight.get("blockers") or []
    assert int(preflight.get("blocker_count") or 0) == len(blockers), preflight
    if preflight.get("status") == "blocked":
        assert blockers, preflight
    for blocker in blockers:
        assert isinstance(blocker, dict), preflight


def _assert_cleanup_rerun(
    cleanup_rerun: dict[str, Any],
    base: Path,
    *,
    require_outputs: bool,
) -> None:
    for key in ("output_dir", "run_result", "report"):
        assert cleanup_rerun.get(key), cleanup_rerun
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


if __name__ == "__main__":
    raise SystemExit(main())
