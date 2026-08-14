from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import runtime as runtime_cli
from roboclaws.backends.isaaclab import runtime_camera as runtime_camera
from roboclaws.backends.isaaclab import runtime_capture as runtime_capture
from roboclaws.backends.isaaclab import runtime_commands as runtime_commands
from roboclaws.backends.isaaclab import runtime_dependencies as runtime_dependencies
from roboclaws.backends.isaaclab import runtime_evidence as runtime_evidence
from roboclaws.backends.isaaclab import runtime_initialization as runtime_initialization
from roboclaws.backends.isaaclab import runtime_state as runtime_state


def test_isaac_usd_scene_index_extracts_room_outlines(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePrim:
        def __init__(self, path: str, name: str) -> None:
            self._path = path
            self._name = name

        def GetPath(self) -> str:
            return self._path

        def GetName(self) -> str:
            return self._name

    fake_prim = _FakePrim("/val_1/Geometry/room_2_visual_0", "room_2_visual_0")

    class _FakeStage:
        def Traverse(self) -> list[_FakePrim]:
            return [fake_prim]

    class _FakeUsdStage:
        @staticmethod
        def Open(_path: str) -> _FakeStage:
            return _FakeStage()

    class _FakeUsdGeom:
        pass

    monkeypatch.setitem(
        sys.modules,
        "pxr",
        types.SimpleNamespace(Usd=types.SimpleNamespace(Stage=_FakeUsdStage), UsdGeom=_FakeUsdGeom),
    )
    monkeypatch.setattr(
        runtime_capture,
        "_usd_world_bounds",
        lambda _prim, *, usd_geom: {
            "center": [2.99, 4.983, 1.2],
            "size": [5.98, 9.966, 0.2],
        },
    )
    monkeypatch.setattr(
        runtime_capture,
        "_annotate_usd_index_geometry",
        lambda **_kwargs: None,
    )

    diagnostics = runtime_capture._inspect_usd_scene_index(Path("scene.usda"))

    assert diagnostics["room_outline_count"] == 1
    assert diagnostics["room_outlines"][0]["room_id"] == "room_2"
    assert diagnostics["room_outlines"][0]["center"] == pytest.approx([2.99, 4.983])
    assert diagnostics["room_outlines"][0]["half_extents"] == pytest.approx([2.99, 4.983])
    assert diagnostics["room_outlines"][0]["provenance"] == "isaac_usd_room_mesh_world_bounds"


@pytest.mark.parametrize("source_text", ["{bad json\n", "[]\n"])
def test_isaac_molmospaces_scene_metadata_ignores_bad_optional_source(
    tmp_path: Path,
    source_text: str,
) -> None:
    scene_dir = tmp_path / "val_0"
    scene_dir.mkdir()
    scene_usd = scene_dir / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")
    (scene_dir / "scene_metadata.json").write_text(source_text, encoding="utf-8")

    assert runtime_dependencies._load_molmospaces_scene_metadata(scene_usd) == {}


def test_isaac_molmospaces_scene_metadata_allows_missing_optional_source(
    tmp_path: Path,
) -> None:
    scene_usd = tmp_path / "scene.usda"
    scene_usd.write_text("#usda 1.0\n", encoding="utf-8")

    assert runtime_dependencies._load_molmospaces_scene_metadata(scene_usd) == {}


def test_isaac_scene_binding_can_match_synthetic_handle_to_real_usd_metadata() -> None:
    object_index = {
        "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6": {
            "usd_prim_path": "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
            "category": "Mug",
            "public_label": "Mug Mug|surface|6|56 RoboTHOR_mug_ai2_2_v",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
        },
        "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7": {
            "usd_prim_path": "/val_0/Geometry/mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7",
            "category": "Mug",
            "public_label": "Mug Mug|surface|7|71 Mug_1",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "mug_8caf1bb3f88e9a00e02dfe9e6518aeb0_1_0_7",
        },
    }

    binding = runtime_dependencies._bind_public_scene_item(
        public_id="mug_01",
        public_label="ceramic mug",
        category="dish",
        index=object_index,
        kind="object",
    )

    assert binding["status"] == "bound"
    assert binding["usd_handle"] == "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    assert binding["usd_prim_path"] == (
        "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    )
    assert binding["match_strategy"] == "public_id_prefix_first"
    assert binding["index_source"] == "usd_stage_traversal"

    state = {
        "scene_binding_diagnostics": {"selected_object_bindings": {"mug_01": binding}},
        "object_index": object_index,
    }
    assert runtime_state._object_usd_prim_path(state, "mug_01") == (
        "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    )


def test_isaac_scene_binding_does_not_bind_generic_dish_to_unrelated_category() -> None:
    object_index = {
        "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3": {
            "usd_prim_path": "/val_1/Geometry/sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
            "category": "DishSponge",
            "public_label": "DishSponge DishSponge|surface|3|17 Dish_Sponge_1",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
        }
    }

    binding = runtime_dependencies._bind_public_scene_item(
        public_id="mug_01",
        public_label="ceramic mug",
        category="dish",
        index=object_index,
        kind="object",
    )

    assert binding["status"] == "unresolved"
    assert binding["match_strategy"] == "none"
    assert binding["usd_prim_path"] == ""


def test_isaac_scene_binding_still_allows_specific_unique_category() -> None:
    object_index = {
        "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6": {
            "usd_prim_path": "/val_0/Geometry/mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
            "category": "Mug",
            "public_label": "Mug Mug|surface|6|56 RoboTHOR_mug_ai2_2_v",
            "index_source": "usd_stage_traversal",
            "metadata_handle": "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6",
        }
    }

    binding = runtime_dependencies._bind_public_scene_item(
        public_id="cleanup_object_01",
        public_label="unlabeled cleanup object",
        category="Mug",
        index=object_index,
        kind="object",
    )

    assert binding["status"] == "bound"
    assert binding["usd_handle"] == "mug_3ebc45568ed53a18c8797978b3744a99_1_0_6"
    assert binding["match_strategy"] in {"semantic_category_token_unique", "unique_category"}


def test_isaac_scene_index_can_generate_scene_specific_cleanup_scenario() -> None:
    object_index = {
        "baseballbat_37665ef33aee57e330674e8ff865507e_1_0_2": {
            "asset_id": "BaseballBat_2",
            "category": "BaseballBat",
            "index_source": "usd_stage_traversal",
            "is_static": False,
            "kind": "object",
            "metadata_handle": "baseballbat_37665ef33aee57e330674e8ff865507e_1_0_2",
            "metadata_object_id": "BaseballBat|surface|2|10",
            "parent": "bed_258d27d5fe50e324961c7a8698ace951_1_0_2",
            "public_label": "BaseballBat BaseballBat|surface|2|10 BaseballBat_2",
            "usd_prim_path": "/val_1/Geometry/baseballbat_37665ef33aee57e330674e8ff865507e_1_0_2",
        },
        "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2": {
            "asset_id": "Bowl_12",
            "category": "Bowl",
            "index_source": "usd_stage_traversal",
            "is_static": False,
            "kind": "object",
            "metadata_handle": "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
            "metadata_object_id": "Bowl|surface|2|4",
            "parent": "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            "public_label": "Bowl Bowl|surface|2|4 Bowl_12",
            "usd_prim_path": "/val_1/Geometry/bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2",
        },
        "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3": {
            "asset_id": "Dish_Sponge_1",
            "category": "DishSponge",
            "index_source": "usd_stage_traversal",
            "is_static": False,
            "kind": "object",
            "metadata_handle": "sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
            "metadata_object_id": "DishSponge|surface|3|17",
            "parent": "crapper_cd6fa77f725b7ec4a4ced5913731ae93_1_0_3",
            "public_label": "DishSponge DishSponge|surface|3|17 Dish_Sponge_1",
            "usd_prim_path": "/val_1/Geometry/sponge_41cc9aa65073b4cd1fc4d9871335148d_1_0_3",
        },
    }
    receptacle_index = {
        "ashcan_a20a3404d9e4ddd7e8d84c88e9975333_1_0_3": {
            "asset_id": "bin_16",
            "category": "GarbageCan",
            "index_source": "usd_stage_traversal",
            "kind": "receptacle",
            "metadata_handle": "ashcan_a20a3404d9e4ddd7e8d84c88e9975333_1_0_3",
            "public_label": "GarbageCan GarbageCan|3|2 bin_16",
            "usd_prim_path": "/val_1/Geometry/ashcan_a20a3404d9e4ddd7e8d84c88e9975333_1_0_3",
        },
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2": {
            "asset_id": "Dining_Table_203_1",
            "category": "DiningTable",
            "index_source": "usd_stage_traversal",
            "kind": "receptacle",
            "metadata_handle": "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
            "public_label": "DiningTable DiningTable|2|1|0 Dining_Table_203_1",
            "usd_prim_path": "/val_1/Geometry/diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
        },
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3": {
            "asset_id": "Sink_1",
            "category": "Sink",
            "index_source": "usd_stage_traversal",
            "kind": "receptacle",
            "metadata_handle": "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
            "public_label": "Sink Sink|3|1|0 Sink_1",
            "usd_prim_path": "/val_1/Geometry/sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
        },
    }

    scenario = runtime_commands._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=1,
        seed=7,
        generated_mess_count=1,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert scenario.scenario_id == "isaac-scene-index-procthor-10k-val-1-7-1"
    assert [item.receptacle_id for item in scenario.receptacles] == [
        "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2",
        "sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",
    ]
    assert scenario.objects[0].object_id == "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2"
    assert scenario.objects[0].location_id == "diningtable_f113cf7f8367e89f709b53cbee1a1c05_1_0_2"
    target = scenario.private_manifest.targets[0]
    assert target.object_id == "bowl_847a24bfa9d8b1a1f26661ebbb850f56_1_0_2"
    assert target.valid_receptacle_ids == ("sink_07e796f32d0d3efce9acf4be00f3bc53_1_0_3",)
    bindings = runtime_dependencies._scene_binding_diagnostics(
        runtime_mode="real",
        scenario=scenario,
        object_index=object_index,
        receptacle_index=receptacle_index,
        real_smoke={},
    )
    assert bindings["status"] == "selected_bound"
    assert bindings["selected_object_bound_count"] == 1
    assert bindings["selected_target_receptacle_bound_count"] == 1


