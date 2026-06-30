from __future__ import annotations

import pytest

from roboclaws.household.profiles import (
    CAMERA_LABELS_PROFILE,
    CAMERA_RAW_PROFILE,
    ISAACLAB_SUBPROCESS_BACKEND,
    ROBOT_VIEW_REPORT,
    SEMANTIC_REPORT,
    SMOKE_PROFILE,
    WORLD_PUBLIC_LABELS_PROFILE,
    evidence_lane,
    evidence_lane_metadata,
    evidence_lane_metadata_for_run,
    evidence_lane_names,
    validate_evidence_lane_camera_labeler,
    validate_evidence_lane_metadata,
)
from roboclaws.household.realworld_contract import (
    CAMERA_MODEL_POLICY_MODE,
    RAW_FPV_ONLY_MODE,
    SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY,
    VISIBLE_OBJECT_DETECTIONS_MODE,
)
from roboclaws.household.subprocess_backend import MOLMOSPACES_SUBPROCESS_BACKEND


def test_evidence_lane_registry_contains_public_lanes_only() -> None:
    assert evidence_lane_names() == (
        WORLD_PUBLIC_LABELS_PROFILE,
        CAMERA_LABELS_PROFILE,
        CAMERA_RAW_PROFILE,
    )

    for legacy_name in (
        "world-oracle-labels",
        "visual",
        "semantic",
        "raw-fpv",
        "camera_model_policy",
        "world-labels",
        "world-labels-sanitized",
        "camera-raw",
        "camera-labels",
    ):
        with pytest.raises(ValueError):
            evidence_lane(legacy_name)


@pytest.mark.parametrize(
    ("evidence_lane_name", "agent_input", "perception_mode", "report"),
    [
        (
            WORLD_PUBLIC_LABELS_PROFILE,
            "sanitized_world_labels",
            VISIBLE_OBJECT_DETECTIONS_MODE,
            ROBOT_VIEW_REPORT,
        ),
        (CAMERA_RAW_PROFILE, "raw_camera", RAW_FPV_ONLY_MODE, ROBOT_VIEW_REPORT),
        (CAMERA_LABELS_PROFILE, "camera_labels", CAMERA_MODEL_POLICY_MODE, ROBOT_VIEW_REPORT),
    ],
)
def test_evidence_lane_expands_to_contract_metadata(
    evidence_lane_name: str,
    agent_input: str,
    perception_mode: str,
    report: str,
) -> None:
    metadata = evidence_lane_metadata(evidence_lane_name)

    validate_evidence_lane_metadata(metadata, expected_evidence_lane=evidence_lane_name)
    assert "profile" not in metadata
    assert metadata["mode"] == evidence_lane_name
    assert metadata["evidence_lane"] == evidence_lane_name
    assert metadata["agent_input"] == agent_input
    assert metadata["perception_mode"] == perception_mode
    assert metadata["report"] == report


