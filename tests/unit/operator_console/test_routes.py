from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.launch.agent_engines import agent_engine_spec
from roboclaws.launch.worlds import MOLMOSPACES_CONSOLE_WORLD_IDS, WORLD_SPECS
from roboclaws.operator_console import workflows as console_workflows
from roboclaws.operator_console.launcher import ConsoleLaunchError, build_launch_argv
from roboclaws.operator_console.routes import (
    default_workflow_selection_id,
    get_selection,
    list_console_combinations,
    list_evidence_lanes,
    list_prior_catalog,
    list_workflows,
    list_worlds,
    selection_task_selector,
    validate_supported_routes_against_catalog,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_CLEANUP,
    AGIBOT_SDK_MAP_BUILD,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_DIRECT_MAP_BUILD,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
)


def test_world_catalog_exposes_scene_first_console_choices() -> None:
    worlds = {world["id"]: world for world in list_worlds()}

    assert tuple(world_id for world_id in worlds if world_id.startswith("molmospaces/")) == (
        *MOLMOSPACES_CONSOLE_WORLD_IDS,
    )
    assert "molmospaces/val_6" not in worlds
    assert "molmospaces/val_8" not in worlds
    default_world = MOLMOSPACES_CONSOLE_WORLD_IDS[0]
    assert default_world == "molmospaces/val_0"
    assert worlds[default_world]["available_backends"] == ["mujoco"]
    assert worlds["molmospaces/procthor-10k-val/11"]["available_backends"] == ["mujoco"]
    assert worlds["molmospaces/procthor-10k-val/11"]["preview_assets"] == {
        "fpv": {
            "path": "/previews/molmospaces-procthor-10k-val-11-fpv.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-fpv.png",
        },
        "map": {
            "path": "/previews/molmospaces-procthor-10k-val-11-map.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-map.png",
        },
        "chase": {
            "path": "/previews/molmospaces-procthor-10k-val-11-chase.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-chase.png",
        },
        "topdown": {
            "path": "/previews/molmospaces-procthor-10k-val-11-topdown.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-topdown.png",
        },
    }
    assert worlds["molmospaces/procthor-objaverse-val/10"]["available_backends"] == ["mujoco"]
    assert worlds["molmospaces/procthor-objaverse-val/10"]["preview_assets"] == {
        "fpv": {
            "path": "/previews/molmospaces-procthor-objaverse-val-10-fpv.png",
            "href": "/previews/molmospaces-procthor-objaverse-val-10-fpv.png",
        },
        "map": {
            "path": "/previews/molmospaces-procthor-objaverse-val-10-map.png",
            "href": "/previews/molmospaces-procthor-objaverse-val-10-map.png",
        },
        "chase": {
            "path": "/previews/molmospaces-procthor-objaverse-val-10-chase.png",
            "href": "/previews/molmospaces-procthor-objaverse-val-10-chase.png",
        },
        "topdown": {
            "path": "/previews/molmospaces-procthor-objaverse-val-10-topdown.png",
            "href": "/previews/molmospaces-procthor-objaverse-val-10-topdown.png",
        },
    }
    assert worlds["agibot-g2/map-12"]["preview_assets"] == {
        "map": {
            "path": "/previews/b1-map12-map.png",
            "href": "/previews/b1-map12-map.png",
        },
        "topdown": {
            "path": "/previews/b1-map12-topdown.png",
            "href": "/previews/b1-map12-topdown.png",
        },
    }
    assert worlds["b1-map12"]["preview_assets"] == {
        "fpv": {
            "path": "/previews/b1-map12-fpv.png",
            "href": "/previews/b1-map12-fpv.png",
        },
        "map": {
            "path": "/previews/b1-map12-map.png",
            "href": "/previews/b1-map12-map.png",
        },
        "chase": {
            "path": "/previews/b1-map12-chase.png",
            "href": "/previews/b1-map12-chase.png",
        },
        "topdown": {
            "path": "/previews/b1-map12-topdown.png",
            "href": "/previews/b1-map12-topdown.png",
        },
    }
    assert "ai2thor/FloorPlan201" not in worlds
    assert "ai2thor-games/FloorPlan201" not in worlds
    assert worlds["planner-proof/default"]["preview_assets"] == {
        "map": {
            "path": "/previews/molmospaces-val_0-map.png",
            "href": "/previews/molmospaces-val_0-map.png",
        },
    }
    assert worlds["agibot-g2/map-12"]["available_backends"] == ["agibot-gdk"]
    assert worlds["b1-map12"]["available_backends"] == ["isaaclab"]
    assert worlds["b1-map12"]["default_backend"] == "isaaclab"


