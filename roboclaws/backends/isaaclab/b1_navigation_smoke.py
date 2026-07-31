#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from PIL import Image

from roboclaws.backends.isaaclab.b1_readiness_artifacts import build_readiness_artifact
from roboclaws.backends.isaaclab.b1_readiness_validation import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    NAVIGATION_PROVENANCE,
    NAVIGATION_SMOKE_SCHEMA,
    READINESS_SCHEMA,
    SEMANTIC_SOURCE,
    SEMANTIC_USD_BLOCKED,
    WAYPOINT_POSE_REQUESTS_SCHEMA,
    validate_navigation_smoke_artifact,
    validate_waypoint_pose_requests_artifact,
)
from roboclaws.backends.isaaclab.isaac_worker_cli import _positive_int_arg
from roboclaws.core.json_sources import read_json_object  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local Isaac B1 / Map 12 pose-driven navigation smoke."
    )
    subparsers = parser.add_subparsers(dest="command")
    capture_one = subparsers.add_parser("_capture-one")
    capture_one.add_argument("--request", type=Path, required=True)
    capture_one.add_argument("--output", type=Path, required=True)

    parser.add_argument("--b1-root", type=Path)
    parser.add_argument("--map12-root", type=Path)
    parser.add_argument("--readiness-artifact", type=Path)
    parser.add_argument(
        "--waypoint-pose-requests",
        type=Path,
        help=(
            "Optional b1_map12_waypoint_pose_requests_v1 artifact. When provided, "
            "navigation smoke captures those residual-backed on-demand poses instead of "
            "the first readiness candidate waypoints."
        ),
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--robot-name", default="rby1m")
    parser.add_argument("--render-width", type=_positive_int_arg, default=540)
    parser.add_argument("--render-height", type=_positive_int_arg, default=360)
    parser.add_argument(
        "--render-scene-usd",
        type=Path,
        default=DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
        help=(
            "Visual-route scene USD used for same-pose robot FPV/Chase/topdown captures. "
            "The B1 root remains the registration/readiness source."
        ),
    )
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "_capture-one":
        return capture_one(args)
    if args.output_dir is None:
        raise SystemExit("--output-dir is required")
    if args.accept_nvidia_eula:
        os.environ["OMNI_KIT_ACCEPT_EULA"] = "YES"
    return run_navigation_smoke(args)


def run_navigation_smoke(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = output_dir / "navigation_smoke.json"
    readiness = load_or_build_readiness(args)
    waypoints, request_blocker = navigation_smoke_waypoints(
        readiness=readiness,
        waypoint_pose_requests=args.waypoint_pose_requests,
    )
    if request_blocker:
        artifact = blocked_artifact(
            readiness=readiness,
            reason=request_blocker,
        )
        write_artifact(artifact_path, artifact)
        return 2
    if len(waypoints) < 2:
        artifact = blocked_artifact(
            readiness=readiness,
            reason=(
                "B1 / Map 12 navigation smoke requires at least two residual-backed "
                "waypoint poses before it can claim navigation support."
            ),
        )
        write_artifact(artifact_path, artifact)
        return 2

    from roboclaws.backends.isaaclab import runtime_state

    robot_import = runtime_state._rby1m_robot_import_plan(str(args.robot_name))
    if robot_import.get("status") != "imported":
        artifact = blocked_artifact(
            readiness=readiness,
            reason="RBY1M Isaac robot USD import artifact is not ready.",
            blockers=list(robot_import.get("blockers") or []),
            robot_import=robot_import,
        )
        write_artifact(artifact_path, artifact)
        return 2

    scene_usd = selected_render_scene_usd(args=args, readiness=readiness)
    if not scene_usd.is_file():
        artifact = blocked_artifact(
            readiness=readiness,
            reason=f"B1 scene USD is missing: {scene_usd}",
            robot_import=robot_import,
        )
        write_artifact(artifact_path, artifact)
        return 2

    waypoint_evidence = []
    child_failures: list[dict[str, Any]] = []
    for index, waypoint in enumerate(waypoints, start=1):
        request_path = output_dir / f"waypoint_{index:02d}_request.json"
        result_path = output_dir / f"waypoint_{index:02d}_result.json"
        request = {
            "scene_usd": str(scene_usd),
            "robot_import": robot_import,
            "waypoint": waypoint,
            "output_dir": str(output_dir / f"waypoint_{index:02d}_views"),
            "render_width": int(args.render_width),
            "render_height": int(args.render_height),
        }
        request_path.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "roboclaws.backends.isaaclab.b1_navigation_smoke",
                "_capture-one",
                "--request",
                str(request_path),
                "--output",
                str(result_path),
            ],
            cwd=Path(__file__).resolve().parents[3],
            check=False,
            capture_output=True,
            text=True,
        )
        (output_dir / f"waypoint_{index:02d}_stdout.log").write_text(
            completed.stdout,
            encoding="utf-8",
        )
        (output_dir / f"waypoint_{index:02d}_stderr.log").write_text(
            completed.stderr,
            encoding="utf-8",
        )
        if completed.returncode != 0 or not result_path.is_file():
            child_failures.append(
                {
                    "waypoint_id": waypoint.get("waypoint_id"),
                    "returncode": completed.returncode,
                    "stderr_tail": completed.stderr[-2000:],
                }
            )
            continue
        try:
            result = read_json_object(result_path, label="navigation smoke child result")
        except (FileNotFoundError, ValueError) as exc:
            child_failures.append(
                {
                    "waypoint_id": waypoint.get("waypoint_id"),
                    "returncode": completed.returncode,
                    "stderr_tail": completed.stderr[-2000:],
                    "source_error": str(exc),
                }
            )
            continue
        waypoint_evidence.append(result)

    provisional_passed = (
        navigation_smoke_has_distinct_pose_evidence(waypoint_evidence) and not child_failures
    )
    artifact = {
        "schema": NAVIGATION_SMOKE_SCHEMA,
        "status": "passed" if provisional_passed else "blocked",
        "readiness_schema": readiness.get("schema"),
        "b1_scene_usd": str(scene_usd),
        "visual_route": {
            "scene_id": "B1_floor2_slow"
            if scene_usd == DEFAULT_B1_VISUAL_ROUTE_SCENE_USD
            else scene_usd.stem,
            "scene_usd": str(scene_usd),
            "selected": scene_usd == DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
            "status": "same_pose_render_verified"
            if scene_usd == DEFAULT_B1_VISUAL_ROUTE_SCENE_USD
            else "custom_render_scene_verified",
        },
        "semantic_source": SEMANTIC_SOURCE,
        "semantic_usd_binding_status": SEMANTIC_USD_BLOCKED,
        "semantic_anchors_are_usd_truth": False,
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "manipulation_supported": False,
        "robot_navigation_supported": provisional_passed,
        "robot_navigation_provenance": NAVIGATION_PROVENANCE
        if provisional_passed
        else "blocked_local_isaac_b1_map12_navigation_smoke",
        "navigation_provenance": "kinematic_pose_driven" if provisional_passed else "blocked",
        "alignment_artifact": str(
            waypoints[0].get("alignment_artifact") or readiness.get("alignment_artifact") or ""
        ),
        "alignment_transform_source": str(
            waypoints[0].get("alignment_transform_source")
            or readiness.get("residual_evidence", {}).get("transform_source")
            or ""
        ),
        "planner_backed": False,
        "physical_robot": False,
        "navigation_waypoint_count": len(waypoint_evidence),
        "robot_view_evidence_status": "available" if provisional_passed else "blocked",
        "waypoint_evidence": waypoint_evidence,
        "child_failures": child_failures,
        "robot_import": robot_import,
    }
    validation_errors = validate_navigation_smoke_artifact(artifact, require_files=True)
    if validation_errors:
        artifact["status"] = "blocked"
        artifact["robot_navigation_supported"] = False
        artifact["robot_navigation_provenance"] = "blocked_local_isaac_b1_map12_navigation_smoke"
        artifact["navigation_provenance"] = "blocked"
        artifact["robot_view_evidence_status"] = "blocked"
    artifact["validation"] = {
        "status": "passed" if not validation_errors else "failed",
        "errors": validation_errors,
    }
    write_artifact(artifact_path, artifact)
    return 0 if artifact["validation"]["status"] == "passed" else 2


