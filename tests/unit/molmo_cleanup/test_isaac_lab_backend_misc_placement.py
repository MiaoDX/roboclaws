from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

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
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _unit_isaac_object_index,
    _unit_isaac_receptacle_index,
)


def test_isaac_lab_backend_can_navigate_to_relative_pose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
    )
    captured: dict[str, object] = {}

    def fake_run_worker(command: str, *args: str) -> dict[str, object]:
        captured["command"] = command
        captured["args"] = args
        return {
            "ok": True,
            "tool": "navigate_to_relative_pose",
            "applied_delta": {
                "forward_m": 0.25,
                "lateral_m": -0.125,
                "yaw_delta_deg": 15.0,
            },
        }

    monkeypatch.setattr(backend, "_run_worker", fake_run_worker)

    result = backend.navigate_to_relative_pose(
        forward_m=0.25,
        lateral_m=-0.125,
        yaw_delta_deg=15,
    )

    assert result["ok"] is True
    assert captured["command"] == "navigate_to_relative_pose"
    assert captured["args"] == (
        "--forward-m",
        "0.25",
        "--lateral-m",
        "-0.125",
        "--yaw-delta-deg",
        "15.0",
    )


def test_isaac_support_pose_uses_usd_world_bounds_center() -> None:
    support = runtime_dependencies._support_pose_from_usd_bounds(
        {
            "center": [2.5, 5.5, 0.75],
            "max": [3.0, 6.0, 1.2],
            "size": [1.0, 2.0, 0.9],
        },
        fallback={"frame": "world", "x": 99.0, "y": 99.0, "z": 0.0, "yaw_deg": 45.0},
    )

    assert support is not None
    assert support["frame"] == "usd_world"
    assert support["x"] == pytest.approx(2.5)
    assert support["y"] == pytest.approx(5.5)
    assert support["z"] == pytest.approx(1.2)
    assert support["yaw_deg"] == pytest.approx(45.0)
    assert support["support_radius_m"] == pytest.approx(1.0)
    assert support["source"] == "usd_world_bounds_top_center"


def test_isaac_robot_pose_prefers_bound_receptacle_support_pose() -> None:
    state = {
        "scene_binding_diagnostics": {
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_handle": "real_sink",
                    "usd_prim_path": "/val_1/Geometry/real_sink",
                }
            }
        },
        "receptacle_index": {
            "real_sink": {
                "support_pose": {
                    "frame": "usd_world",
                    "x": 2.5,
                    "y": 5.5,
                    "z": 0.75,
                    "source": "usd_world_bounds_top_center",
                    "support_radius_m": 0.8,
                },
                "usd_world_bounds": {"center": [2.5, 5.5, 0.75]},
            }
        },
        "object_index": {
            "bowl_01": {
                "usd_world_bounds": {"center": [4.5, 7.5, 0.9]},
            }
        },
    }

    pose = runtime_state._robot_pose_for_receptacle(state, "sink_01")

    assert pose["frame"] == "molmospaces_scene_frame_v1"
    assert pose["schema"] == "cleanup_robot_pose_result_v1"
    assert pose["pose_source"] == "roboclaws_shared_scene_frame_support_pose"
    assert pose["pose_request"]["schema"] == "cleanup_robot_pose_request_v1"
    assert pose["pose_request"]["resolver"] == "roboclaws.cleanup_robot_pose.near_target_v1"
    assert pose["support_pose_source"] == "usd_world_bounds_top_center"
    assert pose["target_position"] == pytest.approx([2.5, 5.5, 0.75])
    distance_to_target = math.hypot(pose["x"] - 2.5, pose["y"] - 5.5)
    assert distance_to_target == pytest.approx(1.15)


