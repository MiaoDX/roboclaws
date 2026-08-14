from __future__ import annotations

from pathlib import Path

import pytest

LOCAL_ASSET_MODULES = {
    # These validate private B1 / Agibot map exports or robot-data-lab scene
    # assets that are present on local workstations but not in GitHub checkout.
    "test_b1_map12_alignment_fit_cli.py",
    "test_b1_map12_base_metric_map.py",
    "test_b1_map12_base_metric_sidecar.py",
    "test_b1_map12_correspondence_review_cli.py",
    "test_b1_map12_label_tool.py",
    "test_b1_map12_manual_alignment_overlay_cli.py",
    "test_b1_scene_topdown_diagnostic.py",
    "test_molmospaces_source_pin.py",
}

LOCAL_ASSET_MODULE_PREFIXES = ("test_b1_map12_verified_alignment_",)

LOCAL_ASSET_TESTS = {
    "test_agibot_map_context_scripts_misc.py": {
        "test_agibot_nav_json_artifact_source_rejects_invalid_payloads",
        "test_agibot_nav_raw_map_source_rejects_malformed_gzip_json",
        "test_agibot_nav_raw_map_source_rejects_non_object_gzip_json",
        "test_agibot_nav_raw_map_source_rejects_plain_json_file",
    },
    "test_base_waypoint_builder.py": {
        "test_base_waypoint_builder_preserves_b1_map12_waypoints",
    },
    "test_cleanup_validation_runtime.py": {
        "test_checker_accepts_b1_robot_consumption_proof_without_rby1m_readiness",
        "test_checker_rejects_b1_robot_consumption_manifest_drift",
        "test_checker_rejects_b1_robot_consumption_without_manifest",
        "test_checker_rejects_b1_robot_consumption_without_verified_navigation",
    },
    "test_cross_environment_semantic_map_parity.py": {
        "test_b1_uses_dt_room_reference_and_alignment_correspondence_manifest",
    },
    "test_nav2_map_bundle_contract.py": {
        "test_base_metric_map_v1_validation_accepts_b1_bundle",
        "test_base_metric_map_v1_validation_rejects_contract_violations",
    },
    "test_scene_room_semantic_overlay.py": {
        "test_b1_base_metric_map_materializes_review_labels_without_retargeting_map",
    },
}

SLOW_MODULES = {
    # CI-safe but too expensive for commit-time scoped hooks.
    "test_molmospaces_realworld_cleanup.py",
}

SLOW_MODULE_PREFIXES = (
    "test_household_mcp_server_",
    "test_isaac_lab_backend_",
    "test_household_runtime_contract_",
)

SLOW_TESTS = {
    "test_molmo_mcp_smoke_shared_semantic_loop.py": {
        "test_realworld_mcp_smoke_uses_shared_fixture_style_semantic_loop",
    },
    "test_molmo_realworld_mcp_smoke_artifacts.py": {
        "test_realworld_mcp_smoke_writes_agent_artifacts",
    },
}

LAYER_DIRS = ("local", "slow", "contract", "unit")

CONTRACT_NAME_PARTS = (
    "appliance",
    "artifact",
    "bridge",
    "check_",
    "coding_agent",
    "contract",
    "harness",
    "just_recipes",
    "mcp",
    "realworld",
    "replay",
    "report",
    "transcript",
    "verify_",
)

EXPLICIT_LAYER_MARKERS = ("local", "slow", "contract", "unit")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        layer = _layer_for_item(item)
        item.add_marker(getattr(pytest.mark, layer))
        if _is_slow_item(item):
            item.add_marker(pytest.mark.slow)


def _layer_for_item(item: pytest.Item) -> str:
    for marker_name in EXPLICIT_LAYER_MARKERS:
        if any(item.iter_markers(marker_name)):
            return marker_name

    path = Path(str(item.path))
    filename = path.name
    stem = filename.removeprefix("test_").removesuffix(".py")

    if filename in LOCAL_ASSET_MODULES or filename.startswith(LOCAL_ASSET_MODULE_PREFIXES):
        return "local"
    if item.name.split("[", 1)[0] in LOCAL_ASSET_TESTS.get(filename, set()):
        return "local"
    directory_layer = _directory_layer(item, path)
    if directory_layer:
        return directory_layer
    if any(part in stem for part in CONTRACT_NAME_PARTS):
        return "contract"
    return "unit"


def _directory_layer(item: pytest.Item, path: Path) -> str:
    try:
        relative_parts = path.relative_to(Path(str(item.config.rootpath)) / "tests").parts
    except ValueError:
        return ""
    if relative_parts and relative_parts[0] in LAYER_DIRS:
        return relative_parts[0]
    return ""


def _is_slow_item(item: pytest.Item) -> bool:
    filename = Path(str(item.path)).name
    if filename in SLOW_MODULES or filename.startswith(SLOW_MODULE_PREFIXES):
        return True
    return item.name.split("[", 1)[0] in SLOW_TESTS.get(filename, set())
