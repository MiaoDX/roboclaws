"""Isaac Lab worker runtime composition."""

from __future__ import annotations

# This module is the typed dependency vocabulary imported by the behavior owners.
# ruff: noqa: F401
import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from PIL import Image

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


from roboclaws.backends.isaaclab import (
    isaac_camera_capture,
    isaac_camera_geometry,
    isaac_capture_quality,
    isaac_mapping_diagnostics,
    isaac_placement_resolution,
    isaac_render_diagnostics,
    isaac_robot_camera_stage,
    isaac_robot_import,
    isaac_robot_pose_focus,
    isaac_robot_view_artifacts,
    isaac_runtime_capture,
    isaac_runtime_diagnostics,
    isaac_runtime_smoke_usd,
    isaac_scenario_builders,
    isaac_scenario_state,
    isaac_scene_bindings,
    isaac_scene_camera_capture,
    isaac_scene_camera_geometry,
    isaac_scene_index_geometry,
    isaac_scene_index_metadata,
    isaac_segmentation_diagnostics,
    isaac_semantic_labels,
    isaac_semantic_pose_projection,
    isaac_semantic_pose_robot_view,
    isaac_semantic_pose_stage,
    isaac_semantic_pose_state,
    isaac_stage_lighting,
    isaac_support_surface_geometry,
    isaac_usd_xform,
    isaac_worker_cli,
    isaac_worker_commands,
    isaac_worker_context,
    isaac_worker_outputs,
    isaac_worker_protocol,
    isaac_worker_state,
)
from roboclaws.household.backend import HELD_LOCATION_ID
from roboclaws.household.camera_control import (
    DEFAULT_SCENE_PROBE_LIGHTING_PROFILE,
    normalize_camera_control_request,
)
from roboclaws.household.isaac_lab_backend import (
    ISAAC_SEMANTIC_POSE_EVENT_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SCHEMA,
    ISAAC_SEMANTIC_POSE_STATE_SOURCE,
)
from roboclaws.household.manipulation_contract import ISAAC_SEMANTIC_POSE_PROVENANCE
from roboclaws.household.types import CleanupScenario

STATE_SCHEMA = "isaac_lab_backend_state_v1"

DEFAULT_WIDTH = 540

DEFAULT_HEIGHT = 360

ROBOT_VIEW_KEYS = ("fpv", "chase", "topdown", "verify")

SCENE_BINDING_SCHEMA = isaac_scene_bindings.SCENE_BINDING_SCHEMA

_bind_public_scene_item = isaac_scene_bindings.bind_public_scene_item

_scene_binding_diagnostics = isaac_scene_bindings.scene_binding_diagnostics

_scene_index_match = isaac_scene_bindings.scene_index_match

_authored_reference_asset_paths = isaac_scene_index_geometry.authored_reference_asset_paths

_fallback_room_outlines_from_indices = (
    isaac_scene_index_geometry.fallback_room_outlines_from_indices
)

_is_local_reference_asset_path = isaac_scene_index_geometry.is_local_reference_asset_path

_local_reference_asset_missing = isaac_scene_index_geometry.local_reference_asset_missing

_room_outlines_from_scene_index_diagnostics = (
    isaac_scene_index_geometry.room_outlines_from_scene_index_diagnostics
)

_round_vec3 = isaac_scene_index_geometry.round_vec3

_usd_list_op_items = isaac_scene_index_geometry.usd_list_op_items

_category_from_usd_name = isaac_scene_index_metadata.category_from_usd_name

_contains_child_segment = isaac_scene_index_metadata.contains_child_segment

_is_molmospaces_object_metadata = isaac_scene_index_metadata.is_molmospaces_object_metadata

_is_molmospaces_receptacle_metadata = isaac_scene_index_metadata.is_molmospaces_receptacle_metadata

_is_object_prim_path = isaac_scene_index_metadata.is_object_prim_path

_is_receptacle_prim_path = isaac_scene_index_metadata.is_receptacle_prim_path

_load_molmospaces_scene_metadata = isaac_scene_index_metadata.load_molmospaces_scene_metadata

_merge_molmospaces_metadata_index = isaac_scene_index_metadata.merge_molmospaces_metadata_index

