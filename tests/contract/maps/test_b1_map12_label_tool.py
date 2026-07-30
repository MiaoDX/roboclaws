from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

import scripts.maps.render_b1_scene_topdown_diagnostic as scene_diagnostic
from roboclaws.maps.b1_alignment import build_alignment_residuals
from scripts.maps.render_b1_map12_label_tool import (
    LABEL_DRAFT_MANIFEST_SCHEMA,
    LABEL_TOOL_PACKET_SCHEMA,
    SourceMapTransform,
    build_label_tool_packet,
    draft_label_from_shape,
    draft_manifest_from_shapes,
    label_tool_template,
    label_tool_template_path,
    materialize_scene_evidence_artifacts,
    navigation_memory_layer_from_path,
    pixel_to_world,
    render_label_tool_html,
    scene_bounds_review_seed_packet,
    validate_label_draft_manifest,
    world_to_pixel,
    write_label_tool_artifacts,
)
from scripts.maps.render_b1_scene_gaussian_topdown import (
    build_topdown_camera_request,
    topdown_render_packet,
)
from scripts.maps.render_b1_scene_topdown_diagnostic import build_scene_topdown_diagnostic
from tests.contract.maps.b1_map12_verified_alignment_support import (
    alignment_anchor,
    correspondence_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MAP_BUNDLE = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / ("robot_map_12") / "agibot"
)
ROOM_SEMANTICS = REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"
NAVIGATION_MEMORY = (
    REPO_ROOT
    / "vendors"
    / "agibot_sdk"
    / "artifacts"
    / "maps"
    / ("robot_map_12")
    / "navigation_memory.json"
)
SCENE_ROOT = (
    REPO_ROOT / "data" / "robot-data-lab" / "scene-engine" / "data" / ("2rd_floor_seperated")
)
SCRIPT = REPO_ROOT / "scripts" / "maps" / "render_b1_map12_label_tool.py"
REMOVED_AUTHORED_BUNDLE = REPO_ROOT / "assets" / "maps" / "agibot-robot-map-12"


def test_map12_label_tool_pixel_world_roundtrip() -> None:
    transform = SourceMapTransform(
        width_px=913,
        height_px=716,
        resolution_m=0.0500000007451,
        origin_x=-35.1000022888,
        origin_y=-22.3000011444,
    )
    source_point = {"x": -7.1, "y": 2.65}

    pixel = world_to_pixel(source_point["x"], source_point["y"], transform)
    restored = pixel_to_world(pixel["x"], pixel["y"], transform)

    assert restored["x"] == pytest.approx(source_point["x"])
    assert restored["y"] == pytest.approx(source_point["y"])


def test_label_tool_packet_starts_from_current_semantics_only(tmp_path: Path) -> None:
    semantics_path = _write_polygon_semantics(tmp_path)

    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE, semantics_path=semantics_path)

    assert packet["schema"] == LABEL_TOOL_PACKET_SCHEMA
    assert packet["draft_manifest_schema"] == LABEL_DRAFT_MANIFEST_SCHEMA
    assert packet["map_bundle"].endswith("vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot")
    assert packet["scene_root"].endswith(
        "data/robot-data-lab/scene-engine/data/2rd_floor_seperated"
    )
    assert packet["source_map_frame_policy"] == "raw_source_map_frame_no_rectified_display_frame"
    assert packet["draft_policy"] == {
        "review_status": "draft",
        "export_alignment_status": "candidate",
        "verified_status_allowed": False,
        "source_map_mutated": False,
    }
    assert packet["map"]["image_width_px"] == 913
    assert packet["map"]["image_height_px"] == 716
    assert len(packet["shapes"]) == 1
    assert all(shape["alignment_status"] == "candidate" for shape in packet["shapes"])
    assert {shape["review_status"] for shape in packet["shapes"]} == {"draft"}
    assert all(shape["source_map_frame_id"] == "map" for shape in packet["shapes"])

    manifest = packet["initial_draft_manifest"]
    assert validate_label_draft_manifest(manifest) == []
    assert manifest["source_map_mutated"] is False
    assert manifest["verified_status_allowed"] is False
    assert all(label["alignment_status"] == "candidate" for label in manifest["labels"])


