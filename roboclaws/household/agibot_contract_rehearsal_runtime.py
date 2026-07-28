from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any

from roboclaws.household.household_runtime_contract import REALWORLD_CONTRACT
from roboclaws.household.manipulation_provenance import BLOCKED_CAPABILITY_PROVENANCE
from roboclaws.household.profiles import MOLMOSPACES_SIM_BACKEND

EXECUTION_BACKEND = MOLMOSPACES_SIM_BACKEND
NAVIGATION_BACKEND = MOLMOSPACES_SIM_BACKEND
NAVIGATION_PROVENANCE = "agibot_shaped_molmospaces_sim_normal_navi"
OBSERVATION_PROVENANCE = "agibot_shaped_molmospaces_sim_policy_observation"
AGIBOT_MOLMOSPACES_SIM_BACKEND = "agibot_molmospaces_sim"
AGIBOT_SHAPED_SIM_BACKEND = AGIBOT_MOLMOSPACES_SIM_BACKEND


def simulated_observation(
    response: dict[str, Any],
    *,
    observation_image: Path,
    run_dir: Path,
    runtime: str,
    metric_map: dict[str, Any],
    waypoint_id: str,
) -> dict[str, Any]:
    detections = list(response.get("visible_object_detections") or [])
    waypoint = _waypoint_by_id(metric_map, waypoint_id) or {}
    room_id = str(response.get("room_id") or waypoint.get("room_id") or "")
    return {
        "ok": True,
        "tool": "observe",
        "status": "ok",
        "contract": REALWORLD_CONTRACT,
        "observation_id": f"molmospaces_sim_observe_{int(time.time_ns())}",
        "room_id": room_id,
        "waypoint_id": waypoint_id,
        "policy_observation_camera": "molmospaces_sim_policy_camera",
        "primitive_provenance": OBSERVATION_PROVENANCE,
        "execution_backend": EXECUTION_BACKEND,
        "simulated": True,
        "physical_robot": False,
        "runtime": runtime,
        "camera_artifact": relpath(observation_image, run_dir),
        "raw_fpv_observation": {
            "observation_id": "molmospaces_sim_policy_observation",
            "room_id": room_id,
            "waypoint_id": waypoint_id,
            "artifact_status": "simulated_policy_observation",
            "image_artifacts": {"fpv": relpath(observation_image, run_dir)},
            "camera_offset": {"yaw_delta_deg": 0, "pitch_delta_deg": 0},
        },
        "visible_object_detections": detections,
        "private_target_truth_included": False,
        "physical_cleanup_ready": False,
        "public_contract_note": (
            "Simulated policy observation from MolmoSpaces contract rehearsal. "
            "This is not an Agibot head_color camera capture."
        ),
    }


def simulated_navigation(
    response: dict[str, Any],
    *,
    metric_map: dict[str, Any],
    waypoint_id: str,
    runtime: str,
) -> dict[str, Any]:
    waypoint = _waypoint_by_id(metric_map, waypoint_id) or {}
    ok = bool(response.get("ok", True))
    return {
        "ok": ok,
        "tool": "navigate_to_waypoint",
        "status": "ok" if ok else "blocked_capability",
        "contract": REALWORLD_CONTRACT,
        "waypoint_id": waypoint_id,
        "navigation_backend": NAVIGATION_BACKEND,
        "execution_backend": EXECUTION_BACKEND,
        "primitive_provenance": NAVIGATION_PROVENANCE if ok else BLOCKED_CAPABILITY_PROVENANCE,
        "navigation_status": "succeeded" if ok else "blocked",
        "goal_source": "inspection_waypoint",
        "goal_pose": {
            "frame_id": waypoint.get("frame_id", metric_map.get("frame_id", "map")),
            "x": waypoint.get("x", 0.0),
            "y": waypoint.get("y", 0.0),
            "yaw": waypoint.get("yaw", 0.0),
        },
        "current_pose": {
            "frame_id": waypoint.get("frame_id", metric_map.get("frame_id", "map")),
            "x": waypoint.get("x", 0.0),
            "y": waypoint.get("y", 0.0),
            "yaw": waypoint.get("yaw", 0.0),
        },
        "pose_source": "molmospaces_sim_waypoint_arrival",
        "route_validation": response.get("route_validation", {"ok": ok}),
        "simulated": True,
        "physical_robot": False,
        "runtime": runtime,
        "physical_cleanup_ready": False,
        "manipulation_ready": False,
        "public_contract_note": (
            "Simulated waypoint navigation through the Agibot-shaped runner "
            "contract. This is not Pnc.normal_navi or physical arrival evidence."
        ),
    }