def test_isaac_support_placement_resolver_uses_usd_bounds() -> None:
    state = {
        "scenario": {
            "objects": [
                {
                    "object_id": "mug_01",
                    "name": "mug",
                    "category": "dish",
                    "location_id": "sofa_01",
                    "pickupable": True,
                }
            ],
            "receptacles": [
                {
                    "receptacle_id": "sink_01",
                    "name": "sink",
                    "category": "Sink",
                    "room_area": "kitchen",
                }
            ],
        },
        "locations": {"mug_01": "sofa_01"},
        "containment": {},
        "object_pose_overrides": {},
        "object_index": _unit_isaac_object_index(),
        "receptacle_index": _unit_isaac_receptacle_index(),
        "scene_binding_diagnostics": {
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_handle": "mug_01",
                    "usd_prim_path": "/World/Objects/mug_01",
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_handle": "sink_01",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                }
            },
        },
    }

    resolution = runtime_state._resolve_isaac_placement(
        state,
        object_id="mug_01",
        receptacle_id="sink_01",
        index=0,
        relation="on",
        source="unit",
    )

    assert resolution["support_status"] == "direct_support"
    assert resolution["contact_proof"] == "usd_bounds_direct_support"
    assert resolution["position"] == pytest.approx([2.5, 5.5, 1.615])
    assert resolution["object_bottom_offset_m"] == pytest.approx(0.4)
    assert resolution["support_clearance_m"] == pytest.approx(0.015)
    diagnostic = runtime_state._isaac_placement_diagnostic(
        state=state,
        object_id="mug_01",
        receptacle_id="sink_01",
        relation="on",
        source="unit",
        placement_resolution=resolution,
    )
    assert diagnostic["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert diagnostic["direct_support_proven"] is True
    assert diagnostic["support_surface_top_z"] == pytest.approx(1.2)


def test_isaac_receptacle_support_surfaces_prefer_broad_lower_descendant() -> None:
    class _FakePrim:
        def __init__(
            self,
            path: str,
            *,
            type_name: str = "Mesh",
            children: list["_FakePrim"] | None = None,
        ) -> None:
            self._path = path
            self._type_name = type_name
            self.children = children or []

        def GetPath(self) -> str:
            return self._path

        def GetTypeName(self) -> str:
            return self._type_name

        def IsA(self, _type: object) -> bool:
            return self._type_name == "Mesh"

    mattress = _FakePrim("/World/Receptacles/bed_01/Geometry/mattress")
    bedsheet = _FakePrim("/World/Receptacles/bed_01/Geometry/bedsheet")
    headboard = _FakePrim("/World/Receptacles/bed_01/Geometry/headboard")
    rail = _FakePrim("/World/Receptacles/bed_01/Geometry/rail")
    bed = _FakePrim(
        "/World/Receptacles/bed_01",
        type_name="Xform",
        children=[mattress, bedsheet, headboard, rail],
    )
    bounds_by_path = {
        "/World/Receptacles/bed_01": {
            "center": [2.0, 3.0, 0.85],
            "min": [0.8, 1.8, 0.0],
            "max": [3.2, 4.2, 1.7],
            "size": [2.4, 2.4, 1.7],
        },
        "/World/Receptacles/bed_01/Geometry/mattress": {
            "center": [2.0, 3.0, 0.45],
            "min": [0.9, 1.9, 0.2],
            "max": [3.1, 4.1, 0.7],
            "size": [2.2, 2.2, 0.5],
        },
        "/World/Receptacles/bed_01/Geometry/bedsheet": {
            "center": [2.05, 3.02, 0.43],
            "min": [0.95, 1.92, 0.2],
            "max": [3.15, 4.12, 0.66],
            "size": [2.2, 2.2, 0.46],
        },
        "/World/Receptacles/bed_01/Geometry/headboard": {
            "center": [2.0, 4.15, 0.85],
            "min": [0.8, 4.05, 0.0],
            "max": [3.2, 4.25, 1.7],
            "size": [2.4, 0.2, 1.7],
        },
        "/World/Receptacles/bed_01/Geometry/rail": {
            "center": [0.86, 3.0, 0.7],
            "min": [0.8, 1.8, 0.0],
            "max": [0.92, 4.2, 1.4],
            "size": [0.12, 2.4, 1.4],
        },
    }
    original_usd_world_bounds = runtime_capture._usd_world_bounds
    original_iter_usd_prim_range = runtime_capture._iter_usd_prim_range
    runtime_capture._usd_world_bounds = (  # type: ignore[method-assign]
        lambda prim, *, usd_geom: bounds_by_path[str(prim.GetPath())]
    )
    runtime_capture._iter_usd_prim_range = lambda prim: [  # type: ignore[method-assign]
        prim,
        *getattr(prim, "children", []),
    ]

    try:
        surfaces = runtime_capture._usd_receptacle_support_surfaces(
            prim=bed,
            usd_geom=SimpleNamespace(Gprim=object),
        )
    finally:
        runtime_capture._usd_world_bounds = original_usd_world_bounds  # type: ignore[method-assign]
        runtime_capture._iter_usd_prim_range = original_iter_usd_prim_range  # type: ignore[method-assign]

    assert surfaces[0]["source"] == "isaac_usd_descendant_support_surface_union"
    assert surfaces[0]["top_z"] == pytest.approx(0.7)
    assert surfaces[1]["surface_id"] in {
        "/World/Receptacles/bed_01/Geometry/mattress",
        "/World/Receptacles/bed_01/Geometry/bedsheet",
    }
    assert surfaces[1]["source"] == "isaac_usd_descendant_support_surface"
    assert all("headboard" not in item["surface_id"] for item in surfaces[:2])


def test_isaac_support_placement_resolver_uses_descendant_support_surface() -> None:
    state = {
        "scenario": {
            "objects": [
                {
                    "object_id": "bowl_01",
                    "name": "bowl",
                    "category": "dish",
                    "location_id": "sink_01",
                    "pickupable": True,
                }
            ],
            "receptacles": [
                {
                    "receptacle_id": "bed_01",
                    "name": "bed",
                    "category": "Bed",
                    "room_area": "bedroom",
                }
            ],
        },
        "locations": {"bowl_01": "sink_01"},
        "containment": {},
        "object_pose_overrides": {},
        "object_index": {
            "bowl_01": {
                "usd_prim_path": "/World/Objects/bowl_01",
                "category": "Bowl",
                "public_label": "bowl_01",
                "usd_world_bounds": {
                    "center": [0.0, 0.0, 0.1],
                    "min": [-0.1, -0.1, 0.0],
                    "max": [0.1, 0.1, 0.2],
                    "size": [0.2, 0.2, 0.2],
                },
            }
        },
        "receptacle_index": {
            "bed_01": {
                "usd_prim_path": "/World/Receptacles/bed_01",
                "category": "Bed",
                "public_label": "bed_01",
                "usd_world_bounds": {
                    "center": [2.0, 3.0, 0.85],
                    "min": [0.8, 1.8, 0.0],
                    "max": [3.2, 4.2, 1.7],
                    "size": [2.4, 2.4, 1.7],
                },
                "support_surfaces": [
                    {
                        "surface_id": "/World/Receptacles/bed_01/Geometry/support_union",
                        "center": [2.0, 3.0],
                        "top_z": 0.7,
                        "half_extents": [1.1, 1.1],
                        "area_m2": 4.84,
                        "source": "isaac_usd_descendant_support_surface_union",
                    }
                ],
            }
        },
        "scene_binding_diagnostics": {},
    }

    resolution = runtime_state._resolve_isaac_placement(
        state,
        object_id="bowl_01",
        receptacle_id="bed_01",
        index=0,
        relation="on",
        source="unit",
    )

    assert resolution["support_status"] == "direct_support"
    assert resolution["position"] == pytest.approx([2.0, 3.0, 0.835])
    assert resolution["support_surface"]["surface_id"].endswith("/support_union")
    assert resolution["support_surface"]["top_z"] == pytest.approx(0.7)
    assert resolution["support_surface"]["source"] == "isaac_usd_descendant_support_surface_union"


def test_isaac_mess_seed_updates_locations_and_pose_overrides() -> None:
    state = {
        "scenario": {
            "objects": [
                {
                    "object_id": "mug_01",
                    "name": "mug",
                    "category": "dish",
                    "location_id": "sink_01",
                    "pickupable": True,
                }
            ],
            "receptacles": [
                {
                    "receptacle_id": "sink_01",
                    "name": "sink",
                    "category": "Sink",
                    "room_area": "kitchen",
                },
                {
                    "receptacle_id": "sofa_01",
                    "name": "sofa",
                    "category": "Sofa",
                    "room_area": "living",
                },
            ],
        },
        "private_manifest": {
            "targets": [{"object_id": "mug_01", "valid_receptacle_ids": ["sink_01"]}],
        },
        "generated_mess_manifest": {
            "schema": "roboclaws_generated_mess_manifest_v1",
            "targets": [
                {
                    "object_id": "mug_01",
                    "valid_receptacle_ids": ["sink_01"],
                    "target_receptacle_id": "sink_01",
                    "start_receptacle_id": "sofa_01",
                    "relation": "on",
                    "placement_index": 3,
                }
            ],
        },
        "locations": {"mug_01": "sink_01"},
        "containment": {},
        "object_pose_overrides": {},
        "mess_placement_diagnostics": [],
        "object_index": _unit_isaac_object_index(),
        "receptacle_index": {
            **_unit_isaac_receptacle_index(),
            "sofa_01": {
                "usd_prim_path": "/World/Receptacles/sofa_01",
                "category": "Sofa",
                "public_label": "sofa_01",
                "usd_world_bounds": {
                    "center": [1.0, 2.0, 0.4],
                    "min": [0.5, 1.5, 0.0],
                    "max": [1.5, 2.5, 0.8],
                    "size": [1.0, 1.0, 0.8],
                },
                "support_pose": {
                    "frame": "usd_world",
                    "x": 1.0,
                    "y": 2.0,
                    "z": 0.8,
                    "source": "usd_world_bounds_top_center",
                    "support_radius_m": 0.5,
                },
            },
        },
        "scene_binding_diagnostics": {},
    }

    runtime_state._seed_generated_mess_placements(state)

    assert state["locations"]["mug_01"] == "sofa_01"
    assert state["scenario"]["objects"][0]["location_id"] == "sofa_01"
    assert state["object_pose_overrides"]["mug_01"]["position_source"] == (
        "isaac_support_placement_resolver"
    )
    assert state["object_pose_overrides"]["mug_01"]["source"] == "canonical_mess_manifest"
    assert state["mess_placement_diagnostics"][0]["diagnostic_source"] == (
        "canonical_mess_manifest"
    )
    assert state["mess_placement_diagnostics"][0]["placement_support_status"] == ("direct_support")


def test_isaac_robot_view_focus_prefers_object_pose() -> None:
    state = {
        "scene_binding_diagnostics": {
            "selected_object_bindings": {
                "mug_01": {
                    "status": "bound",
                    "usd_handle": "mug_01",
                    "usd_prim_path": "/World/Objects/mug_01",
                }
            }
        },
        "object_index": _unit_isaac_object_index(),
        "receptacle_index": _unit_isaac_receptacle_index(),
    }
    state["semantic_pose_state"] = {
        "object_poses": runtime_state._semantic_object_poses_from_state(
            {
                **state,
                "scenario": {
                    "objects": [{"object_id": "mug_01", "location_id": "sink_01"}],
                },
                "locations": {"mug_01": "sink_01"},
                "containment": {},
                "current_receptacle_id": "sink_01",
            }
        )
    }

    focus = runtime_commands._robot_view_focus(
        state,
        {"target_position": [2.5, 5.5, 1.2]},
        focus_object_id="mug_01",
        focus_receptacle_id="sink_01",
    )

    assert focus["source"] == "isaac_semantic_pose_object_pose"
    assert focus["focus_position"] == pytest.approx([4.0, 5.0, 0.4])
    assert focus["fpv_visibility"]["status"] == "segmentation_unavailable"
    assert focus["visibility"]["status"] == "segmentation_unavailable"


def test_isaac_object_bottom_offset_uses_usd_root_position_before_bbox_center() -> None:
    state = {
        "object_index": {
            "teddy_01": {
                "usd_world_bounds": {
                    "min": [1.0, 2.0, 0.84],
                    "center": [1.2, 2.2, 1.10],
                    "max": [1.4, 2.4, 1.36],
                },
                "usd_world_root_position": [1.2, 2.2, 0.90],
            }
        },
        "objects": {
            "teddy_01": {
                "object_id": "teddy_01",
                "category": "TeddyBear",
            }
        },
    }

    assert runtime_state._isaac_object_bottom_offset(state, "teddy_01") == (pytest.approx(0.06))