def test_label_tool_scene_bound_review_uses_single_label_tool_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene_topdown = _write_fake_scene_topdown_packet(tmp_path)
    monkeypatch.setattr(
        scene_diagnostic,
        "scene_object_bounds_from_usd",
        lambda _path: _fake_object_bounds_for_all_partitions(),
    )
    diagnostic = build_scene_topdown_diagnostic(
        scene_root=SCENE_ROOT,
        output_dir=tmp_path / "scene-diagnostic",
        scene_topdown_render=scene_topdown,
    )
    diagnostic["validation"] = {"status": "passed", "errors": []}
    diagnostic_path = tmp_path / "scene_topdown_diagnostic.json"
    diagnostic_path.write_text(json.dumps(diagnostic), encoding="utf-8")
    alignment_artifact = _write_verified_alignment_artifact(tmp_path)

    packet = build_label_tool_packet(
        map_bundle=MAP_BUNDLE,
        scene_topdown_render_path=scene_topdown,
        scene_topdown_diagnostic_path=diagnostic_path,
        alignment_artifact_path=alignment_artifact,
        room_label_reference_path=ROOM_SEMANTICS,
        seed_review_shapes_from_scene_bounds=True,
    )

    assert packet["schema"] == LABEL_TOOL_PACKET_SCHEMA
    assert packet["review_shape_seed_policy"]["enabled"] is True
    assert packet["review_shape_seed_policy"]["geometry_source"] == "generated_candidate"
    assert packet["review_shape_seed_policy"]["label_status"] == "candidate_draft_only"
    assert packet["scene_reference"]["source_topdown_image"].endswith("views/top2down.png")
    assert packet["scene_reference"]["source_diagnostic"] == str(diagnostic_path)
    assert len(packet["scene_reference"]["regions"]) >= 6
    assert {shape["asset_partition_id"] for shape in packet["shapes"]} >= {
        "meeting_room_a",
        "meeting_room_b",
        "meeting_room_c",
    }
    assert all(
        shape["review_seed"]["source"] == "digital_twin_object_aggregate_bbox"
        for shape in packet["shapes"]
    )
    assert {label["alignment_status"] for label in packet["initial_draft_manifest"]["labels"]} == {
        "candidate"
    }
    assert {label["review_status"] for label in packet["initial_draft_manifest"]["labels"]} == {
        "draft"
    }


def test_label_tool_defaults_to_vendor_map12_without_authored_semantics() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)

    assert packet["map_bundle"].endswith("vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot")
    assert packet["source_semantics"].endswith(
        "vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot/semantics.json"
    )
    assert packet["shapes"] == []
    assert packet["source_map_layers"] == {
        "coordinate_policy": "map_native_layers_use_source_map_frame_coordinates_only",
        "driveable_ways": [],
        "fixtures": [],
        "inspection_waypoints": [],
    }
    assert len(packet["navigation_memory_layer"]["items"]) == 9
    assert packet["initial_draft_manifest"]["labels"] == []