_metadata_room_id = isaac_scene_index_metadata.metadata_room_id

_molmospaces_metadata_prim_path = isaac_scene_index_metadata.molmospaces_metadata_prim_path

_molmospaces_prim_path_rank = isaac_scene_index_metadata.molmospaces_prim_path_rank

_usd_handle_from_prim = isaac_scene_index_metadata.usd_handle_from_prim

_usd_index_entry = isaac_scene_index_metadata.usd_index_entry

_usd_metadata_index_entry = isaac_scene_index_metadata.usd_metadata_index_entry

_usd_safe_name = isaac_scene_index_metadata.usd_safe_name

_MOLMOSPACES_SCENE_INDEX_RECEPTACLE_CATEGORY_NORMS = (
    isaac_scene_index_metadata.MOLMOSPACES_SCENE_INDEX_RECEPTACLE_CATEGORY_NORMS
)

_is_usd_renderable_support_candidate = (
    isaac_support_surface_geometry.is_usd_renderable_support_candidate
)

_support_pose_from_support_surface = (
    isaac_support_surface_geometry.support_pose_from_support_surface
)

_support_pose_from_usd_bounds = isaac_support_surface_geometry.support_pose_from_usd_bounds

_support_surface_from_usd_bounds = isaac_support_surface_geometry.support_surface_from_usd_bounds

_usd_support_surface_score = isaac_support_surface_geometry.usd_support_surface_score

_usd_support_surface_union = isaac_support_surface_geometry.usd_support_surface_union_entry

SEGMENTATION_SCHEMA = isaac_segmentation_diagnostics.SEGMENTATION_SCHEMA

ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA = (
    isaac_render_diagnostics.ISAAC_NATIVE_RENDER_DIAGNOSTICS_SCHEMA
)

ISAAC_SEGMENTATION_DATA_TYPES = isaac_segmentation_diagnostics.ISAAC_SEGMENTATION_DATA_TYPES

MAX_SEGMENTATION_CANDIDATES = isaac_segmentation_diagnostics.MAX_SEGMENTATION_CANDIDATES

RBY1M_CHASE_CAMERA_OFFSET_M = isaac_camera_geometry.RBY1M_CHASE_CAMERA_OFFSET_M

RBY1M_CHASE_CAMERA_TARGET_OFFSET_M = isaac_camera_geometry.RBY1M_CHASE_CAMERA_TARGET_OFFSET_M

RBY1M_HEAD_CAMERA_ZERO_QUAT_WXYZ = isaac_camera_geometry.RBY1M_HEAD_CAMERA_ZERO_QUAT_WXYZ

RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG = isaac_camera_geometry.RBY1M_HEAD_CAMERA_VERTICAL_FOV_DEG

RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM = isaac_camera_geometry.RBY1M_HEAD_CAMERA_FOCAL_LENGTH_MM

REAL_SMOKE_CAPTURE_METHOD = "isaac_lab_camera_rgb"

REAL_ROBOT_VIEW_CAPTURE_METHOD = "isaac_lab_camera_rgb_static_robot_views"

REAL_ROBOT_VIEW_RERENDER_METHOD = "isaac_lab_camera_rgb_semantic_pose_robot_views"

REAL_SMOKE_RENDERER_MODE = "isaac_lab_headless_rtx"

PLACEMENT_DIAGNOSTIC_SCHEMA = isaac_placement_resolution.PLACEMENT_DIAGNOSTIC_SCHEMA

ISAAC_PLACEMENT_RESOLVER_SOURCE = isaac_placement_resolution.ISAAC_PLACEMENT_RESOLVER_SOURCE

ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE = (
    isaac_support_surface_geometry.ISAAC_DESCENDANT_SUPPORT_SURFACE_SOURCE
)

ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE = (
    isaac_support_surface_geometry.ISAAC_DESCENDANT_SUPPORT_SURFACE_UNION_SOURCE
)

ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE = (
    isaac_support_surface_geometry.ISAAC_WORLD_BOUNDS_SUPPORT_SURFACE_SOURCE
)

ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA = isaac_robot_import.ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA

_DEFERRED_SIMULATION_APP: list[Any | None] = [None]

_current_stage_bounds = isaac_stage_lighting.current_stage_bounds

