from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

from roboclaws.household.agibot_map_bundle import write_agibot_nav2_map_bundle
from roboclaws.maps.bundle import validate_nav2_map_bundle
from scripts.maps.export_agibot_map_bundle import main as export_main

REPO_ROOT = Path(__file__).resolve().parents[3]
ROBOT_MAP_12_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "runtime_map_prior" / "robot_map_12"
ROBOT_MAP_12_CONTEXT = (
    REPO_ROOT / "tests" / "fixtures" / "agibot_robot_map_12_context.completed.json"
)


def test_export_agibot_map12_nav2_bundle(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "agibot-robot-map-12"

    rc = export_main(
        [
            "--source-map-dir",
            str(ROBOT_MAP_12_FIXTURE),
            "--context-json",
            str(ROBOT_MAP_12_CONTEXT),
            "--output-dir",
            str(bundle_dir),
        ]
    )

    validation = validate_nav2_map_bundle(bundle_dir)
    assert rc == 0
    assert validation.errors == ()
    assert validation.metadata["map_id"] == "agibot-robot-map-12_base_metric_map"
    assert validation.metadata["room_count"] == 4
    assert validation.metadata["waypoint_count"] == 5
    assert (bundle_dir / "preview.png").is_file()


@pytest.mark.parametrize(
    ("raw_map", "expected_message"),
    [
        ("{not-json\n", r"Agibot raw map source must contain valid JSON object: .*raw_map"),
        ("[]\n", r"Agibot raw map source must contain a JSON object: .*raw_map"),
    ],
)
def test_export_agibot_map_bundle_rejects_malformed_raw_map_source(
    tmp_path: Path,
    raw_map: str,
    expected_message: str,
) -> None:
    source_map_dir = _copy_robot_map12_fixture(tmp_path)
    raw_map_path = source_map_dir / "agibot" / "raw_map.json.gz"
    with gzip.open(raw_map_path, "wt", encoding="utf-8") as handle:
        handle.write(raw_map)

    with pytest.raises(ValueError, match=expected_message):
        write_agibot_nav2_map_bundle(
            source_map_dir=source_map_dir,
            context_json=ROBOT_MAP_12_CONTEXT,
            bundle_dir=tmp_path / "bundle",
        )


def test_export_agibot_map_bundle_rejects_malformed_source_metadata(
    tmp_path: Path,
) -> None:
    source_map_dir = _copy_robot_map12_fixture(tmp_path)
    source_path = source_map_dir / "agibot" / "source.json"
    source_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Agibot map source must contain a JSON object: .*source\.json",
    ):
        write_agibot_nav2_map_bundle(
            source_map_dir=source_map_dir,
            context_json=ROBOT_MAP_12_CONTEXT,
            bundle_dir=tmp_path / "bundle",
        )


def test_export_agibot_map_bundle_rejects_malformed_context_source(
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"Agibot map source must contain a JSON object: .*context\.json",
    ):
        write_agibot_nav2_map_bundle(
            source_map_dir=ROBOT_MAP_12_FIXTURE,
            context_json=context_path,
            bundle_dir=tmp_path / "bundle",
        )


def _copy_robot_map12_fixture(tmp_path: Path) -> Path:
    source_map_dir = tmp_path / "robot_map_12"
    shutil.copytree(ROBOT_MAP_12_FIXTURE, source_map_dir)
    return source_map_dir
