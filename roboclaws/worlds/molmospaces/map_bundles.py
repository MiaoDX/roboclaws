"""Launch-time map bundle naming contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

SIM_MAP_BUNDLE_ASSET_ROOT = Path("assets") / "maps"
MOLMOSPACES_MAP_BUNDLE_ROOT = SIM_MAP_BUNDLE_ASSET_ROOT / "molmospaces"


def molmospaces_nav2_map_bundle_path(
    *,
    scene_source: str,
    scene_index: int,
    asset_root: Path = SIM_MAP_BUNDLE_ASSET_ROOT,
) -> Path:
    """Return the canonical prebuilt Nav2 bundle path for a MolmoSpaces scene."""

    source = str(scene_source).strip()
    if not source:
        raise ValueError("scene_source is required for MolmoSpaces map bundle selection")
    index = int(scene_index)
    if index < 0:
        raise ValueError("scene_index must be >= 0 for MolmoSpaces map bundle selection")
    return Path(asset_root) / "molmospaces" / source / str(index)


def molmospaces_nav2_map_bundle_arg(*, scene_source: str, scene_index: int) -> str:
    """Return the launch override for the canonical MolmoSpaces map bundle."""

    path = molmospaces_nav2_map_bundle_path(
        scene_source=scene_source,
        scene_index=scene_index,
    )
    return f"map_bundle={path.as_posix()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the canonical prebuilt Nav2 bundle path for a MolmoSpaces scene."
    )
    parser.add_argument("--scene-source", required=True)
    parser.add_argument("--scene-index", required=True, type=int)
    parser.add_argument("--asset-root", type=Path, default=SIM_MAP_BUNDLE_ASSET_ROOT)
    args = parser.parse_args(argv)
    print(
        molmospaces_nav2_map_bundle_path(
            scene_source=args.scene_source,
            scene_index=args.scene_index,
            asset_root=args.asset_root,
        ).as_posix()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
