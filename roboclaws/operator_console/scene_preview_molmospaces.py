"""MolmoSpaces operator-console scene preview production."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
    HouseholdRuntimeContract,
)
from roboclaws.household.subprocess_backend import MolmoSpacesSubprocessBackend
from roboclaws.launch.worlds import world_spec
from roboclaws.operator_console.scene_preview_b1_camera import (
    _read_molmospaces_backend_state,
    _static_navigation_preview,
)
from roboclaws.operator_console.scene_preview_common import (
    _first_public_waypoint,
    _molmospaces_scene_ref,
    _preview_metadata,
    _public_waypoints,
    _scene_alignment,
    _select_chase_preview,
    _topdown_camera_request,
    _world_slug,
)


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
    spec = world_spec(world_id)
    map_bundle = next(
        (
            value.split("=", 1)[1]
            for value in spec.default_overrides
            if value.startswith("map_bundle=")
        ),
        "",
    )
    if not map_bundle:
        raise ValueError(f"world {world_id} has no map_bundle override")
    map_bundle_dir = Path(map_bundle)
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
