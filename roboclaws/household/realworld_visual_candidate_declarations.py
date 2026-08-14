from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roboclaws.household.household_runtime_contract import HouseholdRuntimeContract

from roboclaws.core.raw_fpv_guidance import (
    raw_fpv_visual_candidate_recovery,
    raw_fpv_visual_candidate_recovery_hint,
)
from roboclaws.household import (
    realworld_runtime_map_targets,
    realworld_visual_candidate_lifecycle,
    realworld_visual_candidates,
    realworld_visual_perception_navigation,
)
from roboclaws.household.household_backend_contract import SYNTHETIC_BACKEND
from roboclaws.household.visual_grounding import (
    EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
    SIM_VISUAL_GROUNDING_PIPELINE_ID,
    VisualGroundingContractError,
    image_payload_for_raw_observation,
    pipeline_summary_from_response,
    sim_visual_grounding_pipeline,
    visual_grounding_failure_response,
    visual_grounding_request,
)

RAW_FPV_ONLY_MODE = "raw_fpv_only"
CAMERA_MODEL_POLICY_MODE = "camera_model_policy"
REALWORLD_CONTRACT = "realworld_cleanup_v1"
CAMERA_MODEL_POLICY_NAME = "camera_model_policy_baseline"
SIMULATED_CAMERA_MODEL_PROVENANCE = realworld_visual_candidates.SIMULATED_CAMERA_MODEL_PROVENANCE
_manual_visual_grounding_pipeline = realworld_visual_candidates._manual_visual_grounding_pipeline


