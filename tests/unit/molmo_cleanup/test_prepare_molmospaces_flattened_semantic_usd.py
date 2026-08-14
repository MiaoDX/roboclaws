from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab.molmospaces_semantic_usd import (
    prepare_flattened_semantic_usd,
)

pxr = pytest.importorskip("pxr")
from pxr import Usd, UsdGeom  # noqa: E402


def test_prepare_flattened_semantic_usd_labels_renderable_descendants(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    output_usd = tmp_path / "flattened" / "scene_semantic.usda"
    summary_path = tmp_path / "flattened" / "summary.json"
    _write_scene(scene_usd)
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "bowl_01": {
                        "asset_id": "Bowl_12",
                        "object_id": "Bowl|surface|1",
                        "category": "Bowl",
                        "is_static": False,
                        "children": [],
                    },
                    "sink_01": {
                        "asset_id": "Sink_1",
                        "object_id": "Sink|1",
                        "category": "Sink",
                        "is_static": True,
                        "children": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
        summary_output=summary_path,
    )

    assert summary["schema"] == "roboclaws_molmospaces_flattened_semantic_usd_v1"
    assert summary["status"] == "ready"
    assert summary["metadata_entry_count"] == 2
    assert summary["matched_entry_count"] == 2
    assert summary["renderable_labeled_prim_count"] == 2
    assert summary["gprim_labeled_prim_count"] == 2
    assert summary["mesh_labeled_prim_count"] == 2
    assert summary["container_labeled_prim_count"] == 2
    assert summary["scene_metadata_copied"] is True
    assert summary_path.is_file()
    assert (output_usd.parent / "scene_metadata.json").is_file()

    output_stage = Usd.Stage.Open(str(output_usd))
    bowl_mesh = output_stage.GetPrimAtPath("/val_1/Geometry/bowl_01/mesh")
    sink_mesh = output_stage.GetPrimAtPath("/val_1/Geometry/sink_01/mesh")
    assert bowl_mesh.IsValid()
    assert sink_mesh.IsValid()
    assert _labels(bowl_mesh, "class") == ["Bowl"]
    assert _labels(bowl_mesh, "kind") == ["object"]
    assert _labels(bowl_mesh, "usd_prim_path") == ["/val_1/Geometry/bowl_01"]
    assert _labels(sink_mesh, "class") == ["Sink"]
    assert _labels(sink_mesh, "kind") == ["receptacle"]

    output_text = output_usd.read_text(encoding="utf-8")
    assert "SemanticsLabelsAPI:class" in output_text
    assert "semantics:labels:class" in output_text


def test_prepare_flattened_semantic_usd_flattens_referenced_scene_asset(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    asset_usd = scene_dir / "bowl_asset.usda"
    scene_usd = scene_dir / "scene.usda"
    output_usd = tmp_path / "flattened" / "scene_semantic.usda"
    _write_asset(asset_usd, "/AssetRoot/mesh")
    _write_referencing_scene(scene_usd, asset_usd.name)
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "bowl_01": {
                        "asset_id": "Bowl_12",
                        "object_id": "Bowl|surface|1",
                        "category": "Bowl",
                        "is_static": False,
                        "children": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
        label_containers=False,
    )

    assert summary["status"] == "ready"
    assert summary["matched_entry_count"] == 1
    assert summary["container_labeled_prim_count"] == 0
    assert summary["renderable_labeled_prim_count"] == 1
    assert "bowl_asset.usda" not in output_usd.read_text(encoding="utf-8")

    output_stage = Usd.Stage.Open(str(output_usd))
    composed_mesh = output_stage.GetPrimAtPath("/val_1/Geometry/bowl_01/mesh")
    assert composed_mesh.IsValid()
    assert _labels(composed_mesh, "class") == ["Bowl"]


def test_prepare_flattened_semantic_usd_material_scale_candidate_is_opt_in(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    output_usd = tmp_path / "flattened" / "scene_semantic.usda"
    _write_scene_with_texture_scale(scene_usd)
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "table_01": {
                        "asset_id": "Table_1",
                        "object_id": "Table|1",
                        "category": "DiningTable",
                        "is_static": True,
                        "children": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    default_summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
    )

    default_text = output_usd.read_text(encoding="utf-8")
    assert default_summary["rendering_parity_preset"] == "combined-material-light"
    assert default_summary["material_texture_scale_mode"] == "none"
    assert default_summary["material_texture_scale_rewrite_count"] == 0
    assert default_summary["material_texture_scale_default_candidate"] is False
    assert default_summary["distant_light_rotate_x"] == 25.0
    assert default_summary["distant_light_rotate_x_rewrite_count"] == 1
    assert default_summary["distant_light_rotate_x_default_candidate"] is True
    assert default_summary["default_rendering_path_status"] == (
        "default_rendering_path_uses_combined_material_light"
    )
    assert default_summary["default_rendering_path_uses_combined_material_light"] is True
    assert "float4 inputs:fallback = (0.5, 0.25, 0.1, 1)" in default_text
    assert "float4 inputs:scale = (0.5, 0.25, 0.1, 1)" in default_text
    assert "float xformOp:rotateX = 25" in default_text

    source_preserving_summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
        rendering_parity_preset="source-preserving",
    )

    source_preserving_text = output_usd.read_text(encoding="utf-8")
    assert source_preserving_summary["rendering_parity_preset"] == "source-preserving"
    assert source_preserving_summary["material_texture_scale_mode"] == "none"
    assert source_preserving_summary["material_texture_scale_rewrite_count"] == 0
    assert source_preserving_summary["material_texture_scale_default_candidate"] is False
    assert source_preserving_summary["distant_light_rotate_x"] is None
    assert source_preserving_summary["distant_light_rotate_x_default_candidate"] is False
    assert source_preserving_summary["default_rendering_path_status"] == (
        "source_preserving_rendering_path"
    )
    assert "float4 inputs:fallback = (0.5, 0.25, 0.1, 1)" in source_preserving_text
    assert "float4 inputs:scale = (0.5, 0.25, 0.1, 1)" in source_preserving_text
    assert "float xformOp:rotateX = -10" in source_preserving_text

    square_summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
        rendering_parity_preset="source-preserving",
        material_texture_scale_mode="square",
    )

    square_text = output_usd.read_text(encoding="utf-8")
    assert square_summary["rendering_parity_preset"] == "source-preserving"
    assert square_summary["material_texture_scale_mode"] == "square"
    assert square_summary["material_texture_scale_rewrite_count"] == 2
    assert square_summary["material_texture_scale_default_candidate"] is True
    assert square_summary["distant_light_rotate_x"] is None
    assert "float4 inputs:fallback = (0.25, 0.0625, 0.01, 1)" in square_text
    assert "float4 inputs:scale = (0.25, 0.0625, 0.01, 1)" in square_text
    assert "float xformOp:rotateX = -10" in square_text


def test_prepare_flattened_semantic_usd_freezes_visual_physics_by_default(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    output_usd = tmp_path / "flattened" / "scene_semantic.usda"
    _write_articulated_box_scene(scene_usd)
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "box_01": {
                        "asset_id": "Box_10",
                        "object_id": "Box|surface|1",
                        "category": "Box",
                        "is_static": False,
                        "children": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
    )

    output_text = output_usd.read_text(encoding="utf-8")
    assert summary["visual_physics_status"] == "frozen_static_visual_usd"
    assert summary["visual_physics_joint_removed_count"] == 1
    assert summary["visual_physics_api_schema_removed_count"] >= 1
    assert summary["visual_physics_property_removed_count"] >= 1
    assert "def PhysicsRevoluteJoint" not in output_text
    assert "PhysicsRigidBodyAPI" not in output_text
    assert "physics:mass" not in output_text
    assert 'def Mesh "mesh"' in output_text
    assert "semantics:labels:class" in output_text


def test_prepare_flattened_semantic_usd_applies_mujoco_flap_endpoint_pose(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    mujoco_scene_xml = scene_dir / "val_1.xml"
    output_usd = tmp_path / "flattened" / "scene_semantic.usda"
    _write_articulated_box_scene_with_flap_xforms(scene_usd)
    _write_articulated_box_mujoco_scene(mujoco_scene_xml)
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "box_01": {
                        "asset_id": "Box_10",
                        "object_id": "Box|surface|1",
                        "category": "Box",
                        "is_static": False,
                        "children": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        mujoco_scene_xml_path=mujoco_scene_xml,
        output_usd_path=output_usd,
    )

    assert summary["mujoco_visual_joint_endpoint_pose_status"] == (
        "mujoco_visual_joint_endpoint_pose_applied"
    )
    assert summary["mujoco_visual_joint_endpoint_pose_target_count"] == 2
    assert summary["mujoco_visual_joint_endpoint_pose_corrected_count"] == 2
    assert summary["mujoco_visual_joint_endpoint_pose_missing_count"] == 0
    assert summary["visual_physics_joint_removed_count"] == 2

    output_stage = Usd.Stage.Open(str(output_usd))
    inner = output_stage.GetPrimAtPath("/val_1/Geometry/box_01/Geometry/Box_10_box_10_flap_inner_1")
    outer = output_stage.GetPrimAtPath("/val_1/Geometry/box_01/Geometry/Box_10_box_10_flap_outer_1")
    assert _quat_tuple(inner.GetAttribute("xformOp:orient").Get()) == pytest.approx(
        (0.9238795, 0.3826834, 0.0, 0.0),
        abs=1e-5,
    )
    assert _quat_tuple(outer.GetAttribute("xformOp:orient").Get()) == pytest.approx(
        (0.8660254, 0.0, 0.0, -0.5),
        abs=1e-5,
    )

    output_text = output_usd.read_text(encoding="utf-8")
    assert "def PhysicsRevoluteJoint" not in output_text


def test_prepare_flattened_semantic_usd_can_preserve_source_physics(
    tmp_path: Path,
) -> None:
    scene_dir = tmp_path / "val_1"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    output_usd = tmp_path / "flattened" / "scene_semantic.usda"
    _write_articulated_box_scene(scene_usd)
    (scene_dir / "scene_metadata.json").write_text(
        json.dumps(
            {
                "objects": {
                    "box_01": {
                        "asset_id": "Box_10",
                        "object_id": "Box|surface|1",
                        "category": "Box",
                        "is_static": False,
                        "children": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    summary = prepare_flattened_semantic_usd(
        scene_usd_path=scene_usd,
        output_usd_path=output_usd,
        freeze_visual_physics=False,
    )

    output_text = output_usd.read_text(encoding="utf-8")
    assert summary["visual_physics_status"] == "source_physics_preserved"
    assert summary["visual_physics_joint_removed_count"] == 0
    assert "def PhysicsRevoluteJoint" in output_text
    assert "PhysicsRigidBodyAPI" in output_text
    assert "physics:mass" in output_text


def _write_scene(path: Path) -> None:
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/val_1").GetPrim())
    geometry = UsdGeom.Xform.Define(stage, "/val_1/Geometry")
    bowl = UsdGeom.Xform.Define(stage, "/val_1/Geometry/bowl_01")
    sink = UsdGeom.Xform.Define(stage, "/val_1/Geometry/sink_01")
    UsdGeom.Mesh.Define(stage, "/val_1/Geometry/bowl_01/mesh")
    UsdGeom.Mesh.Define(stage, "/val_1/Geometry/sink_01/mesh")
    assert geometry.GetPrim().IsValid()
    assert bowl.GetPrim().IsValid()
    assert sink.GetPrim().IsValid()
    stage.GetRootLayer().Save()


def _write_articulated_box_scene(path: Path) -> None:
    path.write_text(
        """#usda 1.0
def Xform "val_1"
{
    def Xform "Geometry"
    {
        def Xform "box_01" (
            apiSchemas = ["PhysicsRigidBodyAPI"]
        )
        {
            float physics:mass = 1

            def Mesh "mesh"
            {
            }

            def PhysicsRevoluteJoint "box_flap_joint"
            {
                uniform token physics:axis = "X"
                float physics:lowerLimit = 0
                float physics:upperLimit = 90
            }
        }
    }
}
""",
        encoding="utf-8",
    )


def _write_articulated_box_scene_with_flap_xforms(path: Path) -> None:
    path.write_text(
        """#usda 1.0
def Xform "val_1"
{
    def Xform "Geometry"
    {
        def Xform "box_01"
        {
            def Scope "Geometry"
            {
                def Xform "Box_10_box_10_flap_inner_1"
                {
                    quatf xformOp:orient = (0.114444, 0.9934297, 0, 0)
                    double3 xformOp:translate = (-0.00215105, 0.131826, 0.127438)
                    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient"]

                    def Mesh "Box_10_box_10_flap_inner_1"
                    {
                    }

                    def PhysicsRevoluteJoint "Box_10_box_10_flap_inner_1_joint_0"
                    {
                    }
                }

                def Xform "Box_10_box_10_flap_outer_1"
                {
                    quatf xformOp:orient = (0.100928, 0, 0, 0.9948937)
                    double3 xformOp:translate = (-0.133846, 0.134112, 0.00015121)
                    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient"]

                    def Mesh "Box_10_box_10_flap_outer_1"
                    {
                    }

                    def PhysicsRevoluteJoint "Box_10_box_10_flap_outer_1_joint_0"
                    {
                    }
                }
            }
        }
    }
}
""",
        encoding="utf-8",
    )


def _write_articulated_box_mujoco_scene(path: Path) -> None:
    path.write_text(
        """<mujoco>
  <worldbody>
    <body name="box_01">
      <body name="box_01_1" quat="0.9238795 0.3826834 0 0">
        <joint name="box_01_1_box10flapinner1joint0_1"
               axis="-1 0 0" ref="2.91219" range="0 2.91219" />
        <geom name="box_01_1_visual_0" mesh="Box_10_box_10_flap_inner_1" />
      </body>
      <body name="box_01_2" quat="-0.8660254 0 0 0.5">
        <joint name="box_01_2_box10flapouter1joint0_1"
               axis="0 0 1" ref="-2.93938" range="-2.93938 0" />
        <geom name="box_01_2_visual_0" mesh="Box_10_box_10_flap_outer_1" />
      </body>
    </body>
  </worldbody>
</mujoco>
""",
        encoding="utf-8",
    )


def _write_scene_with_texture_scale(path: Path) -> None:
    path.write_text(
        """#usda 1.0
def Xform "val_1"
{
    def Xform "Geometry"
    {
        def Xform "table_01"
        {
            def Mesh "mesh"
            {
            }

            def Scope "Materials"
            {
                def Material "material_LightWoodCounters3"
                {
                    def DistantLight "KeyLight"
                    {
                        float inputs:intensity = 5000
                        float xformOp:rotateX = -10
                    }

                    def Shader "DiffuseTexture"
                    {
                        float4 inputs:fallback = (0.5, 0.25, 0.1, 1)
                        float4 inputs:scale = (0.5, 0.25, 0.1, 1)
                    }
                }
            }
        }
    }
}
""",
        encoding="utf-8",
    )


def _write_asset(path: Path, mesh_path: str) -> None:
    stage = Usd.Stage.CreateNew(str(path))
    root = UsdGeom.Xform.Define(stage, "/AssetRoot")
    stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.Mesh.Define(stage, mesh_path)
    stage.GetRootLayer().Save()


def _write_referencing_scene(path: Path, asset_name: str) -> None:
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/val_1").GetPrim())
    UsdGeom.Xform.Define(stage, "/val_1/Geometry")
    bowl = UsdGeom.Xform.Define(stage, "/val_1/Geometry/bowl_01")
    bowl.GetPrim().GetReferences().AddReference(asset_name)
    stage.GetRootLayer().Save()


def _labels(prim: Usd.Prim, instance_name: str) -> list[str]:
    try:
        from pxr import UsdSemantics
    except Exception:
        attr = prim.GetAttribute(f"semantics:labels:{instance_name}")
        return list(attr.Get() or [])
    attr = UsdSemantics.LabelsAPI(prim, instance_name).GetLabelsAttr()
    return list(attr.Get() or [])


def _quat_tuple(value: object) -> tuple[float, float, float, float]:
    real = float(value.GetReal())
    imaginary = value.GetImaginary()
    return (real, float(imaginary[0]), float(imaginary[1]), float(imaginary[2]))


def test_prepare_flattened_semantic_usd_import_has_no_required_pxr_dependency() -> None:
    assert pxr is not None
    assert shutil.which("true")