def test_scene_preview_rendered_views_never_alias_other_preview_types() -> None:
    worlds = {world["id"]: world for world in list_worlds()}

    for world_id, world in worlds.items():
        previews = world["preview_assets"]
        if "topdown" in previews:
            assert previews["topdown"]["href"] != previews.get("map", {}).get("href"), world_id
            assert previews["topdown"]["href"] != previews.get("fpv", {}).get("href"), world_id
            assert "-topdown." in previews["topdown"]["href"], world_id
        if "chase" in previews:
            assert previews["chase"]["href"] != previews.get("map", {}).get("href"), world_id
            assert previews["chase"]["href"] != previews.get("fpv", {}).get("href"), world_id
            assert previews["chase"]["href"] != previews.get("topdown", {}).get("href"), world_id
            assert "-chase." in previews["chase"]["href"], world_id


def test_molmospaces_scene_previews_have_render_provenance() -> None:
    preview_root = (
        Path(__file__).resolve().parents[3] / "roboclaws/operator_console/static/previews"
    )

    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        previews = WORLD_SPECS[world_id].preview_assets
        assert {view for view, _path in previews} == {"fpv", "map", "chase", "topdown"}
        assert all(path.startswith("/previews/") for _view, path in previews)
        scene_name = world_id.replace("/", "-")
        metadata_path = preview_root / f"{scene_name}-preview.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["schema"] == "operator_console_scene_preview_v1"
        assert metadata["world_id"] == world_id
        assert metadata["backend"] == "mujoco"
        assert metadata["views"]["fpv"]["view"] == "raw_fpv"
        assert metadata["views"]["fpv"]["waypoint_id"]
        assert metadata["views"]["fpv"]["provenance"] == (
            "mujoco_robot_head_camera_first_public_waypoint"
        )
        assert metadata["views"]["chase"]["view"] == "chase_camera"
        assert metadata["views"]["chase"]["waypoint_id"]
        assert metadata["views"]["chase"]["provenance"] == (
            "mujoco_robot_camera_follower_public_waypoint"
        )
        assert metadata["views"]["chase"]["selection_policy"] == (
            "first_reviewable_public_waypoint_fallback_to_first"
        )
        assert metadata["views"]["chase"]["selection_status"] in {
            "first_waypoint_reviewable",
            "alternate_waypoint_reviewable",
            "fallback_first_waypoint_low_detail",
        }
        assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
        assert metadata["views"]["topdown"]["provenance"] == (
            "mujoco_camera_control_canonical_eye_target"
        )
        assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
        assert metadata["views"]["map"]["provenance"] == "map_bundle_preview_png"
        assert "semantic_projection" not in metadata["views"]["map"]
        assert "scene_alignment" not in metadata["views"]["map"]


