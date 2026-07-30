from __future__ import annotations

import sys
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_dependencies as runtime_dependencies
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from roboclaws.household.isaac_lab_backend import (
    IsaacLabSubprocessBackend,
)


def test_isaac_lab_backend_can_request_segmentation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_init_args: list[str] = []
    original_run_worker = IsaacLabSubprocessBackend._run_worker

    def wrapped_run_worker(
        self: IsaacLabSubprocessBackend,
        command: str,
        *args: str,
    ) -> dict[str, object]:
        if command == "init":
            captured_init_args.extend(args)
        return original_run_worker(self, command, *args)

    monkeypatch.setattr(IsaacLabSubprocessBackend, "_run_worker", wrapped_run_worker)

    IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        enable_segmentation=True,
        segmentation_data_types=("instance_id_segmentation_fast",),
    )

    assert "--enable-segmentation" in captured_init_args
    assert captured_init_args[-2:] == [
        "--segmentation-data-type",
        "instance_id_segmentation_fast",
    ]


def test_isaac_lab_backend_can_request_segmentation_semantic_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_init_args: list[str] = []
    original_run_worker = IsaacLabSubprocessBackend._run_worker

    def wrapped_run_worker(
        self: IsaacLabSubprocessBackend,
        command: str,
        *args: str,
    ) -> dict[str, object]:
        if command == "init":
            captured_init_args.extend(args)
        return original_run_worker(self, command, *args)

    monkeypatch.setattr(IsaacLabSubprocessBackend, "_run_worker", wrapped_run_worker)

    IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        segmentation_data_types=("semantic_segmentation",),
        segmentation_semantic_filter=("usd_prim_path",),
    )

    assert "--enable-segmentation" in captured_init_args
    assert [
        "--segmentation-data-type",
        "semantic_segmentation",
        "--segmentation-semantic-filter",
        "usd_prim_path",
    ] == captured_init_args[-4:]


def test_isaac_lab_segmentation_capture_extracts_selected_bbox() -> None:
    import numpy as np

    class CameraData:
        output = {
            "instance_id_segmentation_fast": np.array(
                [
                    [[0], [0], [0], [0]],
                    [[0], [3], [3], [0]],
                    [[0], [3], [3], [0]],
                    [[0], [0], [0], [0]],
                ]
            )
        }
        info = {
            "instance_id_segmentation_fast": {
                "idToLabels": {3: "/World/Objects/mug_01"},
            }
        }

    class Camera:
        data = CameraData()

    view = runtime_camera._camera_segmentation_view_diagnostics(
        Camera(),
        data_types=("instance_id_segmentation_fast",),
        view_name="fpv",
        np=np,
    )
    capture = runtime_camera._camera_segmentation_capture_diagnostics(
        [view],
        requested_data_types=("instance_id_segmentation_fast",),
        semantic_filter=["class"],
    )
    diagnostics = runtime_evidence.segmentation_diagnostics(
        "real",
        real_smoke={"segmentation": capture},
        scene_binding_diagnostics={
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Objects/mug_01",
                }
            },
            "selected_target_receptacle_bindings": {},
        },
    )

    assert capture["output_data_types"] == ["instance_id_segmentation_fast"]
    assert capture["requested_data_types"] == ["instance_id_segmentation_fast"]
    assert capture["semantic_filter"] == ["class"]
    assert capture["candidate_bbox_count"] == 1
    assert diagnostics["status"] == "available"
    assert diagnostics["semantic_filter"] == ["class"]
    assert diagnostics["candidate_bbox_count"] == 1
    assert diagnostics["selected_usd_prim_match_count"] == 1
    assert diagnostics["selected_candidate_bboxes"][0]["bbox_xyxy"] == [1, 1, 3, 3]
    assert diagnostics["agent_facing"] is False
    assert diagnostics["no_simulator_label_fallback"] is True


def test_isaac_segmentation_matches_usd_paths_case_insensitively() -> None:
    diagnostics = runtime_evidence.segmentation_diagnostics(
        "real",
        real_smoke={
            "segmentation": {
                "requested_data_types": ["semantic_segmentation"],
                "output_data_types": ["semantic_segmentation"],
                "candidate_bboxes": [
                    {
                        "data_type": "semantic_segmentation",
                        "label": "/world/objects/mug_01",
                        "label_id": 4,
                        "usd_prim_path": "/world/objects/mug_01",
                        "bbox_xyxy": [8, 8, 32, 36],
                        "pixel_count": 144,
                        "image_size": [540, 360],
                    }
                ],
                "no_simulator_label_fallback": True,
            }
        },
        scene_binding_diagnostics={
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Objects/mug_01",
                    "has_renderable_geometry": True,
                }
            },
            "selected_target_receptacle_bindings": {},
        },
    )

    assert diagnostics["available"] is True
    assert diagnostics["selected_usd_prim_match_count"] == 1


def test_isaac_lab_segmentation_capture_accepts_list_info_shape() -> None:
    import numpy as np

    class CameraData:
        output = {
            "semantic_segmentation": np.array(
                [
                    [[0], [0], [0], [0]],
                    [[0], [5], [5], [0]],
                    [[0], [5], [5], [0]],
                    [[0], [0], [0], [0]],
                ]
            )
        }
        info = [
            {
                "semantic_segmentation": {
                    "idToLabels": {"5": {"usd_prim_path": "/World/Objects/bowl_01"}},
                }
            }
        ]

    class Camera:
        data = CameraData()

    view = runtime_camera._camera_segmentation_view_diagnostics(
        Camera(),
        data_types=("semantic_segmentation",),
        view_name="fpv",
        np=np,
    )
    capture = runtime_camera._camera_segmentation_capture_diagnostics(
        [view],
        requested_data_types=("semantic_segmentation",),
    )

    assert capture["output_data_types"] == ["semantic_segmentation"]
    assert capture["candidate_bbox_count"] == 1
    assert capture["candidate_bboxes"][0]["label"] == "/World/Objects/bowl_01"
    assert capture["candidate_bboxes"][0]["bbox_xyxy"] == [1, 1, 3, 3]