@pytest.mark.parametrize(
    ("semantics_text", "expected_error"),
    [
        (
            None,
            r"semantics missing: .*explicit-semantics\.json",
        ),
        (
            "{not-json\n",
            r"semantics must contain valid JSON object: .*explicit-semantics\.json",
        ),
        (
            json.dumps([]),
            r"semantics must contain a JSON object: .*explicit-semantics\.json",
        ),
    ],
)
def test_label_tool_rejects_malformed_explicit_semantics_source(
    tmp_path: Path,
    semantics_text: str | None,
    expected_error: str,
) -> None:
    semantics_path = tmp_path / "explicit-semantics.json"
    if semantics_text is not None:
        semantics_path.write_text(semantics_text, encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        build_label_tool_packet(
            map_bundle=MAP_BUNDLE,
            semantics_path=semantics_path,
        )


@pytest.mark.parametrize(
    ("source_text", "expected_error"),
    [
        (
            "{not-json\n",
            r"map source metadata must contain valid JSON object: .*source\.json",
        ),
        (
            json.dumps([]),
            r"map source metadata must contain a JSON object: .*source\.json",
        ),
    ],
)
def test_label_tool_rejects_malformed_source_metadata_when_defaulting_semantics(
    tmp_path: Path,
    source_text: str,
    expected_error: str,
) -> None:
    map_bundle = _copy_map12_bundle(tmp_path)
    (map_bundle / "source.json").write_text(source_text, encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        build_label_tool_packet(map_bundle=map_bundle)


def test_label_tool_rejects_missing_source_metadata_when_defaulting_semantics(
    tmp_path: Path,
) -> None:
    map_bundle = _copy_map12_bundle(tmp_path)
    (map_bundle / "source.json").unlink()

    with pytest.raises(ValueError, match=r"map source metadata missing: .*source\.json"):
        build_label_tool_packet(map_bundle=map_bundle)


def test_authored_map12_bundle_stays_removed() -> None:
    assert not REMOVED_AUTHORED_BUNDLE.exists()


def test_label_tool_packet_has_empty_source_map_layers_without_authored_bundle() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    layers = packet["source_map_layers"]

    assert layers["coordinate_policy"] == "map_native_layers_use_source_map_frame_coordinates_only"
    assert layers["fixtures"] == []
    assert layers["inspection_waypoints"] == []
    assert layers["driveable_ways"] == []


def test_label_tool_packet_exposes_navigation_memory_layer() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    layer = packet["navigation_memory_layer"]
    items = {item["id"]: item for item in layer["items"]}

    assert layer["coordinate_policy"] == "navigation_memory_pose_and_nav_goal_are_map_frame_priors"
    assert len(items) == 9
    assert items["kitchen_center"]["kind"] == "room"
    assert items["kitchen_center"]["label"] == "厨房/吧台区域"
    assert items["kitchen_center"]["pose"]["frame_id"] == "map"
    assert items["kitchen_center"]["nav_goal"]["frame_id"] == "map"
    assert items["fridge_main"]["pose"]["x"] == pytest.approx(1.6879071220842632)
    assert items["fridge_main"]["nav_goal"]["x"] == pytest.approx(1.125)


@pytest.mark.parametrize(
    ("navigation_memory", "expected_error"),
    [
        (
            [],
            "navigation_memory.json must contain a JSON object",
        ),
        (
            {},
            "navigation_memory.json must contain a non-empty items list "
            "or catalog.navigation_memory list",
        ),
        (
            {"items": []},
            "navigation_memory.json items must be a non-empty list",
        ),
        (
            {"items": [[]]},
            "navigation_memory.json item 1 must be a JSON object",
        ),
        (
            {"items": [{"id": "bad_anchor", "nav_goal": {"x": "bad", "y": 1.0}}]},
            "navigation_memory.json item bad_anchor nav_goal x must be a finite number",
        ),
        (
            {"items": [{"id": "bad_anchor"}]},
            "navigation_memory.json item bad_anchor must include pose or nav_goal",
        ),
    ],
)
def test_label_tool_rejects_malformed_navigation_memory_sources(
    tmp_path: Path,
    navigation_memory: object,
    expected_error: str,
) -> None:
    map_bundle = _copy_map12_bundle(tmp_path)
    navigation_memory_path = map_bundle.parent / "navigation_memory.json"
    navigation_memory_path.write_text(json.dumps(navigation_memory), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        build_label_tool_packet(map_bundle=map_bundle)


def test_label_tool_rejects_malformed_navigation_memory_json(tmp_path: Path) -> None:
    map_bundle = _copy_map12_bundle(tmp_path)
    navigation_memory_path = map_bundle.parent / "navigation_memory.json"
    navigation_memory_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"navigation_memory.json must contain valid JSON object: .*navigation_memory\.json",
    ):
        build_label_tool_packet(map_bundle=map_bundle)


def test_label_tool_accepts_catalog_navigation_memory_items(tmp_path: Path) -> None:
    map_bundle = _copy_map12_bundle(tmp_path)
    navigation_memory_path = map_bundle.parent / "navigation_memory.json"
    navigation_memory = json.loads(navigation_memory_path.read_text(encoding="utf-8"))
    items = navigation_memory.pop("items")
    navigation_memory["catalog"] = {"navigation_memory": items}
    navigation_memory_path.write_text(json.dumps(navigation_memory), encoding="utf-8")

    packet = build_label_tool_packet(map_bundle=map_bundle)

    assert len(packet["navigation_memory_layer"]["items"]) == 9


def test_navigation_memory_layer_rejects_missing_source(tmp_path: Path) -> None:
    transform = SourceMapTransform(
        width_px=913,
        height_px=716,
        resolution_m=0.0500000007451,
        origin_x=-35.1000022888,
        origin_y=-22.3000011444,
    )

    with pytest.raises(ValueError, match=r"navigation_memory\.json missing: .*missing\.json"):
        navigation_memory_layer_from_path(
            tmp_path / "missing.json", transform=transform, frame_id="map"
        )


def test_label_tool_packet_excludes_scene_evidence_by_default() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)

    assert "scene_evidence" not in packet


def test_label_tool_does_not_seed_scene_bounds_by_default() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)

    assert packet["shapes"] == []
    assert packet["review_shape_seed_policy"]["enabled"] is False
    assert "scene_reference" not in packet