def blocked_manipulation(tool: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool,
        "status": "blocked_capability",
        "contract": REALWORLD_CONTRACT,
        "primitive_provenance": BLOCKED_CAPABILITY_PROVENANCE,
        "error_reason": "blocked_capability",
        "failure_type": "simulated_contract_rehearsal_manipulation_blocked",
        "backend_error_summary": (
            "MolmoSpaces Agibot Contract Rehearsal validates observe and waypoint "
            "navigation only; manipulation remains blocked."
        ),
        "execution_backend": EXECUTION_BACKEND,
        "simulated": True,
        "physical_robot": False,
        "physical_cleanup_ready": False,
        "manipulation_ready": False,
    }


def write_stage_artifact(
    *,
    run_dir: Path,
    stage_dir: Path,
    stage: str,
    status: str,
    ok: bool,
    tool_response: dict[str, Any],
    artifacts: dict[str, str],
    note: str,
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": "agibot_shaped_sim_stage_result_v1",
        "stage": stage,
        "status": status,
        "ok": ok,
        "contract": REALWORLD_CONTRACT,
        "backend": AGIBOT_SHAPED_SIM_BACKEND,
        "execution_backend": EXECUTION_BACKEND,
        "navigation_backend": NAVIGATION_BACKEND,
        "simulated": True,
        "physical_robot": False,
        "artifacts": artifacts,
        "tool_response": tool_response,
        "evidence_note": note,
        "gdk_imported_by_roboclaws": False,
    }
    write_json(stage_dir / "run_result.json", result)
    (stage_dir / "report.html").write_text(_stage_report_html(result), encoding="utf-8")
    return {
        "stage": stage,
        "status": status,
        "ok": ok,
        "report": relpath(stage_dir / "report.html", run_dir),
        "run_result": relpath(stage_dir / "run_result.json", run_dir),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def relpath(path: Path | str, root: Path) -> str:
    path = Path(path)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _waypoint_by_id(metric_map: dict[str, Any], waypoint_id: str) -> dict[str, Any] | None:
    for waypoint in metric_map.get("inspection_waypoints") or []:
        if str(waypoint.get("waypoint_id") or "") == waypoint_id:
            return waypoint
    return None


def _stage_report_html(result: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in (result.get("artifacts") or {}).items()
    )
    stage_title = html.escape(str(result.get("stage", "stage")).replace("_", " ").title())
    status = html.escape(str(result.get("status", "")))
    execution_backend = html.escape(str(result.get("execution_backend", "")))
    simulated = html.escape(str(result.get("simulated", "")))
    physical_robot = html.escape(str(result.get("physical_robot", "")))
    note = html.escape(str(result.get("evidence_note", "")))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(str(result.get("stage", "stage")))}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 32px; color: #172033; }}
    .metric {{
      display: inline-block;
      margin: 0 12px 12px 0;
      padding: 10px 12px;
      border: 1px solid #d8dee9;
      border-radius: 6px;
    }}
    .metric span {{ display: block; color: #61708a; font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d8dee9; padding: 8px; text-align: left; }}
  </style>
</head>
<body>
  <p>MolmoSpaces Agibot Contract Rehearsal</p>
  <h1>{stage_title}</h1>
  <div class="metric"><span>Status</span><strong>{status}</strong></div>
  <div class="metric"><span>Execution backend</span><strong>{execution_backend}</strong></div>
  <div class="metric"><span>Simulated</span><strong>{simulated}</strong></div>
  <div class="metric"><span>Physical robot</span><strong>{physical_robot}</strong></div>
  <p>{note}</p>
  <table><thead><tr><th>Artifact</th><th>Path</th></tr></thead><tbody>{rows}</tbody></table>
</body>
</html>
"""
