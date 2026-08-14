from __future__ import annotations

import argparse
from pathlib import Path


def build_arg_parser(
    *,
    default_render_width: int,
    default_render_height: int,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MolmoSpaces JSON worker for roboclaws.")
    parser.add_argument("--state-path", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_init_parser(subparsers)
    _add_snapshot_parser(subparsers, default_render_width, default_render_height)
    _add_robot_views_parser(subparsers, default_render_width, default_render_height)
    _add_camera_views_parser(subparsers, default_render_width, default_render_height)
    _add_action_parsers(subparsers)
    return parser


def _add_init_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    init = subparsers.add_parser("init")
    init.add_argument("--seed", type=int, default=7)
    init.add_argument("--scene-source", default="procthor-10k-val")
    init.add_argument("--scene-index", type=int, default=0)
    init.add_argument("--include-robot", action="store_true")
    init.add_argument("--robot-name", default="rby1m")
    init.add_argument("--generated-mess-count", type=int, default=5)
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


def _add_snapshot_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    default_width: int,
    default_height: int,
) -> None:
    subparsers.add_parser("observe")
    subparsers.add_parser("locations")
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output-path", type=Path, required=True)
    snapshot.add_argument("--title", default="")
    snapshot.add_argument("--render-width", type=_positive_int_arg, default=default_width)
    snapshot.add_argument("--render-height", type=_positive_int_arg, default=default_height)


def _add_robot_views_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
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


def _add_camera_views_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    default_width: int,
    default_height: int,
) -> None:
    camera_views = subparsers.add_parser("camera_views")
    camera_views.add_argument("--output-dir", type=Path, required=True)
    camera_views.add_argument("--view-specs-path", type=Path)
    camera_views.add_argument("--camera-request-path", type=Path)
    camera_views.add_argument("--render-width", type=_positive_int_arg, default=default_width)
    camera_views.add_argument("--render-height", type=_positive_int_arg, default=default_height)


def _add_action_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    navigate_object = subparsers.add_parser("navigate_to_object")
    navigate_object.add_argument("--object-id", required=True)

    navigate_waypoint = subparsers.add_parser("navigate_to_waypoint")
    navigate_waypoint.add_argument("--waypoint-json", required=True)

    navigate_relative = subparsers.add_parser("navigate_to_relative_pose")
    navigate_relative.add_argument("--forward-m", type=float, default=0.0)
    navigate_relative.add_argument("--lateral-m", type=float, default=0.0)
    navigate_relative.add_argument("--yaw-delta-deg", type=float, default=0.0)

    navigate_receptacle = subparsers.add_parser("navigate_to_receptacle")
    navigate_receptacle.add_argument("--receptacle-id", required=True)

    frame_comparison_object_parser = subparsers.add_parser("frame_comparison_object")
    frame_comparison_object_parser.add_argument("--object-id", required=True)

    pick = subparsers.add_parser("pick")
    pick.add_argument("--object-id", required=True)

    open_receptacle_parser = subparsers.add_parser("open_receptacle")
    open_receptacle_parser.add_argument("--receptacle-id", required=True)

    close_receptacle_parser = subparsers.add_parser("close_receptacle")
    close_receptacle_parser.add_argument("--receptacle-id", required=True)

    place = subparsers.add_parser("place")
    place.add_argument("--receptacle-id", required=True)

    place_inside_parser = subparsers.add_parser("place_inside")
    place_inside_parser.add_argument("--receptacle-id", required=True)

    done = subparsers.add_parser("done")
    done.add_argument("--reason", default="")

    subparsers.add_parser("serve")


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer; got {value!r}")
    return parsed