def test_b1_map12_scene_preview_has_v1_runtime_camera_provenance() -> None:
    preview_root = (
        Path(__file__).resolve().parents[3] / "roboclaws/operator_console/static/previews"
    )

    metadata = json.loads((preview_root / "b1-map12-preview.json").read_text(encoding="utf-8"))

    assert metadata["schema"] == "operator_console_scene_preview_v1"
    assert metadata["world_id"] == "b1-map12"
    assert metadata["backend"] == "isaaclab"
    assert metadata["renderer"] == "b1_map12_static_gaussian_topdown_with_isaac_runtime_camera"
    assert metadata["scene_usd_path"] == (
        "data/robot-data-lab/scene-engine/data/2rd_floor_seperated/storey_1/scene_gs.usda"
    )
    assert metadata["camera_preview_artifact"]["schema"] == "b1_map12_navigation_smoke_v1"
    assert metadata["camera_preview_artifact"]["source_artifact_name"] == "navigation_smoke.json"
    assert metadata["camera_preview_artifact"]["selected_waypoint_id"] == (
        "b1_aligned_plastic_bottle_table_1"
    )
    assert "path" not in metadata["camera_preview_artifact"]
    assert metadata["views"]["fpv"]["provenance"] == ("isaac_runtime_robot_mounted_head_camera_fpv")
    assert metadata["views"]["fpv"]["robot_mounted"] is True
    assert not str(metadata["views"]["fpv"].get("source_artifact_view", "")).startswith("/")
    assert "source_path" not in metadata["views"]["fpv"]
    assert metadata["views"]["chase"]["provenance"] == "isaac_runtime_report_chase_camera"
    assert not str(metadata["views"]["chase"].get("source_artifact_view", "")).startswith("/")
    assert "source_path" not in metadata["views"]["chase"]
    assert metadata["views"]["map"]["view"] == "base_metric_map_preview"
    assert metadata["views"]["map"]["artifact_source_family"] == "base_metric_map_bundle"
    assert metadata["views"]["topdown"]["view"] == "topdown_scene_render"
    assert metadata["views"]["topdown"]["artifact_source_family"] == "scene_camera_render"
    assert metadata["views"]["topdown"]["provenance"] == "b1_scene_gaussian_topdown_crop_z1p8_png"
    assert metadata["views"]["topdown"]["alignment_status"] == (
        "height_cropped_gaussian_scene_topdown"
    )
    assert "first_waypoint_id" not in metadata["views"]["topdown"]
    assert "diagnostic_views" not in metadata
    assert metadata["map_bundle"] == "vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot"
    assert "runtime_map_bundle" not in metadata


def test_console_combinations_are_catalog_backed_axes() -> None:
    enabled = list_console_combinations(include_disabled=False)

    assert {
        (
            route.world_id,
            route.backend_id,
            route.intent_id,
            route.agent_engine_id,
            route.provider_profile,
            route.evidence_lane,
        )
        for route in enabled
    } >= {
        (
            "molmospaces/val_0",
            "mujoco",
            "map-build",
            "direct-runner",
            None,
            "world-public-labels",
        ),
        (
            "molmospaces/procthor-objaverse-val/0",
            "mujoco",
            "map-build",
            "direct-runner",
            None,
            "world-public-labels",
        ),
        (
            "molmospaces/procthor-objaverse-val/1",
            "mujoco",
            "open-ended",
            "openai-agents-sdk",
            "codex-router-responses",
            "world-public-labels",
        ),
        (
            "b1-map12",
            "isaaclab",
            "open-ended",
            "openai-agents-sdk",
            "codex-router-responses",
            "world-public-labels",
        ),
    }
    validate_supported_routes_against_catalog()


def test_selection_task_selector_keeps_open_tasks_out_of_preset_vocabulary() -> None:
    assert selection_task_selector("cleanup") == "cleanup"
    assert selection_task_selector("map-build") == "map-build"
    assert selection_task_selector("open-ended") == "open-task"


def test_openai_agents_route_payload_lists_provider_profiles() -> None:
    route = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    payload = route.to_payload()

    assert payload["provider_profile"] == "codex-router-responses"
    assert payload["supported_provider_profiles"] == [
        "codex-router-responses",
        "mimo-mify-responses",
        "minimax-responses",
        "mimo-tp-openai-chat",
        "mimo-inside-openai-chat",
        "kimi-openai-chat",
    ]
    route_by_profile = {route["provider_profile"]: route for route in payload["provider_routes"]}
    assert route_by_profile["mimo-mify-responses"]["route_status"] == "provisional"
    assert route_by_profile["mimo-tp-openai-chat"]["wire_api"] == "chat-completions"
    assert route_by_profile["minimax-responses"]["route_capabilities"]["image_transport"] == (
        "unknown"
    )


def test_openclaw_agent_engine_marks_validation_required() -> None:
    spec = agent_engine_spec("openclaw-gateway")

    assert spec.availability == "validation-required"


def test_console_exposes_all_supported_household_evidence_lanes() -> None:
    lanes = tuple(lane["id"] for lane in list_evidence_lanes())
    assert lanes == (
        "world-public-labels",
        "camera-grounded-labels",
        "camera-raw-fpv",
    )

    enabled_ids = {route.id for route in list_console_combinations(include_disabled=False)}
    for lane in lanes:
        assert (
            f"molmospaces/procthor-objaverse-val/0::mujoco::map-build::direct-runner::{lane}"
            in enabled_ids
        )
        assert (
            f"molmospaces/procthor-objaverse-val/0::mujoco::open-task::openai-agents-sdk::"
            f"{lane}" in enabled_ids
        )

    grounded = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::map-build::direct-runner::camera-grounded-labels"
    )
    assert "camera_labeler=grounding-dino" in grounded.launch_default_overrides
    agibot_grounded = get_selection(AGIBOT_SDK_MAP_BUILD)
    assert agibot_grounded.enabled
    assert "camera_labeler=grounding-dino" in agibot_grounded.launch_default_overrides


