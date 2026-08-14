from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.task_intents import normalize_household_intent
from roboclaws.household import (
    realworld_contract_init,
    realworld_done_readiness,
    realworld_visual_candidates,
)
from roboclaws.household.household_backend_contract import HouseholdBackendSession
from roboclaws.household.household_runtime_artifacts import HouseholdRuntimeArtifactsMixin
from roboclaws.household.household_runtime_manipulation import HouseholdRuntimeManipulationMixin
from roboclaws.household.household_runtime_navigation import HouseholdRuntimeNavigationMixin
from roboclaws.household.household_runtime_perception import HouseholdRuntimePerceptionMixin
from roboclaws.household.household_runtime_support import (
    _assert_no_forbidden_agent_view_keys,
    _float_or_zero,
    _public_acceptance_config,
)
from roboclaws.household.household_runtime_support import (
    _declared_category_matches_object as _declared_category_matches_object,
)
from roboclaws.household.household_runtime_support import (
    cleanup_policy_trace_from_events as cleanup_policy_trace_from_events,
)
from roboclaws.household.household_runtime_support import (
    forbidden_agent_view_keys as forbidden_agent_view_keys,
)
from roboclaws.household.household_runtime_support import (
    infer_target_fixture_for_detection as infer_target_fixture_for_detection,
)
from roboclaws.household.household_runtime_support import (
    real_robot_readiness_from_events as real_robot_readiness_from_events,
)
from roboclaws.household.types import CleanupScenario
from roboclaws.household.visual_grounding import (
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    VisualGroundingClient,
)

REALWORLD_CONTRACT = "realworld_cleanup_v1"
REAL_ROBOT_MAP_BUNDLE_SCHEMA = "real_robot_map_bundle_v1"
RUNTIME_METRIC_MAP_SCHEMA = "runtime_metric_map_v1"
INSPECTION_OBSERVATION_SCHEMA = "target_inspection_observation_v1"
CLEANUP_WORKLIST_SCHEMA = "cleanup_worklist_v1"
CLEANUP_POLICY_TRACE_SCHEMA = "cleanup_policy_trace_v1"
REAL_ROBOT_READINESS_SCHEMA = "real_robot_readiness_v1"
DETERMINISTIC_SWEEP_POLICY = "deterministic_sweep_baseline"
DEFAULT_REALWORLD_TASK = "帮我收拾这个房间"
VISIBLE_OBJECT_DETECTIONS_MODE = "visible_object_detections"
RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
WORLD_LABELS_DETECTION_POLICY = "world_labels"
SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY = "sanitized_visible_object_detections"
VISIBLE_DETECTION_EXPOSURE_POLICIES = frozenset(
    (WORLD_LABELS_DETECTION_POLICY, SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY)
)
CAMERA_MODEL_POLICY_SCHEMA = "camera_model_policy_v1"
CAMERA_MODEL_POLICY_NAME = "camera_model_policy_baseline"
MODEL_DECLARED_OBSERVATION_SCHEMA = "model_declared_observation_v1"
MODEL_DECLARED_OBSERVATIONS_SCHEMA = "model_declared_observations_v1"
VISUAL_GROUNDING_EVIDENCE_SCHEMA = realworld_visual_candidates.VISUAL_GROUNDING_EVIDENCE_SCHEMA
DONE_READINESS_SCHEMA = "done_readiness_v1"
DONE_READINESS_POLICY_RAW_FPV = realworld_done_readiness.DONE_READINESS_POLICY_RAW_FPV
DONE_READINESS_POLICY_EXPLICIT = realworld_done_readiness.DONE_READINESS_POLICY_EXPLICIT
MODEL_DECLARED_OBSERVATION_SOURCE = "model_declared_observation"
MAIN_CLEANUP_AGENT_PRODUCER = realworld_visual_candidates.MAIN_CLEANUP_AGENT_PRODUCER
TEST_AGENT_PRODUCER = realworld_visual_candidates.TEST_AGENT_PRODUCER
SIMULATED_CAMERA_MODEL_PROVENANCE = realworld_visual_candidates.SIMULATED_CAMERA_MODEL_PROVENANCE
SANITIZED_VISIBLE_OBJECT_DETECTIONS_PROVENANCE = "sanitized_visible_object_detections"
WORLD_PUBLIC_LABELS_PROFILE = "world-public-labels"
_visual_candidates = realworld_visual_candidates
VISUAL_CANDIDATE_ALREADY_HANDLED_REASON = _visual_candidates.VISUAL_CANDIDATE_ALREADY_HANDLED_REASON
VISUAL_EVIDENCE_REVIEWABLE_STATUS = realworld_visual_candidates.VISUAL_EVIDENCE_REVIEWABLE_STATUS
VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS = _visual_candidates.VISUAL_EVIDENCE_NOT_REVIEWABLE_STATUS
CANDIDATE_STATE_SEMANTIC = realworld_visual_candidates.CANDIDATE_STATE_SEMANTIC
CANDIDATE_STATE_VISUALLY_CONFIRMED = realworld_visual_candidates.CANDIDATE_STATE_VISUALLY_CONFIRMED
CANDIDATE_STATE_NAVIGATION_AUTHORIZED = _visual_candidates.CANDIDATE_STATE_NAVIGATION_AUTHORIZED
VISUAL_GROUNDING_CATEGORY_HINTS = realworld_visual_candidates.VISUAL_GROUNDING_CATEGORY_HINTS
REALWORLD_PERCEPTION_MODES = frozenset(
    (VISIBLE_OBJECT_DETECTIONS_MODE, RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE)
)
_NON_ACTIONABLE_HANDLE_STATES = frozenset({"placed", "placed_closed", "skipped", "stale"})
_FORBIDDEN_AGENT_VIEW_KEYS = frozenset(
    {
        "generated_mess_set",
        "generated_mess_count",
        "environment_setup",
        "relocation_policy",
        "relocation_count",
        "relocated_object_ids",
        "relocated_objects",
        "before_relocation_positions",
        "after_relocation_positions",
        "target_count",
        "acceptable_destination_sets",
        "valid_receptacle_ids",
        "private_manifest",
        "is_misplaced",
        "global_movable_object_inventory",
        "target_receptacle_id",
    }
)