def test_isaac_scene_index_uses_shared_generated_mess_selection() -> None:
    object_index = {
        "alarmclock_a": {
            "asset_id": "Alarm_Clock_1",
            "category": "AlarmClock",
            "kind": "object",
            "parent": "bed_01",
            "public_label": "AlarmClock AlarmClock|surface|1|1 Alarm_Clock_1",
        },
        "alarmclock_b": {
            "asset_id": "Alarm_Clock_2",
            "category": "AlarmClock",
            "kind": "object",
            "parent": "bed_02",
            "public_label": "AlarmClock AlarmClock|surface|1|2 Alarm_Clock_2",
        },
        "apple_a": {
            "asset_id": "Apple_1",
            "category": "Apple",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Apple Apple|surface|1|3 Apple_1",
        },
        "book_a": {
            "asset_id": "Book_1",
            "category": "Book",
            "kind": "object",
            "parent": "desk_01",
            "public_label": "Book Book|surface|1|4 Book_1",
        },
        "plate_a": {
            "asset_id": "Plate_1",
            "category": "Plate",
            "kind": "object",
            "parent": "table_01",
            "public_label": "Plate Plate|surface|1|5 Plate_1",
        },
        "pillow_a": {
            "asset_id": "Pillow_1",
            "category": "Pillow",
            "kind": "object",
            "parent": "sofa_01",
            "public_label": "Pillow Pillow|surface|1|6 Pillow_1",
        },
        "remote_a": {
            "asset_id": "Remote_1",
            "category": "RemoteControl",
            "kind": "object",
            "parent": "desk_02",
            "public_label": "RemoteControl RemoteControl|surface|1|7 Remote_1",
        },
    }
    receptacle_index = {
        "bed_01": {"category": "Bed", "kind": "receptacle", "public_label": "Bed Bed|1|1"},
        "bed_02": {"category": "Bed", "kind": "receptacle", "public_label": "Bed Bed|1|2"},
        "counter_01": {
            "category": "CounterTop",
            "kind": "receptacle",
            "public_label": "CounterTop CounterTop|1|1",
        },
        "desk_01": {"category": "Desk", "kind": "receptacle", "public_label": "Desk Desk|1|1"},
        "desk_02": {"category": "Desk", "kind": "receptacle", "public_label": "Desk Desk|1|2"},
        "fridge_01": {
            "category": "Fridge",
            "kind": "receptacle",
            "public_label": "Fridge Fridge|1|1",
        },
        "shelf_01": {
            "category": "ShelvingUnit",
            "kind": "receptacle",
            "public_label": "ShelvingUnit ShelvingUnit|1|1",
        },
        "sink_01": {"category": "Sink", "kind": "receptacle", "public_label": "Sink Sink|1|1"},
        "sofa_01": {"category": "Sofa", "kind": "receptacle", "public_label": "Sofa Sofa|1|1"},
        "stand_01": {
            "category": "TVStand",
            "kind": "receptacle",
            "public_label": "TVStand TVStand|1|1",
        },
    }

    scenario = runtime_commands._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=7,
        generated_mess_count=5,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert [item.category for item in scenario.objects] == [
        "Plate",
        "Book",
        "Potato",
        "RemoteControl",
        "Pillow",
    ]
    assert [target.valid_receptacle_ids[0] for target in scenario.private_manifest.targets] == [
        "sink_01",
        "shelf_01",
        "fridge_01",
        "stand_01",
        "bed_01",
    ]
    assert scenario.private_manifest.success_threshold == 4