def test_operator_console_exposes_product_workflow_metadata() -> None:
    workflows = {workflow["id"]: workflow for workflow in list_workflows()}

    assert tuple(workflows) == (
        "build-map",
        "open-task",
        "cleanup",
        "open-task-with-map",
        "cleanup-with-map",
        "prepare-standard-mess",
        "reset-scene",
    )
    assert {workflow["coverage"]["owner_type"] for workflow in workflows.values()} == {
        "eval_suite",
        "unit_contract",
        "manual_operational_control",
    }
    assert workflows["build-map"]["coverage"]["owner_id"] == "map_build_consumer"
    assert workflows["open-task"]["coverage"]["owner_id"] == "open_ended_goals"
    assert workflows["cleanup"]["coverage"]["owner_id"] == "cleanup_capability"
    assert workflows["cleanup-with-map"]["requires_runtime_map_prior"] is True
    assert workflows["prepare-standard-mess"]["scenario_setup"] == (
        "relocate-cleanup-related-objects"
    )
    assert workflows["reset-scene"]["coverage"]["owner_type"] == "manual_operational_control"


def test_scene_workflow_payload_defaults_to_camera_grounded_and_empty_prior_catalog() -> None:
    worlds = {world["id"]: world for world in list_worlds()}
    world = worlds["molmospaces/procthor-objaverse-val/0"]
    workflows = {workflow["id"]: workflow for workflow in world["workflow_actions"]}

    assert list_prior_catalog() == ()
    assert default_workflow_selection_id(
        "molmospaces/procthor-objaverse-val/0", "open-task"
    ).endswith("::camera-grounded-labels")
    assert workflows["open-task"]["default_evidence_lane"] == "camera-grounded-labels"
    assert workflows["open-task"]["default_camera_labeler"] == "grounding-dino"
    assert workflows["open-task"]["default_route_id"].endswith("::camera-grounded-labels")
    assert workflows["cleanup"]["default_route_id"].endswith("::camera-grounded-labels")
    assert workflows["cleanup"]["enabled"] is True
    assert workflows["cleanup-with-map"]["enabled"] is False
    assert workflows["cleanup-with-map"]["allows_prior_override"] is True
    assert workflows["cleanup-with-map"]["recommended_prior"] is None
    assert (
        "No accepted Runtime Map Prior Snapshot"
        in (workflows["cleanup-with-map"]["disabled_reason"])
    )


def test_scene_workflow_payload_enables_with_map_from_accepted_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "runtime_map_prior_snapshot.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    catalog = tmp_path / "recommended_runtime_map_priors.json"
    _write_prior_catalog(catalog, prior)
    monkeypatch.setattr(console_workflows, "RECOMMENDED_PRIOR_CATALOG_PATH", catalog)

    worlds = {world["id"]: world for world in list_worlds()}
    world = worlds["molmospaces/procthor-objaverse-val/0"]
    workflows = {workflow["id"]: workflow for workflow in world["workflow_actions"]}
    catalog_rows = list_prior_catalog()

    assert catalog_rows[0]["path"] == str(prior)
    assert catalog_rows[0]["staleness"] == "compatible"
    assert workflows["open-task-with-map"]["enabled"] is True
    assert workflows["cleanup-with-map"]["enabled"] is True
    assert workflows["cleanup-with-map"]["disabled_reason"] == ""
    assert workflows["cleanup-with-map"]["recommended_prior"]["path"] == str(prior)


def test_scene_workflow_payload_keeps_blocking_stale_catalog_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "runtime_map_prior_snapshot.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    catalog = tmp_path / "recommended_runtime_map_priors.json"
    _write_prior_catalog(catalog, prior, staleness="blocking_stale")
    monkeypatch.setattr(console_workflows, "RECOMMENDED_PRIOR_CATALOG_PATH", catalog)

    worlds = {world["id"]: world for world in list_worlds()}
    world = worlds["molmospaces/procthor-objaverse-val/0"]
    workflows = {workflow["id"]: workflow for workflow in world["workflow_actions"]}

    assert list_prior_catalog()[0]["staleness"] == "blocking_stale"
    assert workflows["cleanup-with-map"]["enabled"] is False
    assert workflows["cleanup-with-map"]["recommended_prior"] is None


def test_scene_workflow_payload_marks_missing_catalog_prior_blocking_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_prior = tmp_path / "missing_runtime_map_prior_snapshot.json"
    catalog = tmp_path / "recommended_runtime_map_priors.json"
    _write_prior_catalog(catalog, missing_prior)
    monkeypatch.setattr(console_workflows, "RECOMMENDED_PRIOR_CATALOG_PATH", catalog)

    worlds = {world["id"]: world for world in list_worlds()}
    world = worlds["molmospaces/procthor-objaverse-val/0"]
    workflows = {workflow["id"]: workflow for workflow in world["workflow_actions"]}

    assert list_prior_catalog()[0]["staleness"] == "blocking_stale"
    assert workflows["cleanup-with-map"]["enabled"] is False
    assert workflows["cleanup-with-map"]["recommended_prior"] is None


def test_molmospaces_scene_choices_use_scene_specific_launch_defaults(tmp_path) -> None:
    enabled_ids = {route.id for route in list_console_combinations(include_disabled=False)}
    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        assert f"{world_id}::mujoco::map-build::direct-runner::world-public-labels" in enabled_ids
    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        assert f"{world_id}::mujoco::cleanup::openai-agents-sdk::world-public-labels" in enabled_ids

    objaverse0 = get_selection(MUJOCO_SDK_CLEANUP)
    val10 = get_selection(
        "molmospaces/procthor-objaverse-val/10::mujoco::map-build::direct-runner::world-public-labels"
    )

    assert "scene_index=0" in objaverse0.launch_default_overrides
    assert "map_bundle=assets/maps/molmospaces/procthor-objaverse-val/0" in (
        objaverse0.launch_default_overrides
    )
    assert "scene_index=10" in val10.launch_default_overrides
    assert "map_bundle=assets/maps/molmospaces/procthor-objaverse-val/10" in (
        val10.launch_default_overrides
    )
    assert val10.to_payload()["preview_assets"]["fpv"]["href"] == (
        "/previews/molmospaces-procthor-objaverse-val-10-fpv.png"
    )
    procthor11 = get_selection(
        "molmospaces/procthor-10k-val/11::mujoco::map-build::direct-runner::world-public-labels"
    )
    assert procthor11.to_payload()["preview_assets"] == {
        "fpv": {
            "path": "/previews/molmospaces-procthor-10k-val-11-fpv.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-fpv.png",
        },
        "map": {
            "path": "/previews/molmospaces-procthor-10k-val-11-map.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-map.png",
        },
        "chase": {
            "path": "/previews/molmospaces-procthor-10k-val-11-chase.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-chase.png",
        },
        "topdown": {
            "path": "/previews/molmospaces-procthor-10k-val-11-topdown.png",
            "href": "/previews/molmospaces-procthor-10k-val-11-topdown.png",
        },
    }
    argv = build_launch_argv(val10, root=tmp_path, run_id="run-val-10")
    assert "world=molmospaces/procthor-objaverse-val/10" in argv
    assert "scene_source=procthor-objaverse-val" in argv
    assert "scene_index=10" in argv
    assert "map_bundle=assets/maps/molmospaces/procthor-objaverse-val/10" in argv


def test_molmospaces_cleanup_routes_are_selectable_for_ui_scenes() -> None:
    all_ids = {route.id for route in list_console_combinations()}
    enabled_ids = {route.id for route in list_console_combinations(include_disabled=False)}

    assert not any(route_id.startswith("molmospaces/val_6::") for route_id in all_ids)
    assert not any(route_id.startswith("molmospaces/val_8::") for route_id in all_ids)

    assert (
        "molmospaces/val_1::mujoco::map-build::openai-agents-sdk::world-public-labels"
        not in all_ids
    )
    assert (
        "molmospaces/val_1::mujoco::cleanup::openai-agents-sdk::world-public-labels" not in all_ids
    )

    assert not any(
        "::isaaclab::" in route_id for route_id in all_ids if route_id.startswith("molmospaces/")
    )
    assert (
        "molmospaces/procthor-objaverse-val/1::mujoco::map-build::direct-runner::"
        "world-public-labels" in enabled_ids
    )
    assert (
        "molmospaces/procthor-objaverse-val/0::mujoco::open-task::openai-agents-sdk::"
        "world-public-labels" in enabled_ids
    )
    assert B1_OPENAI_AGENTS_OPEN_TASK in enabled_ids

    for world_id in MOLMOSPACES_CONSOLE_WORLD_IDS:
        assert f"{world_id}::mujoco::cleanup::openai-agents-sdk::world-public-labels" in enabled_ids


def test_console_enables_b1_camera_grounded_isaac_lane() -> None:
    enabled_ids = {route.id for route in list_console_combinations(include_disabled=False)}
    route = get_selection(B1_OPENAI_AGENTS_CAMERA_GROUNDED)

    assert route.id in enabled_ids
    assert route.enabled is True
    assert route.disabled_reason == ""
    assert "camera_labeler=grounding-dino" in route.base_args()
    assert "b1-map12::isaaclab::open-task::openai-agents-sdk::camera-raw-fpv" in enabled_ids


def test_disabled_combinations_have_concrete_reasons() -> None:
    disabled = [route for route in list_console_combinations() if not route.enabled]

    assert disabled
    reasons = {route.id: route.disabled_reason for route in disabled}
    assert "Physical manipulation is not active" in reasons[AGIBOT_SDK_CLEANUP]
    assert B1_OPENAI_AGENTS_CAMERA_GROUNDED not in reasons


def test_payload_exposes_orthogonal_ui_metadata() -> None:
    mujoco = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK).to_payload()
    agibot = get_selection(AGIBOT_SDK_MAP_BUILD).to_payload()
    b1_openai_agents = get_selection(B1_OPENAI_AGENTS_OPEN_TASK).to_payload()

    assert mujoco["world_id"] == "molmospaces/procthor-objaverse-val/0"
    assert mujoco["backend_id"] == "mujoco"
    assert mujoco["agent_engine_id"] == "openai-agents-sdk"
    assert mujoco["provider_profile"] == "codex-router-responses"
    assert mujoco["scenario_setup"] == "baseline"
    assert "agent_engine=openai-agents-sdk" in mujoco["argv_preview"]
    assert "scenario_setup=baseline" in mujoco["argv_preview"]
    assert mujoco["field_groups"] == ["common"]
    assert "grounding" not in mujoco["view_modes"]
    assert mujoco["supports_operator_steer"] is True
    assert mujoco["supports_paused_handoff_resume"] is True
    assert (
        get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK).to_payload()["supports_paused_handoff_resume"]
        is True
    )

    assert agibot["field_groups"] == ["common", "agibot", "agibot_gates"]
    assert "context_json" in agibot["required_overrides"]
    assert "grounding" in agibot["view_modes"]

    assert b1_openai_agents["world_id"] == "b1-map12"
    assert b1_openai_agents["backend_id"] == "isaaclab"
    assert b1_openai_agents["agent_engine_id"] == "openai-agents-sdk"
    assert b1_openai_agents["provider_profile"] == "codex-router-responses"
    assert b1_openai_agents["required_overrides"] == []
    assert [gate["id"] for gate in b1_openai_agents["gates"]] == [
        "provider_key",
        "mcp_port_free",
    ]
    assert b1_openai_agents["field_groups"] == ["common"]
    assert not any(
        item.startswith("b1_alignment_artifact=")
        for item in b1_openai_agents["launch_default_overrides"]
    )
    assert not any(
        item.startswith("b1_navigation_artifact=")
        for item in b1_openai_agents["launch_default_overrides"]
    )
    assert b1_openai_agents["supports_relative_navigation_control"] is True
    assert b1_openai_agents["supports_paused_handoff_resume"] is True
    assert "agent_engine=openai-agents-sdk" in b1_openai_agents["argv_preview"]


def test_prompt_gating_uses_argv_element_not_shell_joining(tmp_path) -> None:
    selection = get_selection(MUJOCO_OPENAI_AGENTS_OPEN_TASK)
    argv = build_launch_argv(
        selection,
        root=tmp_path,
        run_id="run-1",
        prompt="collect mugs; rm -rf / should stay text",
    )

    assert argv[:6] == [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-objaverse-val/0",
        "backend=mujoco",
        "agent_engine=openai-agents-sdk",
    ]
    assert "evidence_lane=world-public-labels" in argv
    assert "provider_profile=codex-router-responses" in argv
    assert "scenario_setup=baseline" in argv
    assert "prompt=collect mugs; rm -rf / should stay text" in argv