def test_label_tool_can_seed_editable_draft_labels_from_dt_object_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene_topdown = _write_fake_scene_topdown_packet(tmp_path)
    monkeypatch.setattr(
        scene_diagnostic,
        "scene_object_bounds_from_usd",
        lambda _path: _fake_object_bounds_for_all_partitions(),
    )
    diagnostic = build_scene_topdown_diagnostic(
        scene_root=SCENE_ROOT,
        output_dir=tmp_path / "scene-diagnostic",
        scene_topdown_render=scene_topdown,
    )
    diagnostic["validation"] = {"status": "passed", "errors": []}
    diagnostic_path = tmp_path / "scene_topdown_diagnostic.json"
    diagnostic_path.write_text(json.dumps(diagnostic), encoding="utf-8")
    alignment_artifact = _write_verified_alignment_artifact(tmp_path)

    packet = build_label_tool_packet(
        map_bundle=MAP_BUNDLE,
        scene_topdown_render_path=scene_topdown,
        scene_topdown_diagnostic_path=diagnostic_path,
        alignment_artifact_path=alignment_artifact,
        room_label_reference_path=ROOM_SEMANTICS,
        seed_review_shapes_from_scene_bounds=True,
    )

    assert packet["review_shape_seed_policy"] == {
        "enabled": True,
        "seed_count": 6,
        "source": str(diagnostic_path),
        "alignment_artifact": str(alignment_artifact),
        "room_label_reference": str(ROOM_SEMANTICS),
        "geometry_source": "generated_candidate",
        "label_status": "candidate_draft_only",
        "note": (
            "Seeds come from Digital Twin object aggregate bboxes transformed back into "
            "Map12 with verified alignment. They are intentionally draft-only."
        ),
    }
    assert len(packet["shapes"]) == 6
    meeting_room_b = {shape["asset_partition_id"]: shape for shape in packet["shapes"]}[
        "meeting_room_b"
    ]
    assert meeting_room_b["shape_id"] == "scene_bbox_seed_meeting_room_b"
    assert meeting_room_b["label"] == "Meeting room B"
    assert meeting_room_b["semantic_source"] == "digital_twin_object_aggregate_bbox_review_seed"
    assert meeting_room_b["geometry_source"] == "generated_candidate"
    assert meeting_room_b["alignment_status"] == "candidate"
    assert meeting_room_b["review_status"] == "draft"
    assert meeting_room_b["review_seed"]["source"] == "digital_twin_object_aggregate_bbox"
    assert meeting_room_b["review_seed"]["source_review_status"] == "accepted"
    assert meeting_room_b["review_seed"]["object_bounds_count"] == 1
    assert len(meeting_room_b["geometry"]["polygon"]) == 4
    assert len(meeting_room_b["geometry"]["pixel_polygon"]) == 4
    assert packet["scene_reference"]["schema"] == "b1_map12_label_tool_scene_reference_v1"
    assert packet["scene_reference"]["source_topdown_image"].endswith("views/top2down.png")
    assert len(packet["scene_reference"]["regions"]) == 6

    manifest = packet["initial_draft_manifest"]
    assert validate_label_draft_manifest(manifest) == []
    assert {label["alignment_status"] for label in manifest["labels"]} == {"candidate"}
    assert {label["review_status"] for label in manifest["labels"]} == {"draft"}


