from __future__ import annotations

import argparse

from roboclaws.household.cleanup_validation_args import (
    _reject_legacy_robot_view_camera_control_flag,
    build_parser,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    parser.add_argument("--require-advisory-scoring", action="store_true")
    args = parser.parse_args(argv)
    _reject_legacy_robot_view_camera_control_flag(parser, args)
    return args