def test_smoke_is_a_synthetic_preset_not_public_evidence_lane() -> None:
    assert SMOKE_PROFILE not in evidence_lane_names()
    metadata = evidence_lane_metadata(SMOKE_PROFILE)

    assert metadata["mode"] == SMOKE_PROFILE
    assert metadata["evidence_lane"] == WORLD_PUBLIC_LABELS_PROFILE
    assert metadata["preset"] == SMOKE_PROFILE
    assert metadata["agent_input"] == "sanitized_world_labels"
    assert metadata["detection_exposure_policy"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY


def test_world_public_labels_profile_is_no_destination_detector_ablation() -> None:
    metadata = evidence_lane_metadata(WORLD_PUBLIC_LABELS_PROFILE)

    validate_evidence_lane_metadata(metadata, expected_evidence_lane=WORLD_PUBLIC_LABELS_PROFILE)
    assert metadata["backend"] == MOLMOSPACES_SUBPROCESS_BACKEND
    assert metadata["agent_input"] == "sanitized_world_labels"
    assert metadata["perception_mode"] == VISIBLE_OBJECT_DETECTIONS_MODE
    assert metadata["detection_exposure_policy"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
    assert "destination" in metadata["summary"].lower()
    assert "withheld" in metadata["model_input_note"].lower()


def test_world_labels_lane_is_not_image_reasoning_or_map_mode() -> None:
    metadata = evidence_lane_metadata(WORLD_PUBLIC_LABELS_PROFILE)

    assert metadata["backend"] == MOLMOSPACES_SUBPROCESS_BACKEND
    assert metadata["agent_input"] == "sanitized_world_labels"
    assert metadata["input_provenance"] == "simulator_state"
    assert metadata["detection_exposure_policy"] == SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY
    assert "world-public" in metadata["summary"].lower()
    assert "withheld" in metadata["model_input_note"]
    assert "image reasoning" not in metadata["summary"].lower()
    assert "online" not in metadata["summary"].lower()
    assert "offline" not in metadata["summary"].lower()


def test_world_labels_run_metadata_can_disable_robot_view_capture() -> None:
    metadata = evidence_lane_metadata_for_run(
        evidence_lane_name=WORLD_PUBLIC_LABELS_PROFILE,
        backend=MOLMOSPACES_SUBPROCESS_BACKEND,
        perception_mode=VISIBLE_OBJECT_DETECTIONS_MODE,
        record_robot_views=False,
    )

    assert metadata["backend"] == MOLMOSPACES_SUBPROCESS_BACKEND
    assert metadata["include_robot"] is True
    assert metadata["record_robot_views"] is False
    assert metadata["report"] == SEMANTIC_REPORT
    assert "robot-view timeline capture was disabled" in metadata["model_input_note"].lower()


def test_camera_raw_profile_withholds_structured_labels() -> None:
    metadata = evidence_lane_metadata(CAMERA_RAW_PROFILE)

    assert metadata["agent_input"] == "raw_camera"
    assert metadata["perception_mode"] == RAW_FPV_ONLY_MODE
    assert "withheld" in metadata["summary"]
    assert "structured object labels" in metadata["summary"]


def test_camera_raw_run_metadata_allows_isaac_head_camera_backend() -> None:
    metadata = evidence_lane_metadata_for_run(
        evidence_lane_name=CAMERA_RAW_PROFILE,
        backend=ISAACLAB_SUBPROCESS_BACKEND,
        perception_mode=RAW_FPV_ONLY_MODE,
        record_robot_views=True,
    )

    validate_evidence_lane_metadata(
        metadata,
        expected_evidence_lane=CAMERA_RAW_PROFILE,
        expected_backend=ISAACLAB_SUBPROCESS_BACKEND,
        expected_perception_mode=RAW_FPV_ONLY_MODE,
    )
    assert metadata["world_backend"] == "isaac_sim"
    assert metadata["agent_input"] == "raw_camera"
    assert "Isaac" in metadata["summary"]
    assert "robot-mounted head camera" in metadata["model_input_note"]


def test_camera_grounded_labels_requires_camera_labeler() -> None:
    with pytest.raises(ValueError, match="requires camera_labeler"):
        evidence_lane_metadata_for_run(
            evidence_lane_name=CAMERA_LABELS_PROFILE,
            backend=MOLMOSPACES_SUBPROCESS_BACKEND,
            perception_mode=CAMERA_MODEL_POLICY_MODE,
            record_robot_views=True,
        )

    metadata = evidence_lane_metadata_for_run(
        evidence_lane_name=CAMERA_LABELS_PROFILE,
        backend=MOLMOSPACES_SUBPROCESS_BACKEND,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        record_robot_views=True,
        camera_labeler="grounding-dino",
    )

    assert metadata["evidence_lane"] == CAMERA_LABELS_PROFILE
    assert metadata["camera_labeler"] == "grounding-dino"


def test_camera_grounded_run_metadata_allows_isaac_head_camera_backend() -> None:
    metadata = evidence_lane_metadata_for_run(
        evidence_lane_name=CAMERA_LABELS_PROFILE,
        backend=ISAACLAB_SUBPROCESS_BACKEND,
        perception_mode=CAMERA_MODEL_POLICY_MODE,
        record_robot_views=True,
        camera_labeler="grounding-dino",
    )

    validate_evidence_lane_metadata(
        metadata,
        expected_evidence_lane=CAMERA_LABELS_PROFILE,
        expected_backend=ISAACLAB_SUBPROCESS_BACKEND,
        expected_perception_mode=CAMERA_MODEL_POLICY_MODE,
    )
    assert metadata["world_backend"] == "isaac_sim"
    assert metadata["agent_input"] == "camera_labels"
    assert metadata["camera_labeler"] == "grounding-dino"
    assert "Isaac Lab" in metadata["summary"]
    assert "robot-mounted head camera" in metadata["model_input_note"]


@pytest.mark.parametrize(
    "camera_labeler",
    ["sim-projected-labels", "fake-http", "contract-fake"],
)
def test_non_deployable_camera_labelers_are_rejected(camera_labeler: str) -> None:
    with pytest.raises(ValueError, match="unsupported camera_labeler"):
        evidence_lane_metadata_for_run(
            evidence_lane_name=CAMERA_LABELS_PROFILE,
            backend=MOLMOSPACES_SUBPROCESS_BACKEND,
            perception_mode=CAMERA_MODEL_POLICY_MODE,
            record_robot_views=True,
            camera_labeler=camera_labeler,
        )


def test_camera_labeler_rejected_on_world_or_raw_lanes() -> None:
    with pytest.raises(ValueError, match="only valid"):
        validate_evidence_lane_camera_labeler(
            evidence_lane=WORLD_PUBLIC_LABELS_PROFILE,
            camera_labeler="grounding-dino",
        )
