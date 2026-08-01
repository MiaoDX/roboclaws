from __future__ import annotations

import math
import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SOURCE,
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
    IsaacLabSubprocessBackend,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE


def _write_b1_scene_gs_fixture(source_dir: Path) -> Path:
    source_dir.mkdir()
    scene_gs = source_dir / "scene_gs.usda"
    scene_gs.write_text(
        "#usda 1.0\n"
        'def Xform "combined" {\n'
        '    def "sim" (prepend references = @./scene.usd@) {}\n'
        '    def Xform "gs" (prepend references = @./xm_large_scene.usdz@) {}\n'
        "}\n",
        encoding="utf-8",
    )
    (source_dir / "scene.usd").write_text("#usda 1.0\n", encoding="utf-8")
    with zipfile.ZipFile(source_dir / "xm_large_scene.usdz", "w") as archive:
        archive.writestr("default.usda", "#usda 1.0\n")
        archive.writestr("gauss.usda", "#usda 1.0\n")
        archive.writestr("xm_large_scene.nurec", b"nurec")
    return scene_gs


def _fake_isaac_backend(tmp_path: Path) -> IsaacLabSubprocessBackend:
    return IsaacLabSubprocessBackend(
        run_dir=tmp_path,
        python_executable=Path(sys.executable),
        runtime_mode="fake",
        include_robot=True,
        generated_mess_count=1,
    )


def _assert_fake_isaac_runtime_metadata(backend: IsaacLabSubprocessBackend) -> None:
    assert backend.backend == ISAACLAB_SUBPROCESS_BACKEND
    assert backend.runtime["runtime_mode"] == "fake"
    assert backend.runtime["renderer_mode"] == "fake_isaac_protocol"
    assert backend.runtime["rendering"]["status"] == "fake_protocol"
    assert backend.runtime["rendering"]["real_rendering_proven"] is False
    native_render = backend.runtime["rendering"]["native_render_diagnostics"]
    assert native_render["schema"] == "isaac_native_render_diagnostics_v1"
    assert native_render["status"] == "fake_protocol"
    assert native_render["settings_api_available"] is False
    assert native_render["settings_mutation_attempted"] is False
    assert native_render["default_render_settings_changed"] is False
    assert native_render["post_render_comparison_profile"]["source"] == (
        "not_a_native_renderer_setting"
    )
    assert native_render["tone_mapping"]["operator"]["status"] == "not_available"
    assert native_render["camera_exposure"]["auto_exposure_enabled"]["status"] == ("not_available")
    assert native_render["ocio"]["config"]["status"] == "not_available"
    assert backend.runtime["visual_artifact_provenance"] == "fake_protocol_placeholder_image"
    assert backend.object_index
    assert backend.receptacle_index
    assert backend.scenario_source == "default_cleanup_scenario"


def _assert_fake_isaac_scene_bindings(backend: IsaacLabSubprocessBackend) -> None:
    assert backend.scene_binding_diagnostics["schema"] == "isaac_public_scene_bindings_v1"
    assert backend.scene_binding_diagnostics["status"] == "placeholder_mapping"
    assert backend.scene_binding_diagnostics["source"] == "scenario_fixture"
    assert backend.scene_binding_diagnostics["selected_object_count"] == 1
    assert backend.scene_binding_diagnostics["selected_object_bound_count"] == 1
    assert backend.scene_binding_diagnostics["selected_target_receptacle_count"] == 1
    assert backend.scene_binding_diagnostics["selected_target_receptacle_bound_count"] == 1
    assert backend.scene_binding_diagnostics["private_manifest_exposed_to_agent"] is False
    assert backend.segmentation["status"] == "blocked_capability"
    assert backend.segmentation["agent_facing"] is False
    assert backend.segmentation["no_simulator_label_fallback"] is True
    assert backend.scene_load["status"] == "fake_protocol"
    assert backend.scene_load["usd_stage_loaded"] is False
    assert any(item["area"] == "camera_capture" for item in backend.mapping_gaps)
    assert any(item["status"] == "placeholder_visuals" for item in backend.mapping_gaps)
    assert any(item["area"] == "public_scene_bindings" for item in backend.mapping_gaps)


