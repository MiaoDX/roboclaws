from __future__ import annotations

import argparse
from pathlib import Path

LEGACY_ROBOT_VIEW_CAMERA_CONTROL_FLAG = "--require-canonical-robot-view-camera-control"


def _add_core_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path, help="run_result.json or a directory of seed-* runs")
    parser.add_argument("--expect-task")
    parser.add_argument("--expect-task-name")
    parser.add_argument("--expect-backend")
    parser.add_argument("--expect-policy")
    parser.add_argument("--expect-profile", help="Expected cleanup evidence lane or smoke preset.")
    parser.add_argument("--expect-mcp-server")
    parser.add_argument("--expect-seeds")
    parser.add_argument("--min-generated-mess-count", type=int, default=1)
    parser.add_argument("--require-agent-driven", action="store_true")
    parser.add_argument("--require-clean-agent-run", action="store_true")
    parser.add_argument(
        "--allow-partial-cleanup",
        action="store_true",
        help="Validate contract/report evidence without requiring cleanup success.",
    )
    parser.add_argument("--require-robot-views", action="store_true")


def _add_evidence_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-raw-fpv-observations", action="store_true")
    parser.add_argument("--require-camera-model-policy", action="store_true")
    parser.add_argument("--require-runtime-metric-map", action="store_true")
    parser.add_argument("--require-goal-contract", action="store_true")
    parser.add_argument("--require-completion-claim", action="store_true")
    parser.add_argument("--require-map-build", action="store_true")
    parser.add_argument("--require-agibot-g2-hardware", action="store_true")
    parser.add_argument("--require-base-metric-map", action="store_true")
    parser.add_argument("--expect-visual-grounding-pipeline")
    parser.add_argument("--require-visual-grounding-failure", action="store_true")
    parser.add_argument("--require-model-declared-observations", action="store_true")
    parser.add_argument("--min-model-declared-observations", type=int, default=1)
    parser.add_argument("--min-model-declared-actions", type=int, default=0)
    parser.add_argument("--min-restored-count", type=int, default=None)
    parser.add_argument("--min-semantic-accepted-count", type=int, default=None)
    parser.add_argument("--min-sweep-coverage", type=float, default=None)
    parser.add_argument(
        "--min-adjust-camera-count",
        type=int,
        default=0,
        help="Require at least this many adjust_camera tool requests for adaptive proof runs.",
    )
    parser.add_argument(
        "--expect-map-build-scan-profile",
        help="Require the map-build scan profile id, normally fixture-focused.",
    )
    parser.add_argument(
        "--min-map-build-body-turn-count",
        type=int,
        default=0,
        help="Require at least this many navigate_to_relative_pose requests for map-build scans.",
    )
    parser.add_argument(
        "--min-generated-target-inspection-candidates",
        type=int,
        default=0,
        help=(
            "Require at least this many public generated target-inspection candidates "
            "for adaptive proof runs."
        ),
    )


def _add_planner_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-planner-proof-attachment", action="store_true")
    parser.add_argument("--require-planner-proof-quality", action="store_true")
    parser.add_argument(
        "--require-planner-proof-min-steps",
        type=int,
        default=None,
        help="Require every attached planner proof to execute at least this many steps.",
    )
    parser.add_argument("--accept-blocked-planner-cleanup-primitives", action="store_true")
    parser.add_argument("--require-planner-backed-cleanup-primitives", action="store_true")
    parser.add_argument(
        "--require-bound-planner-cleanup-object",
        action="append",
        default=[],
        metavar="OBJECT_ID:TARGET_RECEPTACLE_ID",
        help=(
            "Require one cleanup object/target pair to have all cleanup subphases "
            "strictly planner_backed. Repeat for multiple bound objects."
        ),
    )
    parser.add_argument(
        "--require-mixed-planner-cleanup-primitives",
        action="store_true",
        help=(
            "Require a partial rerun state: at least one bound planner-backed "
            "object and at least one unmatched api_semantic object, with the "
            "global primitive gate still blocked."
        ),
    )
    parser.add_argument("--accept-blocked-planner-cleanup-bridge", action="store_true")
    parser.add_argument("--require-planner-cleanup-bridge-ready", action="store_true")
    parser.add_argument("--require-waypoint-honesty", action="store_true")
    parser.add_argument("--require-real-robot-alignment", action="store_true")
    parser.add_argument("--require-b1-robot-consumption-proof", action="store_true")


def _add_isaac_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--require-isaac-runtime", action="store_true")
    parser.add_argument("--require-isaac-real-runtime", action="store_true")
    parser.add_argument("--require-isaac-scene-loaded", action="store_true")
    parser.add_argument("--require-isaac-local-scene-usd", action="store_true")
    parser.add_argument("--require-isaac-selected-usd-bindings", action="store_true")
    parser.add_argument("--require-isaac-semantic-pose", action="store_true")
    parser.add_argument("--require-isaac-robot-view-provenance", action="store_true")
    parser.add_argument("--require-isaac-segmentation-evidence", action="store_true")
    parser.add_argument("--require-isaac-snapshot-provenance", action="store_true")
    parser.add_argument(
        "--require-isaac-scene-index-map-context",
        action="store_true",
        help=(
            "Require Isaac scene-index cleanup runs to expose map/waypoint context "
            "generated from the loaded scene instead of a stale prebuilt map bundle."
        ),
    )


def _add_robot_camera_checker_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        LEGACY_ROBOT_VIEW_CAMERA_CONTROL_FLAG,
        action="store_true",
        dest="unsupported_legacy_robot_view_camera_control",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--require-robot-head-camera-fpv",
        action="store_true",
        help=(
            "Require every cleanup agent-facing FPV view to come from a robot-mounted "
            "head camera or an explicit backend head-camera-equivalent contract."
        ),
    )


def reject_legacy_robot_view_camera_control_flag(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    if args.unsupported_legacy_robot_view_camera_control:
        parser.error(
            f"{LEGACY_ROBOT_VIEW_CAMERA_CONTROL_FLAG} is obsolete; "
            "use --require-robot-head-camera-fpv."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate ADR-0003 real-world-style Molmo cleanup artifacts."
    )
    _add_core_checker_args(parser)
    _add_evidence_checker_args(parser)
    _add_planner_checker_args(parser)
    _add_isaac_checker_args(parser)
    _add_robot_camera_checker_args(parser)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    reject_legacy_robot_view_camera_control_flag(parser, args)
    return args
