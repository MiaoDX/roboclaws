from __future__ import annotations

import json
import sys
import types
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
from tests.unit.molmo_cleanup.isaac_lab_backend_support import (
    _existing_translate_xformable_type,
    _FakeSinglePrimStage,
    _install_semantic_pose_stage_pxr,
    _offset_parent_xformable_type,
    _recording_xform_common_api_type,
    _semantic_pose_stage_state,
)


def test_isaac_semantic_pose_stage_application_uses_exact_pose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []

    class _FakePrim:
        def IsValid(self) -> bool:
            return True

    class _FakeStage:
        def GetPrimAtPath(self, path: str) -> _FakePrim:
            assert path == "/World/Objects/mug_01"
            return _FakePrim()

    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

    class _FakeGf:
        @staticmethod
        def Vec3d(*values: float) -> tuple[float, float, float]:
            return (float(values[0]), float(values[1]), float(values[2]))

    fake_pxr = types.SimpleNamespace(
        Gf=_FakeGf,
        UsdGeom=types.SimpleNamespace(XformCommonAPI=_FakeXformCommonAPI),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)

    result = runtime_camera._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeStage()),
        semantic_pose_state={
            "object_poses": {
                "mug_01": {
                    "usd_prim_path": "/World/Objects/mug_01",
                    "support_receptacle_id": "sink_01",
                    "position": [9.0, 8.0, 7.0],
                }
            },
            "receptacle_index": {
                "sink_01": {
                    "support_pose": {
                        "x": 2.5,
                        "y": 5.5,
                        "z": 1.2,
                    }
                }
            },
        },
    )

    assert result["status"] == "applied"
    assert translations == [(9.0, 8.0, 7.0)]
    assert result["applied_objects"][0]["target_position"] == [9.0, 8.0, 7.0]


def test_isaac_semantic_pose_stage_application_converts_world_pose_to_parent_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []
    _install_semantic_pose_stage_pxr(
        monkeypatch,
        xform_common_api=_recording_xform_common_api_type(translations),
        xformable=_offset_parent_xformable_type((10.0, 20.0, 0.5)),
    )

    result = runtime_camera._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(
            get_current_stage=lambda: _FakeSinglePrimStage("/World/Room/Objects/mug_01")
        ),
        semantic_pose_state=_semantic_pose_stage_state(
            object_id="mug_01",
            usd_prim_path="/World/Room/Objects/mug_01",
            position=[12.0, 23.0, 4.5],
            support_receptacle_id="sink_01",
        ),
    )

    assert result["status"] == "applied"
    assert translations == [pytest.approx((2.0, 3.0, 4.0))]
    assert result["applied_objects"][0]["target_position"] == [12.0, 23.0, 4.5]
    assert result["applied_objects"][0]["authored_translate"] == [2.0, 3.0, 4.0]
    assert result["applied_objects"][0]["authored_translate_frame"] == "parent_local"


def test_isaac_semantic_pose_stage_application_updates_existing_translate_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []
    _install_semantic_pose_stage_pxr(
        monkeypatch,
        xform_common_api=_recording_xform_common_api_type(
            translations,
            failure_message="existing translate op should be authored directly",
        ),
        xformable=_existing_translate_xformable_type(translations, (3.0, 4.0, 5.0)),
    )

    result = runtime_camera._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(
            get_current_stage=lambda: _FakeSinglePrimStage("/World/Geometry/teddy")
        ),
        semantic_pose_state=_semantic_pose_stage_state(
            object_id="teddy",
            usd_prim_path="/World/Geometry/teddy",
            position=[8.0, 10.0, 12.0],
            support_receptacle_id="desk",
        ),
    )

    assert result["status"] == "applied"
    assert translations == [pytest.approx((5.0, 6.0, 7.0))]
    applied = result["applied_objects"][0]
    assert applied["authored_translate"] == [5.0, 6.0, 7.0]
    assert applied["translate_application_method"] == "existing_xformOp_translate"
    assert applied["authored_xform_op"] == "xformOp:translate"


def test_isaac_semantic_pose_stage_application_blocks_parent_transform_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []

    class _FakeParent:
        def __bool__(self) -> bool:
            return True

    class _FakePrim:
        def IsValid(self) -> bool:
            return True

        def GetParent(self) -> _FakeParent:
            return _FakeParent()

    class _FakeStage:
        def GetPrimAtPath(self, path: str) -> _FakePrim:
            assert path == "/World/Room/Objects/mug_01"
            return _FakePrim()

    class _BrokenXformable:
        def __init__(self, parent: _FakeParent) -> None:
            self.parent = parent

        def ComputeLocalToWorldTransform(self, time_code: float) -> object:
            assert time_code == 0.0
            raise RuntimeError("missing parent xform")

    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

    class _FakeGf:
        @staticmethod
        def Vec3d(*values: float) -> tuple[float, float, float]:
            return (float(values[0]), float(values[1]), float(values[2]))

    fake_pxr = types.SimpleNamespace(
        Gf=_FakeGf,
        UsdGeom=types.SimpleNamespace(
            XformCommonAPI=_FakeXformCommonAPI,
            Xformable=_BrokenXformable,
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)

    result = runtime_camera._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeStage()),
        semantic_pose_state={
            "object_poses": {
                "mug_01": {
                    "usd_prim_path": "/World/Room/Objects/mug_01",
                    "support_receptacle_id": "sink_01",
                    "position": [12.0, 23.0, 4.5],
                }
            },
            "receptacle_index": {},
        },
    )

    assert result["status"] == "blocked"
    assert result["applied_object_count"] == 0
    assert result["failed_objects"][0]["reason"] == "parent_local_transform_failed"
    assert translations == []


