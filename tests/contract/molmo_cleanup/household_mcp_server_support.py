from __future__ import annotations

import asyncio
import importlib.util
import math
from pathlib import Path
from typing import Any

from roboclaws.core.goals import normalize_goal_contract
from roboclaws.core.task_intents import TASK_INTENT_SPECS
from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_mcp_server import (
    make_household_world_mcp as _make_household_world_mcp,
)
from roboclaws.household.household_runtime_contract import (
    RAW_FPV_ONLY_MODE,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_ROBOT_VIEW_VARIANT,
    ISAACLAB_SUBPROCESS_BACKEND,
)
from roboclaws.household.realworld_visual_candidate_declarations import (
    simulated_declaration_inputs_for_waypoint,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.types import (
    CleanupReceptacle,
    CleanupScenario,
    PrivateScoringManifest,
)
from roboclaws.launch.catalog import SURFACE_SPECS
from roboclaws.mcp.profiles import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _open_ended_goal_contract(prompt: str):
    return normalize_goal_contract(
        surface=SURFACE_SPECS["household-world"],
        intent=TASK_INTENT_SPECS["open-ended"],
        raw_prompt=prompt,
        required_capabilities=TASK_INTENT_SPECS["open-ended"].required_capabilities,
    )


SMOKE_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_realworld_agent_mcp_smoke.py"

PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def make_household_world_mcp(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("map_bundle_dir", PREBUILT_BUNDLE)
    kwargs.setdefault(
        "required_capability_profiles",
        (
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        ),
    )
    return _make_household_world_mcp(*args, **kwargs)


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("run_molmo_realworld_agent_mcp_smoke", SMOKE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fastmcp_tool_names(server: Any) -> set[str]:
    return set(server._mcp._tool_manager._tools)


def _listed_fastmcp_tool_names(server: Any) -> set[str]:
    return {tool.name for tool in asyncio.run(server._mcp.list_tools())}


def _assert_run_evidence_lane(run_result: dict[str, Any], expected: str) -> None:
    assert run_result["evidence_lane"] == expected
    assert run_result["evidence_lane_metadata"]["evidence_lane"] == expected


def _first_destination_option_from_done(server: Any, object_id: str) -> dict[str, Any]:
    done = server.call_tool("done", reason="probe public destination options")
    pending = [
        dict(item)
        for blocker in (done.get("completion") or {}).get("blockers") or []
        if blocker.get("type") == "pending_cleanup_candidates"
        for item in blocker.get("pending_cleanup_candidates") or []
    ]
    item = next(item for item in pending if item.get("object_id") == object_id)
    options = item.get("destination_options") or []
    assert options, item
    return dict(options[0])


class _FakeVisualBackend(ApiSemanticCleanupBackend):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.robot_view_camera_offsets: list[dict[str, float]] = []

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        self.robot_view_camera_offsets.append(
            {
                "yaw_delta_deg": camera_yaw_offset_deg,
                "pitch_delta_deg": camera_pitch_offset_deg,
            }
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        views = {}
        for key in ("fpv", "chase", "topdown", "verify"):
            path = output_dir / f"{label}_{key}.png"
            path.write_bytes(b"fake png")
            views[key] = str(path)
        has_focus = bool(focus_object_id or focus_receptacle_id)
        return {
            "ok": True,
            "robot_pose": {
                "x": 1.0,
                "y": 2.0,
                "theta": 0.0,
                "head_pitch": -0.25,
                "theta_source": "target_facing_base_yaw",
                "head_pitch_source": "target_framing_head_pitch",
                "same_room_as_target": True,
            },
            "robot_trajectory": [{"x": 1.0, "y": 2.0}],
            "view_variant": "molmospaces-rby1m-fpv-topdown-chase-verify",
            "view_provenance": "test_fake_visual_backend",
            "camera_control_contract": {
                "schema": "robot_view_camera_control_contract_v1",
                "status": "backend_local_robot_camera",
                "camera_model": "backend_local_robot_view",
                "same_pose_api": False,
                "agent_facing_fpv": {
                    "source": "test_fake_fpv",
                    "canonical_camera_control": False,
                },
            },
            "focus": {
                "has_focus": has_focus,
                "object_id": focus_object_id,
                "receptacle_id": focus_receptacle_id,
                "provenance": "public_mujoco_state_report_aid" if has_focus else None,
                "fpv_visibility": {
                    "status": "ok",
                    "boxes": [{"label": focus_object_id or focus_receptacle_id}],
                    "object_pixels": 300,
                    "receptacle_pixels": 120,
                },
                "visibility": {
                    "status": "ok",
                    "boxes": [{"label": focus_object_id or focus_receptacle_id}],
                    "object_pixels": 150,
                    "receptacle_pixels": 120,
                },
            },
            "room_outline_count": 1,
            "views": views,
        }


class MolmoSpacesSubprocessBackend(_FakeVisualBackend):
    backend = "molmospaces_subprocess"
    requested_generated_mess_count = 5


class IsaacLabSubprocessBackend(_FakeVisualBackend):
    backend = ISAACLAB_SUBPROCESS_BACKEND
    requested_generated_mess_count = 5

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        capture = super().write_robot_views(
            output_dir,
            label=label,
            focus_object_id=focus_object_id,
            focus_receptacle_id=focus_receptacle_id,
            camera_yaw_offset_deg=camera_yaw_offset_deg,
            camera_pitch_offset_deg=camera_pitch_offset_deg,
        )
        capture["view_variant"] = ISAACLAB_ROBOT_VIEW_VARIANT
        capture["view_provenance"] = "test_fake_isaac_visual_backend"
        return capture


def _empty_cleanup_scenario(scenario_id: str) -> CleanupScenario:
    return CleanupScenario(
        scenario_id=scenario_id,
        task="check MCP done readiness policy",
        seed=7,
        objects=(),
        receptacles=(
            CleanupReceptacle("sofa_01", "Sofa", "living_area", category="Sofa"),
            CleanupReceptacle("floor_01", "Floor", "living_area", category="Floor"),
            CleanupReceptacle("armchair_01", "Armchair", "living_area", category="Armchair"),
            CleanupReceptacle("desk_01", "Desk", "office", category="Desk"),
            CleanupReceptacle(
                "coffee_table_01", "Coffee Table", "living_area", category="CoffeeTable"
            ),
            CleanupReceptacle("sink_01", "Sink", "kitchen", category="Sink"),
            CleanupReceptacle("bookshelf_01", "Bookshelf", "living_area", category="ShelvingUnit"),
            CleanupReceptacle(
                "laundry_hamper_01", "Laundry Hamper", "bedroom", category="LaundryHamper"
            ),
            CleanupReceptacle("fridge_01", "Fridge", "kitchen", category="Fridge"),
            CleanupReceptacle("toy_bin_01", "Toy Bin", "living_area", category="ToyBin"),
        ),
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=(),
            success_threshold=0,
        ),
    )


def _raw_fpv_camera_raw_server(tmp_path: Path) -> Any:
    scenario = build_cleanup_scenario(seed=7)
    backend = MolmoSpacesSubprocessBackend(scenario)
    return make_household_world_mcp(
        run_dir=tmp_path,
        scenario=scenario,
        base_contract=HouseholdBackendSession(scenario, backend=backend),
        port=0,
        policy="codex_agent",
        agent_driven=True,
        record_robot_views=True,
        perception_mode=RAW_FPV_ONLY_MODE,
        evidence_lane="camera-raw-fpv",
    )


def _complete_raw_fpv_heading_coverage(server: Any) -> None:
    metric_map = server.call_tool("metric_map")
    for waypoint in metric_map["inspection_waypoints"]:
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
        for heading in (0.0, 90.0, 180.0, 270.0):
            server.call_tool("observe")
            server.contract._raw_fpv_observations[-1][  # noqa: SLF001
                "camera_control_contract"
            ] = {
                "robot_pose": {
                    "pose_source": "relative_robot_frame",
                    "theta": math.radians(heading),
                }
            }


def _sweep_with_unresolved_raw_fpv_declarations(
    server: Any,
    *,
    declaration_count: int,
) -> None:
    metric_map = server.call_tool("metric_map")
    declarations = 0
    for waypoint in metric_map["inspection_waypoints"]:
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
        observation = server.call_tool("observe")
        if declarations < declaration_count:
            response = server.call_tool(
                "navigate_to_visual_candidate",
                source_observation_id=observation["raw_fpv_observation"]["observation_id"],
                category="imaginary widget",
                evidence_note="nonexistent public object declaration for done guard",
                image_region={"type": "verbal_region", "value": "front area"},
            )
            assert response["ok"] is False
            assert response["error_reason"] == "visual_candidate_not_resolved"
            declarations += 1
    assert declarations == declaration_count


def _clean_raw_fpv_candidate(
    server: Any,
    *,
    observation_id: str,
    candidate_input: dict[str, Any],
) -> str | None:
    candidate = server.call_tool(
        "navigate_to_visual_candidate",
        source_observation_id=observation_id,
        category=str(candidate_input["category"]),
        source_fixture_id=str(candidate_input.get("source_fixture_id") or ""),
        evidence_note=str(candidate_input.get("evidence_note") or ""),
        image_region=candidate_input.get("image_region")
        or {"type": "bbox", "value": [0.12, 0.24, 0.18, 0.16]},
    )
    if not candidate.get("ok"):
        return None
    object_id = str(candidate["object_id"])
    assert server.call_tool("pick", object_id=object_id)["ok"] is True
    fixture_id = str(candidate["candidate_fixture_id"])
    assert server.call_tool("navigate_to_receptacle", fixture_id=fixture_id)["ok"] is True
    if candidate["recommended_tool"] == "place_inside":
        placed = server.call_tool("place_inside", fixture_id=fixture_id)
        if (
            not placed.get("ok")
            and placed.get("error_reason") == "semantic_order"
            and placed.get("required_tool") == "open_receptacle"
        ):
            assert server.call_tool("open_receptacle", fixture_id=fixture_id)["ok"] is True
            placed = server.call_tool("place_inside", fixture_id=fixture_id)
            assert placed["ok"] is True
            assert server.call_tool("close_receptacle", fixture_id=fixture_id)["ok"] is True
    else:
        placed = server.call_tool("place", fixture_id=fixture_id)
    assert placed["ok"] is True
    server.call_tool("observe")
    return object_id


def _complete_raw_fpv_cleanup_chains(
    server: Any,
    *,
    required_count: int,
) -> set[str]:
    metric_map = server.call_tool("metric_map")
    handled: set[str] = set()
    for waypoint in metric_map["inspection_waypoints"]:
        waypoint_id = str(waypoint["waypoint_id"])
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint_id)
        observation = server.call_tool("observe")
        observation_id = observation["raw_fpv_observation"]["observation_id"]
        public_waypoint = server.contract._waypoint_by_id(waypoint_id)  # noqa: SLF001
        if public_waypoint is None:
            continue
        candidate_inputs = simulated_declaration_inputs_for_waypoint(
            server.contract,
            public_waypoint,
            observation_id=observation_id,
        )
        for candidate_input in candidate_inputs:
            object_id = _clean_raw_fpv_candidate(
                server,
                observation_id=observation_id,
                candidate_input=candidate_input,
            )
            if object_id is None or object_id in handled:
                continue
            handled.add(object_id)
            if len(handled) >= required_count:
                break
        if len(handled) >= required_count:
            break
    assert len(handled) >= required_count
    for waypoint in metric_map["inspection_waypoints"]:
        if waypoint.get("visited"):
            continue
        server.call_tool("navigate_to_waypoint", waypoint_id=waypoint["waypoint_id"])
        server.call_tool("observe")
    return handled
