"""Current support geometry determines object locations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from roboclaws.backends.molmospaces import scenario_state


def _fixture(
    name: str, origin: list[float], center: list[float], half_extents: list[float], top_z: float
) -> dict[str, Any]:
    return {
        "receptacle_id": name,
        "position": origin,
        "support_surfaces": [{"center": center, "half_extents": half_extents, "top_z": top_z}],
    }


@pytest.fixture
def offset_counter_and_desk() -> list[dict[str, Any]]:
    return [
        _fixture("counter", [0.0, 0.0, 0.5], [1.0, 0.0], [0.8, 0.4], 1.0),
        _fixture("desk", [1.8, 0.0, 0.6], [1.8, 0.0], [0.1, 0.3], 0.7),
    ]


def test_support_area_owns_object_despite_closer_furniture_center(
    offset_counter_and_desk: list[dict[str, Any]],
) -> None:
    assert scenario_state.nearest_receptacle([1.3, 0.0, 1.03], offset_counter_and_desk) == "counter"


def test_height_separates_overlapping_supports() -> None:
    fixtures = [
        _fixture("upper", [0.0, 0.0, 1.7], [0.0, 0.0], [0.5, 0.5], 1.8),
        _fixture("lower", [0.3, 0.0, 0.7], [0.0, 0.0], [0.5, 0.5], 0.8),
    ]
    assert scenario_state.nearest_receptacle([0.0, 0.0, 0.83], fixtures) == "lower"


def test_all_fixture_support_surfaces_are_considered() -> None:
    fixture = _fixture("shelves", [2.0, 0.0, 1.0], [2.0, 0.0], [0.3, 0.3], 1.8)
    fixture["support_surfaces"].append(
        {"center": [0.0, 0.0], "half_extents": [0.4, 0.4], "top_z": 0.8}
    )
    neighbor = _fixture("neighbor", [0.0, 0.0, 1.0], [0.0, 0.0], [0.3, 0.3], 1.4)
    assert scenario_state.nearest_receptacle([0.0, 0.0, 0.82], [neighbor, fixture]) == "shelves"


def test_geometry_free_fixture_is_a_point_in_three_dimensions() -> None:
    fixtures = [
        {"receptacle_id": "above", "position": [0.0, 0.0, 3.0]},
        {"receptacle_id": "near", "position": [0.1, 0.0, 0.8], "support_surfaces": []},
    ]
    assert scenario_state.nearest_receptacle([0.0, 0.0, 0.83], fixtures) == "near"


def test_read_locations_uses_current_geometry_and_keeps_held_and_contained_objects(
    monkeypatch: pytest.MonkeyPatch, offset_counter_and_desk: list[dict[str, Any]]
) -> None:
    data = SimpleNamespace(xpos=[[1.3, 0.0, 1.03]])
    hooks = SimpleNamespace(
        load_model_data_for_state=lambda _state: (object(), data),
        apply_qpos=lambda _data, _qpos: None,
        xyz=list,
    )
    monkeypatch.setattr(scenario_state.mujoco, "mj_forward", lambda _model, _data: None)
    monkeypatch.setattr(scenario_state.mujoco, "mj_name2id", lambda *_args: 0)
    state = {
        "qpos": [],
        "held_object_id": "held",
        "objects": {
            "observed": {"body_name": "observed", "seeded_start_receptacle_id": "desk"},
            "held": {"body_name": "held"},
            "contained": {"body_name": "contained", "contained_in": "cabinet"},
            "static": {"pickupable": False},
        },
        "receptacles": {x["receptacle_id"]: x for x in offset_counter_and_desk},
    }
    assert scenario_state.read_locations(state, hooks=hooks) == {
        "observed": "counter",
        "held": "held_by_agent",
        "contained": "cabinet",
    }