def test_label_tool_rejects_scene_bound_seeds_without_verified_alignment(tmp_path: Path) -> None:
    scene_topdown = _write_fake_scene_topdown_packet(tmp_path)
    diagnostic = {
        "schema": scene_diagnostic.DIAGNOSTIC_SCHEMA,
        "validation": {"status": "passed", "errors": []},
        "partitions": [
            {
                "partition_id": "meeting_room_a",
                "object_bounds_count": 1,
                "scene_frame_bounds": {
                    "status": "extracted_from_scene_usd_world_bounds",
                    "min_x": 1.0,
                    "min_y": 2.0,
                    "max_x": 3.0,
                    "max_y": 4.0,
                },
            }
        ],
    }
    diagnostic_path = tmp_path / "scene_topdown_diagnostic.json"
    diagnostic_path.write_text(json.dumps(diagnostic), encoding="utf-8")
    alignment_path = tmp_path / "alignment_residuals.json"
    alignment_path.write_text(
        json.dumps(
            {
                "global_alignment_status": "candidate",
                "selected_transform": {
                    "type": "rigid_2d",
                    "source": "reviewed_correspondence_fit",
                },
            }
        ),
        encoding="utf-8",
    )
    transform = SourceMapTransform(
        width_px=913,
        height_px=716,
        resolution_m=0.0500000007451,
        origin_x=-35.1000022888,
        origin_y=-22.3000011444,
    )

    with pytest.raises(
        ValueError,
        match="alignment artifact must have global_alignment_status=verified",
    ):
        scene_bounds_review_seed_packet(
            scene_topdown_diagnostic_path=diagnostic_path,
            alignment_artifact_path=alignment_path,
            room_label_reference_path=ROOM_SEMANTICS,
            scene_topdown_render_path=scene_topdown,
            transform=transform,
            frame_id="map",
        )


def test_label_tool_packet_exposes_scene_evidence_without_scene_object_coordinates() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE, include_gaussian_scene=True)
    scene_evidence = packet["scene_evidence"]
    room = scene_evidence["rooms"]["meeting_room_a"]

    assert (
        scene_evidence["coordinate_policy"]
        == "do_not_project_scene_or_gaussian_objects_without_verified_transform"
    )
    assert room["candidate_scene_partition_id"] == "meeting_room_a"
    assert room["alignment_status"] == "candidate"
    assert room["identity_status"] == "candidate_name_match_not_verified_identity"
    assert room["coordinate_status"] == "scene_evidence_has_no_map_coordinates"
    assert room["object_name_counts"]["chair"] == 22
    assert "object_map_coordinates" not in json.dumps(scene_evidence)


def test_label_tool_materializes_repo_local_scene_evidence_artifacts(tmp_path: Path) -> None:
    packet = {
        "scene_evidence": {
            "rooms": {
                "meeting_room_a": {
                    "evidence_artifacts": [
                        "output/operator-console/missing.png",
                        str(Path("/etc/passwd")),
                    ]
                }
            }
        }
    }

    repo_local = REPO_ROOT / "output" / "b1-map12" / "label-tool-test-source.png"
    repo_local.parent.mkdir(parents=True, exist_ok=True)
    repo_local.write_bytes(b"repo local fake image")
    try:
        packet["scene_evidence"]["rooms"]["meeting_room_a"]["evidence_artifacts"][0] = str(
            repo_local.relative_to(REPO_ROOT)
        )
        materialize_scene_evidence_artifacts(packet, output_dir=tmp_path)
    finally:
        repo_local.unlink(missing_ok=True)

    links = packet["scene_evidence"]["rooms"]["meeting_room_a"]["evidence_artifact_links"]
    assert links[0]["available"] is True
    assert links[0]["href"].startswith("evidence/")
    assert (tmp_path / links[0]["href"]).is_file()
    assert links[1] == {
        "source_path": "/etc/passwd",
        "available": False,
        "href": "",
    }


def test_label_tool_html_template_is_external_and_supports_shape_moves() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    html = render_label_tool_html(packet, image_data_url_value="data:image/png;base64,abc")

    assert label_tool_template_path().name == "b1_map12_label_tool_template.html"
    assert label_tool_template().startswith("<!doctype html>")
    assert 'data-mode="rectangle"' in html
    assert 'id="undoAction"' in html
    assert "function pushUndoSnapshot" in html
    assert "function undoLastAction" in html
    assert "function restoreEditorSnapshot" in html
    assert "function createRectangleShape" in html
    assert 'state.drag.type === "newRectangle"' in html
    assert "function moveShapeByDelta" in html
    assert "startGeometry: cloneGeometry(hit.shape.geometry)" in html
    assert "shape.geometry.polygon = geometry.polygon.map" in html
    assert 'event.key.toLowerCase() === "z"' in html
    assert 'pushUndoSnapshot("deleteShape")' in html
    assert 'pushUndoSnapshot("resetInitial")' in html
    assert 'pushUndoSnapshot("importDraft")' in html
    assert 'pushUndoSnapshot("newRectangle")' in html


