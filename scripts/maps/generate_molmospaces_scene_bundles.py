#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.household.household_backend_contract import (
    build_household_backend_session,  # noqa: E402
)
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND  # noqa: E402
from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_path  # noqa: E402
from roboclaws.launch.scene_sampler import eval_sampler_rows, ui_sampler_rows  # noqa: E402
from roboclaws.maps.bundle import (  # noqa: E402
    metric_map_bundle_metadata,
    validate_base_metric_map_v1_bundle,
    validate_nav2_map_bundle,
    write_nav2_map_bundle,
)
from roboclaws.maps.molmospaces_preparation import (  # noqa: E402
    prepare_molmospaces_base_metric_map,
)

DEFAULT_SCENES: tuple[tuple[str, int], ...] = (("procthor-10k-val", 0),)
GENERATION_SCHEMA = "molmospaces_scene_nav2_bundle_generation_v1"


@dataclass(frozen=True)
class SceneTarget:
    scene_source: str
    scene_index: int

    @property
    def token(self) -> str:
        return f"{self.scene_source}/{self.scene_index}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate canonical prebuilt Nav2 map bundles for MolmoSpaces scenes. "
            "This is an offline asset-preparation path; public runs still require "
            "the generated bundle to exist before launch."
        )
    )
    parser.add_argument(
        "--active-sampler-scenes",
        action="store_true",
        help="Generate the default scene plus current UI/eval-stress sampler scenes.",
    )
    parser.add_argument(
        "--scene",
        action="append",
        default=[],
        metavar="SOURCE/INDEX",
        help="Scene to generate, for example procthor-objaverse-val/10. Repeatable.",
    )
    parser.add_argument("--scene-source", help="Single scene source.")
    parser.add_argument("--scene-index", type=int, help="Single scene index.")
    parser.add_argument("--asset-root", type=Path, default=Path("assets") / "maps")
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("output") / "map-bundle-generation" / "molmospaces",
        help="Directory for generation manifests and temporary backend state.",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--molmospaces-python", type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing canonical bundle directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generation plan without initializing MolmoSpaces.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable plan/result payload.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    targets = generation_targets(
        active_sampler_scenes=args.active_sampler_scenes,
        scene_specs=tuple(args.scene),
        scene_source=args.scene_source,
        scene_index=args.scene_index,
    )
    if not targets:
        raise SystemExit(
            "provide --active-sampler-scenes, --scene SOURCE/INDEX, or "
            "both --scene-source and --scene-index"
        )

    plan = generation_plan(targets, asset_root=args.asset_root)
    if args.dry_run:
        _emit(plan, as_json=args.json)
        return

    manifest = generate_scene_bundles(
        targets,
        asset_root=args.asset_root,
        run_root=args.run_root,
        seed=args.seed,
        molmospaces_python=args.molmospaces_python,
        force=args.force,
    )
    _emit(manifest, as_json=args.json)


def generation_targets(
    *,
    active_sampler_scenes: bool,
    scene_specs: tuple[str, ...] = (),
    scene_source: str | None = None,
    scene_index: int | None = None,
) -> tuple[SceneTarget, ...]:
    targets: list[SceneTarget] = []
    if active_sampler_scenes:
        targets.extend(SceneTarget(source, index) for source, index in DEFAULT_SCENES)
        for row in [*ui_sampler_rows(), *eval_sampler_rows()]:
            if row.scene_index is not None:
                targets.append(SceneTarget(row.scene_source, row.scene_index))
    for spec in scene_specs:
        targets.append(_parse_scene_spec(spec))
    if scene_source is not None or scene_index is not None:
        if scene_source is None or scene_index is None:
            raise SystemExit("provide both --scene-source and --scene-index")
        targets.append(SceneTarget(str(scene_source), int(scene_index)))
    return _dedupe_targets(targets)


def generation_plan(
    targets: tuple[SceneTarget, ...],
    *,
    asset_root: Path,
) -> dict[str, Any]:
    rows = []
    for target in targets:
        output_dir = molmospaces_nav2_map_bundle_path(
            scene_source=target.scene_source,
            scene_index=target.scene_index,
            asset_root=asset_root,
        )
        rows.append(
            {
                "scene_source": target.scene_source,
                "scene_index": target.scene_index,
                "output_dir": output_dir.as_posix(),
                "exists": output_dir.exists(),
            }
        )
    return {
        "schema": GENERATION_SCHEMA,
        "mode": "plan",
        "target_count": len(rows),
        "targets": rows,
    }


def generate_scene_bundles(
    targets: tuple[SceneTarget, ...],
    *,
    asset_root: Path,
    run_root: Path,
    seed: int,
    molmospaces_python: Path | None,
    force: bool,
) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for target in targets:
        rows.append(
            _generate_scene_bundle(
                target,
                asset_root=asset_root,
                run_root=run_root,
                seed=seed,
                molmospaces_python=molmospaces_python,
                force=force,
            )
        )
    manifest = {
        "schema": GENERATION_SCHEMA,
        "mode": "generated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "target_count": len(rows),
        "targets": rows,
    }
    manifest_path = run_root / "generation_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest["manifest_path"] = manifest_path.as_posix()
    return manifest