def _assert_fake_isaac_scene_index_payload(backend: IsaacLabSubprocessBackend) -> None:
    scene_index_payload = backend.scene_index_artifact_payload()
    assert scene_index_payload["schema"] == ISAAC_SCENE_INDEX_ARTIFACT_SCHEMA
    assert scene_index_payload["backend"] == ISAACLAB_SUBPROCESS_BACKEND
    assert scene_index_payload["agent_facing"] is False
    assert scene_index_payload["private_manifest_exposed_to_agent"] is False
    assert "private_manifest" not in scene_index_payload
    assert scene_index_payload["scene_load"]["status"] == "fake_protocol"
    assert scene_index_payload["scenario_source"] == "default_cleanup_scenario"
    assert scene_index_payload["generated_mess_count"] == 1
    assert scene_index_payload["object_index_count"] == len(scene_index_payload["object_index"])
    assert scene_index_payload["receptacle_index_count"] == len(
        scene_index_payload["receptacle_index"]
    )


def _assert_fake_isaac_mess_diagnostics(backend: IsaacLabSubprocessBackend) -> None:
    assert len(backend.mess_placement_diagnostics) == 1
    mess_diagnostic = backend.mess_placement_diagnostics[0]
    assert mess_diagnostic["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert mess_diagnostic["diagnostic_source"] == "mess_seed"
    assert mess_diagnostic["placement_support_status"] in {
        "direct_support",
        "degraded_elevated",
        "semantic_contained_in_receptacle",
    }


def _assert_fake_isaac_snapshot(backend: IsaacLabSubprocessBackend, tmp_path: Path) -> None:
    snapshot_path = tmp_path / "snapshot.png"
    backend.write_snapshot(snapshot_path, title="Fake Isaac snapshot")
    assert snapshot_path.is_file()
    assert snapshot_path.stat().st_size > 0
    assert backend.snapshot_artifacts[-1]["placeholder_visuals"] is True
    assert (
        backend.snapshot_artifacts[-1]["native_render_diagnostics"]["schema"]
        == "isaac_native_render_diagnostics_v1"
    )
    assert (
        backend.snapshot_artifacts[-1]["snapshot_provenance"]["source"]
        == "placeholder_protocol_image"
    )


def _assert_fake_isaac_robot_views(
    backend: IsaacLabSubprocessBackend,
    tmp_path: Path,
) -> None:
    views = backend.write_robot_views(
        tmp_path / "robot_views",
        label="0001_pick",
        focus_object_id=backend.scenario.objects[0].object_id,
        focus_receptacle_id=backend.scenario.receptacles[0].receptacle_id,
    )
    assert views["ok"] is True
    assert views["view_variant"] == ISAACLAB_ROBOT_VIEW_VARIANT
    assert views["native_render_diagnostics"]["schema"] == "isaac_native_render_diagnostics_v1"
    assert views["native_render_diagnostics"]["default_render_settings_changed"] is False
    assert set(views["views"]) == {"fpv", "chase", "topdown", "verify"}
    for path in views["views"].values():
        assert Path(path).is_file()


def _exercise_fake_isaac_semantic_pose_actions(
    backend: IsaacLabSubprocessBackend,
) -> tuple[str, str, dict[str, object], dict[str, object]]:
    object_id = backend.scenario.objects[0].object_id
    receptacle_id = backend.scenario.private_manifest.targets[0].valid_receptacle_ids[0]
    nav = backend.navigate_to_object(object_id)
    pick = backend.pick(object_id)
    target = backend.navigate_to_receptacle(receptacle_id)
    place = backend.place(receptacle_id)
    done = backend.done("fake protocol test complete")

    for response in (nav, pick, target, place):
        assert response["ok"] is True
        assert response["primitive_provenance"] == ISAAC_SEMANTIC_POSE_PROVENANCE
        assert response["planner_backed"] is False
        assert response["physical_robot"] is False
        assert response["semantic_pose_event"]["rendered_to_usd"] is False
        assert response["semantic_pose_event"]["state_source"] == ISAAC_SEMANTIC_POSE_STATE_SOURCE
    return object_id, receptacle_id, place, done


def _assert_fake_isaac_action_results(
    place: dict[str, object],
    done: dict[str, object],
    object_id: str,
    receptacle_id: str,
) -> None:
    assert done["final_locations"][object_id] == receptacle_id
    assert place["placement_diagnostic"]["schema"] == "molmospaces_semantic_placement_diagnostic_v1"
    assert place["placement_diagnostic"]["diagnostic_source"] == "cleanup_place"
    assert (
        place["placement_support_status"]
        == place["placement_diagnostic"]["placement_support_status"]
    )


def _assert_fake_isaac_semantic_pose_state(
    backend: IsaacLabSubprocessBackend,
    object_id: str,
    receptacle_id: str,
) -> None:
    semantic_pose_state = backend.semantic_pose_state
    assert semantic_pose_state["schema"] == ISAAC_SEMANTIC_POSE_STATE_SCHEMA
    assert semantic_pose_state["primitive_provenance"] == ISAAC_SEMANTIC_POSE_PROVENANCE
    assert semantic_pose_state["rendered_to_usd"] is False
    assert semantic_pose_state["planner_backed"] is False
    assert semantic_pose_state["physical_robot"] is False
    assert semantic_pose_state["object_poses"][object_id]["location_id"] == receptacle_id
    assert semantic_pose_state["object_poses"][object_id]["rendered_to_usd"] is False
    assert semantic_pose_state["object_poses"][object_id]["position_source"] == (
        "isaac_support_placement_resolver"
    )
    assert [event["tool"] for event in semantic_pose_state["transform_events"]] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]


