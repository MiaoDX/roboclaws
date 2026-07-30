from __future__ import annotations

import pytest

from roboclaws.backends.isaaclab import isaac_scenario_state


class _Hooks:
    @staticmethod
    def receptacle_prefers_inside(_receptacle: dict[str, object]) -> bool:
        return True


def test_molmospaces_manifest_target_rejects_invalid_relation() -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces import scenario_state

    with pytest.raises(
        ValueError,
        match="generated mess manifest relation must be 'on' or 'inside'",
    ):
        scenario_state.target_relation(
            {},
            {"object_id": "mug_01", "relation": "beside"},
            hooks=_Hooks(),
        )


def test_molmospaces_manifest_target_rejects_invalid_placement_index() -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces import scenario_state

    for placement_index in (None, 1.2, True):
        with pytest.raises(
            ValueError,
            match="generated mess manifest placement_index must be an integer",
        ):
            scenario_state.target_placement_index(
                4,
                {"object_id": "mug_01", "placement_index": placement_index},
            )


def test_molmospaces_non_manifest_seed_keeps_backend_fallbacks() -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces import scenario_state

    assert (
        scenario_state.target_relation(
            {},
            None,
            hooks=_Hooks(),
        )
        == "inside"
    )
    assert scenario_state.target_placement_index(4, None) == 4


def test_molmospaces_placement_clearance_score_prefers_open_candidate(monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces import placement as molmospaces_placement

    aabbs = {
        "occupied": {
            "min_x": 0.0,
            "max_x": 0.2,
            "min_y": 0.0,
            "max_y": 0.2,
            "min_z": 0.0,
            "max_z": 0.4,
        }
    }

    monkeypatch.setattr(
        molmospaces_placement,
        "object_world_aabb",
        lambda _model, _data, item, *, hooks: aabbs.get(item["object_id"]),
    )
    state = {
        "objects": {
            "target": {"object_id": "target"},
            "occupied": {"object_id": "occupied", "location_relation": "on"},
            "held": {"object_id": "held", "location_relation": "held"},
        }
    }
    hooks = object()
    near = molmospaces_placement.candidate_dynamic_clearance_score(
        object(),
        object(),
        state,
        state["objects"]["target"],
        [0.1, 0.1, 0.2],
        footprint=(0.05, 0.05),
        bottom_offset=0.0,
        hooks=hooks,
    )
    open_space = molmospaces_placement.candidate_dynamic_clearance_score(
        object(),
        object(),
        state,
        state["objects"]["target"],
        [1.0, 1.0, 0.2],
        footprint=(0.05, 0.05),
        bottom_offset=0.0,
        hooks=hooks,
    )
    assert open_space > near


def test_molmospaces_direct_support_chooses_farther_clear_slot(monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from roboclaws.backends.molmospaces import placement as molmospaces_placement

    occupied = {
        "min_x": -0.15,
        "max_x": 0.15,
        "min_y": -0.15,
        "max_y": 0.15,
        "min_z": 0.4,
        "max_z": 0.8,
    }
    monkeypatch.setattr(
        molmospaces_placement,
        "object_footprint_half_extents",
        lambda *_args, **_kwargs: (0.05, 0.05),
    )
    monkeypatch.setattr(
        molmospaces_placement,
        "object_bottom_offset",
        lambda *_args, **_kwargs: 0.1,
    )
    monkeypatch.setattr(
        molmospaces_placement,
        "object_height",
        lambda *_args, **_kwargs: 0.2,
    )
    monkeypatch.setattr(
        molmospaces_placement,
        "object_world_aabb",
        lambda _model, _data, item, *, hooks: occupied if item["object_id"] == "occupied" else None,
    )
    monkeypatch.setattr(
        molmospaces_placement,
        "surface_candidate_positions",
        lambda *_args, **_kwargs: [[0.0, 0.0, 0.6], [0.8, 0.0, 0.6]],
    )
    surface = {
        "surface_id": "desk_top",
        "center": [0.0, 0.0],
        "top_z": 0.5,
        "half_extents": [1.0, 1.0],
        "area_m2": 4.0,
    }
    result = molmospaces_placement.direct_support_placement(
        object(),
        object(),
        {
            "objects": {
                "target": {"object_id": "target"},
                "occupied": {"object_id": "occupied", "location_relation": "on"},
            }
        },
        {"object_id": "target", "category": "Book"},
        {"category": "Desk", "support_surfaces": [surface]},
        index=0,
        hooks=object(),
    )
    assert result is not None
    assert result["position"] == [0.8, 0.0, 0.6]
    assert result["support_status"] == "direct_support"


def test_isaac_manifest_target_rejects_invalid_relation() -> None:
    with pytest.raises(
        ValueError,
        match="generated mess manifest relation must be 'on' or 'inside'",
    ):
        isaac_scenario_state.target_relation(
            {},
            {"object_id": "mug_01", "relation": "beside"},
            hooks=_Hooks(),
        )


def test_isaac_manifest_target_rejects_invalid_placement_index() -> None:
    for placement_index in (None, 1.2, True):
        with pytest.raises(
            ValueError,
            match="generated mess manifest placement_index must be an integer",
        ):
            isaac_scenario_state.target_placement_index(
                4,
                {"object_id": "mug_01", "placement_index": placement_index},
            )


def test_isaac_non_manifest_seed_keeps_backend_fallbacks() -> None:
    assert isaac_scenario_state.target_relation({}, None, hooks=_Hooks()) == "inside"
    assert isaac_scenario_state.target_placement_index(4, None) == 4
