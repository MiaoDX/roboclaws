from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.core.backend_catalog import (
    BACKEND_SPECS,
    SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND,
    BackendSpec,
)
from roboclaws.household.artifact_paths import home_relative_paths
from roboclaws.household.household_backend_port import (
    HouseholdBackendPort,
    HouseholdRuntimeEvidence,
)
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_SUBPROCESS_BACKEND,
    IsaacLabSubprocessBackend,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_camera_timeline import (
    record_robot_view_step as _record_robot_view_step,
)
from roboclaws.household.subprocess_backend import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
    MolmoSpacesSubprocessBackend,
)
from roboclaws.household.types import CleanupScenario, PrivateScoringManifest

SYNTHETIC_BACKEND = SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND
VISUAL_BACKENDS = frozenset({MOLMOSPACES_SUBPROCESS_BACKEND, ISAACLAB_SUBPROCESS_BACKEND})
CLEANUP_BACKEND_EVIDENCE_SCHEMA = "roboclaws_cleanup_backend_evidence_v1"


class HouseholdBackendSession:
    """Direct-call state mutation session for ADR-0003 cleanup surfaces.

    This is not an agent-facing MCP surface. It keeps the semantic cleanup
    backend callable by the ADR-0003 public/private contract without exposing
    legacy global-inventory helpers such as ``scene_objects`` or
    ``object_done``.
    """

    def __init__(
        self,
        scenario: CleanupScenario | None = None,
        backend: HouseholdBackendPort | None = None,
    ):
        if backend is None:
            from roboclaws.household.backend import ApiSemanticCleanupBackend

            backend = ApiSemanticCleanupBackend(scenario or build_cleanup_scenario())
        self._port = backend

    @property
    def scenario(self) -> CleanupScenario:
        return self._port.scenario

    def backend_name(self) -> str:
        return self._port.backend_name()

    def supports_visual_snapshots(self) -> bool:
        return self._port.supports_visual_snapshots()

    def supports_robot_views(self) -> bool:
        return self._port.supports_robot_views()

    def requested_generated_mess_count(self) -> int | None:
        return self._port.requested_mess_count()

    def object_locations(self) -> dict[str, str]:
        return self._port.object_locations()

    def current_location(self, object_id: str) -> str:
        return str(self.object_locations().get(object_id) or "")

    def location_relation(self, object_id: str) -> str:
        return self._port.location_relation(object_id)

    def scene_index_source(self) -> str:
        return self._port.scene_index_source()

    def scene_index_fixture_pose(self, fixture_id: str) -> list[float] | None:
        return self._port.scene_index_fixture_pose(fixture_id)

    def planner_scene(self) -> dict[str, Any]:
        return self._port.planner_scene()

    def planner_task_binding(self, object_id: str, receptacle_id: str) -> dict[str, Any]:
        return self._port.planner_task_binding(object_id, receptacle_id)

    def runtime_evidence(self) -> HouseholdRuntimeEvidence:
        return self._port.runtime_evidence()

    def final_locations(self, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(fallback or self.object_locations())

    def write_visual_snapshot(self, output_path: Path, *, title: str) -> Path | None:
        return self._port.write_snapshot(output_path, title=title)

    def record_robot_view_step(
        self,
        *,
        steps: list[dict[str, Any]],
        output_dir: Path,
        index: int,
        action: str,
        label_suffix: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        semantic_phase: str | None = None,
        action_evidence: dict[str, Any] | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> int:
        return _record_robot_view_step(
            steps=steps,
            backend=self._port,
            output_dir=output_dir,
            index=index,
            action=action,
            label_suffix=label_suffix,
            focus_object_id=focus_object_id,
            focus_receptacle_id=focus_receptacle_id,
            semantic_phase=semantic_phase,
            action_evidence=action_evidence,
            camera_yaw_offset_deg=camera_yaw_offset_deg,
            camera_pitch_offset_deg=camera_pitch_offset_deg,
        )

    def close(self) -> None:
        try:
            self._port.close()
        except Exception:
            pass

    def observe(self) -> dict[str, Any]:
        return self._port.observe()

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return self._port.navigate_to_object(object_id=object_id)

    def navigate_to_waypoint(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        return self._port.navigate_to_waypoint(waypoint=waypoint)

    def navigate_to_relative_pose(
        self,
        *,
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict[str, Any]:
        return self._port.navigate_to_relative_pose(
            forward_m=forward_m,
            lateral_m=lateral_m,
            yaw_delta_deg=yaw_delta_deg,
        )

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._port.navigate_to_receptacle(receptacle_id=receptacle_id)

    def pick(self, object_id: str) -> dict[str, Any]:
        return self._port.pick(object_id=object_id)

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._port.open_receptacle(receptacle_id=receptacle_id)

    def place(self, receptacle_id: str) -> dict[str, Any]:
        return self._port.place(receptacle_id=receptacle_id)

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        return self._port.place_inside(receptacle_id=receptacle_id)

    def close_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self._port.close_receptacle(receptacle_id=receptacle_id)

    def done(self, reason: str = "") -> dict[str, Any]:
        return self._port.done(reason=reason)

    def attach_runtime_metadata(self, run_result: dict[str, Any], *, run_dir: Path) -> None:
        attach_cleanup_backend_runtime_metadata(
            run_result=run_result,
            port=self._port,
            backend_name=self.backend_name(),
            run_dir=run_dir,
        )


def build_household_backend_session(
    *,
    backend_name: str = SYNTHETIC_BACKEND,
    run_dir: Path,
    seed: int = 1,
    include_robot: bool = False,
    robot_name: str = "rby1m",
    generated_mess_count: int = 10,
    generated_mess_object_ids: tuple[str, ...] = (),
    generated_mess_manifest_path: str | Path | None = None,
    scene_source: str = "procthor-10k-val",
    scene_index: int = 0,
    molmospaces_python: str | Path | None = None,
    map_bundle_dir: str | Path | None = None,
    isaac_scene_usd_path: str | Path | None = None,
    isaac_enable_segmentation: bool = False,
    isaac_segmentation_data_types: tuple[str, ...] | None = None,
    isaac_segmentation_semantic_filter: tuple[str, ...] | None = None,
) -> HouseholdBackendSession:
    backend_instance: Any | None = None
    if backend_name == MOLMOSPACES_SUBPROCESS_BACKEND:
        backend_instance = MolmoSpacesSubprocessBackend(
            run_dir=run_dir,
            seed=seed,
            python_executable=Path(molmospaces_python) if molmospaces_python else None,
            include_robot=include_robot,
            robot_name=robot_name,
            generated_mess_count=generated_mess_count,
            generated_mess_object_ids=generated_mess_object_ids,
            generated_mess_manifest_path=Path(generated_mess_manifest_path)
            if generated_mess_manifest_path is not None
            else None,
            scene_source=scene_source,
            scene_index=scene_index,
        )
        return HouseholdBackendSession(backend_instance.scenario, backend=backend_instance)
    if backend_name == ISAACLAB_SUBPROCESS_BACKEND:
        backend_instance = IsaacLabSubprocessBackend(
            run_dir=run_dir,
            seed=seed,
            include_robot=include_robot,
            robot_name=robot_name,
            generated_mess_count=generated_mess_count,
            generated_mess_object_ids=generated_mess_object_ids,
            generated_mess_manifest_path=Path(generated_mess_manifest_path)
            if generated_mess_manifest_path is not None
            else None,
            scene_source=scene_source,
            scene_index=scene_index,
            map_bundle_dir=Path(map_bundle_dir) if map_bundle_dir is not None else None,
            scene_usd_path=Path(isaac_scene_usd_path) if isaac_scene_usd_path else None,
            enable_segmentation=isaac_enable_segmentation,
            segmentation_data_types=isaac_segmentation_data_types,
            segmentation_semantic_filter=isaac_segmentation_semantic_filter,
        )
        return HouseholdBackendSession(backend_instance.scenario, backend=backend_instance)
    scenario = build_cleanup_scenario(seed=seed)
    if generated_mess_count == 0:
        scenario = scenario_without_private_targets(scenario)
    return HouseholdBackendSession(scenario)


def cleanup_backend_supports_visual_artifacts(backend_name: str) -> bool:
    return backend_name in VISUAL_BACKENDS


def validate_cleanup_backend_capability_request(
    *,
    backend_name: str,
    include_robot: bool,
    record_robot_views: bool,
) -> None:
    supports_visual_artifacts = cleanup_backend_supports_visual_artifacts(backend_name)
    if include_robot and not supports_visual_artifacts:
        raise ValueError("robot inclusion requires a visual subprocess backend")
    if record_robot_views and (not supports_visual_artifacts or not include_robot):
        raise ValueError(
            "record_robot_views requires a visual subprocess backend and include_robot"
        )


def validate_cleanup_run_options(
    *,
    backend_name: str,
    include_robot: bool,
    record_robot_views: bool,
    generated_mess_count: int,
) -> None:
    validate_cleanup_backend_capability_request(
        backend_name=backend_name,
        include_robot=include_robot,
        record_robot_views=record_robot_views,
    )
    if generated_mess_count < 0:
        raise ValueError("generated_mess_count must be >= 0")


def attach_cleanup_backend_runtime_metadata(
    *,
    run_result: dict[str, Any],
    port: HouseholdBackendPort,
    backend_name: str | None = None,
    run_dir: Path,
) -> None:
    resolved_backend_name = backend_name or port.backend_name()
    runtime_evidence = port.runtime_evidence()
    runtime_key = "not_applicable"
    if resolved_backend_name == ISAACLAB_SUBPROCESS_BACKEND:
        _attach_isaac_runtime(
            run_result=run_result, runtime_evidence=runtime_evidence, run_dir=run_dir
        )
        runtime_key = "isaac_runtime"
    elif resolved_backend_name == MOLMOSPACES_SUBPROCESS_BACKEND:
        _attach_molmospaces_runtime(run_result=run_result, runtime_evidence=runtime_evidence)
        runtime_key = "molmospaces_runtime"
    if resolved_backend_name in VISUAL_BACKENDS:
        _attach_common_diagnostics(run_result, runtime_evidence)
    _attach_cleanup_backend_evidence(
        run_result=run_result,
        port=port,
        runtime_evidence=runtime_evidence,
        backend_name=resolved_backend_name,
        runtime_key=runtime_key,
    )


def scenario_without_private_targets(scenario: CleanupScenario) -> CleanupScenario:
    scenario_id = f"{scenario.scenario_id}-baseline"
    return CleanupScenario(
        scenario_id=scenario_id,
        task=scenario.task,
        seed=scenario.seed,
        objects=scenario.objects,
        receptacles=scenario.receptacles,
        private_manifest=PrivateScoringManifest(
            scenario_id=scenario_id,
            targets=(),
            success_threshold=0,
        ),
    )


def _attach_common_diagnostics(
    run_result: dict[str, Any], runtime_evidence: HouseholdRuntimeEvidence
) -> None:
    mess_diagnostics = runtime_evidence["mess_placement_diagnostics"]
    placement_diagnostics = runtime_evidence["placement_diagnostics"]
    run_result["mess_placement_diagnostics"] = mess_diagnostics
    run_result["placement_diagnostics"] = placement_diagnostics


def _attach_molmospaces_runtime(
    *, run_result: dict[str, Any], runtime_evidence: HouseholdRuntimeEvidence
) -> None:
    run_result["molmospaces_runtime"] = home_relative_paths(
        {
            "python_executable": str(runtime_evidence["python_executable"]),
            "runtime": runtime_evidence["runtime"],
            "model_stats": runtime_evidence["model_stats"],
            "scene_xml": runtime_evidence["scene_xml"],
            "metadata_object_count": runtime_evidence["metadata_object_count"],
            "requested_generated_mess_count": runtime_evidence["requested_generated_mess_count"],
            "generated_mess_count": runtime_evidence["generated_mess_count"],
        }
    )
    _attach_robot_metadata(run_result, runtime_evidence)


def _attach_isaac_runtime(
    *,
    run_result: dict[str, Any],
    runtime_evidence: HouseholdRuntimeEvidence,
    run_dir: Path,
) -> None:
    isaac_scene_index_path = run_dir / "isaac_scene_index.json"
    scene_index_payload = runtime_evidence["scene_index_artifact"]
    if scene_index_payload:
        isaac_scene_index_path.write_text(
            json.dumps(scene_index_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        run_result.setdefault("artifacts", {})["isaac_scene_index"] = str(isaac_scene_index_path)
    run_result["isaac_runtime"] = home_relative_paths(
        {
            "python_executable": str(runtime_evidence["python_executable"]),
            "runtime": runtime_evidence["runtime"],
            "scenario_source": runtime_evidence["scenario_source"],
            "scene_usd": runtime_evidence["scene_usd"],
            "scene_index": runtime_evidence["scene_index"],
            "scene_index_artifact": str(isaac_scene_index_path) if scene_index_payload else "",
            "object_index_count": len(runtime_evidence["object_index"]),
            "receptacle_index_count": len(runtime_evidence["receptacle_index"]),
            "object_index": runtime_evidence["object_index"],
            "receptacle_index": runtime_evidence["receptacle_index"],
            "scene_index_diagnostics": runtime_evidence["scene_index_diagnostics"],
            "scene_binding_diagnostics": runtime_evidence["scene_binding_diagnostics"],
            "segmentation": runtime_evidence["segmentation"],
            "scene_load": runtime_evidence["scene_load"],
            "mapping_gaps": runtime_evidence["mapping_gaps"],
            "snapshot_artifacts": runtime_evidence["snapshot_artifacts"],
            "semantic_pose_state": runtime_evidence["semantic_pose_state"],
            "semantic_pose_view_capture": runtime_evidence["semantic_pose_view_capture"],
            "robot": runtime_evidence["robot"],
            "robot_import": runtime_evidence["robot_import"],
            "requested_generated_mess_count": runtime_evidence["requested_generated_mess_count"],
            "generated_mess_count": runtime_evidence["generated_mess_count"],
        }
    )
    _attach_robot_metadata(run_result, runtime_evidence)


def _attach_cleanup_backend_evidence(
    *,
    run_result: dict[str, Any],
    port: HouseholdBackendPort,
    runtime_evidence: HouseholdRuntimeEvidence,
    backend_name: str,
    runtime_key: str,
) -> None:
    launch_spec = _launch_backend_spec_for_implementation(backend_name)
    run_result["cleanup_backend_evidence"] = {
        "schema": CLEANUP_BACKEND_EVIDENCE_SCHEMA,
        "implementation_backend": backend_name,
        "launch_backend": _launch_backend_payload(backend_name, launch_spec),
        "runtime_metadata": {
            "key": runtime_key,
            "attached": bool(runtime_key != "not_applicable" and run_result.get(runtime_key)),
        },
        "artifacts": {
            "keys": sorted(str(key) for key in (run_result.get("artifacts") or {}).keys()),
        },
        "diagnostics": {
            "mess_placement": _diagnostic_summary(run_result.get("mess_placement_diagnostics")),
            "placement": _diagnostic_summary(run_result.get("placement_diagnostics")),
        },
        "capabilities": {
            "visual_artifacts": cleanup_backend_supports_visual_artifacts(backend_name),
            "snapshot_writer": port.supports_visual_snapshots(),
            "robot_view_writer": port.supports_robot_views(),
        },
        "generated_mess": {
            "requested_count": port.requested_mess_count(),
            "actual_count": _optional_int(runtime_evidence["generated_mess_count"]),
        },
        "robot": _robot_evidence(run_result, runtime_evidence),
        "agent_facing": False,
        "private_manifest_exposed_to_agent": False,
    }


def _launch_backend_spec_for_implementation(backend_name: str) -> BackendSpec | None:
    for spec in BACKEND_SPECS.values():
        if spec.implementation_backend == backend_name:
            return spec
    return None


def _launch_backend_payload(backend_name: str, launch_spec: Any | None) -> dict[str, Any]:
    if launch_spec is not None:
        return {
            "id": launch_spec.id,
            "label": launch_spec.label,
            "resource_kind": launch_spec.resource_kind,
        }
    if backend_name == SYNTHETIC_BACKEND:
        return {
            "id": "not_applicable",
            "label": "Synthetic cleanup backend",
            "resource_kind": "in_process",
        }
    return {
        "id": "unknown",
        "label": "Unknown backend",
        "resource_kind": "unknown",
    }


def _diagnostic_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "unavailable", "count": 0}
    if isinstance(value, (list, tuple, set)):
        return {"status": "available", "count": len(value)}
    if isinstance(value, dict):
        return {"status": "available", "count": len(value)}
    return {"status": "available", "count": 1}


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _robot_evidence(
    run_result: dict[str, Any], runtime_evidence: HouseholdRuntimeEvidence
) -> dict[str, Any]:
    robot = run_result.get("robot") or runtime_evidence["robot"]
    robot_import = run_result.get("robot_import") or runtime_evidence["robot_import"]
    payload = {
        "present": isinstance(robot, dict),
        "robot_name": "",
        "import_status": "",
    }
    if isinstance(robot, dict):
        payload["robot_name"] = str(robot.get("robot_name") or "")
    if isinstance(robot_import, dict):
        payload["import_status"] = str(robot_import.get("status") or "")
    return payload


def _attach_robot_metadata(
    run_result: dict[str, Any], runtime_evidence: HouseholdRuntimeEvidence
) -> None:
    robot = runtime_evidence["robot"]
    if robot is None:
        return
    run_result["robot"] = robot
    run_result["robot_import"] = runtime_evidence["robot_import"]
    run_result["robot_name"] = robot.get("robot_name")