def _generate_scene_bundle(
    target: SceneTarget,
    *,
    asset_root: Path,
    run_root: Path,
    seed: int,
    molmospaces_python: Path | None,
    force: bool,
) -> dict[str, Any]:
    output_dir = molmospaces_nav2_map_bundle_path(
        scene_source=target.scene_source,
        scene_index=target.scene_index,
        asset_root=asset_root,
    )
    if output_dir.exists() and not force:
        raise SystemExit(f"bundle already exists, pass --force to overwrite: {output_dir}")

    scene_run_dir = run_root / target.scene_source / str(target.scene_index)
    if scene_run_dir.exists():
        shutil.rmtree(scene_run_dir)
    scene_run_dir.mkdir(parents=True, exist_ok=True)
    staged_bundle_dir = scene_run_dir / "bundle"

    session = build_household_backend_session(
        backend_name=MOLMOSPACES_SUBPROCESS_BACKEND,
        run_dir=scene_run_dir,
        seed=seed,
        generated_mess_count=0,
        scene_source=target.scene_source,
        scene_index=target.scene_index,
        molmospaces_python=molmospaces_python,
    )
    try:
        backend_state = _backend_state_payload(session)
        (scene_run_dir / "source_map_preparation_evidence.json").write_text(
            json.dumps(backend_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        environment_id = canonical_scene_environment_id(
            scene_source=target.scene_source,
            scene_index=target.scene_index,
        )
        metric_map = prepare_molmospaces_base_metric_map(
            backend_state=backend_state,
            scene_source=target.scene_source,
            scene_index=target.scene_index,
            environment_id=environment_id,
            map_id=f"{environment_id}_base_metric_map",
            source_path=backend_state.get("scene_xml"),
        )
        staged_snapshot = write_nav2_map_bundle(
            staged_bundle_dir,
            metric_map=metric_map,
            static_landmarks=[],
        )
        validate_nav2_map_bundle(staged_bundle_dir).raise_for_errors()
        validate_base_metric_map_v1_bundle(staged_bundle_dir).raise_for_errors()
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.move(str(staged_bundle_dir), str(output_dir))
        validation = validate_nav2_map_bundle(output_dir)
        validation.raise_for_errors()
        base_metric_validation = validate_base_metric_map_v1_bundle(output_dir)
        base_metric_validation.raise_for_errors()
    finally:
        session.close()

    return {
        "scene_source": target.scene_source,
        "scene_index": target.scene_index,
        "output_dir": output_dir.as_posix(),
        "run_dir": scene_run_dir.as_posix(),
        "map_id": staged_snapshot.get("map_id", ""),
        "environment_id": staged_snapshot.get("environment_id", ""),
        "parameter_hash": staged_snapshot.get("parameter_hash", ""),
        "validation": validation.as_dict(),
        "base_metric_validation": base_metric_validation.as_dict(),
    }


def _backend_state_payload(session: Any) -> dict[str, Any]:
    backend = getattr(session, "backend", None)
    state_reader = getattr(backend, "_read_state", None)
    if callable(state_reader):
        state = state_reader()
        if isinstance(state, dict):
            return state
    raise RuntimeError("MolmoSpaces source-map preparation requires backend state evidence")


def _parse_scene_spec(spec: str) -> SceneTarget:
    text = str(spec).strip()
    parts = text.rsplit("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SystemExit(f"scene spec must look like SOURCE/INDEX: {spec!r}")
    try:
        index = int(parts[1])
    except ValueError as exc:
        raise SystemExit(f"scene index must be an integer: {spec!r}") from exc
    if index < 0:
        raise SystemExit(f"scene index must be >= 0: {spec!r}")
    return SceneTarget(parts[0], index)


def canonical_scene_metric_map(
    metric_map: dict[str, Any],
    *,
    scene_source: str,
    scene_index: int,
) -> dict[str, Any]:
    """Return a scene-stable Base Metric Map identity for a prebuilt asset."""

    environment_id = canonical_scene_environment_id(
        scene_source=scene_source,
        scene_index=scene_index,
    )
    map_id = f"{environment_id}_base_metric_map"
    map_version = str(metric_map.get("map_version") or "base-metric-map-v1")
    canonical = dict(metric_map)
    canonical["map_id"] = map_id
    canonical["map_version"] = map_version
    canonical["map_bundle"] = metric_map_bundle_metadata(
        environment_id=environment_id,
        map_id=map_id,
        map_version=map_version,
    )
    return canonical


def canonical_scene_environment_id(*, scene_source: str, scene_index: int) -> str:
    return f"molmospaces-{scene_source}-{int(scene_index)}"


def _dedupe_targets(targets: list[SceneTarget]) -> tuple[SceneTarget, ...]:
    seen: set[tuple[str, int]] = set()
    deduped: list[SceneTarget] = []
    for target in targets:
        key = (target.scene_source, target.scene_index)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return tuple(deduped)


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    mode = str(payload.get("mode") or "")
    print(f"molmospaces-scene-bundles {mode}: targets={payload.get('target_count', 0)}")
    for row in payload.get("targets") or []:
        status = "exists" if row.get("exists") else "ready"
        if "validation" in row:
            status = "ok" if (row.get("validation") or {}).get("ok") else "invalid"
        print(
            "- "
            f"{row.get('scene_source')}/{row.get('scene_index')} "
            f"-> {row.get('output_dir')} [{status}]"
        )
    if payload.get("manifest_path"):
        print(f"manifest: {payload['manifest_path']}")


if __name__ == "__main__":
    main()
