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
from roboclaws.maps.runtime_prior_catalog import (
    RUNTIME_PRIOR_CATALOG_SCHEMA,
    RuntimeMapPriorCatalogEntry,
    load_runtime_prior_catalog,
)

DEFAULT_CAMERA_LABELER = "grounding-dino"
DEFAULT_RELOCATION_COUNT = "5"
DEFAULT_PROVIDER_PROFILE = "kimi-openai-chat"

WORKFLOW_BUILD_MAP = "build-map"
WORKFLOW_OPEN_TASK = "open-task"
WORKFLOW_CLEANUP = "cleanup"


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
    supports_runtime_map_prior: bool
    scenario_setup: str
    coverage: WorkflowCoverage
    prompt_required: bool = False
    launchable: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coverage"] = self.coverage.to_payload()
        payload["allows_prior_override"] = self.supports_runtime_map_prior
        payload["requires_runtime_map_prior"] = False
        return payload


WORKFLOWS: tuple[OperatorWorkflow, ...] = (
    OperatorWorkflow(
        id=WORKFLOW_BUILD_MAP,
        label="Build Map",
        intent_id="map-build",
        preset_id="map-build",
        supports_runtime_map_prior=False,
        scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        coverage=WorkflowCoverage("eval_suite", "map_build_quality"),
    ),
    OperatorWorkflow(
        id=WORKFLOW_OPEN_TASK,
        label="Open Task",
        intent_id="open-ended",
        preset_id="",
        supports_runtime_map_prior=True,
        scenario_setup=ENVIRONMENT_SETUP_BASELINE,
        coverage=WorkflowCoverage("eval_suite", "open_ended_goals"),
        prompt_required=True,
    ),
    OperatorWorkflow(
        id=WORKFLOW_CLEANUP,
        label="Cleanup",
        intent_id="cleanup",
        preset_id="cleanup",
        supports_runtime_map_prior=True,
        scenario_setup=ENVIRONMENT_SETUP_RELOCATE_CLEANUP_RELATED_OBJECTS,
        coverage=WorkflowCoverage("eval_suite", "cleanup_capability"),
    ),
)

_WORKFLOW_BY_ID = {workflow.id: workflow for workflow in WORKFLOWS}
RECOMMENDED_PRIOR_CATALOG_PATH = Path(__file__).with_name("recommended_runtime_map_priors.json")


def list_operator_workflows() -> tuple[OperatorWorkflow, ...]:
    return WORKFLOWS


def get_operator_workflow(workflow_id: str) -> OperatorWorkflow:
    try:
        return _WORKFLOW_BY_ID[workflow_id]
    except KeyError as exc:
        raise KeyError(workflow_id) from exc


def list_recommended_priors() -> tuple[RuntimeMapPriorCatalogEntry, ...]:
    return _load_recommended_priors(RECOMMENDED_PRIOR_CATALOG_PATH)


def recommended_prior_for(world_id: str, backend_id: str) -> RuntimeMapPriorCatalogEntry | None:
    for entry in list_recommended_priors():
        if entry.world_id == world_id and entry.backend_id == backend_id and entry.auto_enabled:
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
    payload["allows_prior_override"] = workflow.supports_runtime_map_prior
    payload["requires_runtime_map_prior"] = False
    payload["recommended_prior"] = (
        recommended_prior.to_payload()
        if workflow.supports_runtime_map_prior and recommended_prior is not None
        else None
    )
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
    if not workflow.supports_runtime_map_prior:
        return ""
    recommended = recommended_prior_for(world_id, backend_id)
    if recommended is None:
        return ""
    return recommended.path


def runtime_prior_override_exists(path: str, *, root: Path) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.is_file()


def _load_recommended_priors(path: Path) -> tuple[RuntimeMapPriorCatalogEntry, ...]:
    if not path.is_file():
        return ()
    return load_runtime_prior_catalog(path)


__all__ = [
    "RUNTIME_PRIOR_CATALOG_SCHEMA",
    "RECOMMENDED_PRIOR_CATALOG_PATH",
    "WORKFLOW_BUILD_MAP",
    "WORKFLOW_CLEANUP",
    "WORKFLOW_OPEN_TASK",
    "RuntimeMapPriorCatalogEntry",
    "list_recommended_priors",
    "recommended_prior_for",
]