class HouseholdRuntimeContract(
    HouseholdRuntimeNavigationMixin,
    HouseholdRuntimeManipulationMixin,
    HouseholdRuntimeArtifactsMixin,
    HouseholdRuntimePerceptionMixin,
):
    """ADR-0003 public/private cleanup boundary.

    The backend session owns mutation and private scoring; this contract exposes
    metric navigation, static fixtures, and robot-local observed object handles.
    """

    def __init__(
        self,
        contract: HouseholdBackendSession,
        *,
        task_prompt: str = DEFAULT_REALWORLD_TASK,
        static_fixture_projection_mode: str = "room_only",
        perception_mode: str = VISIBLE_OBJECT_DETECTIONS_MODE,
        map_bundle_dir: str | Path | None = None,
        visual_grounding_client: VisualGroundingClient | None = None,
        visual_grounding_pipeline_id: str = SIM_VISUAL_GROUNDING_PIPELINE_ID,
        visual_grounding_artifact_base_dir: str | Path | None = None,
        visual_grounding_run_id: str = "",
        runtime_map_prior: dict[str, Any] | None = None,
        evidence_lane: str | None = None,
        public_acceptance_config: dict[str, Any] | None = None,
    ) -> None:
        realworld_contract_init.validate_contract_options(
            static_fixture_projection_mode, perception_mode, REALWORLD_PERCEPTION_MODES
        )
        self.contract = contract
        self.backend = contract.backend
        self.scenario: CleanupScenario = contract.backend.scenario
        self.task_prompt = task_prompt
        self.static_fixture_projection_mode = static_fixture_projection_mode
        self.perception_mode = perception_mode
        realworld_contract_init.init_profile_and_acceptance(
            self,
            evidence_lane,
            public_acceptance_config,
            acceptance_helpers=(_public_acceptance_config, normalize_household_intent),
            perception_values=(
                VISIBLE_OBJECT_DETECTIONS_MODE,
                RAW_FPV_ONLY_MODE,
                CAMERA_MODEL_POLICY_MODE,
            ),
            exposure_values=(
                WORLD_PUBLIC_LABELS_PROFILE,
                SANITIZED_VISIBLE_OBJECT_DETECTIONS_POLICY,
                WORLD_LABELS_DETECTION_POLICY,
            ),
        )
        realworld_contract_init.init_visual_grounding(
            self,
            visual_grounding_client=visual_grounding_client,
            visual_grounding_pipeline_id=visual_grounding_pipeline_id,
            visual_grounding_artifact_base_dir=visual_grounding_artifact_base_dir,
            visual_grounding_run_id=visual_grounding_run_id,
            default_pipeline_id=SIM_VISUAL_GROUNDING_PIPELINE_ID,
        )
        realworld_contract_init.init_map_projection(self, map_bundle_dir)
        realworld_contract_init.init_public_map_projection(self)
        self._current_waypoint_id = realworld_contract_init.initial_waypoint_id(self)
        realworld_contract_init.init_runtime_state(
            self,
            runtime_map_prior,
            snapshot_helpers=(_float_or_zero, _assert_no_forbidden_agent_view_keys),
        )