def test_label_tool_rotates_polygons_without_rotated_box_schema(tmp_path: Path) -> None:
    packet = build_label_tool_packet(
        map_bundle=MAP_BUNDLE,
        semantics_path=_write_polygon_semantics(tmp_path),
    )
    html = render_label_tool_html(packet, image_data_url_value="data:image/png;base64,abc")

    assert "function polygonRotateHandle" in html
    assert "function rotatePolygonDrag" in html
    assert 'data-angle-field="polygon_angle"' in html
    assert '"rotated_box"' not in html
    assert packet["initial_draft_manifest"]["labels"][0]["geometry"]["kind"] == "polygon"


def test_label_tool_supports_global_tilt_without_display_frame_contract() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    html = render_label_tool_html(packet, image_data_url_value="data:image/png;base64,abc")

    assert 'id="globalTiltAngle"' in html
    assert 'id="globalTiltScope"' in html
    assert 'id="globalTiltPivot"' in html
    assert "function applyGlobalTilt" in html
    assert "function rotateShapeAround" in html
    assert "function rotateSourceMapLayersAround" in html
    assert "state.sourceMapLayers = cloneSourceMapLayers" in html
    assert "rotateSourceMapLayersAround(pivot, angleRad)" in html
    assert '"rotated_box"' not in html
    assert '"display_frame":' not in html
    assert '"display_frame_transform"' not in html
    assert packet["source_map_frame_policy"] == "raw_source_map_frame_no_rectified_display_frame"


def test_label_tool_draws_map_native_layers_from_tilted_display_state() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    html = render_label_tool_html(packet, image_data_url_value="data:image/png;base64,abc")

    assert "const fixtures = state.sourceMapLayers.fixtures || []" in html
    assert "const waypoints = state.sourceMapLayers.inspection_waypoints || []" in html
    assert "const ways = state.sourceMapLayers.driveable_ways || []" in html
    assert "drawNavigationMemory" in html
    assert "state.navigationMemoryLayer.items || []" in html
    assert "PACKET.source_map_layers?.fixtures || []" not in html
    assert "PACKET.source_map_layers?.inspection_waypoints || []" not in html
    assert "PACKET.source_map_layers?.driveable_ways || []" not in html


def test_label_tool_html_exposes_layer_toggles_and_candidate_scene_panel() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    html = render_label_tool_html(packet, image_data_url_value="data:image/png;base64,abc")

    assert 'data-layer="rooms"' in html
    assert 'data-layer="fixtures"' in html
    assert 'data-layer="waypoints"' in html
    assert 'data-layer="driveableWays"' in html
    assert 'data-layer="memoryNavGoals"' in html
    assert 'data-layer="memoryObjects"' in html
    assert "function drawFixtures" in html
    assert "function drawWaypoints" in html
    assert "function drawDriveableWays" in html
    assert "function renderSceneEvidence" in html
    assert "geometry conflict" in html
    assert "review geometry/source" in html
    assert "sceneEvidenceSection" in html
    assert "candidate_name_match_not_verified_identity" not in html
    assert "do_not_project_scene_or_gaussian_objects_without_verified_transform" not in html
    assert '"scene_evidence"' not in html
    assert '"object_map_coordinates"' not in html
    assert "Geometry source" not in html
    assert 'data-field="geometry_source"' not in html


def test_label_tool_html_can_include_candidate_scene_panel_when_requested() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE, include_gaussian_scene=True)
    html = render_label_tool_html(packet, image_data_url_value="data:image/png;base64,abc")

    assert "evidence_artifact_links" in html
    assert "candidate_name_match_not_verified_identity" in html
    assert "do_not_project_scene_or_gaussian_objects_without_verified_transform" in html


def test_label_tool_html_supports_read_only_scene_reference_canvas() -> None:
    packet = build_label_tool_packet(map_bundle=MAP_BUNDLE)
    packet["scene_reference"] = {
        "schema": "b1_map12_label_tool_scene_reference_v1",
        "image_width_px": 320,
        "image_height_px": 240,
        "regions": [
            {
                "shape_id": "scene_bbox_seed_meeting_room_a",
                "partition_id": "meeting_room_a",
                "label": "Meeting room A",
                "scene_pixel_polygon": [
                    {"x": 10, "y": 20},
                    {"x": 30, "y": 20},
                    {"x": 30, "y": 40},
                    {"x": 10, "y": 40},
                ],
            }
        ],
    }

    html = render_label_tool_html(
        packet,
        image_data_url_value="data:image/png;base64,map",
        scene_reference_data_url_value="data:image/png;base64,scene",
    )

    assert 'const SCENE_REFERENCE_DATA_URL = "data:image/png;base64,scene"' in html
    assert 'id="sceneReferenceCanvas"' in html
    assert "function drawSceneReference" in html
    assert "Read-only Digital Twin object aggregate bbox reference" in html


