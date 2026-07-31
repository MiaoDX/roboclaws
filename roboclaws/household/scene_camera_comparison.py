from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from roboclaws.core import nvidia_eula as eula
from roboclaws.household import (
    scene_camera_capture,
    scene_camera_geometry_contract,
    scene_camera_render_domain,
    scene_camera_report,
)
from roboclaws.household.artifact_paths import output_relpath
from roboclaws.household.camera_control import (
    CAMERA_CONTROL_API_NAME,
    CANONICAL_CAMERA_MODEL,
    CANONICAL_POSE_CALIBRATION,
    DEFAULT_SCENE_PROBE_COLOR_PROFILE,
    DEFAULT_SCENE_PROBE_LENS,
    MOLMOSPACES_SCENE_FRAME,
    SCENE_PROBE_LIGHTING_PROFILES,
    canonical_scene_camera_control_request,
    write_camera_control_request,
)

SCENE_CAMERA_COMPARISON_SCHEMA = "molmospaces_isaac_scene_camera_comparison_v1"
MOLMOSPACES_LANE_ID = scene_camera_render_domain.MOLMOSPACES_LANE_ID
ISAAC_LANE_ID = scene_camera_render_domain.ISAAC_LANE_ID
DEFAULT_RENDER_WIDTH = 960
DEFAULT_RENDER_HEIGHT = 640


@dataclass(frozen=True)
class SceneCameraComparisonConfig:
    output_dir: Path
    scene_usd_path: Path
    seed: int = 7
    generated_mess_count: int = 1
    scene_source: str = "procthor-10k-val"
    scene_index: int = 1
    molmospaces_python: Path = Path(".venv/bin/python")
    isaac_python: Path = Path(".venv-isaaclab/bin/python")
    render_width: int = DEFAULT_RENDER_WIDTH
    render_height: int = DEFAULT_RENDER_HEIGHT
    lighting_profile_id: str = "default"


def _scene_camera_lighting_profile(profile_id: str) -> dict[str, Any]:
    key = str(profile_id or "default")
    profile = SCENE_PROBE_LIGHTING_PROFILES.get(key)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(SCENE_PROBE_LIGHTING_PROFILES))
        raise ValueError(f"unknown scene-camera lighting profile {key!r}; available: {available}")
    return dict(profile)


