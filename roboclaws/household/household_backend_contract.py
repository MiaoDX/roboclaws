from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.household.artifact_paths import home_relative_paths
from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.isaac_lab_backend import (
    ISAACLAB_SUBPROCESS_BACKEND,
    IsaacLabSubprocessBackend,
)
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.semantic_timeline import (
    record_robot_view_step as _record_robot_view_step,
)
from roboclaws.household.subprocess_backend import (
    MOLMOSPACES_SUBPROCESS_BACKEND,
    MolmoSpacesSubprocessBackend,
)
from roboclaws.household.types import CleanupScenario, PrivateScoringManifest
from roboclaws.launch.backends import (
    BACKEND_SPECS,
    SYNTHETIC_CLEANUP_IMPLEMENTATION_BACKEND,
    BackendSpec,
)

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

    def __init__(self, scenario: CleanupScenario | None = None, backend: Any | None = None):
        self.backend = backend or ApiSemanticCleanupBackend(scenario or build_cleanup_scenario())

    @property
    def scenario(self) -> CleanupScenario:
        return self.backend.scenario

    def backend_name(self) -> str:
        return cleanup_backend_name(self.backend)

    def supports_visual_snapshots(self) -> bool:
        return callable(getattr(self.backend, "write_snapshot", None))

    def supports_robot_views(self) -> bool:
        return callable(getattr(self.backend, "write_robot_views", None))

    def requested_generated_mess_count(self) -> int | None:
        requested = getattr(self.backend, "requested_generated_mess_count", None)
        try:
            return int(requested)
        except (TypeError, ValueError):
            return None

    def object_locations(self) -> dict[str, str]:
        return self.backend.object_locations()

    def final_locations(self, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        return dict(fallback or self.object_locations())

    def write_visual_snapshot(self, output_path: Path, *, title: str) -> Path | None:
        writer = getattr(self.backend, "write_snapshot", None)
        if not callable(writer):
            return None
        return writer(output_path, title=title)

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
            backend=self.backend,
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
        backend_close = getattr(self.backend, "close", None)
        if not callable(backend_close):
            return
        try:
            backend_close()
        except Exception:
            pass

    def observe(self) -> dict[str, Any]:
        return self.backend.observe()

    def navigate_to_object(self, object_id: str) -> dict[str, Any]:
        return self.backend.navigate_to_object(object_id=object_id)

    def navigate_to_waypoint(self, waypoint: dict[str, Any]) -> dict[str, Any]:
        navigator = getattr(self.backend, "navigate_to_waypoint", None)
        if callable(navigator):
            return navigator(waypoint=waypoint)
        fixture_ids = waypoint.get("fixture_ids") or []
        fixture_id = str(fixture_ids[0]) if fixture_ids else ""
        if not fixture_id:
            return {
                "ok": True,
                "tool": "navigate_to_waypoint",
                "status": "ok",
                "state_mutation": "agent_pose_semantic",
                "backend_pose_mutation_available": False,
            }
        navigation = dict(self.backend.navigate_to_receptacle(receptacle_id=fixture_id))
        navigation["tool"] = "navigate_to_waypoint"
        navigation["waypoint_id"] = str(waypoint.get("waypoint_id") or "")
        navigation["fallback_receptacle_id"] = fixture_id
        navigation["backend_pose_mutation_available"] = True
        return navigation

    def navigate_to_relative_pose(
        self,
        *,
        forward_m: float = 0.0,
        lateral_m: float = 0.0,
        yaw_delta_deg: float = 0.0,
    ) -> dict[str, Any]:
        navigator = getattr(self.backend, "navigate_to_relative_pose", None)
        if callable(navigator):
            return navigator(
                forward_m=forward_m,
                lateral_m=lateral_m,
                yaw_delta_deg=yaw_delta_deg,
            )
        return {
            "ok": False,
            "tool": "navigate_to_relative_pose",
            "status": "blocked_capability",
            "error_reason": "relative_navigation_unavailable",
            "backend": self.backend_name(),
            "backend_pose_mutation_available": False,
        }

    def navigate_to_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self.backend.navigate_to_receptacle(receptacle_id=receptacle_id)

    def pick(self, object_id: str) -> dict[str, Any]:
        return self.backend.pick(object_id=object_id)

    def open_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self.backend.open_receptacle(receptacle_id=receptacle_id)

    def place(self, receptacle_id: str) -> dict[str, Any]:
        return self.backend.place(receptacle_id=receptacle_id)

    def place_inside(self, receptacle_id: str) -> dict[str, Any]:
        return self.backend.place_inside(receptacle_id=receptacle_id)

    def close_receptacle(self, receptacle_id: str) -> dict[str, Any]:
        return self.backend.close_receptacle(receptacle_id=receptacle_id)

    def done(self, reason: str = "") -> dict[str, Any]:
        return self.backend.done(reason=reason)

    def attach_runtime_metadata(self, run_result: dict[str, Any], *, run_dir: Path) -> None:
        attach_cleanup_backend_runtime_metadata(
            run_result=run_result,
            backend=self.backend,
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


def cleanup_backend_name(backend: Any, *, override: str = "") -> str:
    if override:
        return override
    explicit = getattr(backend, "backend", "")
    if explicit:
        return str(explicit)
    return SYNTHETIC_BACKEND


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
    backend: Any,
    backend_name: str | None = None,
    run_dir: Path,
) -> None:
    resolved_backend_name = backend_name or cleanup_backend_name(backend)
    runtime_key = "not_applicable"
    if resolved_backend_name == ISAACLAB_SUBPROCESS_BACKEND:
        _attach_isaac_runtime(run_result=run_result, backend=backend, run_dir=run_dir)
        runtime_key = "isaac_runtime"
    elif resolved_backend_name == MOLMOSPACES_SUBPROCESS_BACKEND:
        _attach_molmospaces_runtime(run_result=run_result, backend=backend)
        runtime_key = "molmospaces_runtime"
    if resolved_backend_name in VISUAL_BACKENDS:
        _attach_common_diagnostics(run_result, backend)
    _attach_cleanup_backend_evidence(
        run_result=run_result,
        backend=backend,
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


def _attach_common_diagnostics(run_result: dict[str, Any], backend: Any) -> None:
    mess_diagnostics = getattr(backend, "mess_placement_diagnostics", None)
    placement_diagnostics = getattr(backend, "placement_diagnostics", None)
    if mess_diagnostics is not None:
        run_result["mess_placement_diagnostics"] = mess_diagnostics
    if placement_diagnostics is not None:
        run_result["placement_diagnostics"] = placement_diagnostics


def _attach_molmospaces_runtime(*, run_result: dict[str, Any], backend: Any) -> None:
    run_result["molmospaces_runtime"] = home_relative_paths(
        {
            "python_executable": str(getattr(backend, "python_executable", "")),
            "runtime": getattr(backend, "runtime", {}),
            "model_stats": getattr(backend, "model_stats", {}),
            "scene_xml": getattr(backend, "scene_xml", ""),
            "metadata_object_count": getattr(backend, "metadata_object_count", None),
            "requested_generated_mess_count": getattr(
                backend, "requested_generated_mess_count", None
            ),
            "generated_mess_count": getattr(backend, "generated_mess_count", None),
        }
    )
    _attach_robot_metadata(run_result, backend)


def _attach_isaac_runtime(
    *,
    run_result: dict[str, Any],
    backend: Any,
    run_dir: Path,
) -> None:
    isaac_scene_index_path = run_dir / "isaac_scene_index.json"
    scene_index_artifact = getattr(backend, "scene_index_artifact_payload", None)
    scene_index_payload = scene_index_artifact() if callable(scene_index_artifact) else {}
    if scene_index_payload:
        isaac_scene_index_path.write_text(
            json.dumps(scene_index_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        run_result.setdefault("artifacts", {})["isaac_scene_index"] = str(isaac_scene_index_path)
    run_result["isaac_runtime"] = home_relative_paths(
        {
            "python_executable": str(getattr(backend, "python_executable", "")),
            "runtime": getattr(backend, "runtime", {}),
            "scenario_source": getattr(backend, "scenario_source", ""),
            "scene_usd": getattr(backend, "scene_usd", ""),
            "scene_index": getattr(backend, "scene_index", None),
            "scene_index_artifact": str(isaac_scene_index_path) if scene_index_payload else "",
            "object_index_count": len(getattr(backend, "object_index", {})),
            "receptacle_index_count": len(getattr(backend, "receptacle_index", {})),
            "object_index": getattr(backend, "object_index", {}),
            "receptacle_index": getattr(backend, "receptacle_index", {}),
            "scene_index_diagnostics": getattr(backend, "scene_index_diagnostics", {}),
            "scene_binding_diagnostics": getattr(backend, "scene_binding_diagnostics", {}),
            "segmentation": getattr(backend, "segmentation", {}),
            "scene_load": getattr(backend, "scene_load", {}),
            "mapping_gaps": getattr(backend, "current_mapping_gaps", []),
            "snapshot_artifacts": getattr(backend, "snapshot_artifacts", []),
            "semantic_pose_state": getattr(backend, "semantic_pose_state", {}),
            "semantic_pose_view_capture": getattr(backend, "semantic_pose_view_capture", {}),
            "robot": getattr(backend, "robot", None),
            "robot_import": getattr(backend, "robot_import", {}),
            "requested_generated_mess_count": getattr(
                backend, "requested_generated_mess_count", None
            ),
            "generated_mess_count": getattr(backend, "generated_mess_count", None),
        }
    )
    _attach_robot_metadata(run_result, backend)


def _attach_cleanup_backend_evidence(
    *,
    run_result: dict[str, Any],
    backend: Any,
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
            "snapshot_writer": callable(getattr(backend, "write_snapshot", None)),
            "robot_view_writer": callable(getattr(backend, "write_robot_views", None)),
        },
        "generated_mess": {
            "requested_count": _optional_int(
                getattr(backend, "requested_generated_mess_count", None)
            ),
            "actual_count": _optional_int(getattr(backend, "generated_mess_count", None)),
        },
        "robot": _robot_evidence(run_result, backend),
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


def _robot_evidence(run_result: dict[str, Any], backend: Any) -> dict[str, Any]:
    robot = run_result.get("robot") or getattr(backend, "robot", None)
    robot_import = run_result.get("robot_import") or getattr(backend, "robot_import", {})
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


def _attach_robot_metadata(run_result: dict[str, Any], backend: Any) -> None:
    robot = getattr(backend, "robot", None)
    if robot is None:
        return
    run_result["robot"] = robot
    run_result["robot_import"] = getattr(backend, "robot_import", {})
    run_result["robot_name"] = robot.get("robot_name")