def test_isaac_scene_index_can_pin_generated_mess_object_ids() -> None:
    object_index = {
        "apple_01": {
            "asset_id": "Apple_1",
            "category": "Apple",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Apple Apple|surface|1|3 Apple_1",
        },
        "bread_01": {
            "asset_id": "Bread_1",
            "category": "Bread",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Bread Bread|surface|1|4 Bread_1",
        },
    }
    receptacle_index = {
        "counter_01": {
            "category": "CounterTop",
            "kind": "receptacle",
            "public_label": "CounterTop CounterTop|1|1",
        },
        "fridge_01": {
            "category": "Fridge",
            "kind": "receptacle",
            "public_label": "Fridge Fridge|1|1",
        },
    }

    scenario = runtime_commands._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=6,
        generated_mess_count=1,
        generated_mess_object_ids=("apple_01",),
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert [item.object_id for item in scenario.objects] == ["apple_01"]
    assert [target.object_id for target in scenario.private_manifest.targets] == ["apple_01"]
    assert scenario.private_manifest.targets[0].valid_receptacle_ids == ("fridge_01",)


def test_isaac_scene_index_consumes_canonical_generated_mess_manifest() -> None:
    object_index = {
        "apple_01": {
            "asset_id": "Apple_1",
            "category": "Apple",
            "kind": "object",
            "parent": "counter_01",
            "public_label": "Apple Apple|surface|1|3 Apple_1",
        },
        "plate_01": {
            "asset_id": "Plate_1",
            "category": "Plate",
            "kind": "object",
            "parent": "table_01",
            "public_label": "Plate Plate|surface|1|4 Plate_1",
        },
    }
    receptacle_index = {
        "counter_01": {
            "category": "CounterTop",
            "kind": "receptacle",
            "public_label": "CounterTop CounterTop|1|1",
        },
        "fridge_01": {
            "category": "Fridge",
            "kind": "receptacle",
            "public_label": "Fridge Fridge|1|1",
        },
        "sink_01": {"category": "Sink", "kind": "receptacle", "public_label": "Sink Sink|1|1"},
        "sofa_01": {"category": "Sofa", "kind": "receptacle", "public_label": "Sofa Sofa|1|1"},
        "table_01": {
            "category": "DiningTable",
            "kind": "receptacle",
            "public_label": "DiningTable DiningTable|1|1",
        },
    }
    manifest = {
        "schema": "roboclaws_generated_mess_manifest_v1",
        "targets": [
            {
                "object_id": "apple_01",
                "valid_receptacle_ids": ["fridge_01"],
                "target_receptacle_id": "fridge_01",
                "start_receptacle_id": "sofa_01",
                "relation": "on",
                "placement_index": 0,
            },
            {
                "object_id": "plate_01",
                "valid_receptacle_ids": ["sink_01"],
                "target_receptacle_id": "sink_01",
                "start_receptacle_id": "sofa_01",
                "relation": "on",
                "placement_index": 1,
            },
        ],
    }

    scenario = runtime_commands._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=6,
        generated_mess_count=2,
        generated_mess_manifest=manifest,
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    assert [item.object_id for item in scenario.objects] == ["apple_01", "plate_01"]
    assert [item.location_id for item in scenario.objects] == ["sofa_01", "sofa_01"]
    assert [target.valid_receptacle_ids[0] for target in scenario.private_manifest.targets] == [
        "fridge_01",
        "sink_01",
    ]