def test_isaac_semantic_pose_stage_application_does_not_mark_partial_as_rendered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    translations: list[object] = []

    class _FakePrim:
        def __init__(self, valid: bool) -> None:
            self.valid = valid

        def IsValid(self) -> bool:
            return self.valid

    class _FakeStage:
        def GetPrimAtPath(self, path: str) -> _FakePrim:
            return _FakePrim(path.endswith("/mug_01"))

    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

    class _FakeGf:
        @staticmethod
        def Vec3d(*values: float) -> tuple[float, float, float]:
            return (float(values[0]), float(values[1]), float(values[2]))

    fake_pxr = types.SimpleNamespace(
        Gf=_FakeGf,
        UsdGeom=types.SimpleNamespace(XformCommonAPI=_FakeXformCommonAPI),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)

    result = runtime_camera._apply_semantic_pose_state_to_stage(
        stage_utils=SimpleNamespace(get_current_stage=lambda: _FakeStage()),
        semantic_pose_state={
            "object_poses": {
                "mug_01": {
                    "usd_prim_path": "/World/Objects/mug_01",
                    "support_receptacle_id": "sink_01",
                    "position": [1.0, 2.0, 3.0],
                },
                "spoon_01": {
                    "usd_prim_path": "/World/Objects/spoon_01",
                    "support_receptacle_id": "sink_01",
                    "position": [4.0, 5.0, 6.0],
                },
            },
            "receptacle_index": {},
        },
    )

    assert result["status"] == "partial"
    assert result["applied_object_count"] == 1
    assert result["failed_object_count"] == 1
    assert result["rendered_to_usd"] is False
    assert translations == [(1.0, 2.0, 3.0)]


def test_isaac_stage_light_paths_detects_existing_lights_without_pxr() -> None:
    class _FakePrim:
        def __init__(self, path: str, is_light: bool, type_name: str = "") -> None:
            self._path = path
            self._is_light = is_light
            self._type_name = type_name

        def IsValid(self) -> bool:
            return True

        def GetPath(self) -> str:
            return self._path

        def IsA(self, _api: object) -> bool:
            return self._is_light

        def GetTypeName(self) -> str:
            return self._type_name

    class _FakeStage:
        def Traverse(self) -> list[_FakePrim]:
            return [
                _FakePrim("/val_1/scene_skybox_light", True),
                _FakePrim("/val_1/scene_dir_light", False, "DistantLight"),
                _FakePrim("/val_1/Geometry/table", False),
            ]

    paths = runtime_dependencies._stage_light_paths(
        _FakeStage(),
        light_api=object(),
    )

    assert paths == [
        "/val_1/scene_skybox_light",
        "/val_1/scene_dir_light",
    ]


def test_isaac_usd_index_path_heuristics_skip_container_prims() -> None:
    assert runtime_dependencies._is_object_prim_path("/World/Objects") is False
    assert runtime_dependencies._is_object_prim_path("/World/Objects/mug_01") is True
    assert runtime_dependencies._is_receptacle_prim_path("/World/Receptacles") is False
    assert runtime_dependencies._is_receptacle_prim_path("/World/Receptacles/sink_01") is True


