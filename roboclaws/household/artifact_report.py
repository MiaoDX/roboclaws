from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object, read_jsonl_objects
from roboclaws.household.report import render_cleanup_report
from roboclaws.household.types import (
    CleanupObject,
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
)


def rerender_cleanup_report_from_run_result(run_result_path: Path) -> Path:
    """Render a cleanup report from an existing run_result artifact.

    This is the adapter for stale MolmoSpaces cleanup artifacts: callers provide
    the run_result path, and the adapter owns scenario, trace, snapshot, and
    private-manifest loading before delegating to the shared report underlay.
    """
    run_result_path = Path(run_result_path).resolve()
    run_dir = run_result_path.parent
    run_result = _read_json(run_result_path)
    artifacts = run_result.get("artifacts") or {}
    scenario_path = _resolve_artifact(
        run_dir,
        artifacts.get("scenario"),
        default_name="scenario.json",
        artifact_label="scenario",
        declared="scenario" in artifacts,
    )
    if scenario_path.is_file():
        scenario = load_cleanup_scenario_artifact(scenario_path)
    else:
        scenario = cleanup_scenario_shell_from_run_result(run_result)
    trace_events = load_trace_events(
        _resolve_artifact(
            run_dir,
            artifacts.get("trace"),
            default_name="trace.jsonl",
            artifact_label="trace",
            declared="trace" in artifacts,
        )
    )
    before_snapshot = _resolve_artifact(
        run_dir,
        artifacts.get("before_snapshot"),
        default_name="before.png",
        artifact_label="before_snapshot",
        declared="before_snapshot" in artifacts,
    )
    after_snapshot = _resolve_artifact(
        run_dir,
        artifacts.get("after_snapshot"),
        default_name="after.png",
        artifact_label="after_snapshot",
        declared="after_snapshot" in artifacts,
    )
    return render_cleanup_report(
        run_dir=run_dir,
        scenario=scenario,
        run_result=run_result,
        trace_events=trace_events,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        robot_view_steps=run_result.get("robot_view_steps") or [],
    )


def rerender_cleanup_report_from_artifact_path(path: Path) -> Path:
    """Regenerate a cleanup report from either a run directory or run_result path."""
    return rerender_cleanup_report_from_run_result(cleanup_run_result_path(path))


def rerender_cleanup_reports_from_run_results(run_result_paths: list[Path]) -> list[Path]:
    """Regenerate multiple cleanup reports through the same run-result adapter."""
    return [rerender_cleanup_report_from_run_result(path) for path in run_result_paths]


def rerender_cleanup_reports_from_artifact_paths(paths: list[Path]) -> list[Path]:
    """Regenerate multiple cleanup reports from run directories or run_result paths."""
    return [rerender_cleanup_report_from_artifact_path(path) for path in paths]


def cleanup_run_result_path(path: Path) -> Path:
    """Resolve a cleanup run directory or run_result path to `run_result.json`."""
    path = Path(path)
    if path.is_dir():
        return path / "run_result.json"
    return path


def is_cleanup_run_result_artifact(path: Path) -> bool:
    """Return whether a path points at a Molmo cleanup run-result artifact."""
    run_result_path = cleanup_run_result_path(path)
    if not run_result_path.is_file():
        return False
    try:
        run_result = _read_json(run_result_path)
    except (OSError, ValueError):
        return False
    return is_cleanup_run_result(run_result)


def is_cleanup_run_result(run_result: dict[str, Any]) -> bool:
    """Return whether a run_result payload has the cleanup report contract shape."""
    contract = str(run_result.get("contract") or "")
    return (
        isinstance(run_result.get("score"), dict)
        and isinstance(run_result.get("semantic_substeps"), list)
        and contract.startswith("realworld")
        and ("cleanup_status" in run_result or run_result.get("mcp_server") == "household_world")
    )


def cleanup_scenario_shell_from_run_result(run_result: dict[str, Any]) -> CleanupScenario:
    """Build the minimal public scenario needed to re-render an existing report.

    Some ADR-0003 cleanup artifacts predate the `scenario.json` artifact but
    still carry the public run identity, score, trace, snapshots, and robot
    timeline in `run_result.json`. Regeneration should keep those artifacts on
    the shared report underlay without fabricating objects or private targets.
    """
    scenario_id = str(run_result.get("scenario_id") or "unknown")
    return CleanupScenario(
        scenario_id=scenario_id,
        task=str(run_result.get("task_prompt") or ""),
        seed=_int_or_zero(run_result.get("seed")),
        objects=(),
        receptacles=(),
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=(),
            success_threshold=0,
        ),
    )


def load_cleanup_scenario_artifact(scenario_path: Path) -> CleanupScenario:
    """Load the public cleanup scenario plus adjacent private manifest if present."""
    scenario_path = Path(scenario_path)
    payload = _read_json(scenario_path)
    private_manifest_path = scenario_path.with_name("private_manifest.json")
    if private_manifest_path.is_file():
        private_manifest = PrivateScoringManifest.from_dict(_read_json(private_manifest_path))
    else:
        private_manifest = PrivateScoringManifest(
            scenario_id=str(payload["scenario_id"]),
            targets=(),
            success_threshold=0,
        )
    return CleanupScenario(
        scenario_id=str(payload["scenario_id"]),
        task=str(payload.get("task", "")),
        seed=int(payload.get("seed", 0)),
        objects=tuple(_cleanup_object_from_dict(item) for item in payload.get("objects", [])),
        receptacles=tuple(
            _cleanup_receptacle_from_dict(item) for item in payload.get("receptacles", [])
        ),
        private_manifest=private_manifest,
    )


def load_trace_events(trace_path: Path) -> list[dict[str, Any]]:
    return read_jsonl_objects(Path(trace_path), label="cleanup report trace")


def _cleanup_object_from_dict(data: dict[str, Any]) -> CleanupObject:
    return CleanupObject(
        object_id=str(data["object_id"]),
        name=str(data.get("name", data["object_id"])),
        category=str(data.get("category", "")),
        location_id=str(data.get("location_id", "")),
        pickupable=bool(data.get("pickupable", True)),
    )


def _cleanup_receptacle_from_dict(data: dict[str, Any]) -> CleanupReceptacle:
    return CleanupReceptacle(
        receptacle_id=str(data["receptacle_id"]),
        name=str(data.get("name", data["receptacle_id"])),
        room_area=str(data.get("room_area", "")),
        kind=str(data.get("kind", "receptacle")),
        category=str(data["category"]) if data.get("category") is not None else None,
    )


def _resolve_artifact(
    run_dir: Path,
    value: Any,
    *,
    default_name: str,
    artifact_label: str,
    declared: bool,
) -> Path:
    if not declared:
        return run_dir / default_name

    text = str(value or "").strip()
    if not text:
        raise ValueError(f"declared {artifact_label} artifact is empty")
    candidate = Path(text)
    if candidate.is_absolute():
        resolved = candidate
    else:
        resolved = run_dir / candidate
    if not resolved.is_file():
        raise FileNotFoundError(
            f"declared {artifact_label} artifact is missing or not a file: "
            f"{resolved} (from {text!r})"
        )
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    return read_json_object(Path(path), label="cleanup report artifact")


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
