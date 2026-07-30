from __future__ import annotations

from dataclasses import dataclass

from roboclaws.core.provider_catalog import (
    MODEL_CAP_IMAGE_INPUT,
    ROUTE_CAP_SUPPORTED,
    provider_route_spec,
    resolve_route_model,
)

CAMERA_RAW_FPV_LANE = "camera-raw-fpv"


@dataclass(frozen=True)
class EvidenceLaneRequirement:
    lane_id: str
    requires_agent_image_input: bool
    text_only_allowed: bool
    external_visual_producer: str
    notes: str = ""


@dataclass(frozen=True)
class EvidenceLaneCompatibility:
    allowed: bool
    reason: str = ""
    requirement: EvidenceLaneRequirement | None = None


EVIDENCE_LANE_REQUIREMENTS: dict[str, EvidenceLaneRequirement] = {
    "world-public-labels": EvidenceLaneRequirement(
        lane_id="world-public-labels",
        requires_agent_image_input=False,
        text_only_allowed=True,
        external_visual_producer="sanitized-public-labels",
    ),
    "camera-grounded-labels": EvidenceLaneRequirement(
        lane_id="camera-grounded-labels",
        requires_agent_image_input=False,
        text_only_allowed=True,
        external_visual_producer="camera-labeler",
    ),
    CAMERA_RAW_FPV_LANE: EvidenceLaneRequirement(
        lane_id=CAMERA_RAW_FPV_LANE,
        requires_agent_image_input=True,
        text_only_allowed=False,
        external_visual_producer="agent-model-image-input",
        notes="Requires verified runtime image transport, not only model marketing capability.",
    ),
}


def evidence_lane_requirement(lane_id: str) -> EvidenceLaneRequirement:
    try:
        return EVIDENCE_LANE_REQUIREMENTS[lane_id]
    except KeyError:
        raise ValueError(f"unsupported evidence lane: {lane_id}") from None


def evidence_lane_compatibility(
    *,
    evidence_lane: str,
    agent_engine: str,
    provider_profile: str | None,
    model_id: str | None = None,
) -> EvidenceLaneCompatibility:
    requirement = evidence_lane_requirement(evidence_lane)
    if not requirement.requires_agent_image_input:
        return EvidenceLaneCompatibility(allowed=True, requirement=requirement)
    if not provider_profile:
        return EvidenceLaneCompatibility(
            allowed=True,
            requirement=requirement,
        )

    route = provider_route_spec(provider_profile)
    resolved_model_id = model_id or route.default_model_id
    model = resolve_route_model(route.public_profile, resolved_model_id)
    if MODEL_CAP_IMAGE_INPUT not in model.model_capabilities:
        return EvidenceLaneCompatibility(
            allowed=False,
            requirement=requirement,
            reason=(
                f"{evidence_lane} requires agent image input, but model "
                f"{resolved_model_id} is text-only in the provider registry."
            ),
        )
    image_transport = route.route_capability("image_transport", agent_engine=agent_engine)
    if image_transport != ROUTE_CAP_SUPPORTED:
        return EvidenceLaneCompatibility(
            allowed=False,
            requirement=requirement,
            reason=(
                f"{evidence_lane} requires verified image transport for "
                f"{agent_engine}+{route.public_profile}; registry marks image_transport="
                f"{image_transport}."
            ),
        )
    return EvidenceLaneCompatibility(allowed=True, requirement=requirement)