def test_label_draft_manifest_keeps_circle_candidate_and_review_only() -> None:
    manifest = draft_manifest_from_shapes(
        [
            {
                "shape_id": "hand_circle_001",
                "label": "uncertain lounge area",
                "category": "living_room",
                "navigation_area_id": "south_fixture_area",
                "asset_partition_id": "reception_area_a",
                "source_room_id": "",
                "source_map_frame_id": "map",
                "geometry": {
                    "kind": "circle",
                    "center": {"x": 0.7, "y": -3.8},
                    "radius_m": 0.85,
                },
                "map_center": {"x": 0.7, "y": -3.8},
                "polygon_role": "navigation_area",
                "geometry_source": "scene_engine_partition",
                "alignment_status": "verified",
                "review_status": "accepted",
            }
        ],
        source_packet={
            "source_map_frame_id": "map",
            "map_bundle": str(MAP_BUNDLE),
            "source_semantics": str(MAP_BUNDLE / "semantics.json"),
            "source_image": str(MAP_BUNDLE / "map.pgm"),
        },
    )

    assert validate_label_draft_manifest(manifest) == []
    label = manifest["labels"][0]
    assert label["geometry"]["kind"] == "circle"
    assert label["geometry"]["radius_m"] == pytest.approx(0.85)
    assert label["geometry_source"] == "operator_authored_navigation_zone"
    assert label["alignment_status"] == "candidate"
    assert label["review_status"] == "draft"


@pytest.mark.parametrize("polygon_role", ["", "definitely_not_a_contract_role"])
def test_label_draft_manifest_rejects_missing_or_invalid_polygon_role(
    polygon_role: str,
) -> None:
    shape = {
        "shape_id": "bad_role_001",
        "label": "bad role",
        "category": "unknown",
        "navigation_area_id": "",
        "asset_partition_id": "",
        "source_room_id": "",
        "source_map_frame_id": "map",
        "geometry": {
            "kind": "polygon",
            "polygon": [
                {"x": 0.0, "y": 0.0},
                {"x": 1.0, "y": 0.0},
                {"x": 1.0, "y": 1.0},
            ],
        },
        "map_center": {"x": 0.7, "y": -3.8},
        "polygon_role": polygon_role,
        "geometry_source": "scene_engine_partition",
        "alignment_status": "candidate",
        "review_status": "draft",
    }

    with pytest.raises(ValueError, match="label bad_role_001 polygon_role must be one of"):
        draft_manifest_from_shapes(
            [shape],
            source_packet={
                "source_map_frame_id": "map",
                "map_bundle": str(MAP_BUNDLE),
                "source_semantics": str(MAP_BUNDLE / "semantics.json"),
                "source_image": str(MAP_BUNDLE / "map.pgm"),
            },
        )

    manifest = {
        "schema": LABEL_DRAFT_MANIFEST_SCHEMA,
        "source_map_frame_id": "map",
        "map_bundle": str(MAP_BUNDLE),
        "source_semantics": str(MAP_BUNDLE / "semantics.json"),
        "source_image": str(MAP_BUNDLE / "map.pgm"),
        "review_status": "draft",
        "alignment_status": "candidate",
        "source_map_mutated": False,
        "verified_status_allowed": False,
        "labels": [draft_label_from_shape(shape)],
    }

    errors = validate_label_draft_manifest(manifest)

    assert any("polygon_role must be one of" in error for error in errors)


def test_label_draft_manifest_rejects_verified_export(tmp_path: Path) -> None:
    packet = build_label_tool_packet(
        map_bundle=MAP_BUNDLE,
        semantics_path=_write_polygon_semantics(tmp_path),
    )
    manifest = json.loads(json.dumps(packet["initial_draft_manifest"]))
    manifest["labels"][0]["alignment_status"] = "verified"
    manifest["labels"][0]["review_status"] = "accepted"

    errors = validate_label_draft_manifest(manifest)

    assert "label meeting_room_a alignment_status must remain candidate" in errors
    assert "label meeting_room_a review_status must remain draft" in errors


