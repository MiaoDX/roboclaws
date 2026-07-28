#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

from roboclaws.core.json_sources import read_json_object  # noqa: E402
from roboclaws.household.camera_control import canonical_scene_camera_control_request  # noqa: E402
from roboclaws.household.household_backend_contract import HouseholdBackendSession  # noqa: E402
from roboclaws.household.household_runtime_contract import (  # noqa: E402
    RAW_FPV_ONLY_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend  # noqa: E402
from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_path  # noqa: E402
from roboclaws.launch.scene_sampler import parse_molmospaces_world_id  # noqa: E402
from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS  # noqa: E402
from roboclaws.maps.bundle import (  # noqa: E402
    static_landmarks_from_fixture_projection,
    write_nav2_map_bundle_snapshot,
)
from roboclaws.maps.preview import (  # noqa: E402
    BASE_MAP_SOURCE_FAMILY,
    BASE_METRIC_MAP_PREVIEW_ROLE,
    SCENE_RENDER_SOURCE_FAMILY,
    TOPDOWN_SCENE_RENDER_ROLE,
    render_base_metric_map_preview,
)
from scripts.maps.build_b1_map12_base_metric_map import (  # noqa: E402
    DEFAULT_LABELS as B1_BASE_METRIC_LABELS,
)
from scripts.maps.build_b1_map12_base_metric_map import (
    DEFAULT_MAP_BUNDLE as B1_BASE_METRIC_MAP_BUNDLE,
)
from scripts.maps.build_b1_map12_base_metric_map import (
    DEFAULT_ROOM_SEMANTICS as B1_ROOM_SEMANTICS,
)
from scripts.maps.build_b1_map12_base_metric_map import build_base_metric_map_bundle  # noqa: E402

PREVIEW_METADATA_SCHEMA = "operator_console_scene_preview_v1"
DEFAULT_OUTPUT_DIR = Path("roboclaws/operator_console/static/previews")
DEFAULT_WORK_DIR = Path("output/operator-console-scene-previews")
DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 560
B1_MAP12_WORLD_ID = "b1-map12"
B1_GAUSSIAN_SCENE_USD_PATH = Path(
    "data/robot-data-lab/scene-engine/data/2rd_floor_seperated/storey_1/scene_gs.usda"
)
B1_GAUSSIAN_TOPDOWN_PACKET = Path(
    "output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json"
)
B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE = DEFAULT_OUTPUT_DIR / "b1-map12-topdown.png"
B1_BASE_METRIC_MAP_PROVENANCE = "b1_map12_base_metric_map_preview_png"
B1_GAUSSIAN_TOPDOWN_PROVENANCE = "b1_scene_gaussian_topdown_crop_z1p8_png"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = render_previews(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "success" else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render operator-console scene previews. MolmoSpaces previews are real "
            "MuJoCo renders: Raw FPV is captured from the first public waypoint, "
            "Chase is the robot follower camera, the map preview is static Base "
            "Metric Map context, and Top-down is a separate scene camera render. B1 / Map 12 "
            "previews combine checked-in Base Metric Map context with the captured "
            "height-cropped Gaussian top-down slice so "
            "the console can show the experimental digital twin before Isaac starts "
            "without presenting fake FPV or chase camera frames."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--world",
        action="append",
        default=[],
        help="World id to render. Defaults to all visible MolmoSpaces console scenes.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--width", type=_positive_int_arg, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=_positive_int_arg, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help=(
            "Do not render a world when FPV, static map, chase, and top-down preview files "
            "already exist."
        ),
    )
    parser.add_argument(
        "--b1-camera-artifact",
        type=Path,
        help=(
            "Optional real B1 Isaac runtime artifact to promote into FPV/chase previews. "
            "Supported inputs are navigation_smoke.json and run_result.json with "
            "robot_view_steps. Without this, B1 preview generation only writes static "
            "map/top-down assets and will not fabricate camera views."
        ),
    )
    return parser.parse_args(argv)


def render_previews(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for world_id in _selected_world_ids(args.world):
        if world_id == B1_MAP12_WORLD_ID:
            result = render_b1_map12_preview(
                output_dir=output_dir,
                width=int(args.width),
                height=int(args.height),
                skip_existing=bool(args.skip_existing),
                camera_artifact=args.b1_camera_artifact,
            )
        else:
            result = render_molmospaces_preview(
                world_id=world_id,
                output_dir=output_dir,
                work_dir=work_dir,
                seed=int(args.seed),
                width=int(args.width),
                height=int(args.height),
                skip_existing=bool(args.skip_existing),
            )
        results.append(result)

    status = (
        "success"
        if all(item.get("status") in {"rendered", "skipped"} for item in results)
        else "failed"
    )
    return {
        "schema": "operator_console_scene_preview_render_report_v1",
        "status": status,
        "generated_at": _utc_timestamp(),
        "output_dir": str(output_dir),
        "work_dir": str(work_dir),
        "results": results,
    }


def render_molmospaces_preview(
    *,
    world_id: str,
    output_dir: Path,
    work_dir: Path,
    seed: int,
    width: int,
    height: int,
    skip_existing: bool = False,
) -> dict[str, Any]:
    scene_ref = _molmospaces_scene_ref(world_id)
    scene_index = scene_ref.scene_index
    map_bundle_dir = molmospaces_nav2_map_bundle_path(
        scene_source=scene_ref.scene_source,
        scene_index=scene_index,
    )
    slug = _world_slug(world_id)
    fpv_path = output_dir / f"{slug}-fpv.png"
    map_path = output_dir / f"{slug}-map.png"
    chase_path = output_dir / f"{slug}-chase.png"
    topdown_path = output_dir / f"{slug}-topdown.png"
    metadata_path = output_dir / f"{slug}-preview.json"
    if (
        skip_existing
        and fpv_path.exists()
        and map_path.exists()
        and chase_path.exists()
        and topdown_path.exists()
    ):
        return {
            "world_id": world_id,
            "scene_source": scene_ref.scene_source,
            "scene_index": scene_index,
            "status": "skipped",
            "fpv": str(fpv_path),
            "map": str(map_path),
            "chase": str(chase_path),
            "topdown": str(topdown_path),
            "metadata": str(metadata_path),
        }

    run_dir = work_dir / slug
    backend = MolmoSpacesSubprocessBackend(
        run_dir=run_dir / "backend",
        seed=seed,
        scene_source=scene_ref.scene_source,
        scene_index=scene_index,
        include_robot=True,
        robot_name="rby1m",
        generated_mess_count=0,
    )
    try:
        contract = HouseholdRuntimeContract(
            HouseholdBackendSession(backend.scenario, backend=backend),
            perception_mode=RAW_FPV_ONLY_MODE,
            map_bundle_dir=map_bundle_dir,
        )
        metric_map = contract.metric_map()
        waypoint = _first_public_waypoint(metric_map)
        navigation = contract.navigate_to_waypoint(str(waypoint["waypoint_id"]))
        if not navigation.get("ok"):
            return {
                "world_id": world_id,
                "scene_source": scene_ref.scene_source,
                "scene_index": scene_index,
                "status": "navigate_failed",
                "waypoint_id": waypoint.get("waypoint_id"),
                "navigation": navigation,
            }

        views = backend.write_robot_views_with_resolution(
            run_dir / "robot_views",
            label="preview_first_waypoint",
            width=width,
            height=height,
        )
        raw_fpv = Path(str(views.get("views", {}).get("fpv") or ""))
        raw_chase = Path(str(views.get("views", {}).get("chase") or ""))
        if not raw_fpv.is_file():
            return {
                "world_id": world_id,
                "scene_source": scene_ref.scene_source,
                "scene_index": scene_index,
                "status": "fpv_missing",
                "waypoint_id": waypoint.get("waypoint_id"),
                "views": views,
            }
        if not raw_chase.is_file():
            return {
                "world_id": world_id,
                "scene_source": scene_ref.scene_source,
                "scene_index": scene_index,
                "status": "chase_missing",
                "waypoint_id": waypoint.get("waypoint_id"),
                "views": views,
            }

        state = _read_molmospaces_backend_state(
            run_dir / "backend" / "molmospaces_backend_state.json"
        )
        scene_alignment = _scene_alignment(state, width=width, height=height)
        static_map = _static_navigation_preview(
            contract=contract,
            run_dir=run_dir,
            width=width,
            height=height,
        )
        static_map.save(map_path)

        topdown_request = _topdown_camera_request(
            state,
            width=width,
            height=height,
            alignment=scene_alignment,
        )
        request_path = run_dir / "topdown_camera_request.json"
        request_path.write_text(
            json.dumps(topdown_request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        topdown = backend.render_camera_control_request(
            run_dir / "camera_views",
            request_path=request_path,
        )
        raw_topdown = Path(str(topdown.get("images", {}).get("topdown_scene") or ""))
        if not raw_topdown.is_file():
            return {
                "world_id": world_id,
                "scene_source": scene_ref.scene_source,
                "scene_index": scene_index,
                "status": "topdown_missing",
                "waypoint_id": waypoint.get("waypoint_id"),
                "topdown": topdown,
            }

        chase_selection = _select_chase_preview(
            contract=contract,
            backend=backend,
            run_dir=run_dir,
            width=width,
            height=height,
            first_waypoint=waypoint,
            first_navigation=navigation,
            first_robot_views=views,
            first_chase_path=raw_chase,
            candidate_waypoints=_public_waypoints(metric_map)[1:],
        )
        raw_chase = Path(str(chase_selection["path"]))

        shutil.copyfile(raw_fpv, fpv_path)
        shutil.copyfile(raw_chase, chase_path)
        shutil.copyfile(raw_topdown, topdown_path)
        metadata = _preview_metadata(
            world_id=world_id,
            scene_source=scene_ref.scene_source,
            scene_index=scene_index,
            seed=seed,
            width=width,
            height=height,
            map_bundle_dir=map_bundle_dir,
            waypoint=waypoint,
            navigation=navigation,
            robot_views=views,
            topdown_result=topdown,
            topdown_request=topdown_request,
            fpv_path=fpv_path,
            map_path=map_path,
            chase_path=chase_path,
            chase_waypoint=chase_selection["waypoint"],
            chase_navigation=chase_selection["navigation"],
            chase_robot_views=chase_selection["robot_views"],
            chase_selection=chase_selection,
            topdown_path=topdown_path,
            scene_alignment=scene_alignment,
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "world_id": world_id,
            "scene_source": scene_ref.scene_source,
            "scene_index": scene_index,
            "status": "rendered",
            "waypoint_id": waypoint.get("waypoint_id"),
            "fpv": str(fpv_path),
            "map": str(map_path),
            "chase": str(chase_path),
            "topdown": str(topdown_path),
            "metadata": str(metadata_path),
        }
    finally:
        backend.close()


def render_b1_map12_preview(
    *,
    output_dir: Path,
    width: int,
    height: int,
    skip_existing: bool = False,
    camera_artifact: Path | None = None,
) -> dict[str, Any]:
    slug = _world_slug(B1_MAP12_WORLD_ID)
    fpv_path = output_dir / f"{slug}-fpv.png"
    map_path = output_dir / f"{slug}-map.png"
    chase_path = output_dir / f"{slug}-chase.png"
    topdown_path = output_dir / f"{slug}-topdown.png"
    metadata_path = output_dir / f"{slug}-preview.json"
    removed_stale: list[str] = []
    skip_result = (
        _b1_preview_skip_result(
            camera_artifact=camera_artifact,
            fpv_path=fpv_path,
            map_path=map_path,
            chase_path=chase_path,
            topdown_path=topdown_path,
            metadata_path=metadata_path,
            removed_stale=removed_stale,
        )
        if skip_existing
        else None
    )
    if skip_result is not None:
        if skip_result.get("status") == "metadata_unreadable":
            return skip_result
        skip_result["removed_stale"] = removed_stale
        return skip_result

    if camera_artifact is None:
        removed_stale.extend(_unlink_existing_paths(fpv_path, chase_path))

    static_result = _write_b1_static_preview_assets(
        output_dir=output_dir,
        map_path=map_path,
        topdown_path=topdown_path,
        width=width,
        height=height,
    )
    metadata = _b1_map12_preview_metadata(
        width=width,
        height=height,
        map_path=map_path,
        topdown_path=topdown_path,
        static_result=static_result,
    )
    camera_result: dict[str, Any] | None = None
    if camera_artifact is not None:
        camera_result = _promote_b1_camera_previews(
            camera_artifact=Path(camera_artifact),
            fpv_path=fpv_path,
            chase_path=chase_path,
            width=width,
            height=height,
        )
        if camera_result.get("status") != "promoted":
            removed_stale.extend(_unlink_existing_paths(fpv_path, chase_path))
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return {
                "world_id": B1_MAP12_WORLD_ID,
                "scene_source": "b1-gaussian-digital-twin",
                "status": "camera_preview_unavailable",
                "metadata": str(metadata_path),
                "camera_artifact": str(camera_artifact),
                "camera_result": camera_result,
                "removed_stale": removed_stale,
                "map": str(map_path),
                "topdown": str(topdown_path),
            }
        metadata["renderer"] = "b1_map12_static_gaussian_topdown_with_isaac_runtime_camera"
        metadata["views"]["fpv"] = camera_result["views"]["fpv"]
        metadata["views"]["chase"] = camera_result["views"]["chase"]
        metadata["camera_preview_artifact"] = camera_result["artifact"]
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = {
        "world_id": B1_MAP12_WORLD_ID,
        "scene_source": "b1-gaussian-digital-twin",
        "status": "rendered",
        "metadata": str(metadata_path),
        "map": str(map_path),
        "topdown": str(topdown_path),
        "removed_stale": removed_stale,
    }
    if camera_result is not None:
        result.update(
            {
                "fpv": str(fpv_path),
                "chase": str(chase_path),
                "camera_artifact": str(camera_artifact),
                "camera_selection_status": camera_result.get("selection_status"),
            }
        )
    return result


def _unlink_existing_paths(*paths: Path) -> list[str]:
    removed: list[str] = []
    for path in paths:
        if path.exists():
            path.unlink()
            removed.append(str(path))
    return removed


def _b1_preview_skip_result(
    *,
    camera_artifact: Path | None,
    fpv_path: Path,
    map_path: Path,
    chase_path: Path,
    topdown_path: Path,
    metadata_path: Path,
    removed_stale: list[str],
) -> dict[str, Any] | None:
    if not metadata_path.exists():
        return None
    try:
        static_ready = _b1_metadata_has_static_previews(
            metadata_path,
            map_path=map_path,
            topdown_path=topdown_path,
        )
        if camera_artifact is None:
            can_skip = static_ready and _b1_metadata_has_no_camera_previews(metadata_path)
        else:
            metadata_has_real_camera_previews = _b1_metadata_has_real_camera_previews(
                metadata_path,
                camera_artifact=camera_artifact,
            )
            can_skip = (
                static_ready
                and fpv_path.exists()
                and chase_path.exists()
                and metadata_has_real_camera_previews
            )
    except (OSError, ValueError) as exc:
        return {
            "world_id": B1_MAP12_WORLD_ID,
            "scene_source": "b1-gaussian-digital-twin",
            "status": "metadata_unreadable",
            "metadata": str(metadata_path),
            "reason": str(exc),
            "removed_stale": removed_stale,
        }
    if not can_skip:
        return None
    return {
        "world_id": B1_MAP12_WORLD_ID,
        "scene_source": "b1-gaussian-digital-twin",
        "status": "skipped",
        "map": str(map_path),
        "topdown": str(topdown_path),
        **(
            {"fpv": str(fpv_path), "chase": str(chase_path)}
            if fpv_path.exists() and chase_path.exists()
            else {}
        ),
        "metadata": str(metadata_path),
        "removed_stale": removed_stale,
    }


def _b1_metadata_has_static_previews(
    path: Path,
    *,
    map_path: Path,
    topdown_path: Path,
) -> bool:
    if not map_path.exists() or not topdown_path.exists():
        return False
    payload = read_json_object(path, label="B1 preview metadata")
    views = payload.get("views")
    if not isinstance(views, dict):
        return False
    return _b1_static_view_ready(
        views.get("map"),
        expected_path=map_path.name,
        expected_provenance=B1_BASE_METRIC_MAP_PROVENANCE,
    ) and _b1_static_view_ready(
        views.get("topdown"),
        expected_path=topdown_path.name,
        expected_provenance=B1_GAUSSIAN_TOPDOWN_PROVENANCE,
    )


def _b1_static_view_ready(
    view: Any,
    *,
    expected_path: str,
    expected_provenance: str,
) -> bool:
    if not isinstance(view, dict):
        return False
    return (
        str(view.get("path") or "") == expected_path
        and str(view.get("provenance") or "") == expected_provenance
    )


def _b1_metadata_has_no_camera_previews(path: Path) -> bool:
    payload = read_json_object(path, label="B1 preview metadata")
    views = payload.get("views")
    if not isinstance(views, dict):
        return False
    return "fpv" not in views and "chase" not in views


def _read_molmospaces_backend_state(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="MolmoSpaces backend state")


def _b1_metadata_has_real_camera_previews(
    path: Path,
    *,
    camera_artifact: Path | None = None,
) -> bool:
    payload = read_json_object(path, label="B1 preview metadata")
    if camera_artifact is not None and not _b1_metadata_camera_artifact_matches(
        payload,
        camera_artifact=camera_artifact,
    ):
        return False
    return _b1_metadata_payload_has_real_camera_previews(payload)


def _b1_metadata_camera_artifact_matches(
    payload: dict[str, Any],
    *,
    camera_artifact: Path,
) -> bool:
    artifact = payload.get("camera_preview_artifact")
    if not isinstance(artifact, dict):
        return False
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        artifact_hash = str(artifact.get("source_artifact_sha256") or "").strip()
        if artifact_hash:
            return camera_artifact.is_file() and artifact_hash == _file_sha256(camera_artifact)
        return str(artifact.get("source_artifact_name") or "").strip() == camera_artifact.name
    return Path(raw_path).resolve() == camera_artifact.resolve()


def _portable_b1_artifact_view_ref(*, artifact_path: Path, view_path: Path) -> str:
    artifact_path = artifact_path.resolve()
    view_path = view_path.resolve()
    try:
        return view_path.relative_to(artifact_path.parent).as_posix()
    except ValueError:
        return view_path.name


def _b1_metadata_payload_has_real_camera_previews(payload: dict[str, Any]) -> bool:
    views = payload.get("views")
    if not isinstance(views, dict):
        return False
    fpv = views.get("fpv")
    chase = views.get("chase")
    if not isinstance(fpv, dict) or not isinstance(chase, dict):
        return False
    if not str(fpv.get("provenance") or "").startswith("isaac_runtime_") or not str(
        chase.get("provenance") or ""
    ).startswith("isaac_runtime_"):
        return False
    fpv_waypoint = str(fpv.get("waypoint_id") or "").strip()
    chase_waypoint = str(chase.get("waypoint_id") or "").strip()
    if not fpv_waypoint or fpv_waypoint != chase_waypoint:
        return False
    fpv_alignment = str(fpv.get("alignment_artifact") or "").strip()
    chase_alignment = str(chase.get("alignment_artifact") or "").strip()
    if not fpv_alignment or fpv_alignment != chase_alignment:
        return False
    fpv_transform = str(fpv.get("alignment_transform_source") or "").strip()
    chase_transform = str(chase.get("alignment_transform_source") or "").strip()
    if fpv_transform != "reviewed_correspondence_fit" or chase_transform != fpv_transform:
        return False
    artifact = payload.get("camera_preview_artifact")
    if not isinstance(artifact, dict):
        return False
    if str(artifact.get("selected_waypoint_id") or "").strip() != fpv_waypoint:
        return False
    if str(artifact.get("alignment_artifact") or "").strip() != fpv_alignment:
        return False
    return str(artifact.get("alignment_transform_source") or "").strip() == fpv_transform


def _promote_b1_camera_previews(
    *,
    camera_artifact: Path,
    fpv_path: Path,
    chase_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    if not camera_artifact.is_file():
        return {
            "status": "artifact_missing",
            "artifact_path": str(camera_artifact),
        }
    try:
        payload = read_json_object(camera_artifact, label="B1 camera preview artifact")
    except (OSError, ValueError) as exc:
        return {
            "status": "artifact_unreadable",
            "artifact_path": str(camera_artifact),
            "reason": str(exc),
        }
    candidate_results = _evaluate_b1_camera_preview_candidates(
        payload=payload,
        camera_artifact=camera_artifact,
    )
    candidates = candidate_results["candidates"]
    evaluated = candidate_results["evaluated"]
    accepted = candidate_results["accepted"]
    if not accepted:
        return {
            "status": "no_usable_camera_pair",
            "artifact_path": str(camera_artifact),
            "candidate_count": len(candidates),
            "evaluated_candidates": evaluated,
        }
    selected = accepted[0]
    fpv_source = Path(str(selected["fpv_source"]))
    chase_source = Path(str(selected["chase_source"]))
    _fit_preview_image(Image.open(fpv_source), width=width, height=height).save(fpv_path)
    _fit_preview_image(Image.open(chase_source), width=width, height=height).save(chase_path)
    selected_label = str(selected.get("label") or "")
    selected_action = str(selected.get("action") or "")
    selected_waypoint = str(selected.get("waypoint_id") or "")
    camera_control_contract = selected.get("camera_control_contract")
    if not isinstance(camera_control_contract, dict):
        camera_control_contract = {}
    agent_facing_fpv = (
        camera_control_contract.get("agent_facing_fpv")
        if isinstance(camera_control_contract.get("agent_facing_fpv"), dict)
        else {}
    )
    report_chase = (
        camera_control_contract.get("report_chase_view")
        if isinstance(camera_control_contract.get("report_chase_view"), dict)
        else {}
    )
    return {
        "status": "promoted",
        "selection_status": "selected_first_accepted_real_isaac_camera_pair",
        "artifact": {
            "source_artifact_name": camera_artifact.name,
            "source_artifact_sha256": _file_sha256(camera_artifact),
            "source_artifact_status": "external_local_verification_artifact",
            "schema": payload.get("schema") or payload.get("contract") or "",
            "source_kind": selected.get("source_kind"),
            "selected_label": selected_label,
            "selected_action": selected_action,
            "selected_waypoint_id": selected_waypoint,
            "alignment_artifact": selected.get("alignment_artifact")
            or payload.get("alignment_artifact")
            or "",
            "alignment_transform_source": selected.get("alignment_transform_source")
            or payload.get("alignment_transform_source")
            or "",
            "candidate_count": len(candidates),
            "accepted_candidate_count": len(accepted),
        },
        "evaluated_candidates": evaluated,
        "views": {
            "fpv": {
                "path": fpv_path.name,
                "view": "raw_fpv",
                "waypoint_id": selected_waypoint,
                "alignment_artifact": selected.get("alignment_artifact")
                or payload.get("alignment_artifact")
                or "",
                "alignment_transform_source": selected.get("alignment_transform_source")
                or payload.get("alignment_transform_source")
                or "",
                "action": selected_action,
                "label": selected_label,
                "camera": agent_facing_fpv.get("camera_prim_path") or "/World/robot_0/head_camera",
                "provenance": "isaac_runtime_robot_mounted_head_camera_fpv",
                "source_artifact_view": _portable_b1_artifact_view_ref(
                    artifact_path=camera_artifact,
                    view_path=fpv_source,
                ),
                "source": agent_facing_fpv.get("source")
                or "isaac_lab_camera_rgb_robot_mounted_head_camera:fpv",
                "robot_mounted": agent_facing_fpv.get("robot_mounted", True),
                "head_camera_equivalent": agent_facing_fpv.get("head_camera_equivalent", False),
                "image_diagnostics": _image_diagnostics(fpv_path),
            },
            "chase": {
                "path": chase_path.name,
                "view": "chase_camera",
                "waypoint_id": selected_waypoint,
                "alignment_artifact": selected.get("alignment_artifact")
                or payload.get("alignment_artifact")
                or "",
                "alignment_transform_source": selected.get("alignment_transform_source")
                or payload.get("alignment_transform_source")
                or "",
                "action": selected_action,
                "label": selected_label,
                "camera": report_chase.get("camera_prim_path") or "robot_relative_chase_camera",
                "provenance": "isaac_runtime_report_chase_camera",
                "source_artifact_view": _portable_b1_artifact_view_ref(
                    artifact_path=camera_artifact,
                    view_path=chase_source,
                ),
                "source": report_chase.get("source") or "backend_local_report_chase_camera",
                "policy_note": "Chase is report evidence, not agent-facing policy input.",
                "image_diagnostics": _image_diagnostics(chase_path),
            },
        },
    }


def _evaluate_b1_camera_preview_candidates(
    *,
    payload: dict[str, Any],
    camera_artifact: Path,
) -> dict[str, Any]:
    candidates = _b1_camera_preview_candidates(payload, artifact_path=camera_artifact)
    evaluated = [
        _evaluate_b1_camera_preview_candidate(
            payload=payload,
            camera_artifact=camera_artifact,
            candidate=candidate,
        )
        for candidate in candidates
    ]
    accepted = [item for item in evaluated if item.get("status") == "accepted"]
    return {"candidates": candidates, "evaluated": evaluated, "accepted": accepted}


def _evaluate_b1_camera_preview_candidate(
    *,
    payload: dict[str, Any],
    camera_artifact: Path,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    fpv_source = _resolve_b1_artifact_view_path(camera_artifact, candidate.get("fpv"))
    chase_source = _resolve_b1_artifact_view_path(camera_artifact, candidate.get("chase"))
    candidate_result = {
        "label": candidate.get("label"),
        "action": candidate.get("action"),
        "waypoint_id": candidate.get("waypoint_id"),
        "source_kind": candidate.get("source_kind"),
        "fpv_source": str(fpv_source) if fpv_source is not None else "",
        "chase_source": str(chase_source) if chase_source is not None else "",
    }
    provenance_errors = _b1_camera_preview_provenance_errors(payload, candidate)
    if provenance_errors:
        return {
            **candidate_result,
            "status": "provenance_rejected",
            "provenance_errors": provenance_errors,
        }
    if fpv_source is None or chase_source is None:
        return {**candidate_result, "status": "missing_view_path"}
    if not fpv_source.is_file() or not chase_source.is_file():
        return {**candidate_result, "status": "missing_view_file"}
    return _evaluate_b1_camera_preview_quality(
        candidate=candidate,
        candidate_result=candidate_result,
        fpv_source=fpv_source,
        chase_source=chase_source,
    )


def _evaluate_b1_camera_preview_quality(
    *,
    candidate: dict[str, Any],
    candidate_result: dict[str, Any],
    fpv_source: Path,
    chase_source: Path,
) -> dict[str, Any]:
    fpv_diagnostics = _image_diagnostics(fpv_source)
    chase_diagnostics = _image_diagnostics(chase_source)
    errors = [
        *(f"fpv: {error}" for error in _b1_camera_preview_quality_errors(fpv_diagnostics)),
        *(f"chase: {error}" for error in _b1_camera_preview_quality_errors(chase_diagnostics)),
    ]
    result = {
        **candidate_result,
        "fpv_diagnostics": fpv_diagnostics,
        "chase_diagnostics": chase_diagnostics,
        "quality_errors": errors,
    }
    if errors:
        return {**result, "status": "quality_rejected"}
    return {
        **result,
        "status": "accepted",
        "score": _b1_camera_preview_score(fpv_diagnostics)
        + (_b1_camera_preview_score(chase_diagnostics) * 0.75),
        "camera_control_contract": candidate.get("camera_control_contract"),
    }


def _b1_camera_preview_candidates(
    payload: dict[str, Any],
    *,
    artifact_path: Path,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, step in enumerate(payload.get("robot_view_steps") or []):
        if not isinstance(step, dict):
            continue
        views = step.get("views")
        if not isinstance(views, dict):
            continue
        candidates.append(
            {
                "source_kind": "run_result_robot_view_step",
                "label": step.get("label")
                or _b1_camera_label_from_view_path(views.get("fpv"))
                or f"robot_view_step_{index:03d}",
                "action": step.get("action"),
                "waypoint_id": step.get("waypoint_id")
                or step.get("current_waypoint_id")
                or step.get("room_id"),
                "robot_pose_applied": step.get("robot_pose_applied"),
                "alignment_artifact": step.get("alignment_artifact"),
                "alignment_transform_source": step.get("alignment_transform_source"),
                "fpv": views.get("fpv"),
                "chase": views.get("chase"),
                "camera_control_contract": step.get("camera_control_contract"),
            }
        )
    if candidates:
        return candidates
    for index, item in enumerate(payload.get("waypoint_evidence") or []):
        if not isinstance(item, dict):
            continue
        views = item.get("views")
        if not isinstance(views, dict):
            continue
        candidates.append(
            {
                "source_kind": "navigation_smoke_waypoint_evidence",
                "label": item.get("waypoint_id") or f"waypoint_evidence_{index:03d}",
                "action": "navigation_smoke",
                "waypoint_id": item.get("waypoint_id"),
                "robot_pose_applied": item.get("robot_pose_applied"),
                "alignment_artifact": item.get("alignment_artifact"),
                "alignment_transform_source": item.get("alignment_transform_source"),
                "fpv": views.get("fpv"),
                "chase": views.get("chase"),
                "camera_control_contract": {},
            }
        )
    del artifact_path
    return candidates


def _b1_camera_preview_provenance_errors(
    payload: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    source_kind = str(candidate.get("source_kind") or "")
    errors = [
        *_b1_camera_preview_candidate_shape_errors(candidate, source_kind=source_kind),
        *_b1_camera_preview_alignment_errors(payload, candidate),
    ]
    if source_kind == "run_result_robot_view_step":
        errors.extend(_b1_camera_preview_contract_errors(candidate.get("camera_control_contract")))
    return errors


def _b1_camera_preview_candidate_shape_errors(
    candidate: dict[str, Any],
    *,
    source_kind: str,
) -> list[str]:
    errors = []
    if not str(candidate.get("waypoint_id") or "").strip():
        errors.append("missing_waypoint_id")
    if _b1_camera_preview_view_pair_mixed(candidate):
        errors.append("mixed_fpv_chase_view_pair")
    if source_kind not in {
        "run_result_robot_view_step",
        "navigation_smoke_waypoint_evidence",
    }:
        errors.append("unsupported_camera_artifact_source")
    if candidate.get("robot_pose_applied") is not True:
        errors.append("robot_pose_not_applied")
    return errors


def _b1_camera_preview_view_pair_mixed(candidate: dict[str, Any]) -> bool:
    fpv_label = _b1_camera_label_from_view_path(candidate.get("fpv"))
    chase_label = _b1_camera_label_from_view_path(candidate.get("chase"))
    return bool(fpv_label and chase_label and fpv_label != chase_label)


def _b1_camera_preview_alignment_errors(
    payload: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    errors = []
    if not (candidate.get("alignment_artifact") or payload.get("alignment_artifact")):
        errors.append("missing_alignment_artifact")
    transform_source = str(
        candidate.get("alignment_transform_source")
        or payload.get("alignment_transform_source")
        or ""
    )
    if transform_source != "reviewed_correspondence_fit":
        errors.append("missing_reviewed_correspondence_transform_source")
    return errors


def _b1_camera_preview_contract_errors(raw_contract: Any) -> list[str]:
    if not isinstance(raw_contract, dict):
        return ["missing_camera_control_contract"]
    return [
        *_b1_camera_preview_fpv_contract_errors(raw_contract.get("agent_facing_fpv")),
        *_b1_camera_preview_chase_contract_errors(raw_contract.get("report_chase_view")),
    ]


def _b1_camera_preview_fpv_contract_errors(raw_fpv_contract: Any) -> list[str]:
    if not isinstance(raw_fpv_contract, dict):
        return ["missing_agent_facing_fpv_contract"]
    errors = []
    if not (
        raw_fpv_contract.get("robot_mounted") is True
        or raw_fpv_contract.get("head_camera_equivalent") is True
    ):
        errors.append("fpv_not_robot_mounted_or_head_camera_equivalent")
    if _b1_camera_preview_forbidden_runtime_source(raw_fpv_contract.get("source")):
        errors.append("fpv_source_not_robot_runtime")
    return errors


def _b1_camera_preview_chase_contract_errors(raw_chase_contract: Any) -> list[str]:
    if not isinstance(raw_chase_contract, dict):
        return ["missing_report_chase_contract"]
    if _b1_camera_preview_forbidden_runtime_source(raw_chase_contract.get("source")):
        return ["chase_source_not_robot_runtime"]
    return []


def _b1_camera_preview_forbidden_runtime_source(raw_source: Any) -> bool:
    source = str(raw_source or "")
    return "scene_probe" in source or "bbox" in source


def _b1_camera_label_from_view_path(raw_path: Any) -> str:
    if not raw_path:
        return ""
    name = Path(str(raw_path)).name
    for suffix in (".fpv.png", ".chase.png", ".fpv.jpg", ".chase.jpg", ".png", ".jpg"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _static_navigation_preview(
    *,
    contract: HouseholdRuntimeContract,
    run_dir: Path,
    width: int,
    height: int,
) -> Image.Image:
    bundle = write_nav2_map_bundle_snapshot(
        run_dir=run_dir,
        metric_map=contract.metric_map(),
        static_landmarks=static_landmarks_from_fixture_projection(
            contract.static_fixture_projection()
        ),
    )
    preview_path = run_dir / str(
        (bundle.get("artifact_paths") or {}).get("preview_png") or "map_bundle/preview.png"
    )
    if not preview_path.is_file():
        raise RuntimeError(f"missing static navigation preview: {preview_path}")
    return _fit_preview_image(Image.open(preview_path), width=width, height=height)


def _resolve_b1_artifact_view_path(artifact_path: Path, raw_path: Any) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return None
    base_dir = artifact_path.parent.resolve()
    resolved = (base_dir / path).resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError:
        return None
    if resolved.is_file():
        return resolved
    repo_resolved = (REPO_ROOT / path).resolve()
    try:
        repo_resolved.relative_to(REPO_ROOT)
    except ValueError:
        return None
    if repo_resolved.is_file():
        return repo_resolved
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _b1_camera_preview_quality_errors(diagnostics: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if diagnostics.get("visual_status") != "reviewable":
        errors.append(str(diagnostics.get("visual_status") or "not_reviewable"))
    if float(diagnostics.get("max_channel_range") or 0.0) <= 8.0:
        errors.append("too_little_channel_range")
    if float(diagnostics.get("max_stddev") or 0.0) <= 2.0:
        errors.append("too_little_variance")
    if int(diagnostics.get("thumbnail_color_count") or 0) < 128:
        errors.append("too_few_distinct_colors")
    if float(diagnostics.get("edge_fraction_over_8") or 0.0) < 0.02:
        errors.append("too_few_scene_edges")
    return errors


def _b1_camera_preview_score(diagnostics: dict[str, Any]) -> float:
    return (
        float(diagnostics.get("max_stddev") or 0.0)
        + (float(diagnostics.get("max_channel_range") or 0.0) / 100.0)
        + (float(diagnostics.get("thumbnail_color_count") or 0.0) / 1000.0)
        + (float(diagnostics.get("edge_fraction_over_8") or 0.0) * 10.0)
    )


def _preview_metadata(
    *,
    world_id: str,
    scene_source: str,
    scene_index: int,
    seed: int,
    width: int,
    height: int,
    map_bundle_dir: Path | None = None,
    waypoint: dict[str, Any],
    navigation: dict[str, Any],
    robot_views: dict[str, Any],
    topdown_result: dict[str, Any],
    topdown_request: dict[str, Any],
    fpv_path: Path,
    map_path: Path,
    chase_path: Path,
    chase_waypoint: dict[str, Any],
    chase_navigation: dict[str, Any],
    chase_robot_views: dict[str, Any],
    chase_selection: dict[str, Any],
    topdown_path: Path,
    scene_alignment: dict[str, Any],
) -> dict[str, Any]:
    topdown_view = next(
        (
            item
            for item in topdown_result.get("views") or []
            if item.get("view_id") == "topdown_scene"
        ),
        {},
    )
    return {
        "schema": PREVIEW_METADATA_SCHEMA,
        "generated_at": _utc_timestamp(),
        "world_id": world_id,
        "backend": "mujoco",
        "renderer": "molmospaces_subprocess_mujoco",
        "scene_source": scene_source,
        "scene_index": scene_index,
        "map_bundle_dir": str(map_bundle_dir) if map_bundle_dir is not None else "",
        "seed": seed,
        "render_resolution": {"width": width, "height": height},
        "views": {
            "fpv": {
                "path": fpv_path.name,
                "view": "raw_fpv",
                "waypoint_id": str(waypoint.get("waypoint_id") or ""),
                "camera": "robot_0/head_camera",
                "provenance": "mujoco_robot_head_camera_first_public_waypoint",
                "navigation_status": navigation.get("status") or "ok",
                "image_diagnostics": _image_diagnostics(fpv_path),
                "camera_diagnostics": (robot_views.get("camera_diagnostics") or {})
                .get("views", {})
                .get("fpv", {}),
            },
            "map": {
                "path": map_path.name,
                "view": BASE_METRIC_MAP_PREVIEW_ROLE,
                "visual_role": BASE_METRIC_MAP_PREVIEW_ROLE,
                "artifact_source_family": BASE_MAP_SOURCE_FAMILY,
                "provenance": "map_bundle_preview_png",
                "alignment_status": "source_map_frame_preview",
                "image_diagnostics": _image_diagnostics(map_path),
            },
            "chase": {
                "path": chase_path.name,
                "view": "chase_camera",
                "waypoint_id": str(chase_waypoint.get("waypoint_id") or ""),
                "camera": "robot_0/camera_follower",
                "provenance": "mujoco_robot_camera_follower_public_waypoint",
                "navigation_status": chase_navigation.get("status") or "ok",
                "selection_policy": "first_reviewable_public_waypoint_fallback_to_first",
                "selection_status": chase_selection.get("status"),
                "candidate_count_evaluated": chase_selection.get("candidate_count_evaluated"),
                "image_diagnostics": _image_diagnostics(chase_path),
                "camera_diagnostics": (chase_robot_views.get("camera_diagnostics") or {})
                .get("views", {})
                .get("chase", {}),
            },
            "topdown": {
                "path": topdown_path.name,
                "view": TOPDOWN_SCENE_RENDER_ROLE,
                "visual_role": TOPDOWN_SCENE_RENDER_ROLE,
                "artifact_source_family": SCENE_RENDER_SOURCE_FAMILY,
                "waypoint_id": str(waypoint.get("waypoint_id") or ""),
                "camera_model": topdown_request.get("camera_model"),
                "camera_pose": {
                    "eye": topdown_view.get("eye"),
                    "target": topdown_view.get("target"),
                    "azimuth": topdown_view.get("azimuth"),
                    "elevation": topdown_view.get("elevation"),
                    "distance": topdown_view.get("distance"),
                },
                "provenance": "mujoco_camera_control_canonical_eye_target",
                "alignment_status": "mujoco_scene_rendered",
                "scene_alignment": scene_alignment,
                "image_diagnostics": _image_diagnostics(topdown_path),
            },
        },
    }


def _select_chase_preview(
    *,
    contract: HouseholdRuntimeContract,
    backend: MolmoSpacesSubprocessBackend,
    run_dir: Path,
    width: int,
    height: int,
    first_waypoint: dict[str, Any],
    first_navigation: dict[str, Any],
    first_robot_views: dict[str, Any],
    first_chase_path: Path,
    candidate_waypoints: list[dict[str, Any]],
) -> dict[str, Any]:
    first_diagnostics = _image_diagnostics(first_chase_path)
    if first_diagnostics["visual_status"] == "reviewable":
        return {
            "status": "first_waypoint_reviewable",
            "path": first_chase_path,
            "waypoint": first_waypoint,
            "navigation": first_navigation,
            "robot_views": first_robot_views,
            "candidate_count_evaluated": 1,
        }

    candidate_count = 1
    for index, waypoint in enumerate(candidate_waypoints, start=2):
        waypoint_id = str(waypoint.get("waypoint_id") or "")
        if not waypoint_id:
            continue
        navigation = contract.navigate_to_waypoint(waypoint_id)
        candidate_count += 1
        if not navigation.get("ok"):
            continue
        robot_views = backend.write_robot_views_with_resolution(
            run_dir / "robot_views",
            label=f"preview_chase_candidate_{index:02d}",
            width=width,
            height=height,
        )
        chase_path = Path(str((robot_views.get("views") or {}).get("chase") or ""))
        if not chase_path.is_file():
            continue
        if _image_diagnostics(chase_path)["visual_status"] != "reviewable":
            continue
        return {
            "status": "alternate_waypoint_reviewable",
            "path": chase_path,
            "waypoint": dict(waypoint),
            "navigation": navigation,
            "robot_views": robot_views,
            "candidate_count_evaluated": candidate_count,
        }

    return {
        "status": "fallback_first_waypoint_low_detail",
        "path": first_chase_path,
        "waypoint": first_waypoint,
        "navigation": first_navigation,
        "robot_views": first_robot_views,
        "candidate_count_evaluated": candidate_count,
    }


def _write_b1_static_preview_assets(
    *,
    output_dir: Path,
    map_path: Path,
    topdown_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b1-map12-preview-") as temp_dir:
        bundle_dir = Path(temp_dir) / "base-metric-map"
        bundle_result = build_base_metric_map_bundle(
            map_bundle=B1_BASE_METRIC_MAP_BUNDLE,
            labels_path=B1_BASE_METRIC_LABELS,
            room_semantics_path=B1_ROOM_SEMANTICS,
            output_dir=bundle_dir,
        )
        semantics = read_json_object(
            bundle_dir / "semantics.json",
            label="B1 Base Metric Map semantics",
        )
        render_base_metric_map_preview(
            semantics=semantics,
            output_path=map_path,
            width=width,
            height=height,
            provenance=B1_BASE_METRIC_MAP_PROVENANCE,
        )
        gaussian_topdown = _write_b1_gaussian_topdown_preview(
            output_path=topdown_path,
            width=width,
            height=height,
        )
        return {
            "map_bundle": str(B1_BASE_METRIC_MAP_BUNDLE),
            "base_metric_labels": str(B1_BASE_METRIC_LABELS),
            "room_semantics": str(B1_ROOM_SEMANTICS),
            "navigation_area_count": int(bundle_result["navigation_area_count"]),
            "inspection_waypoint_count": int(bundle_result["inspection_waypoint_count"]),
            "semantic_label_count": len(semantics.get("rooms") or []),
            "gaussian_topdown": gaussian_topdown,
            "first_waypoint_id": str(
                ((semantics.get("inspection_waypoints") or [{}])[0]).get("waypoint_id") or ""
            ),
        }


def _write_b1_gaussian_topdown_preview(
    *,
    output_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    packet = _b1_gaussian_topdown_packet_or_none()
    source_image = _b1_gaussian_topdown_source_image(packet)
    if source_image is None:
        source_image = _fallback_b1_gaussian_topdown_image(output_path)
    if source_image is None:
        raise FileNotFoundError(
            "B1 Gaussian topdown source missing: expected "
            f"{B1_GAUSSIAN_TOPDOWN_PACKET} or {B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE}"
        )
    _fit_preview_image(Image.open(source_image), width=width, height=height).save(output_path)
    return _b1_gaussian_topdown_metadata(packet=packet, source_image=source_image)


def _b1_gaussian_topdown_packet_or_none() -> dict[str, Any] | None:
    if not B1_GAUSSIAN_TOPDOWN_PACKET.is_file():
        return None
    packet = read_json_object(B1_GAUSSIAN_TOPDOWN_PACKET, label="B1 Gaussian topdown packet")
    if packet.get("geometry_status") != "rendered_gaussian_scene_topdown":
        raise ValueError("B1 Gaussian topdown packet must be rendered_gaussian_scene_topdown")
    return packet


def _b1_gaussian_topdown_source_image(packet: dict[str, Any] | None) -> Path | None:
    if packet is None:
        return None
    raw_path = str(packet.get("topdown_image") or "").strip()
    if not raw_path:
        raise ValueError("B1 Gaussian topdown packet missing topdown_image")
    image_path = Path(raw_path)
    if image_path.is_file():
        return image_path
    repo_path = REPO_ROOT / image_path
    if repo_path.is_file():
        return repo_path
    raise FileNotFoundError(f"B1 Gaussian topdown image missing: {raw_path}")


def _fallback_b1_gaussian_topdown_image(output_path: Path) -> Path | None:
    fallback = B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE
    if not _checked_in_b1_gaussian_topdown_is_current():
        return None
    if output_path.resolve() == fallback.resolve():
        return output_path if output_path.is_file() else None
    return fallback if fallback.is_file() else None


def _b1_gaussian_topdown_metadata(
    *,
    packet: dict[str, Any] | None,
    source_image: Path,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_image": _portable_repo_path(source_image),
        "source_packet": str(B1_GAUSSIAN_TOPDOWN_PACKET),
        "source_status": "captured_gaussian_topdown_packet"
        if packet is not None
        else "checked_in_operator_preview_png",
    }
    if packet is None:
        return metadata
    visibility_policy = packet.get("scene_visibility_policy")
    if isinstance(visibility_policy, dict):
        metadata["scene_visibility_policy"] = _portable_b1_metadata_value(visibility_policy)
    for key in (
        "geometry_status",
        "capture_status",
        "prepared_scene_usd",
        "scene_usd",
        "up_axis",
        "horizontal_axes",
        "scene_xy_bounds",
        "pixel_to_scene_xyz",
        "camera",
        "width_px",
        "height_px",
    ):
        if key in packet:
            metadata[key] = _portable_b1_metadata_value(packet[key])
    return metadata


def _checked_in_b1_gaussian_topdown_is_current() -> bool:
    metadata_path = DEFAULT_OUTPUT_DIR / "b1-map12-preview.json"
    if not metadata_path.is_file():
        return False
    try:
        payload = read_json_object(metadata_path, label="checked-in B1 preview metadata")
    except (OSError, ValueError):
        return False
    views = payload.get("views") if isinstance(payload.get("views"), dict) else {}
    topdown = views.get("topdown") if isinstance(views.get("topdown"), dict) else {}
    return (
        str(topdown.get("provenance") or "") == B1_GAUSSIAN_TOPDOWN_PROVENANCE
        and str(topdown.get("artifact_source_family") or "") == SCENE_RENDER_SOURCE_FAMILY
        and B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE.is_file()
    )


def _portable_b1_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _portable_b1_metadata_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_b1_metadata_value(item) for item in value]
    if isinstance(value, str):
        return _portable_repo_path(Path(value)) if value.startswith("/") else value
    return value


def _portable_repo_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _b1_map12_preview_metadata(
    *,
    width: int,
    height: int,
    map_path: Path,
    topdown_path: Path,
    static_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": PREVIEW_METADATA_SCHEMA,
        "generated_at": _utc_timestamp(),
        "world_id": B1_MAP12_WORLD_ID,
        "backend": "isaaclab",
        "renderer": "b1_map12_static_gaussian_topdown_previews",
        "scene_source": "b1-gaussian-digital-twin",
        "scene_usd_path": str(B1_GAUSSIAN_SCENE_USD_PATH),
        "map_bundle": static_result["map_bundle"],
        "base_metric_labels": static_result["base_metric_labels"],
        "room_semantics": static_result["room_semantics"],
        "render_resolution": {"width": width, "height": height},
        "views": {
            "map": {
                "path": map_path.name,
                "view": BASE_METRIC_MAP_PREVIEW_ROLE,
                "visual_role": BASE_METRIC_MAP_PREVIEW_ROLE,
                "artifact_source_family": BASE_MAP_SOURCE_FAMILY,
                "provenance": B1_BASE_METRIC_MAP_PROVENANCE,
                "alignment_status": "verified_source_map_frame",
                "image_diagnostics": _image_diagnostics(map_path),
            },
            "topdown": {
                "path": topdown_path.name,
                "view": TOPDOWN_SCENE_RENDER_ROLE,
                "visual_role": TOPDOWN_SCENE_RENDER_ROLE,
                "artifact_source_family": SCENE_RENDER_SOURCE_FAMILY,
                "provenance": B1_GAUSSIAN_TOPDOWN_PROVENANCE,
                "alignment_status": "height_cropped_gaussian_scene_topdown",
                **static_result["gaussian_topdown"],
                "image_diagnostics": _image_diagnostics(topdown_path),
            },
        },
    }


def _fit_preview_image(image: Image.Image, *, width: int, height: int) -> Image.Image:
    source = image.convert("RGB")
    source.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), (228, 231, 235))
    x = (width - source.width) // 2
    y = (height - source.height) // 2
    canvas.paste(source, (x, y))
    return canvas


def _topdown_camera_request(
    state: dict[str, Any],
    *,
    width: int,
    height: int,
    alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    alignment = alignment or _scene_alignment(state, width=width, height=height)
    center = alignment["center"]
    vertical_fov_deg = 45.0
    camera_distance = (
        float(alignment["span_y_m"]) / (2.0 * math.tan(math.radians(vertical_fov_deg / 2.0))) * 1.04
    )
    camera_height = float(center[2]) + max(1.0, camera_distance)
    return canonical_scene_camera_control_request(
        [
            {
                "view_id": "topdown_scene",
                "label": "Top-down Scene View",
                "camera_basis": "whole_scene_true_topdown_aligned_to_scene_bounds",
                "eye": [center[0], center[1], camera_height],
                "target": center,
                "azimuth": 90.0,
                "scene_alignment": alignment,
                "calibration_status": "mujoco_scene_rendered",
            }
        ],
        lens={"vertical_fov_deg": vertical_fov_deg, "focal_length_mm": 24.0},
        width=width,
        height=height,
    )


def _scene_alignment(state: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    points = _scene_points(state)
    if not points:
        min_x = min_y = -0.5
        max_x = max_y = 0.5
    else:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    pad = 0.35
    min_x -= pad
    max_x += pad
    min_y -= pad
    max_y += pad
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    target_aspect = max(float(width) / max(float(height), 1.0), 0.001)
    current_aspect = span_x / span_y
    if current_aspect < target_aspect:
        expanded_span_x = span_y * target_aspect
        extra = (expanded_span_x - span_x) / 2.0
        min_x -= extra
        max_x += extra
        span_x = expanded_span_x
    elif current_aspect > target_aspect:
        expanded_span_y = span_x / target_aspect
        extra = (expanded_span_y - span_y) / 2.0
        min_y -= extra
        max_y += extra
        span_y = expanded_span_y
    center = [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0, 0.4]
    return {
        "schema": "operator_console_scene_alignment_v1",
        "bounds": {
            "min_x": round(min_x, 6),
            "max_x": round(max_x, 6),
            "min_y": round(min_y, 6),
            "max_y": round(max_y, 6),
        },
        "center": [round(float(value), 6) for value in center],
        "span_x_m": round(float(span_x), 6),
        "span_y_m": round(float(span_y), 6),
        "camera_span_m": round(float(max(span_x, span_y)), 6),
        "screen_coordinate_convention": "screen_x_world_positive_x_screen_y_world_negative_y",
        "topdown_azimuth_deg": 90.0,
    }


def _scene_points(state: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for outline in state.get("room_outlines") or []:
        if not isinstance(outline, dict):
            continue
        center = outline.get("center")
        half_extents = outline.get("half_extents")
        if not _is_vec(center, 2) or not _is_vec(half_extents, 2):
            continue
        points.append(
            (
                float(center[0]) - float(half_extents[0]),
                float(center[1]) - float(half_extents[1]),
            )
        )
        points.append(
            (
                float(center[0]) + float(half_extents[0]),
                float(center[1]) + float(half_extents[1]),
            )
        )
    for collection_key in ("objects", "receptacles"):
        collection = state.get(collection_key)
        if not isinstance(collection, dict):
            continue
        for item in collection.values():
            if not isinstance(item, dict) or not _is_vec(item.get("position"), 2):
                continue
            position = item["position"]
            points.append((float(position[0]), float(position[1])))
    for pose in state.get("robot_trajectory") or []:
        if not isinstance(pose, dict) or "x" not in pose or "y" not in pose:
            continue
        points.append((float(pose["x"]), float(pose["y"])))
    return points


def _scene_center_and_span(state: dict[str, Any]) -> tuple[list[float], float]:
    alignment = _scene_alignment(state, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT)
    return list(alignment["center"]), float(alignment["camera_span_m"])


def _first_public_waypoint(metric_map: dict[str, Any]) -> dict[str, Any]:
    waypoints = _public_waypoints(metric_map)
    if not waypoints:
        raise ValueError("metric map does not include public inspection waypoints")
    first = waypoints[0]
    if not first.get("waypoint_id"):
        raise ValueError("first public inspection waypoint is invalid")
    return first


def _public_waypoints(metric_map: dict[str, Any]) -> list[dict[str, Any]]:
    waypoints = metric_map.get("inspection_waypoints")
    if not isinstance(waypoints, list):
        return []
    return [
        dict(item)
        for item in waypoints
        if isinstance(item, dict) and str(item.get("waypoint_id") or "")
    ]


def _selected_world_ids(raw_world_ids: list[str]) -> tuple[str, ...]:
    return tuple(raw_world_ids or (*MOLMOSPACES_CONSOLE_WORLD_IDS, B1_MAP12_WORLD_ID))


def _molmospaces_scene_index(world_id: str) -> int:
    return _molmospaces_scene_ref(world_id).scene_index


def _molmospaces_scene_ref(world_id: str):
    return parse_molmospaces_world_id(world_id)


def _world_slug(world_id: str) -> str:
    return world_id.replace("/", "-")


def _is_vec(value: Any, min_length: int) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= min_length


def _image_diagnostics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        stat = ImageStat.Stat(rgb)
        extrema = rgb.getextrema()
        thumbnail = rgb.resize((160, 100))
        thumbnail_colors = thumbnail.getcolors(maxcolors=16_000)
        edges = rgb.convert("L").filter(ImageFilter.FIND_EDGES).resize((160, 100))
        edge_values = list(edges.getdata())
    channel_ranges = [float(high) - float(low) for low, high in extrema]
    max_channel_range = max(channel_ranges)
    max_stddev = max(float(value) for value in stat.stddev)
    visual_status = "low_detail" if max_channel_range <= 8.0 and max_stddev <= 2.0 else "reviewable"
    edge_fraction_over_8 = (
        sum(1 for value in edge_values if int(value) > 8) / float(len(edge_values))
        if edge_values
        else 0.0
    )
    edge_fraction_over_16 = (
        sum(1 for value in edge_values if int(value) > 16) / float(len(edge_values))
        if edge_values
        else 0.0
    )
    return {
        "schema": "operator_console_preview_image_diagnostics_v1",
        "width": int(rgb.width),
        "height": int(rgb.height),
        "mean_rgb": [round(float(value), 3) for value in stat.mean],
        "channel_extrema_rgb": [[int(low), int(high)] for low, high in extrema],
        "max_channel_range": round(max_channel_range, 3),
        "max_stddev": round(max_stddev, 3),
        "thumbnail_color_count": len(thumbnail_colors) if thumbnail_colors is not None else 16000,
        "edge_fraction_over_8": round(edge_fraction_over_8, 6),
        "edge_fraction_over_16": round(edge_fraction_over_16, 6),
        "visual_status": visual_status,
    }


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
