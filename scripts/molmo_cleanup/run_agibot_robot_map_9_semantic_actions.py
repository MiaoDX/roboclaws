#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.household.agibot_map_bundle import (  # noqa: E402
    AGIBOT_MAP_BUNDLE_PROVENANCE,
    write_agibot_nav2_map_bundle,
)
from roboclaws.household.agibot_map_defaults import (  # noqa: E402
    DEFAULT_AGIBOT_CONFIDENCE_LAYER,
    DEFAULT_AGIBOT_ENVIRONMENT_ID,
    DEFAULT_AGIBOT_MAP_ALIAS,
)
from roboclaws.household.artifact_report import (  # noqa: E402
    rerender_cleanup_report_from_artifact_path,
)
from roboclaws.household.household_world_episode import (  # noqa: E402
    SYNTHETIC_BACKEND,
    run_household_world_episode,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIDENCE_LAYER = DEFAULT_AGIBOT_CONFIDENCE_LAYER
NEXT_CONFIDENCE_LAYER = "MolmoSpaces Agibot Contract Rehearsal"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir or args.output_dir / _stamp()
    result = run_agibot_robot_map_9_semantic_actions(
        run_dir=run_dir,
        context_json=args.context_json,
        agibot_map_artifact_dir=args.agibot_map_artifact_dir,
        seed=args.seed,
        generated_mess_count=args.generated_mess_count,
    )
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status": result["cleanup_status"],
                "confidence_layer": result["confidence_layer"],
                "semantic_substeps": len(result["semantic_substeps"]),
                "report": str(run_dir / "report.html"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run semantic cleanup actions over a fetched real AgiBot map artifact "
            "without SDK --execute or physical robot movement."
        )
    )
    parser.add_argument(
        "--context-json",
        type=Path,
        required=True,
        help="Completed agibot_gdk_map_context_authoring_v1 JSON.",
    )
    parser.add_argument(
        "--agibot-map-artifact-dir",
        type=Path,
        required=True,
        help="Path to the injected AgiBot map artifact root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/agibot")
        / f"{DEFAULT_AGIBOT_MAP_ALIAS.replace('_', '-')}-semantic-actions",
        help="Root output directory for timestamped semantic action artifacts.",
    )
    parser.add_argument("--run-dir", type=Path, help="Exact output run directory.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generated-mess-count", type=int, default=5)
    return parser.parse_args(argv)


def run_agibot_robot_map_9_semantic_actions(
    *,
    run_dir: Path,
    context_json: Path,
    agibot_map_artifact_dir: Path,
    seed: int = 7,
    generated_mess_count: int = 5,
) -> dict[str, Any]:
    """Run Roboclaws semantic cleanup over a fetched AgiBot public map bundle."""

    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    source_bundle_dir = run_dir / f"{Path(agibot_map_artifact_dir).name}_semantic_map_source"
    source_bundle = write_agibot_nav2_map_bundle(
        source_map_dir=agibot_map_artifact_dir,
        context_json=context_json,
        bundle_dir=source_bundle_dir,
    )
    result = run_household_world_episode(
        output_dir=run_dir,
        seed=seed,
        backend=SYNTHETIC_BACKEND,
        map_bundle_dir=source_bundle_dir,
        generated_mess_count=generated_mess_count,
    )
    _annotate_confidence_layer(
        result,
        context_json=context_json,
        agibot_map_artifact_dir=agibot_map_artifact_dir,
        source_bundle_dir=source_bundle_dir,
        source_bundle=source_bundle,
    )
    run_result_path = run_dir / "run_result.json"
    run_result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    rerender_cleanup_report_from_artifact_path(run_dir)
    return result


def _annotate_confidence_layer(
    result: dict[str, Any],
    *,
    context_json: Path,
    agibot_map_artifact_dir: Path,
    source_bundle_dir: Path,
    source_bundle: dict[str, Any],
) -> None:
    semantic_substeps = result.get("semantic_substeps") or []
    result["report_eyebrow"] = "Semantic mock evidence"
    result["report_title"] = CONFIDENCE_LAYER
    result["confidence_layer"] = CONFIDENCE_LAYER
    result["confidence_layer_summary"] = (
        "Uses the fetched real AgiBot map artifact as a public navigation map "
        "source while Roboclaws executes semantic cleanup actions with "
        "api_semantic provenance."
    )
    result["next_confidence_layer"] = NEXT_CONFIDENCE_LAYER
    result["agibot_robot_map_9_semantic_actions"] = {
        "schema": "agibot_robot_map_9_semantic_actions_rehearsal_v1",
        "confidence_layer": CONFIDENCE_LAYER,
        "next_confidence_layer": NEXT_CONFIDENCE_LAYER,
        "map_environment_id": str(
            source_bundle.get("environment_id") or DEFAULT_AGIBOT_ENVIRONMENT_ID
        ),
        "map_source_provenance": AGIBOT_MAP_BUNDLE_PROVENANCE,
        "agibot_map_artifact_dir": str(Path(agibot_map_artifact_dir)),
        "context_json": str(Path(context_json)),
        "source_map_bundle": str(source_bundle_dir),
        "source_bundle_snapshot_complete": bool(source_bundle.get("snapshot_complete")),
        "semantic_substep_count": len(semantic_substeps),
        "semantic_action_phases": sorted(
            {
                str(step.get("phase"))
                for item in semantic_substeps
                for step in item.get("steps", [])
                if step.get("phase")
            }
        ),
        "execution_backend": result.get("backend"),
        "primitive_provenance": result.get("primitive_provenance"),
        "physical_robot": False,
        "sdk_runner_execution": False,
        "gdk_navigation_executed": False,
        "molmospaces_contract_rehearsal": False,
        "evidence_note": (
            "Semantic cleanup actions are mock/api-semantic state transitions over an "
            "Agibot-shaped map bundle. They do not prove SDK runner execution, "
            "MolmoSpaces Agibot contract rehearsal, or real GDK motion."
        ),
    }


def _stamp() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
