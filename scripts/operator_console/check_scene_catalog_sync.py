#!/usr/bin/env python3
from __future__ import annotations

import argparse
import filecmp
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]

from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS  # noqa: E402
from roboclaws.worlds.molmospaces.sampling import parse_molmospaces_world_id  # noqa: E402
from scripts.operator_console.export_scene_sampler_readiness import (  # noqa: E402
    _write_generated_eval_artifacts,
)

COMMITTED_SCENE_SAMPLER_SUITE = REPO_ROOT / "evals/household_world/suites/scene_sampler_stress.json"
COMMITTED_SCENE_SAMPLER_SAMPLES = REPO_ROOT / "evals/household_world/samples/scene_sampler"
STATIC_PREVIEW_ROOT = REPO_ROOT / "roboclaws/operator_console/static/previews"


@dataclass(frozen=True)
class SyncIssue:
    check: str
    message: str
    action: str


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = check_scene_catalog_sync(output_dir=args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "success" else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that MolmoSpaces scene catalog changes have synchronized the "
            "operator-console world list, preview assets, and scene-sampler eval fixtures."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/scene-catalog-sync-check"),
        help="Temporary directory for regenerated deterministic artifacts.",
    )
    return parser.parse_args(argv)


def check_scene_catalog_sync(*, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    issues = [
        *_generated_eval_fixture_issues(output_dir),
        *_console_world_issues(),
        *_preview_asset_issues(),
    ]
    return {
        "schema": "operator_console_scene_catalog_sync_check_v1",
        "status": "failed" if issues else "success",
        "output_dir": str(output_dir),
        "summary": {
            "issue_count": len(issues),
            "molmospaces_console_world_count": len(MOLMOSPACES_CONSOLE_WORLD_IDS),
            "molmospaces_console_world_ids": list(MOLMOSPACES_CONSOLE_WORLD_IDS),
        },
        "issues": [issue.__dict__ for issue in issues],
    }


def _generated_eval_fixture_issues(output_dir: Path) -> list[SyncIssue]:
    generated = _write_generated_eval_artifacts(output_dir)
    generated_suite = Path(str(generated["generated_eval_suite"]))
    generated_samples = [Path(path) for path in generated["generated_eval_samples"]]
    issues: list[SyncIssue] = []
    issues.extend(
        _same_file_issue(
            check="scene_sampler_suite",
            generated=generated_suite,
            committed=COMMITTED_SCENE_SAMPLER_SUITE,
        )
    )
    committed_sample_names = {path.name for path in COMMITTED_SCENE_SAMPLER_SAMPLES.glob("*.json")}
    generated_sample_names = {path.name for path in generated_samples}
    for name in sorted(generated_sample_names - committed_sample_names):
        issues.append(
            SyncIssue(
                check="scene_sampler_samples",
                message=f"missing committed scene-sampler eval sample: {name}",
                action=(
                    "copy "
                    f"{output_dir / 'generated_eval/samples/scene_sampler' / name} "
                    f"to {COMMITTED_SCENE_SAMPLER_SAMPLES / name}"
                ),
            )
        )
    for name in sorted(committed_sample_names - generated_sample_names):
        issues.append(
            SyncIssue(
                check="scene_sampler_samples",
                message=f"stale committed scene-sampler eval sample: {name}",
                action=f"remove {COMMITTED_SCENE_SAMPLER_SAMPLES / name}",
            )
        )
    for sample_path in generated_samples:
        committed = COMMITTED_SCENE_SAMPLER_SAMPLES / sample_path.name
        if committed.is_file():
            issues.extend(
                _same_file_issue(
                    check="scene_sampler_samples",
                    generated=sample_path,
                    committed=committed,
                )
            )
    return issues


def _same_file_issue(*, check: str, generated: Path, committed: Path) -> list[SyncIssue]:
    if committed.is_file() and filecmp.cmp(generated, committed, shallow=False):
        return []
    return [
        SyncIssue(
            check=check,
            message=f"generated artifact differs from committed fixture: {committed}",
            action=f"copy {generated} to {committed}",
        )
    ]


def _console_world_issues() -> list[SyncIssue]:
    issues: list[SyncIssue] = []
    by_source: dict[str, list[str]] = {}
    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        source = parse_molmospaces_world_id(world_id).scene_source
        by_source.setdefault(source, []).append(world_id)
    for source, world_ids in sorted(by_source.items()):
        if len(world_ids) != 3:
            issues.append(
                SyncIssue(
                    check="console_worlds",
                    message=f"{source} exposes {len(world_ids)} UI worlds, expected 3",
                    action="update SOURCE_UI_CANDIDATE_INDICES and rerun readiness export",
                )
            )
    if len(by_source) < 2:
        issues.append(
            SyncIssue(
                check="console_worlds",
                message="MolmoSpaces console exposes fewer than two UI-supported scene groups",
                action="inspect scene sampler readiness and committed Base Metric Map bundles",
            )
        )
    return issues


def _preview_asset_issues() -> list[SyncIssue]:
    issues: list[SyncIssue] = []
    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        previews = dict(WORLD_SPECS[world_id].preview_assets)
        missing = [
            view
            for view in ("fpv", "map", "chase", "topdown")
            if view not in previews or not _preview_asset_exists(previews[view])
        ]
        if not missing:
            continue
        issues.append(
            SyncIssue(
                check="operator_console_previews",
                message=f"{world_id} preview assets are incomplete or missing: {missing}",
                action=(
                    ".venv/bin/python scripts/operator_console/render_scene_previews.py "
                    f"--world {world_id}"
                ),
            )
        )
    return issues


def _preview_asset_exists(asset_path: str) -> bool:
    if asset_path.startswith("/previews/"):
        return (STATIC_PREVIEW_ROOT / Path(asset_path).name).is_file()
    if asset_path.startswith("/asset-previews/maps/"):
        relative_path = asset_path.removeprefix("/asset-previews/maps/")
        return (REPO_ROOT / "assets/maps" / relative_path).is_file()
    return False


if __name__ == "__main__":
    raise SystemExit(main())
