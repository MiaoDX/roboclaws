"""Isaac Lab backend runtime support."""

from __future__ import annotations

import argparse
from pathlib import Path

from roboclaws.core.json_sources import parse_json_object_text


def build_arg_parser(
    *,
    default_width: int,
    default_height: int,
    generated_scene_kinds: tuple[str, ...],
    segmentation_data_types: tuple[str, ...],
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isaac Lab cleanup backend worker for Roboclaws.")
    parser.add_argument("--state-path", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_init_parser(
        subparsers,
        generated_scene_kinds=generated_scene_kinds,
        segmentation_data_types=segmentation_data_types,
    )
    _add_state_read_parsers(subparsers)
    _add_snapshot_parser(subparsers, default_width=default_width, default_height=default_height)
    _add_robot_views_parser(subparsers, default_width=default_width, default_height=default_height)
    _add_camera_views_parser(subparsers, default_width=default_width, default_height=default_height)
    _add_action_parsers(subparsers)
    return parser


def _add_init_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    generated_scene_kinds: tuple[str, ...],
    segmentation_data_types: tuple[str, ...],
) -> None:
    init = subparsers.add_parser("init")
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--seed", type=int, default=7)
    init.add_argument("--scene-source", default="procthor-10k-val")
    init.add_argument("--scene-index", type=int, default=0)
    init.add_argument("--generated-mess-count", type=int, default=1)
    init.add_argument(
        "--generated-mess-object-id",
        action="append",
        help="Private run-control object id to include in the generated mess set. Repeatable.",
    )
    init.add_argument(
        "--generated-mess-manifest-path",
        type=Path,
        help="Private backend-neutral generated mess manifest to apply during init.",
    )
    init.add_argument(
        "--generated-scene-kind",
        choices=generated_scene_kinds,
        default="roboclaws_smoke",
        help=(
            "Generated USD control scene to write when --scene-usd-path is omitted. "
            "Use isaac_official_blocks to probe NVIDIA Isaac sample assets."
        ),
    )
    init.add_argument("--runtime-mode", choices=("real", "fake"), default="real")
    init.add_argument("--include-robot", action="store_true")
    init.add_argument("--robot-name", default="rby1m")
    init.add_argument("--map-bundle-dir", type=Path)
    init.add_argument(
        "--enable-segmentation",
        action="store_true",
        help="Request Isaac semantic/instance segmentation tensors during real RGB capture.",
    )
    init.add_argument(
        "--segmentation-data-type",
        action="append",
        choices=segmentation_data_types,
        help=(
            "Isaac segmentation data type to request. Repeat to probe individual "
            "annotators; defaults to all supported segmentation data types."
        ),
    )
    init.add_argument(
        "--segmentation-semantic-filter",
        action="append",
        help=(
            "Semantic label instance name to request from Isaac camera semantic filters. "
            "Repeat to probe class vs usd_prim_path labels; defaults to class."
        ),
    )
    init.add_argument(
        "--scene-usd-path",
        type=Path,
        help=(
            "Optional local USD/USDA scene to load in real mode. Use this for "
            "MolmoSpaces Isaac scene parity once a scene shard is available locally."
        ),
    )


def _add_state_read_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    subparsers.add_parser("locations")
    subparsers.add_parser("observe")


def _add_snapshot_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    default_width: int,
    default_height: int,
) -> None:
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output-path", type=Path, required=True)
    snapshot.add_argument("--title", required=True)
    snapshot.add_argument("--render-width", type=_positive_int_arg, default=default_width)
    snapshot.add_argument("--render-height", type=_positive_int_arg, default=default_height)


