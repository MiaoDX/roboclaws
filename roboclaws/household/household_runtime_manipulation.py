from __future__ import annotations

from typing import Any

from roboclaws.household import (
    realworld_done_readiness,
)
from roboclaws.household.household_runtime_support import _assert_no_forbidden_agent_view_keys
from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.realworld_contract_fixture_projection import (
    _normalize_fixture_category_label,
    _public_destination_policy_for_category,
)
from roboclaws.household.semantic_acceptability import (
    annotate_score_with_semantic_acceptability,
)

REALWORLD_CONTRACT = "realworld_cleanup_v1"
RAW_FPV_ONLY_MODE = "raw_fpv_only"
DONE_READINESS_SCHEMA = "done_readiness_v1"


class HouseholdRuntimeManipulationMixin:
    def pick(self, object_id: str) -> dict[str, Any]:
        if self._handle_is_non_actionable(object_id):
            return self._error(
                "pick",
                "already_handled",
                object_id=object_id,
                required_next_tool="observe",
                recovery_hint=(
                    "This observed handle has already been handled. Continue the "
                    "waypoint sweep instead of picking it again."
                ),
            )
        internal_id = self._internal_object_id(object_id)
        if internal_id is None:
            grounding_error = self._unresolved_visual_candidate_error("pick", object_id)
            if grounding_error is not None:
                return grounding_error
            return self._error("pick", "stale_reference", object_id=object_id)
        visual_evidence_error = self._visual_evidence_actionability_error("pick", object_id)
        if visual_evidence_error is not None:
            return visual_evidence_error
        if getattr(self, "_current_object_handle", None) != object_id:
            return self._semantic_order_error(
                "pick",
                required_tool="navigate_to_object",
                object_id=object_id,
                recovery_hint=(
                    "Call navigate_to_object with this observed object handle before pick. "
                    "The ADR-0003 clean loop is navigate_to_object -> pick -> "
                    "navigate_to_receptacle -> open_receptacle? -> place/place_inside "
                    "-> close_receptacle?."
                ),
            )
        picked = self.contract.pick(internal_id)
        if picked.get("ok"):
            self._held_handle = object_id
            self._current_object_handle = None
            self._current_receptacle_for_handle = None
            self._opened_receptacle_for_handle = None
            self._set_handle_state(object_id, "held", tool="pick")
        result = self._public_manipulation_response("pick", object_id, picked)
        if picked.get("ok"):
            result.update(self._destination_policy_context(object_id))
            result["required_next_tool"] = "navigate_to_receptacle"
        return result

    def navigate_to_receptacle(self, fixture_id: str) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        if internal_fixture_id not in self._fixtures:
            recovery: dict[str, Any] = {}
            if self._held_handle is not None:
                recovery = {
                    "object_id": self._held_handle,
                    "required_tool": "navigate_to_receptacle",
                    "recovery_hint": (
                        "Choose candidate_fixture_id from destination_options; do not invent "
                        "or reuse non-public fixture ids."
                    ),
                    **self._destination_policy_context(self._held_handle),
                }
            return self._error(
                "navigate_to_receptacle",
                "stale_reference",
                fixture_id=requested_fixture_id,
                **recovery,
            )
        if self._held_handle is None:
            return self._semantic_order_error(
                "navigate_to_receptacle",
                required_tool="pick",
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Pick an observed object before navigating to a cleanup fixture. "
                    "Use navigate_to_object -> pick first."
                ),
            )
        destination_policy_error = self._destination_policy_error(
            self._held_handle,
            requested_fixture_id=requested_fixture_id,
            internal_fixture_id=internal_fixture_id,
        )
        if destination_policy_error is not None:
            return destination_policy_error
        response = self.contract.navigate_to_receptacle(internal_fixture_id)
        if not response.get("ok"):
            return self._public_error_from_private(
                "navigate_to_receptacle",
                self._held_handle or "",
                response,
            )
        self._current_waypoint_id = self._public_waypoint_id_for_private_fixture(
            internal_fixture_id
        )
        self._reset_camera_adjustment()
        self._current_receptacle_for_handle = (self._held_handle, internal_fixture_id)
        self._opened_receptacle_for_handle = None
        public_fixture_id = self._public_fixture_response_id(
            internal_fixture_id,
            requested_fixture_id,
        )
        return self._ok(
            "navigate_to_receptacle",
            object_id=self._held_handle,
            receptacle_id=public_fixture_id,
            fixture_id=public_fixture_id,
            navigation_backend=response.get("navigation_backend", API_SEMANTIC_PROVENANCE),
            primitive_provenance=response.get(
                "primitive_provenance",
                API_SEMANTIC_PROVENANCE,
            ),
            goal_pose=self._fixture_pose(internal_fixture_id),
            pose_source="static_fixture_projection",
            staleness_s=0.0,
            pose_confidence=1.0,
            pose_covariance=[0.0, 0.0, 0.0],
            requires_reobserve=False,
            previous_receptacle_id=self._public_fixture_reference_id(
                str(response.get("previous_receptacle_id") or "")
            ),
            state_mutation=response.get("state_mutation"),
            navigation_status=response.get("status"),
        )

    def _destination_policy_error(
        self,
        handle: str,
        *,
        requested_fixture_id: str,
        internal_fixture_id: str,
    ) -> dict[str, Any] | None:
        context = self._destination_policy_context(handle)
        policy = context["destination_policy"]
        allowed_categories = {
            _normalize_fixture_category_label(item)
            for item in policy.get("acceptable_fixture_categories") or []
        }
        fixture = self._fixtures.get(internal_fixture_id) or {}
        requested_category = _normalize_fixture_category_label(
            fixture.get("category") or fixture.get("name")
        )
        if requested_category in allowed_categories:
            return None
        return self._error(
            "navigate_to_receptacle",
            "destination_policy_mismatch",
            object_id=handle,
            fixture_id=requested_fixture_id,
            receptacle_id=requested_fixture_id,
            fixture_category=requested_category,
            destination_policy=policy,
            destination_options=context["destination_options"],
            required_tool="navigate_to_receptacle",
            recovery_hint=(
                "Choose candidate_fixture_id from destination_options. The requested fixture "
                "category is not allowed by this object's public destination policy."
            ),
        )

    def _destination_policy_context(self, handle: str) -> dict[str, Any]:
        detection = self._detections_by_handle.get(handle) or {}
        policy = _public_destination_policy_for_category(detection.get("category"))
        return {
            "destination_policy": policy,
            "destination_options": realworld_done_readiness.destination_options_for_policy(
                self,
                policy,
            ),
        }

    def open_receptacle(self, fixture_id: str) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        if internal_fixture_id not in self._fixtures:
            return self._error(
                "open_receptacle",
                "stale_reference",
                fixture_id=requested_fixture_id,
            )
        if self._held_handle is None:
            return self._semantic_order_error(
                "open_receptacle",
                required_tool="pick",
                fixture_id=requested_fixture_id,
                recovery_hint="Pick an observed object before opening a cleanup fixture.",
            )
        if self._current_receptacle_for_handle != (self._held_handle, internal_fixture_id):
            return self._semantic_order_error(
                "open_receptacle",
                required_tool="navigate_to_receptacle",
                object_id=self._held_handle,
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Call navigate_to_receptacle for this fixture before open_receptacle. "
                    "Fridge-like cleanup must be nav -> open -> place_inside -> close."
                ),
            )
        opened = self.contract.open_receptacle(internal_fixture_id)
        if opened.get("ok"):
            self._opened_receptacle_for_handle = (self._held_handle, internal_fixture_id)
        return self._public_fixture_response(
            "open_receptacle",
            self._public_fixture_response_id(internal_fixture_id, requested_fixture_id),
            opened,
        )

    def place(self, fixture_id: str) -> dict[str, Any]:
        return self._place(fixture_id, inside=False)

    def place_inside(self, fixture_id: str) -> dict[str, Any]:
        return self._place(fixture_id, inside=True)

    def close_receptacle(self, fixture_id: str) -> dict[str, Any]:
        requested_fixture_id = str(fixture_id)
        internal_fixture_id = self._internal_fixture_id_for_public_anchor(requested_fixture_id)
        if internal_fixture_id not in self._fixtures:
            return self._error(
                "close_receptacle", "stale_reference", fixture_id=requested_fixture_id
            )
        pending = self._pending_close_receptacle_for_handle
        if pending is None or pending[1] != internal_fixture_id:
            return self._semantic_order_error(
                "close_receptacle",
                required_tool="place_inside",
                object_id=pending[0] if pending is not None else None,
                fixture_id=requested_fixture_id,
                recovery_hint=(
                    "Call close_receptacle only after place_inside for the same fridge-like "
                    "fixture."
                ),
            )
        handle, _ = pending
        closed = self.contract.close_receptacle(internal_fixture_id)
        public_fixture_id = self._public_fixture_response_id(
            internal_fixture_id,
            requested_fixture_id,
        )
        if closed.get("ok"):
            self._pending_close_receptacle_for_handle = None
            self._set_handle_state(
                handle,
                "placed_closed",
                tool="close_receptacle",
                fixture_id=public_fixture_id,
            )
        return self._public_fixture_response(
            "close_receptacle",
            public_fixture_id,
            closed,
            object_id=handle,
        )

    def done(
        self,
        reason: str = "",
        *,
        semantic_cleanup_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        readiness = self.evaluate_done_readiness(
            semantic_cleanup_evidence=semantic_cleanup_evidence,
        )
        done = self.contract.done(reason=reason)
        if not done.get("ok"):
            return done
        score = annotate_score_with_semantic_acceptability(done["score"], self.scenario)
        final_locations = dict(done["final_locations"])
        metrics = self._realworld_metrics(score, final_locations)
        score.update(metrics)
        response = self._ok(
            "done",
            reason=reason,
            cleanup_status=metrics["completion_status"],
            score=score,
            final_locations=final_locations,
            final_containment=done.get("final_containment", {}),
            tool_event_counts=done.get("tool_event_counts", {}),
            contract=REALWORLD_CONTRACT,
            policy_uses_private_truth=False,
        )
        if readiness["status"] == "blocked":
            blocked = self._done_readiness_blocked_response(readiness)
            blocked.update(
                cleanup_status="incomplete",
                score=score,
                final_locations=final_locations,
                final_containment=done.get("final_containment", {}),
                tool_event_counts=done.get("tool_event_counts", {}),
                terminal=True,
            )
            return blocked
        return response

    def evaluate_done_readiness(
        self,
        *,
        semantic_cleanup_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return realworld_done_readiness.evaluate_done_readiness(
            self,
            semantic_cleanup_evidence=semantic_cleanup_evidence,
            schema=DONE_READINESS_SCHEMA,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _done_readiness_blocked_response(self, readiness: dict[str, Any]) -> dict[str, Any]:
        return realworld_done_readiness.done_readiness_blocked_response(
            readiness,
            schema=DONE_READINESS_SCHEMA,
            error_builder=self._error,
        )

    def _required_model_declared_observations(self) -> int:
        return realworld_done_readiness.required_model_declared_observations(self)

    def _grounded_cleanup_chain_blocker(
        self,
        semantic_cleanup_evidence: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return realworld_done_readiness.grounded_cleanup_chain_blocker(
            self,
            semantic_cleanup_evidence,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
            assert_no_forbidden_agent_view_keys=_assert_no_forbidden_agent_view_keys,
        )

    def _grounded_cleanup_chain_requirement(self) -> tuple[int, str]:
        return realworld_done_readiness.grounded_cleanup_chain_requirement(
            self,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
        )

    def _grounded_cleanup_chain_required_tool(self) -> str:
        return realworld_done_readiness.grounded_cleanup_chain_required_tool(
            self.perception_mode,
            raw_fpv_only_mode=RAW_FPV_ONLY_MODE,
        )

    def _grounded_cleanup_chain_recovery_hint(self, required_tool: str) -> str:
        return realworld_done_readiness.grounded_cleanup_chain_recovery_hint(required_tool)