def test_isaac_scene_index_preserves_teddybear_category_for_placement() -> None:
    object_index = {
        "teddy_01": {
            "asset_id": "Teddy_Bear_1",
            "category": "TeddyBear",
            "kind": "object",
            "parent": "desk_01",
            "public_label": "TeddyBear TeddyBear|surface|1|8 Teddy_Bear_1",
        },
        "pillow_01": {
            "asset_id": "Pillow_1",
            "category": "Pillow",
            "kind": "object",
            "parent": "desk_01",
            "public_label": "Pillow Pillow|surface|1|9 Pillow_1",
        },
    }
    receptacle_index = {
        "bed_01": {"category": "Bed", "kind": "receptacle", "public_label": "Bed Bed|1|1"},
        "desk_01": {"category": "Desk", "kind": "receptacle", "public_label": "Desk Desk|1|1"},
    }

    scenario = runtime_commands._scenario_from_scene_index(
        scene_source="procthor-10k-val",
        scene_index=0,
        seed=1,
        generated_mess_count=2,
        generated_mess_object_ids=("teddy_01", "pillow_01"),
        object_index=object_index,
        receptacle_index=receptacle_index,
    )

    assert scenario is not None
    categories = {item.object_id: item.category for item in scenario.objects}
    assert categories == {"teddy_01": "TeddyBear", "pillow_01": "Pillow"}
    assert [target.valid_receptacle_ids[0] for target in scenario.private_manifest.targets] == [
        "bed_01",
        "bed_01",
    ]


