from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from roboclaws.backends.isaaclab.b1_base_metric_augmentation import (
    B1_MAP12_BASE_METRIC_SIDECAR_SCHEMA,
    B1_ROBOT_CONSUMPTION_MANIFEST_SCHEMA,
    augment_base_metric_map_bundle,
)
from roboclaws.backends.isaaclab.b1_readiness import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    NAVIGATION_PROVENANCE,
)
from roboclaws.maps.b1_base_metric_map import build_base_metric_map_bundle
from roboclaws.maps.bundle import validate_nav2_map_bundle
from roboclaws.maps.runtime_prior_artifact import runtime_metric_map_from_prior_artifact
from roboclaws.maps.runtime_prior_conversion import runtime_prior_snapshot_from_nav2_cleanup_bundle
from roboclaws.maps.runtime_prior_materialization import materialize_runtime_prior_targets

REPO_ROOT = Path(__file__).resolve().parents[3]
MAP12_BUNDLE = (
    REPO_ROOT / "vendors" / "agibot_sdk" / "artifacts" / "maps" / ("robot_map_12") / "agibot"
)
BASE_LABELS = REPO_ROOT / "assets" / "maps" / "b1-map12-base-metric-labels.json"
ROOM_SEMANTICS = REPO_ROOT / "assets" / "maps" / "b1-map12-room-semantics.json"
REMOVED_AUTHORED_BUNDLE = REPO_ROOT / "assets" / "maps" / "agibot-robot-map-12"


def test_checked_in_room_semantics_reference_is_dt_label_only() -> None:
    payload = _read_json(ROOM_SEMANTICS)
    rooms = {room["asset_partition_id"]: room for room in payload["rooms"]}

    assert not REMOVED_AUTHORED_BUNDLE.exists()
    assert payload["schema"] == "scene_room_semantic_overlay_overrides_v1"
    assert payload["policy"]["source_of_truth"] == "digital_twin_scene_partitions"
    assert payload["policy"]["contains_map12_candidate_polygons"] is False
    assert payload["policy"]["contains_navigation_area_bindings"] is False
    assert set(rooms) == {
        "meeting_room_a",
        "meeting_room_b",
        "meeting_room_c",
        "reception_area_a",
        "short_corridor_a",
        "storage_room_a",
    }
    assert rooms["meeting_room_b"]["room_label"] == "Meeting room B"
    assert rooms["meeting_room_b"]["review_status"] == "accepted"
    assert rooms["meeting_room_b"]["semantic_source"] == "digital_twin_room_semantic_reference"
    assert all("geometry" not in room and "polygon" not in room for room in rooms.values())
    assert all(
        "map_polygon" not in room and "navigation_area_id" not in room for room in rooms.values()
    )


def test_base_metric_sidecar_augments_existing_bundle_without_generating_map_context(
    tmp_path: Path,
) -> None:
    base_dir = _base_metric_map(tmp_path)

    result = augment_base_metric_map_bundle(
        base_map_bundle=base_dir,
        output_dir=tmp_path / "runtime",
        allow_blocked_proof=True,
    )
    output_dir = Path(result["output_dir"])
    semantics = _read_json(output_dir / "semantics.json")
    sidecar = _read_json(output_dir / "b1_base_metric_sidecar.json")
    manifest = _read_json(output_dir / "b1_robot_consumption_manifest.json")
    proof = semantics["digital_twin_capabilities"]["robot_consumption_proof"]
    render_proof = semantics["digital_twin_capabilities"]["render_observation_proof"]
    room_proof = semantics["digital_twin_capabilities"]["room_semantic_projection_proof"]

    assert result["schema"] == B1_MAP12_BASE_METRIC_SIDECAR_SCHEMA
    assert result["status"] == "augmented"
    assert validate_nav2_map_bundle(output_dir).ok
    assert semantics["base_metric_map_contract"]["consumer_scope"] == (
        "real_robot_and_digital_twin"
    )
    assert len(semantics["rooms"]) == 8
    assert len(semantics["inspection_waypoints"]) == 5
    assert semantics["navigation_memory_anchors"] == []
    assert semantics["provenance"]["uses_navigation_memory_as_waypoint_source"] is False
    assert semantics["provenance"]["contains_verified_robot_consumption_proof"] is False
    assert proof["status"] == "blocked_missing_verified_alignment"
    assert proof["robot_navigation_supported"] is False
    assert render_proof["status"] == "blocked_missing_verified_same_pose_render_evidence"
    assert render_proof["default_visual_route"]["scene_id"] == "B1_floor2_slow"
    assert room_proof["status"] == "base_metric_map_semantics_only"
    assert room_proof["room_semantics_supported"] is True
    assert room_proof["object_projection_status"] == "blocked_until_object_semantic_anchors"
    assert manifest["schema"] == B1_ROBOT_CONSUMPTION_MANIFEST_SCHEMA
    assert manifest["status"] == "blocked"
    assert manifest["capabilities"]["room_semantics"] is True
    assert manifest["capabilities"]["robot_navigation"] is False
    assert manifest["semantics"]["source"] == "base_metric_map"
    assert manifest["semantics"]["semantic_label_count"] == 8
    assert manifest["policy"]["does_not_use_navigation_memory_as_waypoint_source"] is True
    assert sidecar["policy"]["does_not_generate_rooms_or_waypoints"] is True
    assert sidecar["policy"]["does_not_read_navigation_memory"] is True