def _add_robot_views_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    default_width: int,
    default_height: int,
) -> None:
    robot_views = subparsers.add_parser("robot_views")
    robot_views.add_argument("--output-dir", type=Path, required=True)
    robot_views.add_argument("--label", required=True)
    robot_views.add_argument("--focus-object-id")
    robot_views.add_argument("--focus-receptacle-id")
    robot_views.add_argument("--camera-yaw-offset-deg", type=float, default=0.0)
    robot_views.add_argument("--camera-pitch-offset-deg", type=float, default=0.0)
    robot_views.add_argument("--render-width", type=_positive_int_arg, default=default_width)
    robot_views.add_argument("--render-height", type=_positive_int_arg, default=default_height)
    robot_views.add_argument(
        "--render-settle-frames",
        type=_non_negative_int_arg,
        default=0,
        help=(
            "Extra Isaac render frames to advance after the first nonblank RGB tensor before "
            "saving robot-view images. This is an opt-in capture-quality probe control."
        ),
    )
    robot_views.add_argument(
        "--isaac-aa-op",
        type=int,
        help=(
            "Optional Isaac /rtx/post/aa/op value for an opt-in capture-quality probe. "
            "The worker records the previous value and restores it after capture."
        ),
    )
    robot_views.add_argument(
        "--isaac-tonemap-op",
        type=int,
        help=(
            "Optional Isaac /rtx/post/tonemap/op value for an opt-in native tone probe. "
            "The worker records the previous value and restores it after capture."
        ),
    )
    robot_views.add_argument(
        "--isaac-exposure-bias",
        type=float,
        help=(
            "Optional Isaac /rtx/post/tonemap/exposureBias value for an opt-in native "
            "exposure probe. The worker records the previous value and restores it after "
            "capture."
        ),
    )
    robot_views.add_argument(
        "--isaac-colorcorr-gain",
        type=_parse_rgb_gain,
        help=(
            "Optional Isaac /rtx/post/colorcorr gain as R,G,B for an opt-in native color "
            "correction probe. The worker enables color correction, records previous values, "
            "and restores them after capture."
        ),
    )


def _add_camera_views_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    default_width: int,
    default_height: int,
) -> None:
    camera_views = subparsers.add_parser("camera_views")
    camera_views.add_argument("--output-dir", type=Path, required=True)
    camera_views.add_argument("--view-specs-path", type=Path)
    camera_views.add_argument("--camera-request-path", type=Path)
    camera_views.add_argument("--render-width", type=_positive_int_arg, default=default_width)
    camera_views.add_argument("--render-height", type=_positive_int_arg, default=default_height)


def _add_action_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    object_cmds = ("navigate_to_object", "pick")
    for command in object_cmds:
        item = subparsers.add_parser(command)
        item.add_argument("--object-id", required=True)

    receptacle_cmds = (
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    )
    for command in receptacle_cmds:
        item = subparsers.add_parser(command)
        item.add_argument("--receptacle-id", required=True)

    waypoint = subparsers.add_parser("navigate_to_waypoint")
    waypoint.add_argument(
        "--waypoint-json",
        type=_parse_json_object,
        required=True,
        help="Public waypoint payload from the cleanup map contract.",
    )

    relative = subparsers.add_parser("navigate_to_relative_pose")
    relative.add_argument("--forward-m", type=float, default=0.0)
    relative.add_argument("--lateral-m", type=float, default=0.0)
    relative.add_argument("--yaw-delta-deg", type=float, default=0.0)

    done = subparsers.add_parser("done")
    done.add_argument("--reason", default="")


def _parse_rgb_gain(value: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in str(value).split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("RGB gain must be three comma-separated floats")
    try:
        red, green, blue = (float(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("RGB gain must contain only floats") from exc
    gain = (red, green, blue)
    if any(item <= 0.0 for item in gain):
        raise argparse.ArgumentTypeError("RGB gain values must be positive")
    return gain


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed


def _non_negative_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a non-negative integer; got {value!r}"
        ) from None
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer; got {value!r}")
    return parsed


def _parse_json_object(value: str) -> dict[str, object]:
    try:
        return parse_json_object_text(value, label="Isaac worker inline JSON")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