def test_isaac_scene_index_rejects_missing_explicit_generated_mess_id() -> None:
    with pytest.raises(ValueError, match="explicit generated mess object id is unavailable"):
        runtime_commands._scenario_from_scene_index(
            scene_source="procthor-10k-val",
            scene_index=0,
            seed=6,
            generated_mess_count=1,
            generated_mess_object_ids=("missing_object",),
            object_index={},
            receptacle_index={
                "fridge_01": {
                    "category": "Fridge",
                    "kind": "receptacle",
                    "public_label": "Fridge Fridge|1|1",
                },
            },
        )


def test_isaac_lab_generated_count_selects_private_targets_not_first_object(
    tmp_path: Path,
) -> None:
    args = runtime_cli.parse_args(
        [
            "--state-path",
            str(tmp_path / "state.json"),
            "init",
            "--run-dir",
            str(tmp_path / "run"),
            "--runtime-mode",
            "fake",
            "--generated-mess-count",
            "1",
        ]
    )
    result = runtime_initialization.init_state(args)

    object_ids = [item["object_id"] for item in result["scenario"]["objects"]]
    target_ids = [item["object_id"] for item in result["private_manifest"]["targets"]]

    assert object_ids == ["mug_01"]
    assert target_ids == ["mug_01"]
    assert object_ids != ["toy_car_01"]
    assert result["scene_binding_diagnostics"]["selected_object_count"] == 1
    assert result["scene_binding_diagnostics"]["selected_target_receptacle_count"] == 1
