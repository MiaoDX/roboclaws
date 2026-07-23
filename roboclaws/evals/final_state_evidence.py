"""Private backend-neutral final-state evidence for household graders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, cast

EvidenceStatus = Literal["available", "inconclusive", "unavailable"]
HeldObjectState = Literal["empty", "holding", "unknown"]


@dataclass(frozen=True)
class FinalStateEvidence:
    """Authoritative final state supplied privately to evaluators."""

    status: EvidenceStatus
    locations: Mapping[str, str] = field(default_factory=dict)
    containment: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    held_object_state: HeldObjectState = "unknown"
    held_object_id: str | None = None
    receptacle_states: Mapping[str, str] = field(default_factory=dict)
    source_provenance: tuple[str, ...] = ()
    confidence: float | None = None
    source_errors: tuple[str, ...] = ()


def exact_simulator_final_state_evidence(
    *,
    locations: Mapping[str, str],
    containment: Mapping[str, Mapping[str, str]],
    held_object_id: str | None,
    receptacle_states: Mapping[str, str],
    source_provenance: str,
) -> FinalStateEvidence:
    """Build exact evidence from authoritative simulator state."""

    return FinalStateEvidence(
        status="available",
        locations=dict(locations),
        containment={key: dict(value) for key, value in containment.items()},
        held_object_state="holding" if held_object_id else "empty",
        held_object_id=held_object_id,
        receptacle_states=dict(receptacle_states),
        source_provenance=(source_provenance,),
        confidence=1.0,
    )


def physical_final_state_evidence(
    *,
    observations: Mapping[str, Any] | None = None,
    source_provenance: tuple[str, ...] = (),
    source_errors: tuple[str, ...] = (),
) -> FinalStateEvidence:
    """Normalize independent physical observations without inferring scenario truth."""

    if not observations:
        return FinalStateEvidence(
            status="unavailable",
            source_provenance=source_provenance,
            source_errors=source_errors or ("authoritative_physical_final_state_unobservable",),
        )
    locations = _string_mapping(observations.get("locations"))
    containment = _containment_mapping(observations.get("containment"))
    receptacle_states = _string_mapping(observations.get("receptacle_states"))
    held_object_id = _optional_string(observations.get("held_object_id"))
    held_state = str(observations.get("held_object_state") or "unknown")
    if held_state not in {"empty", "holding", "unknown"}:
        held_state = "unknown"
    complete = bool(locations) and held_state != "unknown"
    return FinalStateEvidence(
        status="available" if complete else "inconclusive",
        locations=locations,
        containment=containment,
        held_object_state=cast(HeldObjectState, held_state),
        held_object_id=held_object_id,
        receptacle_states=receptacle_states,
        source_provenance=source_provenance,
        confidence=_optional_confidence(observations.get("confidence")),
        source_errors=source_errors,
    )


def simulator_evidence_from_run_result(run_result: Mapping[str, Any]) -> FinalStateEvidence:
    """Adapt authoritative simulator result state for private grading."""

    locations = _string_mapping(run_result.get("final_locations"))
    containment = _containment_mapping(run_result.get("final_containment"))
    held_object_id = next(
        (object_id for object_id, location in locations.items() if location == "held_by_agent"),
        None,
    )
    return exact_simulator_final_state_evidence(
        locations=locations,
        containment=containment,
        held_object_id=held_object_id,
        receptacle_states=_string_mapping(run_result.get("final_receptacle_states")),
        source_provenance=str(run_result.get("backend") or "simulator_authoritative_state"),
    )


def final_state_evidence_for_run(run_result: Mapping[str, Any]) -> FinalStateEvidence:
    """Select a private producer from backend provenance."""

    physical_robot = bool(
        isinstance(run_result.get("manipulation_evidence"), Mapping)
        and run_result["manipulation_evidence"].get("physical_robot") is True
    )
    if str(run_result.get("backend_variant") or "") == "agibot_gdk" or physical_robot:
        return physical_final_state_evidence(
            source_provenance=(str(run_result.get("backend") or "agibot_gdk"),)
        )
    return simulator_evidence_from_run_result(run_result)


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _containment_mapping(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): _string_mapping(item) for key, item in value.items() if isinstance(item, Mapping)
    }


def _optional_string(value: Any) -> str | None:
    return str(value) if value not in {None, ""} else None


def _optional_confidence(value: Any) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, confidence))
