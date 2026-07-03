"""Household task declarations."""

from __future__ import annotations

from roboclaws.household.profiles import cleanup_evidence_lane_names
from roboclaws.launch.environment_setup import (
    ENVIRONMENT_SETUP_BASELINE,
    ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
)
from roboclaws.launch.task_specs import TaskPresetSpec, TaskSurfaceSpec

HOUSEHOLD_EVIDENCE_LANES: tuple[str, ...] = cleanup_evidence_lane_names()

HOUSEHOLD_PRESET_SPECS: dict[str, TaskPresetSpec] = {
    "cleanup": TaskPresetSpec(
        preset_id="cleanup",
        intent_id="cleanup",
        skill_name="household-world",
        required_capabilities=(
            "household_world",
            "household_manipulation",
            "household_episode",
        ),
        default_scenario_setup=ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
        report_profile="cleanup",
        validation_gate_tags=("cleanup", "manipulation", "private-scorer-boundary"),
    ),
    "map-build": TaskPresetSpec(
        preset_id="map-build",
        intent_id="map-build",
        skill_name="household-world",
        required_capabilities=("household_world", "household_episode"),
        default_scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        report_profile="runtime_metric_map",
        validation_gate_tags=("map-build", "runtime-metric-map"),
    ),
}

HOUSEHOLD_TASK_SPECS: dict[str, TaskSurfaceSpec] = {
    "household-world": TaskSurfaceSpec(
        surface_id="household-world",
        domain="household",
        supported_dispatch_runners=(
            "direct",
            "mcp-smoke",
            "openai-agents-live",
            "openclaw",
        ),
        supported_intents=("cleanup", "map-build", "open-ended"),
        default_intent="open-ended",
        supported_reports=(),
        default_report=None,
        default_profile="world-public-labels",
        supported_profiles=HOUSEHOLD_EVIDENCE_LANES,
        default_backend="molmospaces_subprocess",
        mcp_server_id="molmo_cleanup_realworld",
        checker_base="household_world",
        required_capabilities=(
            "household_world",
            "household_episode",
        ),
        supported_presets=tuple(HOUSEHOLD_PRESET_SPECS),
    ),
    "planner-proof": TaskSurfaceSpec(
        surface_id="planner-proof",
        domain="household",
        supported_dispatch_runners=("direct", "mcp-smoke"),
        supported_intents=("planner-proof",),
        default_intent="planner-proof",
        supported_reports=("visual", "minimal"),
        default_report="visual",
        default_profile=None,
        supported_profiles=(),
        default_backend="molmospaces_subprocess",
        mcp_server_id="planner_proof",
        checker_base="planner_proof_report",
        required_capabilities=("planner_proof",),
    ),
}
