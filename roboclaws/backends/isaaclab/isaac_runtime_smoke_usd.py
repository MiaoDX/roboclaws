"""Isaac Lab backend runtime support."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roboclaws.household.types import CleanupScenario

GENERATED_SCENE_KINDS = ("roboclaws_smoke", "isaac_official_blocks")
ISAAC_OFFICIAL_ASSET_ROOT = (
    "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac"
)
ISAAC_OFFICIAL_BLOCK_ASSETS = (
    "Props/Blocks/blue_block.usd",
    "Props/Blocks/red_block.usd",
    "Props/Blocks/green_block.usd",
)


def generated_scene_filename(scene_kind: str) -> str:
    if scene_kind == "isaac_official_blocks":
        return "roboclaws_isaac_official_blocks_scene.usda"
    return "roboclaws_phase_a_smoke_scene.usda"


def write_generated_runtime_smoke_usd(
    usd_path: Path,
    scenario: CleanupScenario,
    *,
    scene_kind: str = "roboclaws_smoke",
) -> int:
    if scene_kind == "isaac_official_blocks":
        return write_isaac_official_blocks_runtime_smoke_usd(usd_path, scenario)
    return write_roboclaws_runtime_smoke_usd(usd_path, scenario)


def write_roboclaws_runtime_smoke_usd(
    usd_path: Path,
    scenario: CleanupScenario,
) -> int:
    from pxr import Gf, Usd, UsdGeom, UsdLux

    usd_path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(usd_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    floor = UsdGeom.Cube.Define(stage, "/World/Floor")
    floor.CreateSizeAttr(1.0)
    floor.CreateDisplayColorAttr([Gf.Vec3f(0.28, 0.31, 0.33)])
    UsdGeom.XformCommonAPI(floor).SetTranslate(Gf.Vec3d(0.0, 0.0, -0.025))
    UsdGeom.XformCommonAPI(floor).SetScale(Gf.Vec3f(3.0, 3.0, 0.05))

    selected_object_ids = _selected_cleanup_object_ids(scenario) or [
        scenario.objects[0].object_id if scenario.objects else "object"
    ]
    fixture_positions = _write_runtime_smoke_receptacles(
        stage,
        scenario,
        selected_object_ids=selected_object_ids,
        color=Gf.Vec3f(0.1, 0.46, 0.75),
        z=0.35,
        scale=Gf.Vec3f(0.9, 0.55, 0.25),
    )
    objects_by_id = {item.object_id: item for item in scenario.objects}
    for index, object_id in enumerate(selected_object_ids):
        cleanup_object = UsdGeom.Sphere.Define(
            stage,
            f"/World/Objects/{_usd_safe_name(object_id)}",
        )
        cleanup_object.CreateRadiusAttr(0.16)
        cleanup_object.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.42, 0.12)])
        source_id = objects_by_id.get(object_id).location_id if object_id in objects_by_id else ""
        x, y, z = fixture_positions.get(source_id, (0.0, 0.0, 0.35))
        UsdGeom.XformCommonAPI(cleanup_object).SetTranslate(
            Gf.Vec3d(x + 0.18 + 0.08 * index, y - 0.16, z + 0.38)
        )

    _add_runtime_smoke_light_and_camera(stage, gf=Gf, usd_geom=UsdGeom, usd_lux=UsdLux)
    stage.GetRootLayer().Save()
    return sum(1 for _ in stage.Traverse())


def write_isaac_official_blocks_runtime_smoke_usd(
    usd_path: Path,
    scenario: CleanupScenario,
) -> int:
    from pxr import Gf, Usd, UsdGeom, UsdLux

    usd_path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(usd_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    floor = UsdGeom.Cube.Define(stage, "/World/Floor")
    floor.CreateSizeAttr(1.0)
    floor.CreateDisplayColorAttr([Gf.Vec3f(0.24, 0.26, 0.28)])
    UsdGeom.XformCommonAPI(floor).SetTranslate(Gf.Vec3d(0.0, 0.0, -0.025))
    UsdGeom.XformCommonAPI(floor).SetScale(Gf.Vec3f(3.2, 3.2, 0.05))

    selected_object_ids = _selected_cleanup_object_ids(scenario) or [
        scenario.objects[0].object_id if scenario.objects else "official_block"
    ]
    fixture_positions = _write_runtime_smoke_receptacles(
        stage,
        scenario,
        selected_object_ids=selected_object_ids,
        color=Gf.Vec3f(0.1, 0.44, 0.72),
        z=0.28,
        scale=Gf.Vec3f(0.9, 0.55, 0.18),
    )
    objects_by_id = {item.object_id: item for item in scenario.objects}
    for index, object_id in enumerate(selected_object_ids):
        object_prim_path = f"/World/Objects/{_usd_safe_name(object_id)}"
        cleanup_object = UsdGeom.Xform.Define(stage, object_prim_path)
        cleanup_asset = UsdGeom.Xform.Define(stage, f"{object_prim_path}/Asset")
        asset = ISAAC_OFFICIAL_BLOCK_ASSETS[index % len(ISAAC_OFFICIAL_BLOCK_ASSETS)]
        cleanup_asset.GetPrim().GetReferences().AddReference(f"{ISAAC_OFFICIAL_ASSET_ROOT}/{asset}")
        source_id = objects_by_id.get(object_id).location_id if object_id in objects_by_id else ""
        x, y, z = fixture_positions.get(source_id, (0.0, 0.0, 0.28))
        UsdGeom.XformCommonAPI(cleanup_object).SetTranslate(
            Gf.Vec3d(x + 0.22 + 0.12 * index, y - 0.18, z + 0.26)
        )
        UsdGeom.XformCommonAPI(cleanup_object).SetScale(Gf.Vec3f(1.6, 1.6, 1.6))

    _add_runtime_smoke_light_and_camera(stage, gf=Gf, usd_geom=UsdGeom, usd_lux=UsdLux)
    stage.GetRootLayer().Save()
    return sum(1 for _ in stage.Traverse())


def _write_runtime_smoke_receptacles(
    stage: Any,
    scenario: CleanupScenario,
    *,
    selected_object_ids: list[str],
    color: Any,
    z: float,
    scale: Any,
) -> dict[str, tuple[float, float, float]]:
    from pxr import Gf, UsdGeom

    selected_object_id_set = set(selected_object_ids)
    selected_receptacle_ids = _selected_cleanup_receptacle_ids(scenario)
    source_receptacle_ids = [
        obj.location_id for obj in scenario.objects if obj.object_id in selected_object_id_set
    ]
    receptacle_ids = _dedupe(
        [
            *source_receptacle_ids,
            *selected_receptacle_ids,
            *(item.receptacle_id for item in scenario.receptacles[:1]),
        ]
    )
    if not receptacle_ids:
        receptacle_ids = ["fixture"]

    fixture_positions: dict[str, tuple[float, float, float]] = {}
    for index, receptacle_id in enumerate(receptacle_ids):
        x = (index % 3 - 1) * 0.95
        y = (index // 3) * 0.85
        fixture_positions[receptacle_id] = (x, y, z)
        fixture = UsdGeom.Cube.Define(
            stage,
            f"/World/Receptacles/{_usd_safe_name(receptacle_id)}",
        )
        fixture.CreateSizeAttr(1.0)
        fixture.CreateDisplayColorAttr([color])
        UsdGeom.XformCommonAPI(fixture).SetTranslate(Gf.Vec3d(x, y, z))
        UsdGeom.XformCommonAPI(fixture).SetScale(scale)
    return fixture_positions


def _add_runtime_smoke_light_and_camera(
    stage: Any,
    *,
    gf: Any,
    usd_geom: Any,
    usd_lux: Any,
) -> None:
    key_light = usd_lux.DistantLight.Define(stage, "/World/KeyLight")
    key_light.CreateIntensityAttr(5000.0)
    usd_geom.XformCommonAPI(key_light).SetRotate(gf.Vec3f(-45.0, 0.0, 35.0))

    camera = usd_geom.Camera.Define(stage, "/World/ReferenceCamera")
    camera.CreateFocalLengthAttr(24.0)
    camera.CreateHorizontalApertureAttr(20.955)
    usd_geom.XformCommonAPI(camera).SetTranslate(gf.Vec3d(2.4, -2.6, 1.8))


def _selected_cleanup_object_ids(scenario: CleanupScenario) -> list[str]:
    return _dedupe(target.object_id for target in scenario.private_manifest.targets)


def _selected_cleanup_receptacle_ids(scenario: CleanupScenario) -> list[str]:
    return _dedupe(
        receptacle_id
        for target in scenario.private_manifest.targets
        for receptacle_id in target.valid_receptacle_ids
    )


def _dedupe(values: Any) -> list[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value or "")
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _usd_safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    return safe or "item"