def declare_visual_candidates(
    contract: HouseholdRuntimeContract,
    observation_id: str | None = None,
    *,
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    producer_type: str = SIMULATED_CAMERA_MODEL_PROVENANCE,
    producer_id: str = CAMERA_MODEL_POLICY_NAME,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    if contract.perception_mode not in {RAW_FPV_ONLY_MODE, CAMERA_MODEL_POLICY_MODE}:
        return contract._error(
            "declare_visual_candidates",
            "unsupported_perception_mode",
            perception_mode=contract.perception_mode,
        )
    raw_observation = contract._raw_fpv_observation_by_id(observation_id)
    if raw_observation is None:
        return contract._error(
            "declare_visual_candidates",
            "missing_raw_fpv_observation",
            observation_id=observation_id or "",
        )
    waypoint = contract._waypoint_by_id(str(raw_observation["waypoint_id"]))
    if waypoint is None:
        return contract._error(
            "declare_visual_candidates",
            "missing_waypoint",
            observation_id=str(raw_observation["observation_id"]),
        )

    declaration_inputs = _visual_candidate_declaration_inputs(
        contract,
        raw_observation=raw_observation,
        producer_type=producer_type,
        producer_id=producer_id,
        waypoint=waypoint,
        candidates=candidates,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    if response := declaration_inputs.get("response"):
        return response

    declarations = _registered_visual_candidate_declarations(
        contract,
        raw_observation=raw_observation,
        waypoint=waypoint,
        candidate_inputs=declaration_inputs["candidate_inputs"],
        producer_type=str(declaration_inputs["producer_type"]),
        producer_id=str(declaration_inputs["producer_id"]),
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    if response := declarations.get("response"):
        return response

    return _visual_candidate_declaration_response(
        contract,
        raw_observation=raw_observation,
        declared=declarations["declared"],
        producer_type=str(declaration_inputs["producer_type"]),
        producer_id=str(declaration_inputs["producer_id"]),
        visual_grounding_pipeline=declaration_inputs["visual_grounding_pipeline"],
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )


def _visual_candidate_declaration_inputs(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    waypoint: dict[str, Any],
    candidates: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    producer_type: str,
    producer_id: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None,
) -> dict[str, Any]:
    candidate_inputs = list(candidates or [])
    if candidate_inputs:
        return {
            "candidate_inputs": candidate_inputs,
            "producer_type": producer_type,
            "producer_id": producer_id,
            "visual_grounding_pipeline": _manual_visual_grounding_pipeline(
                candidate_count=len(candidate_inputs),
                producer_type=producer_type,
                producer_id=producer_id,
            ),
        }
    if contract.perception_mode == RAW_FPV_ONLY_MODE:
        return {
            "response": contract._error(
                "declare_visual_candidates",
                "empty_raw_fpv_candidate_registration",
                observation_id=str(raw_observation["observation_id"]),
                recovery_hint=(
                    "In camera-raw-fpv mode, call navigate_to_visual_candidate with one "
                    "explicit candidate when acting on public FPV evidence. Empty "
                    "candidate registration is reserved for camera-grounded-labels producers."
                ),
            )
        }

    producer_result = camera_label_producer_candidates(
        contract,
        raw_observation=raw_observation,
        waypoint=waypoint,
        assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
    )
    return _declaration_inputs_from_camera_label_producer(
        contract,
        raw_observation=raw_observation,
        producer_result=producer_result,
    )


def _declaration_inputs_from_camera_label_producer(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    producer_result: dict[str, Any],
) -> dict[str, Any]:
    visual_grounding_pipeline = producer_result["visual_grounding_pipeline"]
    if not producer_result["ok"]:
        return {
            "response": contract._error(
                "declare_visual_candidates",
                str(producer_result["error_reason"]),
                observation_id=str(raw_observation["observation_id"]),
                visual_grounding_pipeline=visual_grounding_pipeline,
                recovery_hint=producer_result.get("recovery_hint", ""),
            )
        }
    if visual_grounding_pipeline.get("status") == "failed":
        return {
            "response": _failed_visual_grounding_declaration_response(
                contract,
                raw_observation=raw_observation,
                visual_grounding_pipeline=visual_grounding_pipeline,
            )
        }

    producer_type = SIMULATED_CAMERA_MODEL_PROVENANCE
    producer_id = CAMERA_MODEL_POLICY_NAME
    if contract.visual_grounding_pipeline_id != SIM_VISUAL_GROUNDING_PIPELINE_ID:
        producer_type = EXTERNAL_VISUAL_GROUNDING_PROVENANCE
        producer_id = contract.visual_grounding_pipeline_id
    return {
        "candidate_inputs": list(producer_result["candidates"]),
        "producer_type": producer_type,
        "producer_id": producer_id,
        "visual_grounding_pipeline": visual_grounding_pipeline,
    }


def _failed_visual_grounding_declaration_response(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    visual_grounding_pipeline: dict[str, Any],
) -> dict[str, Any]:
    evidence = model_declared_observation_event(
        contract,
        raw_observation=raw_observation,
        producer_type=EXTERNAL_VISUAL_GROUNDING_PROVENANCE,
        producer_id=contract.visual_grounding_pipeline_id,
        declared=[],
        visual_grounding_pipeline=visual_grounding_pipeline,
    )
    contract._camera_model_policy_events.append(evidence)
    return contract._ok(
        "declare_visual_candidates",
        contract=REALWORLD_CONTRACT,
        model_declared_observation_evidence=evidence,
        model_declared_observations=[],
        camera_model_candidates=[],
        visible_object_detections=[],
        private_target_truth_included=False,
    )


def _registered_visual_candidate_declarations(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    waypoint: dict[str, Any],
    candidate_inputs: list[dict[str, Any]],
    producer_type: str,
    producer_id: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None,
) -> dict[str, Any]:
    assert_no_forbidden = assert_no_forbidden_agent_view_keys or (lambda _payload: None)
    declared = []
    for index, candidate in enumerate(candidate_inputs):
        candidate_error = realworld_visual_candidates._visual_candidate_validation_error(
            candidate,
            require_target_fixture_id=False,
            perception_mode=contract.perception_mode,
            producer_type=producer_type,
        )
        if candidate_error is not None:
            return {
                "response": _invalid_visual_candidate_declaration_response(
                    contract,
                    raw_observation=raw_observation,
                    candidate_index=index,
                    candidate_error=candidate_error,
                )
            }
        declared.append(
            realworld_visual_candidate_lifecycle.register_model_declared_candidate(
                contract,
                raw_observation=raw_observation,
                waypoint=waypoint,
                candidate=candidate,
                producer_type=producer_type,
                producer_id=producer_id,
                assert_no_forbidden_agent_view_keys=assert_no_forbidden,
            )
        )
    return {"declared": declared}


def _invalid_visual_candidate_declaration_response(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    candidate_index: int,
    candidate_error: dict[str, str],
) -> dict[str, Any]:
    source_observation_id = str(raw_observation["observation_id"])
    return contract._error(
        "declare_visual_candidates",
        "invalid_visual_candidate",
        observation_id=source_observation_id,
        candidate_index=candidate_index,
        candidate_error=candidate_error,
        raw_fpv_candidate_recovery=raw_fpv_visual_candidate_recovery(
            source_observation_id=source_observation_id,
        ),
        recovery_hint=raw_fpv_visual_candidate_recovery_hint(
            source_observation_id=source_observation_id,
        ),
    )


def _visual_candidate_declaration_response(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    declared: list[dict[str, Any]],
    producer_type: str,
    producer_id: str,
    visual_grounding_pipeline: dict[str, Any],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None,
) -> dict[str, Any]:
    resolved_candidates = [
        dict(contract._detections_by_handle[str(item["object_id"])])
        for item in declared
        if item.get("grounding_status") == "resolved"
        and str(item.get("object_id") or "") in contract._detections_by_handle
    ]
    evidence = model_declared_observation_event(
        contract,
        raw_observation=raw_observation,
        producer_type=producer_type,
        producer_id=producer_id,
        declared=declared,
        visual_grounding_pipeline=visual_grounding_pipeline,
    )
    if assert_no_forbidden_agent_view_keys is not None:
        assert_no_forbidden_agent_view_keys(evidence)
    if contract.perception_mode == CAMERA_MODEL_POLICY_MODE:
        contract._camera_model_policy_events.append(evidence)
    return contract._ok(
        "declare_visual_candidates",
        contract=REALWORLD_CONTRACT,
        model_declared_observation_evidence=evidence,
        model_declared_observations=[
            realworld_runtime_map_targets.public_fixture_reference_payload(
                contract,
                item,
            )
            for item in declared
        ],
        camera_model_candidates=[
            contract._agent_visible_detection_payload(item) for item in resolved_candidates
        ],
        visible_object_detections=[],
        private_target_truth_included=False,
    )


def simulated_declaration_inputs_for_waypoint(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
    *,
    observation_id: str,
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None = None,
) -> list[dict[str, Any]]:
    assert_no_forbidden = assert_no_forbidden_agent_view_keys or (lambda _payload: None)
    inputs = []
    for obj, location_id in realworld_visual_perception_navigation.objects_visible_from_waypoint(
        contract,
        waypoint,
    ):
        handle = contract._handle_for_object(obj.object_id)
        detection = realworld_visual_perception_navigation.detection_for_object_at_location(
            contract,
            obj,
            location_id=location_id,
            handle=handle,
            waypoint=waypoint,
            perception_source=CAMERA_MODEL_POLICY_MODE,
            producer_type=SIMULATED_CAMERA_MODEL_PROVENANCE,
            source_observation_id=observation_id,
            assert_no_forbidden_agent_view_keys=assert_no_forbidden,
        )
        target = realworld_runtime_map_targets.target_fixture_for_detection(
            contract,
            detection,
            include_runtime_backend_fixtures=True,
        )
        target_fixture_id = str((target or {}).get("fixture_id") or location_id)
        inputs.append(
            {
                "category": obj.category,
                "source_fixture_id": location_id,
                "target_fixture_id": target_fixture_id,
                "evidence_note": (
                    "simulated camera model declared a public camera-derived "
                    f"{obj.category} candidate"
                ),
                "image_region": {"type": "bbox", "value": detection["image_bbox"]},
                "confidence": detection.get("visibility_confidence", 0.68),
            }
        )
    return inputs


def simulated_raw_fpv_inputs_for_observation(
    contract: HouseholdRuntimeContract,
    waypoint: dict[str, Any],
    *,
    observation_id: str,
) -> list[dict[str, Any]]:
    payload = getattr(contract, "_private_raw_fpv_bindings_by_observation_id", {}).get(
        observation_id,
        {},
    )
    bindings = {
        str(item.get("object_id") or ""): item
        for item in payload.get("bindings") or []
        if isinstance(item, dict) and item.get("object_id")
    }
    if not bindings and _uses_synthetic_raw_fpv_declarations(contract):
        return [
            {key: value for key, value in candidate.items() if key != "target_fixture_id"}
            for candidate in simulated_declaration_inputs_for_waypoint(
                contract,
                waypoint,
                observation_id=observation_id,
            )
        ]
    inputs: list[dict[str, Any]] = []
    for obj, location_id in realworld_visual_perception_navigation.objects_visible_from_waypoint(
        contract,
        waypoint,
    ):
        binding = bindings.get(obj.object_id)
        if not binding or not binding.get("bbox"):
            continue
        inputs.append(
            {
                "category": obj.category,
                "source_fixture_id": contract._public_fixture_reference_id(location_id),
                "evidence_note": (
                    "simulated camera model declared a public camera-derived "
                    f"{obj.category} candidate"
                ),
                "image_region": {"type": "bbox", "value": list(binding["bbox"])},
                "confidence": 0.9,
            }
        )
    return inputs


def _uses_synthetic_raw_fpv_declarations(
    contract: HouseholdRuntimeContract,
) -> bool:
    return (
        contract.contract.backend_name() == SYNTHETIC_BACKEND
        and contract.visual_grounding_pipeline_id == SIM_VISUAL_GROUNDING_PIPELINE_ID
    )


def camera_label_producer_candidates(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    waypoint: dict[str, Any],
    assert_no_forbidden_agent_view_keys: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    if contract.visual_grounding_pipeline_id == SIM_VISUAL_GROUNDING_PIPELINE_ID:
        candidates = simulated_declaration_inputs_for_waypoint(
            contract,
            waypoint,
            observation_id=str(raw_observation["observation_id"]),
            assert_no_forbidden_agent_view_keys=assert_no_forbidden_agent_view_keys,
        )
        return {
            "ok": True,
            "candidates": candidates,
            "visual_grounding_pipeline": sim_visual_grounding_pipeline(
                candidate_count=len(candidates)
            ),
        }
    if contract.visual_grounding_client is None:
        return {
            "ok": True,
            "candidates": [],
            "visual_grounding_pipeline": pipeline_summary_from_response(
                visual_grounding_failure_response(
                    pipeline_id=contract.visual_grounding_pipeline_id,
                    reason="missing_client",
                    message=(
                        "non-sim camera-grounded-labels camera labeler requires an "
                        "External Visual Grounding Service client"
                    ),
                    latency_ms=0,
                )
            ),
        }
    client_config = getattr(contract.visual_grounding_client, "config", None)
    auth_mode = str(getattr(client_config, "auth_mode", "none"))
    image = image_payload_for_raw_observation(
        raw_observation,
        base_dir=contract.visual_grounding_artifact_base_dir,
    )
    if not _image_payload_is_usable(image):
        return {
            "ok": True,
            "candidates": [],
            "visual_grounding_pipeline": pipeline_summary_from_response(
                visual_grounding_failure_response(
                    pipeline_id=contract.visual_grounding_pipeline_id,
                    reason="missing_raw_fpv_image",
                    message=(
                        "non-sim camera-grounded-labels camera labeler requires "
                        "a readable raw FPV image artifact"
                    ),
                    latency_ms=0,
                ),
                auth_mode=auth_mode,
            ),
        }
    request = visual_grounding_request(
        run_id=contract.visual_grounding_run_id or contract.scenario.scenario_id,
        raw_observation=raw_observation,
        category_hints=list(realworld_visual_candidates.VISUAL_GROUNDING_CATEGORY_HINTS),
        public_map_hints=realworld_visual_candidates._public_map_hints_for_visual_grounding_request(
            contract.static_fixture_projection()
        ),
        pipeline_id=contract.visual_grounding_pipeline_id,
        image=image,
        proposer={
            "producer_id": str(getattr(client_config, "proposer_id", "") or ""),
            "model_id": str(getattr(client_config, "proposer_model_id", "") or ""),
        },
    )
    try:
        response = contract.visual_grounding_client.request_candidates(request)
        pipeline = pipeline_summary_from_response(response, auth_mode=auth_mode)
    except VisualGroundingContractError as exc:
        return {
            "ok": False,
            "error_reason": "visual_grounding_contract_error",
            "recovery_hint": str(exc),
            "candidates": [],
            "visual_grounding_pipeline": {
                "schema": "visual_grounding_pipeline_v1",
                "pipeline_id": contract.visual_grounding_pipeline_id,
                "status": "contract_error",
                "stages": [],
                "candidate_count": 0,
                "unresolved_count": 0,
                "duplicate_rate": 0.0,
                "failure_reason": "contract_error",
                "failure_message": str(exc),
                "auth_mode": "none",
            },
        }
    if pipeline.get("status") == "failed":
        return {
            "ok": True,
            "candidates": [],
            "visual_grounding_pipeline": pipeline,
        }
    return {
        "ok": True,
        "candidates": (
            realworld_visual_candidates._candidate_inputs_from_visual_grounding_response(
                response,
                raw_observation=raw_observation,
                visual_grounding_pipeline=pipeline,
                artifact_base_dir=contract.visual_grounding_artifact_base_dir,
                resolve_destination_fixture_id=lambda **kwargs: _resolved_destination_fixture_id(
                    contract,
                    **kwargs,
                ),
            )
        ),
        "visual_grounding_pipeline": pipeline,
    }


def _image_payload_is_usable(image: dict[str, Any]) -> bool:
    if not str(image.get("bytes_base64") or ""):
        return False
    width = image.get("width")
    height = image.get("height")
    return isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0


def _resolved_destination_fixture_id(
    contract: HouseholdRuntimeContract,
    *,
    category: str,
    source_fixture_id: str,
) -> str:
    pseudo_detection = {
        "category": category,
        "name": category,
        "support_estimate": {"fixture_id": source_fixture_id},
    }
    target = realworld_runtime_map_targets.target_fixture_for_detection(
        contract,
        pseudo_detection,
        include_runtime_backend_fixtures=True,
    )
    return str((target or {}).get("fixture_id") or "")


def model_declared_observation_event(
    contract: HouseholdRuntimeContract,
    *,
    raw_observation: dict[str, Any],
    producer_type: str,
    producer_id: str,
    declared: list[dict[str, Any]],
    visual_grounding_pipeline: dict[str, Any],
) -> dict[str, Any]:
    return realworld_visual_candidates._model_declared_observation_event(
        raw_observation=raw_observation,
        perception_mode=contract.perception_mode,
        producer_type=producer_type,
        producer_id=producer_id,
        declared=declared,
        visual_grounding_pipeline=visual_grounding_pipeline,
    )