def test_label_tool_cli_writes_standalone_html_and_packet(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--output-dir",
            str(tmp_path),
        ],
        check=True,
    )

    packet = json.loads((tmp_path / "label_tool_packet.json").read_text(encoding="utf-8"))
    html = (tmp_path / "label_tool.html").read_text(encoding="utf-8")

    assert packet["schema"] == LABEL_TOOL_PACKET_SCHEMA
    assert packet["initial_draft_manifest"]["schema"] == LABEL_DRAFT_MANIFEST_SCHEMA
    assert "data:image/png;base64," in html
    assert "B1 / Map 12 Label Tool" in html


def test_label_tool_writes_static_artifacts(tmp_path: Path) -> None:
    artifacts = write_label_tool_artifacts(
        map_bundle=MAP_BUNDLE,
        output_dir=tmp_path,
    )

    assert artifacts["shape_count"] == 0
    assert artifacts["html_path"] == tmp_path / "label_tool.html"
    assert artifacts["packet_path"] == tmp_path / "label_tool_packet.json"
    assert (tmp_path / "label_tool.html").is_file()
    packet = json.loads((tmp_path / "label_tool_packet.json").read_text(encoding="utf-8"))
    assert "scene_evidence" not in packet


def test_label_tool_cli_does_not_own_a_server() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--include-gaussian-scene" in result.stdout
    assert "--serve" not in result.stdout
    assert "--host" not in result.stdout
    assert "--port" not in result.stdout


def _copy_map12_bundle(tmp_path: Path) -> Path:
    map_dir = tmp_path / "robot_map_12"
    shutil.copytree(MAP_BUNDLE.parent, map_dir)
    return map_dir / "agibot"


def _write_polygon_semantics(tmp_path: Path) -> Path:
    path = tmp_path / "semantics.json"
    path.write_text(
        json.dumps(
            {
                "schema": "nav2_cleanup_semantics_v1",
                "frame_ids": {"map": "map"},
                "display_frame": None,
                "rooms": [
                    {
                        "room_id": "meeting_room_a",
                        "room_label": "Meeting room A",
                        "category": "meeting_room",
                        "navigation_area_id": "west_corridor",
                        "asset_partition_id": "meeting_room_a",
                        "semantic_source": "test_semantics",
                        "polygon": [
                            {"x": -8.0, "y": 0.0},
                            {"x": -6.0, "y": 0.0},
                            {"x": -6.0, "y": 2.0},
                            {"x": -8.0, "y": 2.0},
                        ],
                    }
                ],
                "fixtures": [],
                "inspection_waypoints": [],
                "driveable_ways": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_fake_scene_topdown_packet(tmp_path: Path) -> Path:
    render_dir = tmp_path / "scene-render"
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
    image_path = render_dir / "views" / "top2down.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (320, 240), color=(220, 225, 230)).save(image_path)
    packet = topdown_render_packet(
        scene_usd=render_dir / "scene_gs.usda",
        prepared_scene_usd=render_dir / "scene_gs.usda",
        scene_bounds=(-2.0, -4.0, 8.0, 4.0),
        request=request,
        request_path=render_dir / "camera_request.json",
        output_dir=render_dir,
        nurec_crop={"status": "applied", "source": "explicit_nurec_crop_max_z"},
        capture_result={
            "ok": True,
            "result_path": str(render_dir / "capture_result.json"),
            "capture": {"images": {"top2down": str(image_path)}},
        },
    )
    packet_path = render_dir / "scene_gaussian_topdown.json"
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


def _write_verified_alignment_artifact(tmp_path: Path) -> Path:
    anchors = [
        alignment_anchor("a1", (0.0, 0.0), (1.0, 2.0)),
        alignment_anchor("a2", (2.0, 0.0), (3.0, 2.0)),
        alignment_anchor("a3", (0.0, 2.0), (1.0, 4.0)),
        alignment_anchor("a4", (2.0, 2.0), (3.0, 4.0)),
        alignment_anchor("a5", (1.0, 3.0), (2.0, 5.0)),
        alignment_anchor("a6", (3.0, 1.0), (4.0, 3.0)),
    ]
    payload = build_alignment_residuals(
        correspondence_manifest(anchors=anchors),
        map_bundle=MAP_BUNDLE,
        output_dir=tmp_path / "alignment",
    )
    path = tmp_path / "alignment_residuals.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
