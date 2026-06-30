"""Product workflow metadata for the operator console."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from roboclaws.household.profiles import CAMERA_GROUNDED_LABELS_LANE
from roboclaws.launch.environment_setup import (
    ENVIRONMENT_SETUP_BASELINE,
    ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
)
from roboclaws.launch.worlds import WORLD_SPECS

DEFAULT_CAMERA_LABELER = "grounding-dino"
DEFAULT_RELOCATION_COUNT = "5"
DEFAULT_PROVIDER_PROFILE = "codex-router-responses"

WORKFLOW_BUILD_MAP = "build-map"
WORKFLOW_OPEN_TASK = "open-task"
WORKFLOW_CLEANUP = "cleanup"
WORKFLOW_OPEN_TASK_WITH_MAP = "open-task-with-map"
WORKFLOW_CLEANUP_WITH_MAP = "cleanup-with-map"
WORKFLOW_PREPARE_STANDARD_MESS = "prepare-standard-mess"
WORKFLOW_RESET_SCENE = "reset-scene"


@dataclass(frozen=True)
class WorkflowCoverage:
    """Automated or operational owner for a console workflow."""

    owner_type: str
    owner_id: str

    def to_payload(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class OperatorWorkflow:
    """Operator-facing workflow action translated into public launch axes."""

    id: str
    label: str
    intent_id: str
    preset_id: str
    requires_runtime_map_prior: bool
    scenario_setup: str
    coverage: WorkflowCoverage
    prompt_required: bool = False
    launchable: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coverage"] = self.coverage.to_payload()
        return payload


@dataclass(frozen=True)
class RuntimeMapPriorCatalogEntry:
    """Recommended Runtime Map Prior Snapshot for a world/backend pair."""

    world_id: str
    backend_id: str
    path: str
    status: str
    source: str
    evidence: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.world_id}::{self.backend_id}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "world_id": self.world_id,
            "backend_id": self.backend_id,
            "path": self.path,
            "status": self.status,
            "source": self.source,
            "evidence": list(self.evidence),
        }


WORKFLOWS: tuple[OperatorWorkflow, ...] = (
    OperatorWorkflow(
        id=WORKFLOW_BUILD_MAP,
        label="Build Map",
        intent_id="map-build",
        preset_id="map-build",
        requires_runtime_map_prior=False,
        scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        coverage=WorkflowCoverage("eval_suite", "map_build_consumer"),
    ),
    OperatorWorkflow(
        id=WORKFLOW_OPEN_TASK,
        label="Open Task",
        intent_id="open-ended",
        preset_id="",
        requires_runtime_map_prior=False,
        scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        coverage=WorkflowCoverage("eval_suite", "open_ended_goals"),
        prompt_required=True,
    ),
    OperatorWorkflow(
        id=WORKFLOW_CLEANUP,
        label="Cleanup",
        intent_id="cleanup",
        preset_id="cleanup",
        requires_runtime_map_prior=False,
        scenario_setup=ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
        coverage=WorkflowCoverage("eval_suite", "cleanup_capability"),
    ),
    OperatorWorkflow(
        id=WORKFLOW_OPEN_TASK_WITH_MAP,
        label="Open Task With Map",
        intent_id="open-ended",
        preset_id="",
        requires_runtime_map_prior=True,
        scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        coverage=WorkflowCoverage("eval_suite", "map_build_consumer"),
        prompt_required=True,
    ),
    OperatorWorkflow(
        id=WORKFLOW_CLEANUP_WITH_MAP,
        label="Cleanup With Map",
        intent_id="cleanup",
        preset_id="cleanup",
        requires_runtime_map_prior=True,
        scenario_setup=ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
        coverage=WorkflowCoverage("eval_suite", "map_build_consumer"),
    ),
    OperatorWorkflow(
        id=WORKFLOW_PREPARE_STANDARD_MESS,
        label="Prepare Standard Mess",
        intent_id="cleanup",
        preset_id="cleanup",
        requires_runtime_map_prior=False,
        scenario_setup=ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
        coverage=WorkflowCoverage("unit_contract", "operator_console_workflows"),
    ),
    OperatorWorkflow(
        id=WORKFLOW_RESET_SCENE,
        label="Reset Scene",
        intent_id="open-ended",
        preset_id="",
        requires_runtime_map_prior=False,
        scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        coverage=WorkflowCoverage("manual_operational_control", "operator_console_reset_scene"),
    ),
)

_WORKFLOW_BY_ID = {workflow.id: workflow for workflow in WORKFLOWS}

RECOMMENDED_PRIORS: tuple[RuntimeMapPriorCatalogEntry, ...] = ()


def list_operator_workflows() -> tuple[OperatorWorkflow, ...]:
    return WORKFLOWS


def get_operator_workflow(workflow_id: str) -> OperatorWorkflow:
    try:
        return _WORKFLOW_BY_ID[workflow_id]
    except KeyError as exc:
        raise KeyError(workflow_id) from exc


def list_recommended_priors() -> tuple[RuntimeMapPriorCatalogEntry, ...]:
    return RECOMMENDED_PRIORS


def recommended_prior_for(world_id: str, backend_id: str) -> RuntimeMapPriorCatalogEntry | None:
    for entry in RECOMMENDED_PRIORS:
        if (
            entry.world_id == world_id
            and entry.backend_id == backend_id
            and entry.status == "accepted"
        ):
            return entry
    return None


def workflow_payloads_for_world(world_id: str, backend_id: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        workflow_payload_for_world(workflow, world_id=world_id, backend_id=backend_id)
        for workflow in WORKFLOWS
    )


def workflow_payload_for_world(
    workflow: OperatorWorkflow,
    *,
    world_id: str,
    backend_id: str,
) -> dict[str, Any]:
    recommended_prior = recommended_prior_for(world_id, backend_id)
    payload = workflow.to_payload()
    payload["default_evidence_lane"] = CAMERA_GROUNDED_LABELS_LANE
    payload["default_camera_labeler"] = DEFAULT_CAMERA_LABELER
    payload["default_provider_profile"] = DEFAULT_PROVIDER_PROFILE
    payload["default_relocation_count"] = DEFAULT_RELOCATION_COUNT
    payload["allows_prior_override"] = workflow.requires_runtime_map_prior
    payload["recommended_prior"] = (
        recommended_prior.to_payload()
        if workflow.requires_runtime_map_prior and recommended_prior is not None
        else None
    )
    if workflow.requires_runtime_map_prior and recommended_prior is None:
        payload["enabled"] = False
        payload["disabled_reason"] = (
            "No accepted Runtime Map Prior Snapshot is cataloged for this scene/backend. "
            "Run Build Map or choose an explicit map override."
        )
    else:
        payload["enabled"] = True
        payload["disabled_reason"] = ""
    return payload


def default_workflow_id_for_world(world_id: str, backend_id: str) -> str:
    if world_id in WORLD_SPECS and backend_id in WORLD_SPECS[world_id].available_backends:
        return WORKFLOW_OPEN_TASK
    return WORKFLOW_BUILD_MAP


def runtime_map_prior_for_workflow(
    *,
    workflow: OperatorWorkflow,
    world_id: str,
    backend_id: str,
    override_path: str,
) -> str:
    path = override_path.strip()
    if path:
        return path
    if not workflow.requires_runtime_map_prior:
        return ""
    recommended = recommended_prior_for(world_id, backend_id)
    if recommended is None:
        raise ValueError(
            "workflow requires runtime_map_prior but no recommended prior is cataloged; "
            "choose an explicit Runtime Map Prior Snapshot override"
        )
    return recommended.path


def runtime_prior_override_exists(path: str, *, root: Path) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.is_file()