def test_isaac_molmospaces_scene_metadata_indexes_real_geometry_prims(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_0"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7": {
                        "hash_name": "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7",
                        "asset_id": "Mug_1",
                        "object_id": "Mug|surface|7|71",
                        "category": "Mug",
                        "is_static": False,
                        "parent": "desk_767b7ce268898119aaeb97804ba52bdd_1_0_7",
                        "children": [],
                    },
                    "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5": {
                        "hash_name": "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5",
                        "asset_id": "Sink_1",
                        "object_id": "Sink|5|1|0",
                        "category": "Sink",
                        "is_static": True,
                        "children": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    object_index: dict[str, dict[str, object]] = {}
    receptacle_index: dict[str, dict[str, object]] = {}

    runtime_dependencies._merge_molmospaces_metadata_index(
        usd_path=scene_usd,
        prim_paths_by_name={
            "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7": [
                "/val_0/Geometry/mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7"
            ],
            "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5": [
                "/val_0/Geometry/sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5"
            ],
        },
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    mug = object_index["mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7"]
    sink = receptacle_index["sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5"]
    assert mug["usd_prim_path"] == "/val_0/Geometry/mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7"
    assert mug["category"] == "Mug"
    assert mug["index_source"] == "usd_stage_traversal"
    assert mug["metadata_source"] == "molmospaces_scene_metadata"
    assert sink["usd_prim_path"] == "/val_0/Geometry/sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_5"
    assert sink["category"] == "Sink"
    assert sink["kind"] == "receptacle"


def test_isaac_molmospaces_metadata_prefers_top_level_geometry_prim() -> None:
    assert (
        runtime_dependencies._molmospaces_metadata_prim_path(
            "mug_01",
            {
                "mug_01": [
                    "/val_0/A/mug_01",
                    "/val_0/Geometry/mug_01",
                    "/val_0/Geometry/mug_01/mesh",
                ]
            },
        )
        == "/val_0/Geometry/mug_01"
    )


def test_isaac_segmentation_diagnostics_reports_unrenderable_selected_prims() -> None:
    diagnostics = runtime_evidence.segmentation_diagnostics(
        "real",
        real_smoke={
            "segmentation": {
                "requested_data_types": ["semantic_segmentation"],
                "output_data_types": ["semantic_segmentation"],
                "candidate_bboxes": [
                    {
                        "data_type": "semantic_segmentation",
                        "label": "BACKGROUND",
                        "label_id": 0,
                        "usd_prim_path": "",
                        "bbox_xyxy": [0, 0, 540, 360],
                        "pixel_count": 194400,
                        "image_size": [540, 360],
                    }
                ],
                "no_simulator_label_fallback": True,
            }
        },
        scene_binding_diagnostics={
            "selected_object_bindings": {
                "bowl_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Objects/bowl_01",
                    "has_renderable_geometry": False,
                }
            },
            "selected_target_receptacle_bindings": {
                "sink_01": {
                    "status": "bound",
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "has_renderable_geometry": True,
                }
            },
        },
    )

    assert diagnostics["available"] is False
    assert diagnostics["selected_usd_unrenderable_prim_paths"] == ["/World/Objects/bowl_01"]
    assert any("no renderable geometry" in blocker for blocker in diagnostics["blockers"])


def test_isaac_scene_index_semantic_labels_are_applied_to_stage_prims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[tuple[str, str, tuple[str, ...]]] = []

    class Prim:
        def __init__(self, path: str, valid: bool = True, type_name: str = "") -> None:
            self.path = path
            self.valid = valid
            self.type_name = type_name

        def IsValid(self) -> bool:
            return self.valid

    bowl = Prim("/World/Objects/bowl_01")
    bowl_mesh = Prim("/World/Objects/bowl_01/mesh", type_name="Mesh")
    sink = Prim("/World/Receptacles/sink_01", type_name="Cube")

    class Stage:
        def __init__(self) -> None:
            self.prims = {
                "/World/Objects/bowl_01": bowl,
                "/World/Receptacles/sink_01": sink,
            }

        def GetPrimAtPath(self, path: str) -> Prim:
            return self.prims.get(path, Prim(path, valid=False))

    class StageUtils:
        @staticmethod
        def get_current_stage() -> Stage:
            return Stage()

    class SimUtils:
        @staticmethod
        def add_labels(
            prim: Prim,
            *,
            labels: list[str],
            instance_name: str,
            overwrite: bool,
        ) -> None:
            assert overwrite is True
            records.append((prim.path, instance_name, tuple(labels)))

    monkeypatch.setattr(
        runtime_camera,
        "_semantic_label_target_prims",
        lambda prim: [bowl, bowl_mesh] if prim is bowl else [prim],
    )

    result = runtime_camera._apply_scene_index_semantic_labels(
        stage_utils=StageUtils(),
        sim_utils=SimUtils(),
        scene_index_diagnostics={
            "object_index": {
                "bowl_01": {
                    "usd_prim_path": "/World/Objects/bowl_01",
                    "category": "Bowl",
                    "kind": "object",
                }
            },
            "receptacle_index": {
                "sink_01": {
                    "usd_prim_path": "/World/Receptacles/sink_01",
                    "category": "Sink",
                    "kind": "receptacle",
                },
                "missing": {
                    "usd_prim_path": "/World/Receptacles/missing",
                    "category": "CounterTop",
                    "kind": "receptacle",
                },
            },
        },
    )

    assert result["status"] == "applied"
    assert result["applied_count"] == 2
    assert result["labeled_prim_count"] == 3
    assert result["descendant_label_count"] == 1
    assert result["gprim_label_count"] == 2
    assert result["mesh_label_count"] == 1
    assert result["missing_prim_count"] == 1
    assert {
        "source_prim_path": "/World/Objects/bowl_01",
        "target_prim_path": "/World/Objects/bowl_01/mesh",
        "target_type": "Mesh",
        "target_kind": "gprim:Mesh",
    } in result["target_samples"]
    assert ("/World/Objects/bowl_01", "class", ("Bowl",)) in records
    assert ("/World/Objects/bowl_01/mesh", "class", ("Bowl",)) in records
    assert (
        "/World/Objects/bowl_01",
        "usd_prim_path",
        ("/World/Objects/bowl_01",),
    ) in records
    assert ("/World/Receptacles/sink_01", "kind", ("receptacle",)) in records