def run_scene_camera_comparison(config: SceneCameraComparisonConfig) -> dict[str, Any]:
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    lighting_profile = _scene_camera_lighting_profile(config.lighting_profile_id)
    manifest: dict[str, Any] = {
        "schema": SCENE_CAMERA_COMPARISON_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "purpose": (
            "Render-only scene identity probe. This does not execute household cleanup, "
            "pick, place, or scoring."
        ),
        "scene": {
            "scene_source": config.scene_source,
            "scene_index": config.scene_index,
            "seed": config.seed,
            "generated_mess_count": config.generated_mess_count,
            "scene_usd_path": str(config.scene_usd_path),
            "render_width": config.render_width,
            "render_height": config.render_height,
            "lighting_profile_id": str(lighting_profile.get("profile_id") or ""),
        },
        "camera_control": {
            "api_name": CAMERA_CONTROL_API_NAME,
            "camera_model": CANONICAL_CAMERA_MODEL,
            "coordinate_frame": MOLMOSPACES_SCENE_FRAME,
            "lens": dict(DEFAULT_SCENE_PROBE_LENS),
            "lighting_profile": dict(lighting_profile),
            "color_profile": dict(DEFAULT_SCENE_PROBE_COLOR_PROFILE),
            "calibration_status": CANONICAL_POSE_CALIBRATION,
            "calibration_note": (
                "One Roboclaws camera-control request carries explicit eye/target/up poses "
                "in the MolmoSpaces scene frame. Backends apply their registered scene-frame "
                "transform internally; the report records fit residuals instead of hiding "
                "camera mismatch behind lane-local orbit overrides."
            ),
            "request_artifact": "camera_control_request.json",
        },
        "frame_mapping_note": (
            "The canonical camera frame is the MolmoSpaces scene frame. Prepared-USD candidate "
            "lanes render the same explicit eye/target/up request for both room-level and "
            "object-anchor views. The report also records USD-bounds residuals for matched "
            "anchors. If residuals are high, the artifact is evidence of a target-definition "
            "or scene geometry mismatch rather than proof of full backend-swappable visual "
            "parity."
        ),
        "official_molmospaces_source": scene_camera_capture._official_molmospaces_source(),
        "room_camera_views": [],
        "anchors": [],
        "view_specs": {},
        "lane_registry": {
            "baseline": MOLMOSPACES_LANE_ID,
            "candidates": [ISAAC_LANE_ID],
            "diagnostic_baseline": MOLMOSPACES_LANE_ID,
            "pairwise_diagnostic_candidate": ISAAC_LANE_ID,
            "candidate_diagnostic_note": (
                "Current scene-camera comparison is the MuJoCo-to-Isaac render parity probe. "
                "Retired third-party render artifacts are historical evidence, not active lanes."
            ),
        },
        "lanes": {},
        "artifacts": {
            "comparison_manifest": "comparison_manifest.json",
            "report": "report.html",
        },
    }

    molmo = scene_camera_capture._capture_molmospaces_lane(config)
    manifest["lanes"][MOLMOSPACES_LANE_ID] = molmo
    molmo_state = molmo.pop("_state", {}) if isinstance(molmo, dict) else {}
    if isinstance(molmo, dict) and isinstance(molmo_state, dict):
        molmo["runtime_object_positions"] = scene_camera_capture._runtime_object_positions(
            molmo_state
        )
        molmo["runtime_render_state"] = scene_camera_capture._runtime_render_state(molmo_state)
    anchors = scene_camera_capture._scene_anchors(molmo_state, limit=4)
    manifest["anchors"] = anchors
    room_views = scene_camera_capture._room_camera_control_views(molmo_state)
    manifest["room_camera_views"] = room_views
    molmo_specs = scene_camera_capture._molmospaces_view_specs(anchors, molmo_state=molmo_state)
    isaac_specs = scene_camera_capture._isaac_view_specs(
        anchors,
        scene_usd_path=config.scene_usd_path,
        scene_index=config.scene_index,
    )
    scene_transform = scene_camera_geometry_contract.identity_scene_frame_transform()
    anchor_views = scene_camera_capture._canonical_camera_control_views(
        anchors,
        molmo_specs=molmo_specs,
        isaac_specs=isaac_specs,
        scene_transform=scene_transform,
    )
    canonical_views = [*room_views, *anchor_views]
    camera_request = canonical_scene_camera_control_request(
        canonical_views,
        width=config.render_width,
        height=config.render_height,
        lens=DEFAULT_SCENE_PROBE_LENS,
        lighting_profile=lighting_profile,
        color_profile=DEFAULT_SCENE_PROBE_COLOR_PROFILE,
    )
    if isinstance(molmo.get("runtime_object_positions"), dict):
        camera_request["runtime_object_positions"] = molmo["runtime_object_positions"]
        camera_request["runtime_object_position_source"] = MOLMOSPACES_LANE_ID
    if isinstance(molmo.get("runtime_render_state"), dict):
        camera_request["runtime_render_state"] = molmo["runtime_render_state"]
        camera_request["runtime_render_state_source"] = MOLMOSPACES_LANE_ID
    camera_request_path = write_camera_control_request(
        output_dir / "camera_control_request.json",
        camera_request,
    )
    manifest["camera_control"]["request_artifact"] = output_relpath(camera_request_path, output_dir)
    manifest["view_specs"] = {
        "room-level-canonical": room_views,
        MOLMOSPACES_LANE_ID: molmo_specs,
        ISAAC_LANE_ID: isaac_specs,
    }
    manifest["scene_frame_transform"] = scene_transform
    manifest["canonical_camera_views"] = canonical_views
    manifest["camera_control"]["view_count"] = len(camera_request.get("views") or [])
    manifest["camera_control"]["same_pose_contract"] = True
    if molmo.get("status") == "success" and canonical_views:
        molmo.update(
            scene_camera_capture._capture_molmospaces_camera_views(
                config,
                camera_request_path=camera_request_path,
                lane_dir=output_dir / "molmospaces",
            )
        )
    manifest["lanes"][ISAAC_LANE_ID] = scene_camera_capture._capture_isaac_lane(
        config,
        camera_request_path=camera_request_path,
        lane_dir=output_dir / "isaaclab",
    )
    manifest["camera_pose_contract"] = (
        scene_camera_geometry_contract.camera_pose_contract_from_capture(
            canonical_views=canonical_views,
            molmospaces_lane=molmo,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    manifest["camera_intrinsics_contract"] = (
        scene_camera_geometry_contract.camera_intrinsics_contract_from_capture(
            requested_lens=camera_request.get("lens"),
            requested_resolution=camera_request.get("render_resolution"),
            molmospaces_lane=molmo,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    manifest["room_scale_contract"] = (
        scene_camera_geometry_contract.room_scale_contract_from_scene_capture(
            room_views=room_views,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    manifest["scene_frame_transform"] = (
        scene_camera_geometry_contract.scene_frame_transform_from_capture(
            canonical_views=canonical_views,
            isaac_lane=manifest["lanes"][ISAAC_LANE_ID],
        )
    )
    scene_camera_report._hydrate_manifest_diagnostics(manifest, output_dir=output_dir)
    scene_camera_report._write_contact_sheet(manifest, output_dir=output_dir)
    manifest_path = output_dir / "comparison_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    scene_camera_report.render_scene_camera_comparison_report(manifest, output_dir=output_dir)
    return manifest


def default_output_dir() -> Path:
    stamp = datetime.now().astimezone().strftime("%m%d_%H%M")
    return Path("output/molmo/scene-camera-comparison") / stamp


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=("Render the same MolmoSpaces scene anchors through MuJoCo and Isaac.")
    )
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--scene-usd-path", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generated-mess-count", type=int, default=1)
    parser.add_argument("--scene-source", default="procthor-10k-val")
    parser.add_argument("--scene-index", type=int, default=1)
    parser.add_argument("--molmospaces-python", type=Path, default=Path(".venv/bin/python"))
    parser.add_argument("--isaac-python", type=Path, default=Path(".venv-isaaclab/bin/python"))
    parser.add_argument("--render-width", type=_positive_int_arg, default=DEFAULT_RENDER_WIDTH)
    parser.add_argument("--render-height", type=_positive_int_arg, default=DEFAULT_RENDER_HEIGHT)
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    parser.add_argument(
        "--lighting-profile",
        default="default",
        choices=tuple(sorted(SCENE_PROBE_LIGHTING_PROFILES)),
        help=(
            "Scene-camera lighting profile. Use shadow-parity for a probe run; "
            "default uses the shared scene_light_rig_v1 single-key review profile."
        ),
    )
    args = parser.parse_args(argv)

    if not args.scene_usd_path.is_file():
        parser.error(f"missing prepared scene USD: {args.scene_usd_path}")
    if not eula.accepted(explicit=args.accept_nvidia_eula):
        parser.error(eula.required_message("scene camera comparison"))
    eula.record_acceptance()
    manifest = run_scene_camera_comparison(
        SceneCameraComparisonConfig(
            output_dir=args.output_dir,
            scene_usd_path=args.scene_usd_path,
            seed=args.seed,
            generated_mess_count=args.generated_mess_count,
            scene_source=args.scene_source,
            scene_index=args.scene_index,
            molmospaces_python=args.molmospaces_python,
            isaac_python=args.isaac_python,
            render_width=args.render_width,
            render_height=args.render_height,
            lighting_profile_id=args.lighting_profile,
        )
    )
    print(f"scene camera comparison manifest: {args.output_dir / 'comparison_manifest.json'}")
    print(f"scene camera comparison report: {args.output_dir / 'report.html'}")
    if scene_camera_report.comparison_successful(manifest):
        return 0
    print("scene camera comparison failed:", file=sys.stderr)
    for summary in scene_camera_report.failed_lane_summaries(manifest):
        print(f"  {summary}", file=sys.stderr)
    return 1


def _positive_int_arg(value: str) -> int:
    import argparse

    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
