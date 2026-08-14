#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.b1_nurec_scene import prepare_b1_nurec_scene_usd
from roboclaws.household.camera_control import (
    CANONICAL_CAMERA_MODEL,
    canonical_scene_camera_control_request,
    write_camera_control_request,
)

TOPDOWN_RENDER_SCHEMA = "b1_scene_gaussian_topdown_render_v1"
SCENE_TOPDOWN_PICK_SOURCE = "rendered_gaussian_scene_topdown_ray_plane_pick"
DEFAULT_SCENE_USD = Path("data/robot-data-lab/scene-engine/data/2rd_floor_seperated/storey_1")
DEFAULT_SCENE_USD = DEFAULT_SCENE_USD / "scene_gs.usda"
DEFAULT_OUTPUT_DIR = Path("output/b1-map12/scene-gaussian-topdown")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the B1 rebuilt Gaussian scene as a required top-down review image."
    )
    parser.add_argument("--scene-usd", type=Path, default=DEFAULT_SCENE_USD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--width", type=_positive_int_arg, default=960)
    parser.add_argument("--height", type=_positive_int_arg, default=640)
    parser.add_argument(
        "--scene-xy-bounds",
        help="Scene XY bounds as min_x,min_y,max_x,max_y. Required; no inferred fallback.",
    )
    parser.add_argument("--camera-height-m", type=_positive_float_arg, default=28.0)
    parser.add_argument("--camera-y-offset-m", type=_positive_float_arg, default=0.05)
    parser.add_argument("--target-z-m", type=_finite_float_arg, default=0.6)
    parser.add_argument("--fov-deg", type=_vertical_fov_arg, default=65.0)
    parser.add_argument(
        "--camera-mode",
        choices=("near-vertical-topdown", "high-oblique"),
        default="near-vertical-topdown",
    )
    parser.add_argument(
        "--nurec-crop-max-z",
        type=float,
        help=(
            "Explicit review-only NuRec crop max Z. Use this to remove upper volume/roof "
            "occlusion. Omit to render the original Gaussian volume."
        ),
    )
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--capture-one-scene", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--camera-request", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--views-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.capture_one_scene:
        return _capture_one_scene_cli(args)
    if not args.scene_xy_bounds:
        raise ValueError("--scene-xy-bounds is required; no inferred bounds fallback is allowed")

    scene_bounds = _parse_bounds(args.scene_xy_bounds)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_usd = Path(args.scene_usd)
    prepared_scene_usd = prepare_b1_nurec_scene_usd(scene_usd) or scene_usd
    nurec_crop = nurec_crop_not_requested()
    if args.nurec_crop_max_z is not None:
        prepared_scene_usd, nurec_crop = prepare_nurec_crop_max_z_scene_usd(
            prepared_scene_usd,
            crop_max_z=float(args.nurec_crop_max_z),
            output_dir=output_dir,
        )
    request = build_topdown_camera_request(
        scene_bounds=scene_bounds,
        width=int(args.width),
        height=int(args.height),
        camera_height_m=float(args.camera_height_m),
        camera_y_offset_m=float(args.camera_y_offset_m),
        target_z_m=float(args.target_z_m),
        fov_deg=float(args.fov_deg),
        camera_mode=str(args.camera_mode),
    )
    request_path = write_camera_control_request(output_dir / "camera_request.json", request)
    packet = topdown_render_packet(
        scene_usd=scene_usd,
        prepared_scene_usd=prepared_scene_usd,
        scene_bounds=scene_bounds,
        request=request,
        request_path=request_path,
        output_dir=output_dir,
        nurec_crop=nurec_crop,
        capture_result=None,
    )
    if args.capture:
        result_path = output_dir / "capture_result.json"
        capture = _capture_scene(
            scene_usd=prepared_scene_usd,
            camera_request=request_path,
            output_dir=output_dir / "views",
            result_path=result_path,
            width=int(args.width),
            height=int(args.height),
        )
        packet = topdown_render_packet(
            scene_usd=scene_usd,
            prepared_scene_usd=prepared_scene_usd,
            scene_bounds=scene_bounds,
            request=request,
            request_path=request_path,
            output_dir=output_dir,
            nurec_crop=nurec_crop,
            capture_result=capture,
        )
    packet_path = output_dir / "scene_gaussian_topdown.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = validate_topdown_render_packet(packet)
    summary = {
        "schema": TOPDOWN_RENDER_SCHEMA,
        "status": "passed" if not errors else "failed",
        "geometry_status": packet.get("geometry_status"),
        "packet": str(packet_path),
        "topdown_image": packet.get("topdown_image"),
        "errors": errors,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if not errors else 2


def build_topdown_camera_request(
    *,
    scene_bounds: tuple[float, float, float, float],
    width: int,
    height: int,
    camera_height_m: float,
    camera_y_offset_m: float,
    target_z_m: float,
    fov_deg: float,
    camera_mode: str,
) -> dict[str, Any]:
    min_x, min_y, max_x, max_y = scene_bounds
    _require_positive_finite(camera_height_m, "--camera-height-m")
    _require_finite(target_z_m, "--target-z-m")
    _require_vertical_fov(fov_deg)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    span = max(max_x - min_x, max_y - min_y)
    if camera_mode == "high-oblique":
        camera_y_offset = span * 0.55
        camera_mode_label = "high_oblique_topdown_perspective"
        label = "B1 Gaussian scene high-oblique top-down"
    elif camera_mode == "near-vertical-topdown":
        camera_y_offset = float(camera_y_offset_m)
        _require_positive_finite(camera_y_offset, "--camera-y-offset-m")
        camera_mode_label = "near_vertical_topdown_perspective"
        label = "B1 Gaussian scene near-vertical top-down"
    else:
        raise ValueError(f"unsupported camera mode: {camera_mode}")
    view = {
        "view_id": "top2down",
        "label": label,
        "camera_model": CANONICAL_CAMERA_MODEL,
        "coordinate_frame": "b1_rebuilt_scene_usd_world_candidate",
        "coordinate_convention": "b1_rebuilt_scene_usd_world_candidate",
        "camera_mode": camera_mode_label,
        "eye": [
            round(center_x, 6),
            round(center_y - camera_y_offset, 6),
            round(camera_height_m, 6),
        ],
        "target": [round(center_x, 6), round(center_y, 6), round(target_z_m, 6)],
        "up": [0.0, 0.0, 1.0],
        "lens": {"focal_length_mm": 18.0, "vertical_fov_deg": float(fov_deg)},
        "calibration_status": "explicit_scene_xy_bounds_topdown_v1",
        "topdown_camera_policy": {
            "requested_camera_mode": camera_mode,
            "camera_y_offset_m": round(float(camera_y_offset), 6),
            "reason": (
                "Isaac Lab's look-at helper is singular when eye and target share the same "
                "XY under world Z-up, so near-vertical topdown records a tiny explicit XY offset."
            )
            if camera_mode == "near-vertical-topdown"
            else "High-oblique review camera retained only when explicitly requested.",
        },
    }
    request = canonical_scene_camera_control_request(
        [view],
        width=width,
        height=height,
        lens={"focal_length_mm": 18.0, "vertical_fov_deg": float(fov_deg)},
        scene_frame="b1_rebuilt_scene_usd_world_candidate",
        calibration_status="explicit_scene_xy_bounds_topdown_v1",
    )
    request["topdown_scene_xy_bounds"] = _bounds_payload(scene_bounds)
    request["topdown_pixel_to_scene_xyz"] = pixel_to_scene_xyz_transform(
        view=view,
        width=width,
        height=height,
    )
    return request


def topdown_render_packet(
    *,
    scene_usd: Path,
    prepared_scene_usd: Path,
    scene_bounds: tuple[float, float, float, float],
    request: dict[str, Any],
    request_path: Path,
    output_dir: Path,
    nurec_crop: dict[str, Any] | None,
    capture_result: dict[str, Any] | None,
) -> dict[str, Any]:
    image = ""
    capture_result_path = ""
    capture_status = "request_written"
    if capture_result:
        capture_status = "captured" if capture_result.get("ok") is True else "failed"
        capture_result_path = str(capture_result.get("result_path") or "")
        images = capture_result.get("capture", {}).get("images", {})
        image = str(images.get("top2down") or "")
    size = image_size(Path(image))
    return {
        "schema": TOPDOWN_RENDER_SCHEMA,
        "geometry_status": "rendered_gaussian_scene_topdown" if image else "render_required",
        "scene_usd": str(scene_usd),
        "prepared_scene_usd": str(prepared_scene_usd),
        "scene_visibility_policy": nurec_crop or nurec_crop_not_requested(),
        "camera_request": str(request_path),
        "capture_result": capture_result_path,
        "capture_status": capture_status,
        "topdown_image": image,
        "width_px": size[0],
        "height_px": size[1],
        "up_axis": "z",
        "horizontal_axes": ["x", "y"],
        "scene_xy_bounds": _bounds_payload(scene_bounds),
        "pixel_to_scene_xyz": {
            **pixel_to_scene_xyz_transform(
                view=request["views"][0],
                width=int(request["render_resolution"]["width"]),
                height=int(request["render_resolution"]["height"]),
            ),
            "note": (
                "Scene picks intersect the perspective camera ray with z=0 in the "
                "recorded scene frame. Different camera heights/FOVs change visibility "
                "and ray geometry; review the recorded camera request before accepting anchors."
            ),
        },
        "camera": dict(request["views"][0]),
        "output_dir": str(output_dir),
    }


def validate_topdown_render_packet(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if packet.get("schema") != TOPDOWN_RENDER_SCHEMA:
        errors.append("unexpected topdown render schema")
    if packet.get("geometry_status") != "rendered_gaussian_scene_topdown":
        errors.append("topdown render must be captured before review")
    image = Path(str(packet.get("topdown_image") or ""))
    if not image.is_file():
        errors.append("topdown render image missing")
    if int(packet.get("width_px") or 0) <= 0 or int(packet.get("height_px") or 0) <= 0:
        errors.append("topdown render image size missing")
    if packet.get("up_axis") != "z":
        errors.append("topdown render must record up_axis=z")
    if packet.get("horizontal_axes") != ["x", "y"]:
        errors.append("topdown render must record horizontal_axes=[x,y]")
    transform = packet.get("pixel_to_scene_xyz")
    if not isinstance(transform, dict):
        errors.append("topdown render missing pixel_to_scene_xyz")
    elif transform.get("source") != SCENE_TOPDOWN_PICK_SOURCE:
        errors.append("topdown render has unexpected pixel_to_scene_xyz source")
    return errors


def nurec_crop_not_requested() -> dict[str, Any]:
    return {
        "status": "not_requested",
        "source": "original_gaussian_scene_volume",
        "note": "No upper-volume/roof crop was applied.",
    }


def prepare_nurec_crop_max_z_scene_usd(
    prepared_scene_usd: Path,
    *,
    crop_max_z: float,
    output_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    if not math.isfinite(float(crop_max_z)):
        raise ValueError("--nurec-crop-max-z must be finite")
    prepared_scene_usd = Path(prepared_scene_usd)
    prepared_text = prepared_scene_usd.read_text(encoding="utf-8")
    default_ref = _optional_usd_reference(prepared_text, "default.usda")
    if default_ref:
        default_path = _resolve_usd_reference(default_ref, base_dir=prepared_scene_usd.parent)
        return_scene_as_default = False
    else:
        _required_usd_reference(prepared_text, "gauss.usda")
        default_path = prepared_scene_usd
        return_scene_as_default = True
    if not default_path.is_file():
        raise FileNotFoundError(f"NuRec default USD missing for explicit crop: {default_path}")

    default_text = default_path.read_text(encoding="utf-8")
    gauss_ref = _required_usd_reference(default_text, "gauss.usda")
    gauss_path = _resolve_usd_reference(gauss_ref, base_dir=default_path.parent)
    if not gauss_path.is_file():
        raise FileNotFoundError(f"NuRec gauss USD missing for explicit crop: {gauss_path}")
    gauss_text = gauss_path.read_text(encoding="utf-8")
    nurec_ref = _required_nurec_reference(gauss_text)
    nurec_path = _resolve_usd_reference(nurec_ref, base_dir=gauss_path.parent)
    if not nurec_path.is_file():
        raise FileNotFoundError(f"NuRec field asset missing for explicit crop: {nurec_path}")

    crop_dir = output_dir / f"prepared-nurec-crop-max-z-{_safe_float_token(crop_max_z)}"
    cropped_default = crop_dir / "default.usda"
    cropped_gauss = crop_dir / "gauss.usda"
    cropped_scene = crop_dir / "scene_gs.cropped_nurec.usda"
    crop_dir.mkdir(parents=True, exist_ok=True)

    cropped_gauss_text, original_max_bounds = _replace_nurec_crop_max_z(
        gauss_text,
        crop_max_z=float(crop_max_z),
    )
    cropped_gauss_text = cropped_gauss_text.replace(
        f"@{nurec_ref}@",
        f"@{nurec_path.resolve().as_posix()}@",
    )
    cropped_default_text = default_text.replace(
        f"@{gauss_ref}@",
        f"@{cropped_gauss.resolve().as_posix()}@",
    )
    if return_scene_as_default:
        returned_scene = cropped_default
    else:
        returned_scene = cropped_scene
        cropped_scene_text = prepared_text.replace(
            f"@{default_ref}@",
            f"@{cropped_default.resolve().as_posix()}@",
        )
        _write_if_changed(cropped_scene, cropped_scene_text)
    _write_if_changed(cropped_default, cropped_default_text)
    _write_if_changed(cropped_gauss, cropped_gauss_text)
    return returned_scene, {
        "status": "applied",
        "source": "explicit_nurec_crop_max_z",
        "crop_max_z": round(float(crop_max_z), 9),
        "original_crop_max_bounds": original_max_bounds,
        "cropped_scene_usd": str(returned_scene),
        "cropped_default_usd": str(cropped_default),
        "cropped_gauss_usd": str(cropped_gauss),
        "source_scene_usd": str(prepared_scene_usd),
        "source_default_usd": str(default_path),
        "source_gauss_usd": str(gauss_path),
        "source_nurec_asset": str(nurec_path),
    }


def _required_usd_reference(text: str, filename: str) -> str:
    ref = _optional_usd_reference(text, filename)
    if not ref:
        raise ValueError(f"required USD reference missing: {filename}")
    return ref


def _optional_usd_reference(text: str, filename: str) -> str:
    pattern = re.compile(rf"@([^@\n]*{re.escape(filename)})@")
    match = pattern.search(text)
    if not match:
        return ""
    return str(match.group(1))


def _resolve_usd_reference(reference: str, *, base_dir: Path) -> Path:
    path = Path(reference)
    if path.is_absolute():
        return path
    return base_dir / path


def _required_nurec_reference(text: str) -> str:
    pattern = re.compile(r"@([^@\n]*\.nurec)@")
    match = pattern.search(text)
    if not match:
        raise ValueError("NuRec field asset reference missing; cannot apply explicit roof crop")
    return str(match.group(1))


def _replace_nurec_crop_max_z(
    gauss_text: str,
    *,
    crop_max_z: float,
) -> tuple[str, list[float]]:
    pattern = re.compile(
        r"(custom float3 omni:nurec:crop:maxBounds = \(\s*)"
        r"([^,\)]+),\s*([^,\)]+),\s*([^,\)]+)"
        r"(\s*\))"
    )
    match = pattern.search(gauss_text)
    if not match:
        raise ValueError("NuRec crop maxBounds missing; cannot apply explicit roof crop")
    original = [float(match.group(index).strip()) for index in (2, 3, 4)]
    replacement = (
        f"{match.group(1)}{original[0]:.9g}, {original[1]:.9g}, "
        f"{float(crop_max_z):.9g}{match.group(5)}"
    )
    return pattern.sub(replacement, gauss_text, count=1), original


def _safe_float_token(value: float) -> str:
    return f"{float(value):.3f}".replace("-", "m").replace(".", "p")


def _write_if_changed(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _capture_scene(
    *,
    scene_usd: Path,
    camera_request: Path,
    output_dir: Path,
    result_path: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--capture-one-scene",
        "--scene-usd",
        str(scene_usd),
        "--camera-request",
        str(camera_request),
        "--views-dir",
        str(output_dir),
        "--result",
        str(result_path),
        "--width",
        str(width),
        "--height",
        str(height),
    ]
    env = os.environ.copy()
    env.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")
    env["ROBOCLAWS_HARD_EXIT_AFTER_ISAAC_CAPTURE"] = "1"
    subprocess.run(command, cwd=Path(__file__).resolve().parents[2], env=env, check=True)
    payload = read_json_object(result_path, label="gaussian topdown capture result")
    payload["result_path"] = str(result_path)
    return payload


def _capture_one_scene_cli(args: argparse.Namespace) -> int:
    if args.camera_request is None or args.views_dir is None or args.result is None:
        raise ValueError("--capture-one-scene requires --camera-request, --views-dir, and --result")
    request = read_json_object(args.camera_request, label="camera request")
    from roboclaws.backends.isaaclab import runtime_camera

    args.result.parent.mkdir(parents=True, exist_ok=True)
    try:
        capture = runtime_camera.capture_scene_camera_views(
            scene_usd=args.scene_usd,
            camera_request=request,
            output_dir=args.views_dir,
            width=int(args.width),
            height=int(args.height),
            semantic_pose_state={},
        )
        payload = {"ok": True, "scene_usd": str(args.scene_usd), "capture": capture}
    except Exception as exc:
        payload = {
            "ok": False,
            "scene_usd": str(args.scene_usd),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        args.result.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        raise
    args.result.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0


def pixel_to_scene_xyz_transform(
    *,
    view: dict[str, Any],
    width: int,
    height: int,
) -> dict[str, Any]:
    lens = view.get("lens") if isinstance(view.get("lens"), dict) else {}
    return {
        "status": "perspective_ray_plane_z0",
        "source": SCENE_TOPDOWN_PICK_SOURCE,
        "projection_model": "camera_ray_intersection_with_z_plane",
        "z_plane": 0.0,
        "width_px": int(width),
        "height_px": int(height),
        "vertical_fov_deg": float(lens.get("vertical_fov_deg") or 65.0),
        "eye": list(view.get("eye") or []),
        "target": list(view.get("target") or []),
        "world_up": [0.0, 0.0, 1.0],
        "formula": "ray = perspective_camera_ray(pixel); scene_xyz = ray intersect z=0",
    }


def _parse_bounds(value: str) -> tuple[float, float, float, float]:
    parts = [float(item.strip()) for item in value.split(",") if item.strip()]
    if len(parts) != 4:
        raise ValueError("--scene-xy-bounds must be min_x,min_y,max_x,max_y")
    min_x, min_y, max_x, max_y = parts
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("--scene-xy-bounds min values must be less than max values")
    return min_x, min_y, max_x, max_y


def _bounds_payload(bounds: tuple[float, float, float, float]) -> dict[str, float]:
    min_x, min_y, max_x, max_y = bounds
    return {
        "min_x": round(float(min_x), 9),
        "min_y": round(float(min_y), 9),
        "max_x": round(float(max_x), 9),
        "max_y": round(float(max_y), 9),
    }


def image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


def _positive_float_arg(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive float; got {value!r}") from None
    try:
        _require_positive_finite(parsed, "value")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive float; got {value!r}") from None
    return parsed


def _finite_float_arg(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a finite float; got {value!r}") from None
    try:
        _require_finite(parsed, "value")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a finite float; got {value!r}") from None
    return parsed


def _vertical_fov_arg(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a vertical FOV in degrees from 1 to 179; got {value!r}"
        ) from None
    try:
        _require_vertical_fov(parsed)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a vertical FOV in degrees from 1 to 179; got {value!r}"
        ) from None
    return parsed


def _require_positive_finite(value: float, label: str) -> None:
    if not math.isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{label} must be a positive finite number")


def _require_finite(value: float, label: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{label} must be finite")


def _require_vertical_fov(value: float) -> None:
    if not math.isfinite(float(value)) or not 1.0 <= float(value) <= 179.0:
        raise ValueError("--fov-deg must be a finite value from 1 to 179 degrees")


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if os.environ.get("ROBOCLAWS_HARD_EXIT_AFTER_ISAAC_CAPTURE") == "1":
        os._exit(code)
    raise SystemExit(code)