def capture_one(args: argparse.Namespace) -> int:
    request = read_json_object(args.request, label="navigation smoke capture request")
    from roboclaws.backends.isaaclab import runtime_capture

    waypoint = request["waypoint"]
    b1_pose = dict(waypoint["b1_pose"])
    b1_pose.setdefault("pose_source", SEMANTIC_SOURCE)
    state = {
        "runtime": {"runtime_mode": "real"},
        "scene_usd": str(request["scene_usd"]),
        "robot_import": dict(request["robot_import"]),
        "semantic_pose_state": {
            "schema": "isaac_semantic_pose_state_v1",
            "robot_pose": b1_pose,
            "object_poses": {},
            "receptacle_index": {},
            "rendered_to_usd": False,
            "planner_backed": False,
            "physical_robot": False,
        },
    }
    output_dir = Path(str(request["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    view_paths = {
        key: output_dir / f"{waypoint['waypoint_id']}.{key}.png"
        for key in ("fpv", "chase", "topdown", "verify")
    }
    capture = runtime_capture.capture_semantic_pose_robot_views(
        state=state,
        scene_usd=Path(str(request["scene_usd"])),
        view_paths=view_paths,
        width=int(request["render_width"]),
        height=int(request["render_height"]),
    )
    images = {
        key: str(value)
        for key, value in dict(capture.get("robot_view_images") or {}).items()
        if key in view_paths
    }
    robot_pose_application = dict(capture.get("robot_pose_stage_application") or {})
    result = {
        "waypoint_id": waypoint.get("waypoint_id"),
        "scene_usd": str(request["scene_usd"]),
        "source_anchor_id": waypoint.get("source_anchor_id"),
        "semantic_source": SEMANTIC_SOURCE,
        "alignment_artifact": waypoint.get("alignment_artifact") or "",
        "alignment_transform_source": waypoint.get("alignment_transform_source") or "",
        "selected_transform_type": waypoint.get("selected_transform_type") or "",
        "map12_nav_goal": waypoint.get("map12_nav_goal"),
        "robot_pose": b1_pose,
        "robot_pose_stage_application": robot_pose_application,
        "robot_pose_applied": robot_pose_application.get("status") == "applied",
        "views": images,
        "shapes": image_shapes(images),
        "render_steps": int(capture.get("render_steps") or 0),
        "native_render_diagnostics": dict(capture.get("native_render_diagnostics") or {}),
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({"status": "passed", "output": str(args.output)}, sort_keys=True))
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result["robot_pose_applied"] and images.get("fpv") else 2)


def load_or_build_readiness(args: argparse.Namespace) -> dict[str, Any]:
    if args.readiness_artifact is not None:
        payload = read_json_object(Path(args.readiness_artifact), label="readiness artifact")
        if payload.get("schema") != READINESS_SCHEMA:
            raise ValueError(f"unexpected readiness artifact schema: {payload.get('schema')!r}")
        return payload
    if args.b1_root is None or args.map12_root is None:
        raise ValueError("either --readiness-artifact or both --b1-root/--map12-root are required")
    return build_readiness_artifact(Path(args.b1_root), Path(args.map12_root))


def selected_render_scene_usd(*, args: argparse.Namespace, readiness: dict[str, Any]) -> Path:
    if args.render_scene_usd is not None:
        return Path(args.render_scene_usd)
    b1_geometry = dict(readiness.get("b1_geometry") or {})
    return Path(
        str(
            dict(b1_geometry.get("renderable_robot_view_usd") or {}).get("path")
            or dict(b1_geometry.get("full_floor_default_usd") or {}).get("path")
            or dict(b1_geometry.get("local_geometry") or {}).get("path")
            or ""
        )
    )


def navigation_smoke_waypoints(
    *,
    readiness: dict[str, Any],
    waypoint_pose_requests: Path | None,
) -> tuple[list[dict[str, Any]], str]:
    if waypoint_pose_requests is not None:
        payload = read_json_object(
            Path(waypoint_pose_requests),
            label="waypoint pose request artifact",
        )
        if payload.get("schema") != WAYPOINT_POSE_REQUESTS_SCHEMA:
            return [], f"unexpected waypoint pose request schema: {payload.get('schema')!r}"
        validation_errors = validate_waypoint_pose_requests_artifact(payload)
        if validation_errors:
            return [], "invalid waypoint pose request artifact: " + "; ".join(validation_errors)
        if payload.get("status") != "ready":
            blocked_reasons = [
                str(item.get("reason") or "")
                for item in payload.get("blocked_requests") or []
                if isinstance(item, dict) and item.get("reason")
            ]
            reason = "; ".join(blocked_reasons) or "waypoint pose request artifact is blocked"
            return [], reason
        if str(payload.get("alignment_transform_source") or "") != "reviewed_correspondence_fit":
            return [], "waypoint pose requests require reviewed correspondence transform"
        return [
            item
            for item in payload.get("waypoints") or []
            if isinstance(item, dict) and isinstance(item.get("b1_pose"), dict)
        ], ""
    readiness_waypoints = [
        item
        for item in readiness.get("map12_overlay", {}).get("candidate_waypoints") or []
        if isinstance(item, dict)
        and isinstance(item.get("b1_pose"), dict)
        and str(item.get("alignment_transform_source") or "") == "reviewed_correspondence_fit"
        and bool(item.get("alignment_artifact"))
    ][:2]
    if len(readiness_waypoints) < 2:
        return [], (
            "navigation smoke requires at least two residual-backed waypoint poses; "
            "provide a ready b1_map12_waypoint_pose_requests_v1 artifact or a readiness "
            "artifact with reviewed-correspondence candidate waypoints"
        )
    return readiness_waypoints, ""


def navigation_smoke_has_distinct_pose_evidence(waypoint_evidence: list[dict[str, Any]]) -> bool:
    if len(waypoint_evidence) < 2:
        return False
    pose_keys = {
        (
            round(float(dict(item.get("robot_pose") or {}).get("x") or 0.0), 3),
            round(float(dict(item.get("robot_pose") or {}).get("y") or 0.0), 3),
        )
        for item in waypoint_evidence
        if isinstance(item, dict)
        and item.get("robot_pose_applied") is True
        and isinstance(item.get("robot_pose"), dict)
    }
    return len(pose_keys) >= 2


def blocked_artifact(
    *,
    readiness: dict[str, Any],
    reason: str,
    blockers: list[str] | None = None,
    robot_import: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": NAVIGATION_SMOKE_SCHEMA,
        "status": "blocked",
        "readiness_schema": readiness.get("schema"),
        "semantic_source": SEMANTIC_SOURCE,
        "semantic_usd_binding_status": SEMANTIC_USD_BLOCKED,
        "semantic_anchors_are_usd_truth": False,
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "manipulation_supported": False,
        "robot_navigation_supported": False,
        "robot_navigation_provenance": "blocked_local_isaac_b1_map12_navigation_smoke",
        "navigation_provenance": "blocked",
        "planner_backed": False,
        "physical_robot": False,
        "navigation_waypoint_count": 0,
        "robot_view_evidence_status": "blocked",
        "waypoint_evidence": [],
        "blocked_reason": reason,
        "blockers": list(blockers or []),
        "robot_import": dict(robot_import or {}),
        "validation": {"status": "failed", "errors": ["navigation smoke did not pass"]},
    }


def image_shapes(images: dict[str, str]) -> dict[str, list[int]]:
    shapes: dict[str, list[int]] = {}
    for key, raw_path in images.items():
        with Image.open(raw_path) as image:
            shapes[key] = [image.height, image.width, len(image.getbands())]
    return shapes


def write_artifact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": payload.get("schema"),
                "status": payload.get("status"),
                "output": str(path),
                "robot_navigation_supported": payload.get("robot_navigation_supported"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