def test_base_metric_sidecar_requires_explicit_robot_consumption_proof(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires explicit --alignment-artifact"):
        augment_base_metric_map_bundle(
            base_map_bundle=_base_metric_map(tmp_path),
            output_dir=tmp_path / "runtime",
        )


def test_base_metric_sidecar_materializes_verified_robot_consumption_proof(
    tmp_path: Path,
) -> None:
    base_dir = _base_metric_map(tmp_path)
    alignment_path = tmp_path / "alignment_residuals.json"
    navigation_path = tmp_path / "navigation_smoke.json"
    alignment_path.write_text(json.dumps(_verified_alignment_artifact()), encoding="utf-8")
    navigation_path.write_text(
        json.dumps(_navigation_artifact(tmp_path, alignment_path=alignment_path)),
        encoding="utf-8",
    )

    result = augment_base_metric_map_bundle(
        base_map_bundle=base_dir,
        alignment_artifact_path=alignment_path,
        navigation_artifact_path=navigation_path,
        output_dir=tmp_path / "runtime",
    )
    output_dir = Path(result["output_dir"])
    semantics = _read_json(output_dir / "semantics.json")
    sidecar = _read_json(output_dir / "b1_base_metric_sidecar.json")
    manifest = _read_json(output_dir / "b1_robot_consumption_manifest.json")
    proof = semantics["digital_twin_capabilities"]["robot_consumption_proof"]
    render_proof = semantics["digital_twin_capabilities"]["render_observation_proof"]

    assert result["robot_navigation_supported"] is True
    assert result["robot_consumption_manifest"] == str(
        output_dir / "b1_robot_consumption_manifest.json"
    )
    assert validate_nav2_map_bundle(output_dir).ok
    assert semantics["spatial_contract"]["alignment_status"] == "verified"
    assert semantics["navigation_memory_anchors"] == []
    assert proof["status"] == "robot_navigation_verified"
    assert proof["alignment_status"] == "verified"
    assert proof["navigation_status"] == "verified"
    assert proof["robot_navigation_supported"] is True
    assert proof["robot_navigation_provenance"] == NAVIGATION_PROVENANCE
    assert proof["navigation_waypoint_count"] == 2
    assert proof["waypoint_ids"] == ["wp_1", "wp_2"]
    assert proof["alignment_artifact"] == str(alignment_path)
    assert proof["navigation_artifact"] == str(navigation_path)
    assert proof["manipulation_supported"] is False
    assert render_proof["render_observation_supported"] is True
    assert render_proof["default_visual_route"]["selected"] is True
    assert sidecar["robot_consumption_proof"]["robot_navigation_supported"] is True
    assert manifest["status"] == "robot_navigation_ready"
    assert manifest["navigation"]["ready"] is True
    assert manifest["navigation"]["waypoint_ids"] == ["wp_1", "wp_2"]
    assert manifest["capabilities"]["robot_navigation"] is True
    assert manifest["capabilities"]["room_semantics"] is True
    assert manifest["capabilities"]["object_semantics"] is False
    assert manifest["blocked_capabilities"][0]["capability"] == "object_semantics"


def test_base_metric_sidecar_exports_canonical_runtime_map_prior_snapshot(
    tmp_path: Path,
) -> None:
    base_dir = _base_metric_map(tmp_path)
    alignment_path = tmp_path / "alignment_residuals.json"
    navigation_path = tmp_path / "navigation_smoke.json"
    alignment_path.write_text(json.dumps(_verified_alignment_artifact()), encoding="utf-8")
    navigation_path.write_text(
        json.dumps(_navigation_artifact(tmp_path, alignment_path=alignment_path)),
        encoding="utf-8",
    )
    result = augment_base_metric_map_bundle(
        base_map_bundle=base_dir,
        alignment_artifact_path=alignment_path,
        navigation_artifact_path=navigation_path,
        output_dir=tmp_path / "runtime",
    )

    snapshot = runtime_prior_snapshot_from_nav2_cleanup_bundle(result["output_dir"])
    materialized = materialize_runtime_prior_targets(snapshot)
    runtime_map = runtime_metric_map_from_prior_artifact(snapshot)

    assert snapshot["schema"] == "runtime_map_prior_snapshot_v1"
    assert snapshot["producer"]["type"] == "offline_nav2_cleanup_bundle_conversion"
    assert snapshot["contract"]["online_offline_equivalent_shape"] is True
    assert snapshot["contract"]["private_truth_included"] is False
    assert snapshot["source_navigation_map"]["source_type"] == "nav2_cleanup_bundle"
    assert (
        snapshot["source_navigation_map"]["digital_twin_capabilities"]["robot_consumption_proof"][
            "robot_navigation_supported"
        ]
        is True
    )
    assert runtime_map["schema"] == "runtime_metric_map_v1"
    assert (
        runtime_map["digital_twin_capabilities"]["robot_consumption_proof"][
            "robot_navigation_supported"
        ]
        is True
    )
    assert (
        runtime_map["digital_twin_capabilities"]["render_observation_proof"][
            "render_observation_supported"
        ]
        is True
    )
    assert snapshot["inspection_waypoints"]
    assert snapshot["public_semantic_anchors"]
    assert materialized["actionable_waypoint_ids"]
    assert materialized["fixture_candidates"] == []
    assert materialized["capability_summary"]["robot_consumption_status"] == (
        "robot_navigation_verified"
    )
    assert materialized["capability_summary"]["robot_navigation_supported"] is True
    assert materialized["capability_summary"]["render_observation_supported"] is True
    assert materialized["capability_summary"]["default_visual_route_selected"] is True
    assert materialized["capability_summary"]["room_semantics_supported"] is True
    assert materialized["capability_summary"]["object_projection_status"] == (
        "blocked_until_object_semantic_anchors"
    )


@pytest.mark.parametrize(
    ("artifact_kind", "source_text", "expected_error"),
    [
        (
            "alignment",
            "{not-json\n",
            r"alignment artifact source must contain valid JSON object: "
            r".*alignment_residuals\.json",
        ),
        (
            "alignment",
            "[]\n",
            r"alignment artifact source must contain a JSON object: .*alignment_residuals\.json",
        ),
        (
            "navigation",
            "{not-json\n",
            r"navigation artifact source must contain valid JSON object: .*navigation_smoke\.json",
        ),
        (
            "navigation",
            "[]\n",
            r"navigation artifact source must contain a JSON object: .*navigation_smoke\.json",
        ),
    ],
)
def test_base_metric_sidecar_rejects_bad_robot_consumption_proof_sources(
    tmp_path: Path,
    artifact_kind: str,
    source_text: str,
    expected_error: str,
) -> None:
    alignment_path = tmp_path / "alignment_residuals.json"
    navigation_path = tmp_path / "navigation_smoke.json"
    if artifact_kind == "alignment":
        alignment_path.write_text(source_text, encoding="utf-8")
        navigation_path.write_text(
            json.dumps(_navigation_artifact(tmp_path, alignment_path=alignment_path)),
            encoding="utf-8",
        )
    else:
        alignment_path.write_text(json.dumps(_verified_alignment_artifact()), encoding="utf-8")
        navigation_path.write_text(source_text, encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        augment_base_metric_map_bundle(
            base_map_bundle=_base_metric_map(tmp_path),
            alignment_artifact_path=alignment_path,
            navigation_artifact_path=navigation_path,
            output_dir=tmp_path / "runtime",
        )


def test_base_metric_sidecar_rejects_navigation_alignment_mismatch(
    tmp_path: Path,
) -> None:
    alignment_path = tmp_path / "alignment_residuals.json"
    other_alignment_path = tmp_path / "other_alignment_residuals.json"
    navigation_path = tmp_path / "navigation_smoke.json"
    alignment_path.write_text(json.dumps(_verified_alignment_artifact()), encoding="utf-8")
    navigation_path.write_text(
        json.dumps(_navigation_artifact(tmp_path, alignment_path=other_alignment_path)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="navigation artifact alignment_artifact must match"):
        augment_base_metric_map_bundle(
            base_map_bundle=_base_metric_map(tmp_path),
            alignment_artifact_path=alignment_path,
            navigation_artifact_path=navigation_path,
            output_dir=tmp_path / "runtime",
        )


def _base_metric_map(tmp_path: Path) -> Path:
    result = build_base_metric_map_bundle(
        map_bundle=MAP12_BUNDLE,
        labels_path=BASE_LABELS,
        room_semantics_path=ROOM_SEMANTICS,
        output_dir=tmp_path / "base-metric-map",
    )
    return Path(result["output_dir"])


def _verified_alignment_artifact() -> dict:
    return {
        "schema": "b1_map12_scene_alignment_residuals_v1",
        "bbox_seed_policy": "known_poor_seed_only",
        "manipulation_supported": False,
        "object_receptacle_usd_binding_status": "blocked_out_of_scope",
        "global_alignment_status": "verified",
        "selected_transform_type": "rigid_2d",
        "selected_transform": {
            "source": "reviewed_correspondence_fit",
            "type": "rigid_2d",
        },
        "residual_evidence": {
            "status": "available",
            "matched_anchor_count": 6,
            "transform_source": "reviewed_correspondence_fit",
            "mean_residual_m": 0.1,
            "median_residual_m": 0.1,
            "p90_residual_m": 0.2,
            "max_residual_m": 0.3,
        },
        "area_alignment": [],
    }


def _navigation_artifact(tmp_path: Path, *, alignment_path: Path) -> dict:
    first = tmp_path / "first.fpv.png"
    second = tmp_path / "second.fpv.png"
    first_chase = tmp_path / "first.chase.png"
    second_chase = tmp_path / "second.chase.png"
    first_topdown = tmp_path / "first.map.png"
    second_topdown = tmp_path / "second.map.png"
    _write_reviewable_image(first, offset=0)
    _write_reviewable_image(second, offset=40)
    _write_reviewable_image(first_chase, offset=80)
    _write_reviewable_image(second_chase, offset=120)
    _write_reviewable_image(first_topdown, offset=160)
    _write_reviewable_image(second_topdown, offset=200)
    return {
        "schema": "b1_map12_navigation_smoke_v1",
        "status": "passed",
        "b1_scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
        "visual_route": {
            "scene_id": "B1_floor2_slow",
            "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
            "selected": True,
            "status": "same_pose_render_verified",
        },
        "robot_navigation_supported": True,
        "robot_navigation_provenance": NAVIGATION_PROVENANCE,
        "navigation_provenance": "kinematic_pose_driven",
        "alignment_artifact": str(alignment_path),
        "alignment_transform_source": "reviewed_correspondence_fit",
        "planner_backed": False,
        "physical_robot": False,
        "semantic_source": "robot_map_12_navigation_memory_overlay",
        "semantic_usd_binding_status": "blocked_until_segmentation_or_manifest",
        "semantic_anchors_are_usd_truth": False,
        "usd_object_index_ready": False,
        "usd_receptacle_index_ready": False,
        "manipulation_supported": False,
        "navigation_waypoint_count": 2,
        "robot_view_evidence_status": "available",
        "waypoint_evidence": [
            {
                "waypoint_id": "wp_1",
                "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
                "robot_pose": {
                    "frame": "b1_rebuilt_scene_usd_world_candidate",
                    "x": -4.0,
                    "y": -8.0,
                    "z": 0.0,
                    "yaw_deg": 0.0,
                },
                "robot_pose_applied": True,
                "alignment_artifact": str(alignment_path),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "views": {"fpv": str(first), "chase": str(first_chase), "map": str(first_topdown)},
            },
            {
                "waypoint_id": "wp_2",
                "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
                "robot_pose": {
                    "frame": "b1_rebuilt_scene_usd_world_candidate",
                    "x": -2.0,
                    "y": -7.0,
                    "z": 0.0,
                    "yaw_deg": 0.0,
                },
                "robot_pose_applied": True,
                "alignment_artifact": str(alignment_path),
                "alignment_transform_source": "reviewed_correspondence_fit",
                "views": {
                    "fpv": str(second),
                    "chase": str(second_chase),
                    "map": str(second_topdown),
                },
            },
        ],
    }


def _write_reviewable_image(path: Path, *, offset: int) -> None:
    image = Image.new("RGB", (32, 24))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = (
                (x * 7 + offset) % 256,
                (y * 11 + offset * 2) % 256,
                ((x + y) * 5 + offset * 3) % 256,
            )
    image.save(path)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