def _assert_fake_isaac_robot_import(backend: IsaacLabSubprocessBackend) -> None:
    if backend.robot_import["status"] == "imported":
        assert backend.robot["embodiment"] == "rby1m"
        assert backend.robot["robot_mounted_head_camera"] is True
    else:
        assert backend.robot["embodiment"] == "rby1m_head_camera_equivalent"
        assert backend.robot["robot_mounted_head_camera"] is False
    assert backend.robot["head_camera_prim_path"] == "/World/robot_0/head_camera"
    assert backend.robot_import["schema"] == "isaac_rby1m_robot_import_plan_v1"
    if backend.robot_import["source_urdf"]:
        assert backend.robot_import["source_urdf"].endswith("model_holobase_isaac.urdf")
    else:
        assert (
            "RBY1M Isaac URDF not found in MolmoSpaces asset cache."
            in backend.robot_import["blockers"]
        )
    assert backend.robot_import["head_link_name"] == "link_head_2"
    assert backend.robot_import["head_camera_prim_path"] == "/World/robot_0/head_camera"
    assert backend.robot_import["head_camera_equivalent"] is (
        backend.robot_import["status"] != "imported"
    )


class _FakeSceneCameraSim:
    device = "cpu"

    def __init__(self) -> None:
        self.steps = 0

    def reset(self) -> None:
        self.steps = 0

    def step(self) -> None:
        self.steps += 1

    def get_physics_dt(self) -> float:
        return 1 / 60


class _FakeSceneCameraSimUtils:
    @staticmethod
    def create_prim(*_args: object, **_kwargs: object) -> None:
        return None

    class PinholeCameraCfg:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs


class _FakeSceneCameraTensor:
    def __init__(self, array: object) -> None:
        self._array = array

    def detach(self) -> "_FakeSceneCameraTensor":
        return self

    cpu = detach

    def numpy(self) -> object:
        return self._array


def _fake_scene_camera_type(np: object) -> type:
    class _FakeCamera:
        def __init__(self, cfg: SimpleNamespace) -> None:
            self.cfg = cfg
            self.data = SimpleNamespace(output={})

        def set_world_poses_from_view(self, *_args: object, **_kwargs: object) -> None:
            return None

        def update(self, *, dt: float) -> None:
            del dt
            frame = np.full((1, 4, 6, 3), 250, dtype=np.uint8)
            frame[:, 0, 0, :] = 230
            self.data.output["rgb"] = _FakeSceneCameraTensor(frame)

    return _FakeCamera


class _FakeSceneCameraTorch:
    float32 = "float32"

    @staticmethod
    def tensor(value: object, **_kwargs: object) -> object:
        return value


def _unit_scene_camera_request() -> dict[str, object]:
    return {
        "camera_model": "canonical_eye_target_camera_v1",
        "views": [
            {
                "view_id": "fpv",
                "eye": [0.0, 0.0, 1.0],
                "target": [1.0, 0.0, 1.0],
            }
        ],
    }


class _FakeRobotPosePrim:
    def __init__(self, path: str) -> None:
        self.path = path

    def IsValid(self) -> bool:
        return True


class _FakeRobotPoseStage:
    def GetPrimAtPath(self, path: str) -> _FakeRobotPosePrim:
        assert path in {"/World/robot_0", "/World/robot_0/head_camera"}
        return _FakeRobotPosePrim(path)


