"""Shared contracts for operator-console scene preview production."""

from pathlib import Path

PREVIEW_METADATA_SCHEMA = "operator_console_scene_preview_v1"
DEFAULT_OUTPUT_DIR = Path("roboclaws/operator_console/static/previews")
DEFAULT_WORK_DIR = Path("output/operator-console-scene-previews")
DEFAULT_WIDTH = 900
DEFAULT_HEIGHT = 560
B1_MAP12_WORLD_ID = "b1-map12"
B1_GAUSSIAN_SCENE_USD_PATH = Path(
    "data/robot-data-lab/scene-engine/data/2rd_floor_seperated/storey_1/scene_gs.usda"
)
B1_GAUSSIAN_TOPDOWN_PACKET = Path(
    "output/b1-map12/scene-gaussian-topdown-crop-z1p8/scene_gaussian_topdown.json"
)
B1_GAUSSIAN_TOPDOWN_FALLBACK_IMAGE = DEFAULT_OUTPUT_DIR / "b1-map12-topdown.png"
B1_BASE_METRIC_MAP_PROVENANCE = "b1_map12_base_metric_map_preview_png"
B1_GAUSSIAN_TOPDOWN_PROVENANCE = "b1_scene_gaussian_topdown_crop_z1p8_png"