def test_map_build_launch_defaults_to_baseline_scenario_setup(tmp_path) -> None:
    selection = get_selection(MUJOCO_DIRECT_MAP_BUILD)
    argv = build_launch_argv(selection, root=tmp_path, run_id="run-1")

    assert "preset=map-build" in argv
    assert "scenario_setup=baseline" in argv
    assert not any(item.startswith("relocation_count=") for item in argv)
    assert not any(item.startswith("generated_mess_count=") for item in argv)


def test_camera_grounded_lane_launch_includes_default_camera_labeler(tmp_path) -> None:
    selection = get_selection(
        "molmospaces/procthor-objaverse-val/0::mujoco::map-build::direct-runner::camera-grounded-labels"
    )
    argv = build_launch_argv(selection, root=tmp_path, run_id="run-1")

    assert "evidence_lane=camera-grounded-labels" in argv
    assert "camera_labeler=grounding-dino" in argv


def test_b1_map12_open_ended_launch_uses_scene_and_map_bundle(tmp_path) -> None:
    alignment_artifact = tmp_path / "alignment_residuals.json"
    navigation_artifact = tmp_path / "navigation_smoke.json"
    selection = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)
    argv = build_launch_argv(
        selection,
        root=tmp_path,
        run_id="run-1",
        overrides={
            "b1_alignment_artifact": str(alignment_artifact),
            "b1_navigation_artifact": str(navigation_artifact),
        },
    )

    assert not any(item.startswith("intent=") for item in argv)
    assert not any(item.startswith("preset=") for item in argv)
    assert "agent_engine=openai-agents-sdk" in argv
    assert "backend=isaaclab" in argv
    assert "scenario_setup=baseline" in argv
    assert "map_bundle=vendors/agibot_sdk/artifacts/maps/robot_map_12/agibot" in argv
    assert "robot_views=on" in argv
    assert (
        "isaac_scene_usd_path=data/robot-data-lab/scene-engine/data/"
        "B1_floor2_slow/usda/F2_all/default.usda"
    ) in argv
    assert f"b1_alignment_artifact={alignment_artifact}" in argv
    assert f"b1_navigation_artifact={navigation_artifact}" in argv
    assert not any(item.startswith("relocation_count=") for item in argv)


def test_b1_map12_launch_generates_robot_proof_artifacts_at_launch(tmp_path) -> None:
    selection = get_selection(B1_OPENAI_AGENTS_OPEN_TASK)

    argv = build_launch_argv(selection, root=tmp_path, run_id="run-1")

    assert not any(item.startswith("b1_alignment_artifact=") for item in argv)
    assert not any(item.startswith("b1_navigation_artifact=") for item in argv)


def test_prompt_rejected_for_unsupported_selection(tmp_path) -> None:
    selection = get_selection(AGIBOT_SDK_CLEANUP)
    with pytest.raises(ConsoleLaunchError, match="custom prompt"):
        build_launch_argv(selection, root=tmp_path, run_id="run-1", prompt="unsafe")


def _write_prior_catalog(
    path: Path,
    prior: Path,
    *,
    staleness: str = "compatible",
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "runtime_map_prior_catalog_v1",
                "entries": [
                    {
                        "id": "molmospaces/procthor-objaverse-val/0::mujoco",
                        "world_id": "molmospaces/procthor-objaverse-val/0",
                        "backend_id": "mujoco",
                        "path": str(prior),
                        "status": "accepted",
                        "staleness": staleness,
                        "source": "runtime_map_prior_selector",
                        "catalog_key": {
                            "world": "molmospaces/procthor-objaverse-val/0",
                            "backend": "mujoco",
                            "source_map_identity": "map-bundle-sha256:abc",
                            "scene_identity": "procthor-objaverse-val/0",
                        },
                        "selected_candidate_id": "candidate-1",
                        "run_id": "run-1",
                        "product_route": {"agent_engine": "openai-agents-sdk"},
                        "producer": {"provider_profile": "codex-router-responses"},
                        "evidence": ["hard_gates_passed"],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
