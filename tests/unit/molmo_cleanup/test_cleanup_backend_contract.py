from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from roboclaws.household.backend import ApiSemanticCleanupBackend
from roboclaws.household.household_backend_contract import (
    CLEANUP_BACKEND_EVIDENCE_SCHEMA,
    SYNTHETIC_BACKEND,
    HouseholdBackendSession,
    attach_cleanup_backend_runtime_metadata,
    build_household_backend_session,
    cleanup_backend_name,
)
from roboclaws.household.scenario import build_cleanup_scenario


class _FacadeVisualBackend(ApiSemanticCleanupBackend):
    backend = "molmospaces_subprocess"
    requested_generated_mess_count = "4"

    def __init__(self) -> None:
        super().__init__(build_cleanup_scenario(seed=3))
        self.closed = False

    def write_snapshot(self, output_path: Path, *, title: str) -> Path:
        output_path.write_text(title, encoding="utf-8")
        return output_path

    def write_robot_views(
        self,
        output_dir: Path,
        *,
        label: str,
        focus_object_id: str | None = None,
        focus_receptacle_id: str | None = None,
        camera_yaw_offset_deg: float = 0.0,
        camera_pitch_offset_deg: float = 0.0,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        views = {}
        for key in ("fpv", "chase"):
            path = output_dir / f"{label}_{key}.png"
            path.write_bytes(b"fake png")
            views[key] = str(path)
        return {
            "ok": True,
            "robot_pose": {"x": 0.0, "y": 0.0},
            "robot_trajectory": [],
            "view_variant": "test",
            "view_provenance": "test",
            "camera_control_contract": {},
            "focus": {
                "has_focus": bool(focus_object_id or focus_receptacle_id),
                "object_id": focus_object_id,
                "receptacle_id": focus_receptacle_id,
            },
            "room_outline_count": 0,
            "views": views,
        }

    def close(self) -> None:
        self.closed = True


def test_cleanup_backend_name_uses_explicit_backend_id() -> None:
    backend = SimpleNamespace(backend="molmospaces_subprocess")

    assert cleanup_backend_name(backend) == "molmospaces_subprocess"
    assert cleanup_backend_name(backend, override="isaaclab_subprocess") == "isaaclab_subprocess"
    assert cleanup_backend_name(SimpleNamespace()) == SYNTHETIC_BACKEND


def test_synthetic_backend_factory_can_build_baseline_scenario(tmp_path: Path) -> None:
    session = build_household_backend_session(
        backend_name=SYNTHETIC_BACKEND,
        run_dir=tmp_path,
        seed=7,
        generated_mess_count=0,
    )

    assert isinstance(session, HouseholdBackendSession)
    assert session.backend_name() == SYNTHETIC_BACKEND
    assert session.backend.scenario.private_manifest.targets == ()
    assert session.backend.scenario.private_manifest.success_threshold == 0


def test_molmospaces_backend_factory_forwards_generated_mess_manifest_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from roboclaws.household import household_backend_contract

    calls: list[dict[str, Any]] = []

    class FakeMolmoSpacesBackend:
        backend = "molmospaces_subprocess"

        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            self.scenario = build_cleanup_scenario(seed=3)

    monkeypatch.setattr(
        household_backend_contract,
        "MolmoSpacesSubprocessBackend",
        FakeMolmoSpacesBackend,
    )
    manifest_path = tmp_path / "generated_mess_manifest.json"

    build_household_backend_session(
        backend_name=household_backend_contract.MOLMOSPACES_SUBPROCESS_BACKEND,
        run_dir=tmp_path,
        generated_mess_count=1,
        generated_mess_manifest_path=manifest_path,
    )

    assert calls[0]["generated_mess_manifest_path"] == manifest_path


def test_synthetic_runtime_metadata_attaches_normalized_backend_evidence(
    tmp_path: Path,
) -> None:
    backend = SimpleNamespace(backend=SYNTHETIC_BACKEND)
    run_result = {"artifacts": {}}

    attach_cleanup_backend_runtime_metadata(
        run_result=run_result,
        backend=backend,
        run_dir=tmp_path,
    )

    evidence = run_result["cleanup_backend_evidence"]
    assert evidence["schema"] == CLEANUP_BACKEND_EVIDENCE_SCHEMA
    assert evidence["implementation_backend"] == SYNTHETIC_BACKEND
    assert evidence["launch_backend"]["id"] == "not_applicable"
    assert evidence["launch_backend"]["resource_kind"] == "in_process"
    assert evidence["runtime_metadata"] == {"key": "not_applicable", "attached": False}
    assert evidence["capabilities"]["visual_artifacts"] is False
    assert evidence["agent_facing"] is False
    assert evidence["private_manifest_exposed_to_agent"] is False
    assert "molmospaces_runtime" not in run_result
    assert "isaac_runtime" not in run_result


def test_cleanup_backend_session_exposes_optional_backend_capabilities(
    tmp_path: Path,
) -> None:
    backend = _FacadeVisualBackend()
    session = HouseholdBackendSession(backend.scenario, backend=backend)

    assert session.scenario is backend.scenario
    assert session.supports_visual_snapshots() is True
    assert session.supports_robot_views() is True
    assert session.requested_generated_mess_count() == 4
    assert session.object_locations() == backend.object_locations()
    assert session.final_locations({"apple_1": "sink_01"}) == {"apple_1": "sink_01"}

    snapshot_path = session.write_visual_snapshot(tmp_path / "snapshot.png", title="Snapshot")
    assert snapshot_path == tmp_path / "snapshot.png"
    assert snapshot_path.read_text(encoding="utf-8") == "Snapshot"

    steps: list[dict[str, Any]] = []
    next_index = session.record_robot_view_step(
        steps=steps,
        output_dir=tmp_path,
        index=0,
        action="before",
        label_suffix="before",
        focus_object_id="apple_1",
    )
    assert next_index == 1
    assert steps[0]["label"] == "0000_before"
    assert steps[0]["views"]["fpv"] == "robot_views/0000_before_fpv.png"

    session.close()
    assert backend.closed is True


def test_molmospaces_runtime_metadata_attaches_common_backend_payload(tmp_path: Path) -> None:
    backend = SimpleNamespace(
        backend="molmospaces_subprocess",
        python_executable=tmp_path / "python",
        runtime={"runtime": "fake"},
        model_stats={"object_count": 3},
        scene_xml=str(tmp_path / "scene.xml"),
        metadata_object_count=3,
        requested_generated_mess_count=5,
        generated_mess_count=4,
        mess_placement_diagnostics=[{"object_id": "apple_1"}],
        placement_diagnostics=[{"object_id": "mug_1"}],
        robot={"robot_name": "rby1m"},
    )
    run_result = {"artifacts": {}}

    attach_cleanup_backend_runtime_metadata(
        run_result=run_result,
        backend=backend,
        run_dir=tmp_path,
    )

    assert run_result["molmospaces_runtime"]["runtime"] == {"runtime": "fake"}
    evidence = run_result["cleanup_backend_evidence"]
    assert evidence["schema"] == CLEANUP_BACKEND_EVIDENCE_SCHEMA
    assert evidence["implementation_backend"] == "molmospaces_subprocess"
    assert evidence["launch_backend"]["id"] == "mujoco"
    assert evidence["runtime_metadata"] == {"key": "molmospaces_runtime", "attached": True}
    assert evidence["diagnostics"]["mess_placement"] == {"status": "available", "count": 1}
    assert evidence["diagnostics"]["placement"] == {"status": "available", "count": 1}
    assert evidence["capabilities"]["visual_artifacts"] is True
    assert evidence["generated_mess"] == {"requested_count": 5, "actual_count": 4}
    assert evidence["robot"] == {
        "present": True,
        "robot_name": "rby1m",
        "import_status": "",
    }
    assert run_result["mess_placement_diagnostics"] == [{"object_id": "apple_1"}]
    assert run_result["placement_diagnostics"] == [{"object_id": "mug_1"}]
    assert run_result["robot_name"] == "rby1m"


def test_isaac_runtime_metadata_writes_scene_index_artifact(tmp_path: Path) -> None:
    scene_index_payload = {
        "schema": "isaac_scene_index_artifact_v1",
        "backend": "isaaclab_subprocess",
        "agent_facing": False,
        "private_manifest_exposed_to_agent": False,
    }
    backend = SimpleNamespace(
        backend="isaaclab_subprocess",
        python_executable=tmp_path / "python",
        runtime={"runtime_mode": "fake"},
        scenario_source="default_cleanup_scenario",
        scene_usd="",
        scene_index=0,
        object_index={"obj": {}},
        receptacle_index={"sink": {}},
        scene_index_diagnostics={"status": "fake"},
        scene_binding_diagnostics={"status": "placeholder_mapping"},
        segmentation={"status": "blocked_capability"},
        scene_load={"status": "fake_protocol"},
        current_mapping_gaps=[{"area": "camera_capture"}],
        snapshot_artifacts=[{"placeholder_visuals": True}],
        semantic_pose_state={"schema": "isaac_semantic_pose_state_v1"},
        semantic_pose_view_capture={},
        robot_import={"status": "missing_urdf"},
        robot={"robot_name": "rby1m"},
        requested_generated_mess_count=1,
        generated_mess_count=1,
        scene_index_artifact_payload=lambda: scene_index_payload,
    )
    run_result = {"artifacts": {}}

    attach_cleanup_backend_runtime_metadata(
        run_result=run_result,
        backend=backend,
        run_dir=tmp_path,
    )

    scene_index_path = tmp_path / "isaac_scene_index.json"
    assert json.loads(scene_index_path.read_text(encoding="utf-8")) == scene_index_payload
    assert run_result["artifacts"]["isaac_scene_index"] == str(scene_index_path)
    assert run_result["isaac_runtime"]["object_index_count"] == 1
    assert run_result["isaac_runtime"]["receptacle_index_count"] == 1
    evidence = run_result["cleanup_backend_evidence"]
    assert evidence["implementation_backend"] == "isaaclab_subprocess"
    assert evidence["launch_backend"]["id"] == "isaaclab"
    assert evidence["runtime_metadata"] == {"key": "isaac_runtime", "attached": True}
    assert evidence["artifacts"]["keys"] == ["isaac_scene_index"]
    assert evidence["robot"] == {
        "present": True,
        "robot_name": "rby1m",
        "import_status": "missing_urdf",
    }
    assert evidence["agent_facing"] is False
    assert evidence["private_manifest_exposed_to_agent"] is False
    assert run_result["robot_import"] == {"status": "missing_urdf"}