class _RecordingHeadCameraOp:
    def __init__(self, name: str, camera_transforms: list[tuple[str, object]]) -> None:
        self.name = name
        self.camera_transforms = camera_transforms

    def Set(self, value: object) -> None:
        self.camera_transforms.append((self.name, value))


class _FakeRobotPoseGf:
    @staticmethod
    def Vec3d(*values: float) -> tuple[float, float, float]:
        return (float(values[0]), float(values[1]), float(values[2]))

    @staticmethod
    def Vec3f(*values: float) -> tuple[float, float, float]:
        return (float(values[0]), float(values[1]), float(values[2]))

    @staticmethod
    def Quatf(real: float, imaginary: object) -> tuple[float, object]:
        return (float(real), imaginary)


def _robot_pose_xform_common_api_type(
    translations: list[object],
    rotations: list[object],
) -> type:
    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakeRobotPosePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            translations.append(value)

        def SetRotate(self, value: object) -> None:
            rotations.append(value)

    return _FakeXformCommonAPI


def _head_camera_xformable_type(camera_transforms: list[tuple[str, object]]) -> type:
    class _FakeXformable:
        def __init__(self, prim: _FakeRobotPosePrim) -> None:
            self.prim = prim

        def ClearXformOpOrder(self) -> None:
            camera_transforms.append(("clear", self.prim.path))

        def AddTranslateOp(self) -> _RecordingHeadCameraOp:
            return _RecordingHeadCameraOp("translate", camera_transforms)

        def AddOrientOp(self) -> _RecordingHeadCameraOp:
            return _RecordingHeadCameraOp("orient", camera_transforms)

        def AddScaleOp(self) -> _RecordingHeadCameraOp:
            return _RecordingHeadCameraOp("scale", camera_transforms)

    return _FakeXformable


def _install_robot_pose_pxr(
    monkeypatch: pytest.MonkeyPatch,
    translations: list[object],
    rotations: list[object],
    camera_transforms: list[tuple[str, object]],
) -> None:
    fake_pxr = types.SimpleNamespace(
        Gf=_FakeRobotPoseGf,
        UsdGeom=types.SimpleNamespace(
            XformCommonAPI=_robot_pose_xform_common_api_type(translations, rotations),
            Xformable=_head_camera_xformable_type(camera_transforms),
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeRobotPoseGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)


def _shared_robot_pose_state() -> dict[str, object]:
    return {
        "robot_pose": {
            "x": 6.37057,
            "y": 8.8752,
            "z": 0.0,
            "theta": math.pi / 2.0,
            "head_pitch": 0.653613,
            "head_pitch_source": "target_framing_head_pitch",
            "pose_source": "roboclaws_shared_scene_frame_support_pose",
        }
    }


class _FakeSemanticPoseParent:
    def __bool__(self) -> bool:
        return True


class _FakeSemanticPosePrim:
    def __init__(self) -> None:
        self.parent = _FakeSemanticPoseParent()

    def IsValid(self) -> bool:
        return True

    def GetParent(self) -> _FakeSemanticPoseParent:
        return self.parent


class _FakeSinglePrimStage:
    def __init__(self, expected_path: str) -> None:
        self.expected_path = expected_path
        self.prim = _FakeSemanticPosePrim()

    def GetPrimAtPath(self, path: str) -> _FakeSemanticPosePrim:
        assert path == self.expected_path
        return self.prim


class _OffsetParentWorldTransform:
    def __init__(self, offset: tuple[float, float, float]) -> None:
        self.offset = offset

    def GetInverse(self) -> "_OffsetParentWorldTransform":
        return self

    def Transform(self, value: object) -> tuple[float, float, float]:
        x, y, z = value
        offset_x, offset_y, offset_z = self.offset
        return (float(x) - offset_x, float(y) - offset_y, float(z) - offset_z)


class _FakeSemanticPoseGf:
    @staticmethod
    def Vec3d(*values: float) -> tuple[float, float, float]:
        return (float(values[0]), float(values[1]), float(values[2]))


class _FakeSemanticPoseOrientOp:
    def GetOpName(self) -> str:
        return "xformOp:orient"


class _RecordingTranslateOp:
    def __init__(self, translations: list[object]) -> None:
        self.translations = translations

    def GetOpName(self) -> str:
        return "xformOp:translate"

    def Set(self, value: object) -> bool:
        self.translations.append(value)
        return True


def _offset_parent_xformable_type(offset: tuple[float, float, float]) -> type:
    class _FakeXformable:
        def __init__(self, parent: _FakeSemanticPoseParent) -> None:
            self.parent = parent

        def ComputeLocalToWorldTransform(self, time_code: float) -> _OffsetParentWorldTransform:
            assert time_code == 0.0
            return _OffsetParentWorldTransform(offset)

    return _FakeXformable


def _existing_translate_xformable_type(
    translations: list[object],
    offset: tuple[float, float, float],
) -> type:
    class _FakeXformable:
        def __init__(self, prim: object) -> None:
            self.prim = prim

        def ComputeLocalToWorldTransform(self, time_code: float) -> _OffsetParentWorldTransform:
            assert time_code == 0.0
            return _OffsetParentWorldTransform(offset)

        def GetOrderedXformOps(self) -> list[object]:
            assert isinstance(self.prim, _FakeSemanticPosePrim)
            return [_RecordingTranslateOp(translations), _FakeSemanticPoseOrientOp()]

    return _FakeXformable


def _recording_xform_common_api_type(
    translations: list[object],
    *,
    failure_message: str | None = None,
) -> type:
    class _FakeXformCommonAPI:
        def __init__(self, prim: _FakeSemanticPosePrim) -> None:
            self.prim = prim

        def SetTranslate(self, value: object) -> None:
            if failure_message is not None:
                raise AssertionError(failure_message)
            translations.append(value)

    return _FakeXformCommonAPI


def _install_semantic_pose_stage_pxr(
    monkeypatch: pytest.MonkeyPatch,
    *,
    xform_common_api: type,
    xformable: type,
) -> None:
    fake_pxr = types.SimpleNamespace(
        Gf=_FakeSemanticPoseGf,
        UsdGeom=types.SimpleNamespace(
            XformCommonAPI=xform_common_api,
            Xformable=xformable,
        ),
    )
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)
    monkeypatch.setitem(sys.modules, "pxr.Gf", _FakeSemanticPoseGf)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", fake_pxr.UsdGeom)