_ensure_capture_lighting = isaac_stage_lighting.ensure_capture_lighting

_normalized_vec3 = isaac_stage_lighting.normalized_vec3

_isaac_distant_light_rotation_from_direction = (
    isaac_stage_lighting.isaac_distant_light_rotation_from_direction
)

_scale_stage_light_intensities = isaac_stage_lighting.scale_stage_light_intensities

_stage_light_paths = isaac_stage_lighting.stage_light_paths

_prim_type_is_light = isaac_stage_lighting.prim_type_is_light

_robot_view_color_profile = isaac_camera_geometry.robot_view_color_profile

_isaac_camera_view_poses = isaac_camera_geometry.isaac_camera_view_poses

_robot_relative_chase_eye_target = isaac_camera_geometry.robot_relative_chase_eye_target

_static_head_camera_pose_for_pitch = isaac_camera_geometry.static_head_camera_pose_for_pitch

_rotate_point_y_about_pivot = isaac_camera_geometry.rotate_point_y_about_pivot

_quat_from_axis_angle = isaac_camera_geometry.quat_from_axis_angle

_quat_multiply = isaac_camera_geometry.quat_multiply

_normalize_quat = isaac_camera_geometry.normalize_quat

_usd_camera_fov_metadata = isaac_camera_geometry.usd_camera_fov_metadata

_matrix4d_rowmajor = isaac_camera_geometry.matrix4d_rowmajor

_usd_attr_float = isaac_camera_geometry.usd_attr_float

_usd_vec = isaac_camera_geometry.usd_vec

_tensor_first_vec3 = isaac_camera_geometry.tensor_first_vec3

_robot_pose_yaw_deg = isaac_camera_geometry.robot_pose_yaw_deg

_optional_float = isaac_camera_geometry.optional_float

_load_camera_view_specs = isaac_scene_camera_geometry.load_camera_view_specs

_lane_camera_orbit = isaac_scene_camera_geometry.lane_camera_orbit

_backend_transform_for_lane = isaac_scene_camera_geometry.backend_transform_for_lane

_apply_scene_transform_to_point = isaac_scene_camera_geometry.apply_scene_transform_to_point

_camera_vec3 = isaac_scene_camera_geometry.camera_vec3

_image_has_variance = isaac_scene_camera_geometry.image_has_variance

_module_version = isaac_runtime_diagnostics.module_version

_generated_scene_filename = isaac_runtime_smoke_usd.generated_scene_filename

_isaac_native_render_diagnostics_unavailable = (
    isaac_render_diagnostics.native_render_diagnostics_unavailable
)

_native_setting_candidate_count = isaac_render_diagnostics.native_setting_candidate_count

_capture_quality_settings_unavailable = (
    isaac_render_diagnostics.capture_quality_settings_unavailable
)

_capture_quality_settings = isaac_render_diagnostics.capture_quality_settings

_isaac_setting_value = isaac_render_diagnostics.isaac_setting_value

_camera_render_product_paths = isaac_render_diagnostics.camera_render_product_paths

_render_product_paths_from_value = isaac_render_diagnostics.render_product_paths_from_value

_restore_isaac_capture_quality_overrides = (
    isaac_capture_quality.restore_isaac_capture_quality_overrides
)

_semantic_label_application_not_requested = (
    isaac_semantic_labels.semantic_label_application_not_requested
)

_semantic_label_target_prims = isaac_semantic_labels.semantic_label_target_prims

_set_usd_xform_translate = isaac_usd_xform.set_usd_xform_translate

_norm = isaac_worker_context.norm

_dict = isaac_worker_context.dict_value

_vec3 = isaac_worker_context.vec3

_has_xy = isaac_worker_context.has_xy

_index_or_default = isaac_worker_context.index_or_default

_objects_by_id = isaac_worker_context.objects_by_id

_receptacles_by_id = isaac_worker_context.receptacles_by_id

_object_index = isaac_worker_context.object_index

_receptacle_index = isaac_worker_context.receptacle_index

_pose_near = isaac_worker_context.pose_near

ISAAC_RBY1M_ROBOT_USD_PATH = isaac_robot_import.ISAAC_RBY1M_ROBOT_USD_PATH

ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH = isaac_robot_import.ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH
