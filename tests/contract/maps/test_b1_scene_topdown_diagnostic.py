from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

import roboclaws.maps.b1_scene_topdown_diagnostic as diagnostic
from roboclaws.maps.b1_scene_topdown_diagnostic import (
    DIAGNOSTIC_SCHEMA,
    build_scene_topdown_diagnostic,
    validate_scene_topdown_diagnostic,
)
from scripts.maps.render_b1_scene_gaussian_topdown import (
    build_topdown_camera_request,
    topdown_render_packet,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "roboclaws.maps.b1_scene_topdown_diagnostic"
SCENE_ROOT = (
    REPO_ROOT / "data" / "robot-data-lab" / "scene-engine" / "data" / ("2rd_floor_seperated")
)


def test_b1_scene_topdown_diagnostic_lists_partitions_and_labels(tmp_path: Path) -> None:
    packet = build_scene_topdown_diagnostic(scene_root=SCENE_ROOT, output_dir=tmp_path)

    assert packet["schema"] == DIAGNOSTIC_SCHEMA
    assert packet["up_axis"] == "z"
    assert packet["horizontal_axes"] == ["x", "y"]
    assert packet["geometry_status"] == "label_inventory_only"
    assert packet["alignment_scope"] == "scene_self_check_only"
    assert packet["map_projection_status"] == "not_projected_to_map12"
    assert "not a Gaussian asset topdown" in packet["geometry_honesty"]
    assert "cannot verify map-scene alignment" in packet["geometry_honesty"]
    assert packet["partition_count"] >= 6
    partition_ids = {partition["partition_id"] for partition in packet["partitions"]}
    assert {"meeting_room_a", "meeting_room_b", "meeting_room_c"}.issubset(partition_ids)
    assert packet["high_signal_object_labels"]
    assert packet["topdown_image"].endswith("scene_topdown_diagnostic.png")
    assert Path(packet["topdown_image"]).is_file()
    assert validate_scene_topdown_diagnostic(packet) == []


def test_b1_scene_topdown_diagnostic_cli_writes_packet_and_report(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--scene-root",
            str(SCENE_ROOT),
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    packet = json.loads((tmp_path / "scene_topdown_diagnostic.json").read_text(encoding="utf-8"))
    assert summary["schema"] == DIAGNOSTIC_SCHEMA
    assert summary["status"] == "passed"
    assert summary["geometry_status"] == "label_inventory_only"
    assert (tmp_path / "scene_topdown_diagnostic.html").is_file()
    html = (tmp_path / "scene_topdown_diagnostic.html").read_text(encoding="utf-8")
    assert "B1 Scene Label Inventory Diagnostic" in html
    assert "not a Gaussian asset topdown" in html
    assert packet["validation"]["status"] == "passed"


def test_b1_scene_topdown_diagnostic_cli_rejects_non_positive_dimensions(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--scene-root",
            str(SCENE_ROOT),
            "--output-dir",
            str(tmp_path),
            "--height",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "expected a positive integer" in completed.stderr


def test_b1_scene_topdown_diagnostic_draws_scene_bounds_on_gaussian_topdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    render_packet_path = _write_fake_scene_topdown_packet(tmp_path)

    monkeypatch.setattr(
        diagnostic,
        "scene_object_bounds_from_usd",
        lambda _path: _fake_object_bounds_for_all_partitions(),
    )

    packet = build_scene_topdown_diagnostic(
        scene_root=SCENE_ROOT,
        output_dir=tmp_path / "overlay",
        scene_topdown_render=render_packet_path,
    )

    assert packet["schema"] == DIAGNOSTIC_SCHEMA
    assert packet["geometry_status"] == "rendered_gaussian_topdown_with_scene_usd_bounds_overlay"
    assert packet["geometry_backend"] == "scene_usd_world_bounds_on_gaussian_topdown"
    assert packet["alignment_scope"] == "scene_self_check_only"
    assert packet["map_projection_status"] == "not_projected_to_map12"
    assert packet["object_bound_count"] == 6
    assert packet["overlay_render_stats"]["drawn_partition_count"] == 6
    assert packet["overlay_render_stats"]["drawn_object_count"] == 6
    assert packet["topdown_image"].endswith("scene_topdown_label_overlay.png")
    assert Path(packet["topdown_image"]).is_file()
    assert validate_scene_topdown_diagnostic(packet) == []


def test_b1_scene_topdown_overlay_rejects_label_inventory_as_input(tmp_path: Path) -> None:
    bad_packet = tmp_path / "scene_topdown_diagnostic.json"
    bad_packet.write_text(
        json.dumps({"schema": DIAGNOSTIC_SCHEMA, "geometry_status": "label_inventory_only"}),
        encoding="utf-8",
    )

    try:
        build_scene_topdown_diagnostic(
            scene_root=SCENE_ROOT,
            output_dir=tmp_path / "overlay",
            scene_topdown_render=bad_packet,
        )
    except ValueError as exc:
        assert "scene top-down render must use schema" in str(exc)
    else:
        raise AssertionError("label inventory diagnostic must not feed Gaussian label overlay")


def test_b1_scene_topdown_overlay_rejects_bad_render_packet_source_json(
    tmp_path: Path,
) -> None:
    bad_packet = tmp_path / "scene_gaussian_topdown.json"
    bad_packet.write_text("{not-json\n", encoding="utf-8")

    try:
        build_scene_topdown_diagnostic(
            scene_root=SCENE_ROOT,
            output_dir=tmp_path / "overlay",
            scene_topdown_render=bad_packet,
        )
    except ValueError as exc:
        message = str(exc)
        assert "scene top-down render source must contain valid JSON object" in message
        assert str(bad_packet) in message
    else:
        raise AssertionError("malformed scene top-down render packet must fail aloud")


def test_b1_scene_topdown_overlay_rejects_non_object_render_packet_source_json(
    tmp_path: Path,
) -> None:
    bad_packet = tmp_path / "scene_gaussian_topdown.json"
    bad_packet.write_text("[]\n", encoding="utf-8")

    try:
        build_scene_topdown_diagnostic(
            scene_root=SCENE_ROOT,
            output_dir=tmp_path / "overlay",
            scene_topdown_render=bad_packet,
        )
    except ValueError as exc:
        message = str(exc)
        assert "scene top-down render source must contain a JSON object" in message
        assert str(bad_packet) in message
    else:
        raise AssertionError("non-object scene top-down render packet must fail aloud")


def test_b1_scene_topdown_overlay_rejects_missing_render_packet_source_json(
    tmp_path: Path,
) -> None:
    missing_packet = tmp_path / "missing_scene_gaussian_topdown.json"

    try:
        build_scene_topdown_diagnostic(
            scene_root=SCENE_ROOT,
            output_dir=tmp_path / "overlay",
            scene_topdown_render=missing_packet,
        )
    except FileNotFoundError as exc:
        message = str(exc)
        assert "scene top-down render source is missing" in message
        assert str(missing_packet) in message
    else:
        raise AssertionError("missing scene top-down render packet must fail aloud")


def _write_fake_scene_topdown_packet(tmp_path: Path) -> Path:
    request = build_topdown_camera_request(
        scene_bounds=(-2.0, -4.0, 8.0, 4.0),
        width=320,
        height=240,
        camera_height_m=18.0,
        camera_y_offset_m=0.05,
        target_z_m=0.6,
        fov_deg=55.0,
        camera_mode="near-vertical-topdown",
    )
    image_path = tmp_path / "views" / "top2down.png"
    image_path.parent.mkdir()
    Image.new("RGB", (320, 240), color=(220, 225, 230)).save(image_path)
    packet = topdown_render_packet(
        scene_usd=tmp_path / "scene_gs.usda",
        prepared_scene_usd=tmp_path / "scene_gs.usda",
        scene_bounds=(-2.0, -4.0, 8.0, 4.0),
        request=request,
        request_path=tmp_path / "camera_request.json",
        output_dir=tmp_path,
        nurec_crop={"status": "applied", "source": "explicit_nurec_crop_max_z"},
        capture_result={
            "ok": True,
            "result_path": str(tmp_path / "capture_result.json"),
            "capture": {"images": {"top2down": str(image_path)}},
        },
    )
    packet_path = tmp_path / "scene_gaussian_topdown.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
    return packet_path


def _fake_object_bounds_for_all_partitions() -> list[dict[str, object]]:
    rows = [
        ("meeting_room_a", "table", 4.0, -2.0, 7.0, 2.0),
        ("meeting_room_b", "desk", 4.0, -5.0, 7.0, -3.5),
        ("meeting_room_c", "tripod", 3.7, -8.0, 5.0, -6.7),
        ("reception_area_a", "sofa", -1.5, -2.5, 2.0, 2.5),
        ("short_corridor_a", "tv", -1.8, -3.5, -0.5, -2.7),
        ("storage_room_a", "trash_bin", -1.7, 2.7, -0.6, 3.5),
    ]
    bounds = []
    for partition_id, label, min_x, min_y, max_x, max_y in rows:
        object_id = f"{partition_id}__{label}_1"
        bounds.append(
            {
                "partition_id": partition_id,
                "object_id": object_id,
                "object_label": label,
                "prim_path": f"/scene/{object_id}",
                "bounds": {
                    "min_x": min_x,
                    "min_y": min_y,
                    "min_z": 0.0,
                    "max_x": max_x,
                    "max_y": max_y,
                    "max_z": 0.8,
                },
                "center": {
                    "x": (min_x + max_x) / 2.0,
                    "y": (min_y + max_y) / 2.0,
                    "z": 0.4,
                },
            }
        )
    return bounds