def _semantic_pose_stage_state(
    *,
    object_id: str,
    usd_prim_path: str,
    position: list[float],
    support_receptacle_id: str,
) -> dict[str, object]:
    return {
        "object_poses": {
            object_id: {
                "usd_prim_path": usd_prim_path,
                "support_receptacle_id": support_receptacle_id,
                "position": position,
            }
        },
        "receptacle_index": {},
    }


def _write_nonblank_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (64, 48), color=(18, 32, 48))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 56, 40), outline=(240, 180, 60), width=3)
    image.save(path)


def _write_robot_view_images(run_dir: Path) -> dict[str, str]:
    paths = {
        "fpv": run_dir / "isaac_runtime_smoke.png",
        "chase": run_dir / "isaac_runtime_smoke.chase.png",
        "topdown": run_dir / "isaac_runtime_smoke.topdown.png",
        "verify": run_dir / "isaac_runtime_smoke.verify.png",
    }
    for index, path in enumerate(paths.values(), start=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (64, 48), color=(18 + index, 32, 48))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 56, 40), outline=(240, 180 - index, 60), width=3)
        image.save(path)
    return {key: str(path) for key, path in paths.items()}


def _unit_isaac_object_index() -> dict[str, dict[str, object]]:
    return {
        "mug_01": {
            "usd_prim_path": "/World/Objects/mug_01",
            "category": "mug01",
            "public_label": "mug_01",
            "index_source": "usd_stage_traversal",
            "usd_world_bounds": {
                "center": [4.0, 5.0, 0.4],
                "min": [3.8, 4.8, 0.0],
                "max": [4.2, 5.2, 0.8],
                "size": [0.4, 0.4, 0.8],
            },
        }
    }


def _unit_isaac_receptacle_index() -> dict[str, dict[str, object]]:
    return {
        "sink_01": {
            "usd_prim_path": "/World/Receptacles/sink_01",
            "category": "sink01",
            "public_label": "sink_01",
            "index_source": "usd_stage_traversal",
            "usd_world_bounds": {
                "center": [2.5, 5.5, 0.75],
                "max": [3.0, 6.0, 1.2],
                "size": [1.0, 1.0, 0.9],
            },
            "support_pose": {
                "frame": "usd_world",
                "x": 2.5,
                "y": 5.5,
                "z": 1.2,
                "source": "usd_world_bounds_top_center",
                "support_radius_m": 0.5,
            },
        }
    }
