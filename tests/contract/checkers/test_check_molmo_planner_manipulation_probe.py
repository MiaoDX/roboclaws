from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from roboclaws.household.manipulation_contract import MANIPULATION_PROBE_CONTRACT
from roboclaws.household.manipulation_provenance import (
    blocked_planner_probe_evidence,
    planner_backed_probe_evidence,
)
from roboclaws.household.rby1m_curobo_gate import (
    rby1m_curobo_gate_from_planner_probe,
)
from scripts.molmo_cleanup import planner_probe_task_sampler_diagnostics as probe_sampler

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_planner_manipulation_probe.py"
RUNNER_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "run_molmo_planner_manipulation_probe.py"


_REPORT_FLAG_LINES = {
    "blocked": "Capability Blockers\n",
    "diagnostics": "Runtime Diagnostics\n",
    "cleanup_binding": "Planner Probe Cleanup Binding\n",
    "proof_quality": "Planner Proof Quality\nProof Quality\nmulti_step_motion\n",
    "cleanup_config_blockers": "Exact task config blockers\ncleanup_scene_xml_missing\n",
    "worker_stages": "Worker Stage Timeline\n",
    "curobo_cache": "CuRobo Extension Cache\n",
    "warp_compatibility": "Warp Compatibility\n",
    "cuda_memory": "CUDA Memory Headroom\n",
    "curobo_memory_profile": "CuRobo Memory Profile\n",
    "task_sampler_robot_placement_profile": "Task Sampler Robot Placement Profile\nrelaxed\n50\n",
    "rby1m_gate": "RBY1M CuRobo Gate\n",
}


def _load_checker_module():
    spec = importlib.util.spec_from_file_location(
        "check_molmo_planner_manipulation_probe", CHECKER_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_runner_module():
    spec = importlib.util.spec_from_file_location(
        "run_molmo_planner_manipulation_probe", RUNNER_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _planner_report_policy_exception_fragment() -> str:
    return (
        "Policy Exception Diagnostics\n"
        "curobo_no_planned_trajectory\n"
        "execute_policy_run\n"
        "ValueError\n"
        "PickAndPlacePrimitive\n"
        "pre_grasp\n"
    )


def _planner_report_placement_scene_diagnostics_fragment() -> str:
    return (
        "Task Sampler Failure Diagnostics\nPickAndPlaceTaskSampler\n"
        "Planner Probe Diagnostic Views\nPlacement Scene Diagnostics\nbook/body\n12\n0.012\n"
    )


def _planner_report_post_placement_rejections_fragment() -> str:
    return (
        "Task Sampler Failure Diagnostics\nPickAndPlaceTaskSampler\n"
        "Planner Probe Diagnostic Views\nPost-Placement Candidate Rejections\n"
        "Post-Placement Rejection Views\nbook/body\n3\n"
    )


def _planner_report_body(flags: dict[str, bool]) -> str:
    body = "Planner-Backed Manipulation Probe\nManipulation Provenance\n"
    for flag, fragment in _REPORT_FLAG_LINES.items():
        if flags[flag]:
            body += fragment
    if flags["policy_exception"]:
        body += _planner_report_policy_exception_fragment()
    if flags["placement_scene_diagnostics"]:
        body += _planner_report_placement_scene_diagnostics_fragment()
    if flags["post_placement_rejections"]:
        body += _planner_report_post_placement_rejections_fragment()
    return body


def _write_report_files(
    tmp_path: Path,
    *,
    blocked: bool = False,
    diagnostics: bool = False,
    cleanup_binding: bool = False,
    rby1m_gate: bool = False,
    worker_stages: bool = False,
    curobo_cache: bool = False,
    warp_compatibility: bool = False,
    cuda_memory: bool = False,
    curobo_memory_profile: bool = False,
    policy_exception: bool = False,
    task_sampler_robot_placement_profile: bool = False,
    placement_scene_diagnostics: bool = False,
    post_placement_rejections: bool = False,
    cleanup_config_blockers: bool = False,
    proof_quality: bool = False,
) -> dict[str, str]:
    stdout = tmp_path / "planner_probe_stdout.txt"
    stderr = tmp_path / "planner_probe_stderr.txt"
    report = tmp_path / "report.html"
    stdout.write_text("{}", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    body = _planner_report_body(
        {
            "blocked": blocked,
            "diagnostics": diagnostics,
            "cleanup_binding": cleanup_binding,
            "rby1m_gate": rby1m_gate,
            "worker_stages": worker_stages,
            "curobo_cache": curobo_cache,
            "warp_compatibility": warp_compatibility,
            "cuda_memory": cuda_memory,
            "curobo_memory_profile": curobo_memory_profile,
            "policy_exception": policy_exception,
            "task_sampler_robot_placement_profile": task_sampler_robot_placement_profile,
            "placement_scene_diagnostics": placement_scene_diagnostics,
            "post_placement_rejections": post_placement_rejections,
            "cleanup_config_blockers": cleanup_config_blockers,
            "proof_quality": proof_quality,
        }
    )
    report.write_text(body, encoding="utf-8")
    return {"stdout": str(stdout), "stderr": str(stderr), "report": str(report)}


def test_runner_preserves_last_worker_stage_from_timeout_stdout() -> None:
    runner = _load_runner_module()
    stdout = "\n".join(
        [
            '{"elapsed_s": 0.01, "event": "worker_start", "stage": "worker_start"}',
            (
                '{"elapsed_s": 0.02, "event": "runtime_diagnostics", '
                '"stage": "runtime_diagnostics", "runtime_diagnostics": '
                '{"modules": {"curobo": {"available": true}}}}'
            ),
            (
                '{"elapsed_s": 0.03, "event": "rby1m_config_import_start", '
                '"stage": "rby1m_config_import"}'
            ),
        ]
    )

    payload = runner._worker_payload_from_stdout(stdout)

    assert payload["last_worker_stage"] == "rby1m_config_import"
    assert payload["runtime_diagnostics"]["modules"]["curobo"]["available"] is True
    assert [item["event"] for item in payload["worker_stage_events"]] == [
        "worker_start",
        "runtime_diagnostics",
        "rby1m_config_import_start",
    ]


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        (
            'ordinary log\n{"event": "worker_start"}\n{bad-json}\n',
            r"planner manipulation probe stdout row must contain valid JSON object: stdout:3",
        ),
        (
            'ordinary log\n["not", "an", "event"]\n',
            r"planner manipulation probe stdout row must contain a JSON object: stdout:2",
        ),
    ],
)
def test_runner_rejects_malformed_json_like_worker_stdout(
    stdout: str,
    message: str,
) -> None:
    runner = _load_runner_module()

    with pytest.raises(ValueError, match=message):
        runner._worker_payload_from_stdout(stdout)


def test_runner_configures_exact_cleanup_task_scene_and_aliases(tmp_path: Path) -> None:
    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    config = SimpleNamespace(
        scene_dataset="procthor-10k",
        data_split="train",
        task_sampler_config=SimpleNamespace(
            house_inds=[8],
            samples_per_house=20,
            max_tasks=10,
            pickup_obj_name=None,
            place_target_name=None,
        ),
        task_config=SimpleNamespace(
            pickup_obj_name=None,
            place_receptacle_name=None,
            place_target_name=None,
        ),
        task_config_preset_exp="stale",
        task_config_preset_scn="stale",
    )
    args = SimpleNamespace(
        cleanup_scene_xml=str(scene_xml),
        cleanup_object_id="observed_001",
        cleanup_target_receptacle_id="sink_01",
        cleanup_source_receptacle_id="counter_01",
        cleanup_planner_object_id="pickup/body",
        cleanup_planner_target_receptacle_id="sink/body",
        cleanup_tools="pick,place",
    )

    result = probe_sampler.configure_exact_cleanup_task(config, args)

    assert result["applied"] is True
    assert config.scene_dataset == str(scene_xml)
    assert config.data_split == "val"
    assert config.task_sampler_config.house_inds == [0]
    assert config.task_sampler_config.max_tasks == 1
    assert config.task_config.pickup_obj_name == "pickup/body"
    assert config.task_config.place_receptacle_name == "sink/body"
    assert config.task_config_preset_exp is None
    assert config.task_config_preset_scn is None


def test_runner_exact_cleanup_task_sampler_adapter_forces_target() -> None:
    class FakeObjectManager:
        def get_object_by_name(self, name: str) -> object:
            assert name == "sink/body"
            return object()

    class FakeSampler:
        place_receptacle_name = None

        def __init__(self) -> None:
            self.candidate_objects = []

        def reset(self):
            self.candidate_objects = [
                SimpleNamespace(name="pickup/body"),
                SimpleNamespace(name="other/body"),
            ]

        def _select_pickup_object(self, env):
            return [item.name for item in self.candidate_objects]

        def _get_place_target_candidates(self, env, pickup_obj_name, supporting_geom_id):
            return ["random/target"]

        def _prepare_place_target(
            self,
            env,
            place_target_name,
            pickup_obj_name,
            pickup_obj_pos,
            supporting_geom_id,
        ):
            return False

    sampler = FakeSampler()
    env = SimpleNamespace(current_batch_index=0, object_managers=[FakeObjectManager()])

    result = probe_sampler.apply_exact_cleanup_task_sampler_adapter(
        sampler,
        {
            "planner_object_id": "pickup/body",
            "planner_target_receptacle_id": "sink/body",
            "target_receptacle_id": "sink_01",
        },
    )

    assert result["applied"] is True
    assert sampler._get_place_target_candidates(env, "pickup/body", 1) == ["sink/body"]
    assert sampler._prepare_place_target(env, "ignored", "pickup/body", None, 1) is True
    assert sampler.place_receptacle_name == "sink/body"
    sampler.reset()
    assert sampler._select_pickup_object(env) == ["pickup/body"] * 3
    assert [item.name for item in sampler.candidate_objects] == ["pickup/body"] * 3
    binding = result["exact_pickup_candidate_binding"]
    assert binding["action"] == "filtered_to_requested_candidate"
    assert binding["retry_budget"] == 3
    assert binding["retry_budget_applied"] is True
    assert binding["requested_present_before"] is True
    assert binding["candidate_count_before"] == 2
    assert binding["candidate_count_after"] == 3


def test_runner_exact_cleanup_task_sampler_adapter_injects_absent_pickup() -> None:
    class FakeSampler:
        def reset(self):
            self.candidate_objects = [SimpleNamespace(name="other/body")]

        def _select_pickup_object(self, env):
            return [item.name for item in self.candidate_objects]

        def _get_place_target_candidates(self, env, pickup_obj_name, supporting_geom_id):
            return ["random/target"]

        def _prepare_place_target(
            self,
            env,
            place_target_name,
            pickup_obj_name,
            pickup_obj_pos,
            supporting_geom_id,
        ):
            return True

    sampler = FakeSampler()
    result = probe_sampler.apply_exact_cleanup_task_sampler_adapter(
        sampler,
        {
            "planner_object_id": "pickup/body",
            "planner_target_receptacle_id": "sink/body",
        },
    )

    sampler.reset()
    assert sampler._select_pickup_object(None) == ["pickup/body"] * 3

    assert [item.name for item in sampler.candidate_objects] == ["pickup/body"] * 3
    binding = result["exact_pickup_candidate_binding"]
    assert binding["action"] == "injected_requested_candidate_name"
    assert binding["retry_budget"] == 3
    assert binding["retry_budget_applied"] is True
    assert binding["requested_present_before"] is False
    assert binding["requested_present_after"] is True


def test_runner_worker_exception_context_preserves_sampler_adapter(tmp_path: Path) -> None:
    runner = _load_runner_module()
    args = SimpleNamespace(
        cleanup_scene_xml=str(tmp_path / "scene.xml"),
        cleanup_object_id="observed_001",
        cleanup_target_receptacle_id="sink_01",
        cleanup_source_receptacle_id="counter_01",
        cleanup_planner_object_id="pickup/body",
        cleanup_planner_target_receptacle_id="sink/body",
        cleanup_tools="navigate_to_object,pick,navigate_to_receptacle,place",
    )
    cleanup_task_config = {
        "schema": "planner_probe_exact_cleanup_task_config_v1",
        "applied": True,
        "scene_xml": str(tmp_path / "scene.xml"),
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
    }
    sampler_adapter = {
        "schema": "planner_probe_exact_cleanup_task_sampler_adapter_v1",
        "applied": True,
        "task_sampler_class": "FakeSampler",
        "planner_target_receptacle_id": "sink/body",
    }

    runner._WORKER_EXCEPTION_CONTEXT.clear()
    runner._record_worker_exception_context(
        cleanup_task_config=cleanup_task_config,
        cleanup_task_sampler_adapter=sampler_adapter,
        requested_cleanup_primitive_binding={
            "requested": True,
            "planner_object_id": "pickup/body",
            "planner_target_receptacle_id": "sink/body",
        },
    )
    context = runner._worker_exception_probe_context(args)

    assert context["cleanup_task_config"] == cleanup_task_config
    assert context["cleanup_task_sampler_adapter"] == sampler_adapter
    assert context["requested_cleanup_primitive_binding"]["planner_target_receptacle_id"] == (
        "sink/body"
    )


def test_runner_task_sampler_failure_diagnostics_records_robot_placement() -> None:
    class FakeTaskConfig:
        pickup_obj_name = "book/body"

    class FakeSamplerConfig:
        base_pose_sampling_radius_range = (0.0, 0.7)
        robot_safety_radius = 0.15
        check_robot_placement_visibility = True
        max_robot_placement_attempts = 10

    class FakeConfig:
        task_config = FakeTaskConfig()
        task_sampler_config = FakeSamplerConfig()

    class FakeObjectManager:
        def get_object_by_name(self, name: str):
            assert name == "book/body"
            return SimpleNamespace(position=[1.0, 2.0, 3.0])

    class FakeSampler:
        config = FakeConfig()

        def __init__(self) -> None:
            self.reported: list[tuple[str, str]] = []
            self.removed: list[str] = []

        def _sample_and_place_robot(self, env):
            raise RuntimeError("placement blocked")

        def report_asset_failure(self, asset_uid, reason):
            self.reported.append((asset_uid, reason))

        def _remove_candidate_object(self, object_name):
            self.removed.append(object_name)

        def get_asset_uid_from_object(self, env, object_name):
            assert object_name == "book/body"
            return "asset-book"

    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(sampler)
    env = SimpleNamespace(current_batch_index=0, object_managers=[FakeObjectManager()])

    with pytest.raises(RuntimeError, match="placement blocked"):
        sampler._sample_and_place_robot(env)
    sampler.report_asset_failure("asset-book", "robot placement failed")
    sampler._remove_candidate_object("book/body")

    assert diagnostics["applied"] is True
    assert diagnostics["robot_placement_attempt_count"] == 1
    assert diagnostics["robot_placement_failure_count"] == 1
    assert diagnostics["asset_failure_count"] == 1
    assert diagnostics["candidate_removal_count"] == 1
    assert diagnostics["last_robot_placement_failure"]["pickup_obj_name"] == "book/body"
    assert diagnostics["last_robot_placement_failure"]["asset_uid"] == "asset-book"
    assert diagnostics["last_robot_placement_failure"]["message"] == "placement blocked"
    assert diagnostics["robot_placement_config"]["robot_safety_radius"] == 0.15


def test_runner_task_sampler_failure_diagnostics_captures_post_placement_view(
    tmp_path: Path,
) -> None:
    runner = _load_runner_module()
    runner._WORKER_EXCEPTION_CONTEXT.clear()

    class FakeSampler:
        config = SimpleNamespace(task_config=SimpleNamespace(pickup_obj_name="book/body"))

        def _sample_and_place_robot(self, env):
            return True

    class FakeRegistry:
        def __init__(self) -> None:
            self.updated = False

        def keys(self):
            return ["wrist_camera_l", "head_camera"]

        def update_all_cameras(self, env) -> list[str]:
            self.updated = True
            return ["head_camera"]

    class FakeEnv:
        def __init__(self) -> None:
            self.camera_manager = SimpleNamespace(registry=FakeRegistry())

        def render_rgb_frame(self, camera_name: str):
            assert camera_name == "head_camera"
            return np.full((3, 4, 3), 64, dtype=np.uint8)

    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(
        sampler,
        output_dir=tmp_path,
        record_exception_context=runner._record_worker_exception_context,
    )

    assert sampler._sample_and_place_robot(FakeEnv()) is True

    artifacts = diagnostics["image_artifacts"]
    assert list(artifacts) == ["post_placement_attempt_001_head_camera"]
    assert (tmp_path / artifacts["post_placement_attempt_001_head_camera"]).is_file()
    assert diagnostics["robot_placement_attempts"][0]["image_artifacts"] == artifacts
    assert runner._WORKER_EXCEPTION_CONTEXT["image_artifacts"] == artifacts


def test_runner_relaxed_task_sampler_profile_overrides_actual_place_robot_near_call() -> None:
    class FakeSamplerConfig:
        base_pose_sampling_radius_range = (0.0, 0.7)
        robot_safety_radius = 0.35
        check_robot_placement_visibility = True
        max_robot_placement_attempts = 10

    config = SimpleNamespace(task_sampler_config=FakeSamplerConfig())
    args = SimpleNamespace(task_sampler_robot_placement_profile="relaxed")

    profile = probe_sampler.apply_task_sampler_robot_placement_profile(config, args)

    assert profile["applied"] is True
    assert profile["before"]["robot_safety_radius"] == 0.35
    assert profile["after"]["robot_safety_radius"] == 0.15
    assert profile["after"]["check_robot_placement_visibility"] is False
    assert profile["place_robot_near_overrides"]["max_tries"] == 50

    class FakeTaskConfig:
        pickup_obj_name = "book/body"

    class FakeConfig:
        task_config = FakeTaskConfig()
        task_sampler_config = config.task_sampler_config

    class FakeSampler:
        config = FakeConfig()

        def _sample_and_place_robot(self, env):
            return env.place_robot_near(
                target=SimpleNamespace(name="book/body"),
                max_tries=10,
                sampling_radius_range=(0.0, 0.7),
                robot_safety_radius=0.35,
                check_camera_visibility=True,
            )

    seen_kwargs: dict[str, object] = {}

    def place_robot_near(**kwargs):
        seen_kwargs.update(kwargs)
        return True

    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(sampler, profile)
    env = SimpleNamespace(
        place_robot_near=place_robot_near, object_managers=[], current_batch_index=0
    )

    assert sampler._sample_and_place_robot(env) is True

    assert seen_kwargs["max_tries"] == 50
    assert seen_kwargs["sampling_radius_range"] == [0.0, 1.2]
    assert seen_kwargs["robot_safety_radius"] == 0.15
    assert seen_kwargs["check_camera_visibility"] is False
    assert diagnostics["place_robot_near_call_count"] == 1
    call = diagnostics["place_robot_near_calls"][0]
    assert call["requested"]["max_tries"] == 10
    assert call["effective"]["max_tries"] == 50
    assert call["effective"]["check_camera_visibility"] is False


def test_runner_wide_task_sampler_profile_extends_radius_and_max_tries() -> None:
    class FakeSamplerConfig:
        base_pose_sampling_radius_range = (0.0, 0.7)
        robot_safety_radius = 0.35
        check_robot_placement_visibility = True
        max_robot_placement_attempts = 10

    config = SimpleNamespace(task_sampler_config=FakeSamplerConfig())
    args = SimpleNamespace(task_sampler_robot_placement_profile="wide")

    profile = probe_sampler.apply_task_sampler_robot_placement_profile(config, args)

    assert profile["applied"] is True
    assert profile["profile"] == "wide"
    assert profile["after"]["base_pose_sampling_radius_range"] == [0.0, 2.0]
    assert profile["after"]["max_robot_placement_attempts"] == 100
    assert profile["place_robot_near_overrides"]["max_tries"] == 100
    assert profile["place_robot_near_overrides"]["sampling_radius_range"] == [0.0, 2.0]


def test_runner_records_placement_scene_diagnostics_for_place_robot_near_call() -> None:
    import numpy as np

    class FakeTaskConfig:
        pickup_obj_name = "book/body"

    class FakeSamplerConfig:
        base_pose_sampling_radius_range = (0.0, 1.2)
        robot_safety_radius = 0.15
        check_robot_placement_visibility = False
        max_robot_placement_attempts = 50

    class FakeConfig:
        task_config = FakeTaskConfig()
        task_sampler_config = FakeSamplerConfig()

    class FakeSampler:
        config = FakeConfig()

        def _sample_and_place_robot(self, env):
            return env.place_robot_near(
                target=SimpleNamespace(name="book/body", position=np.array([0.0, 0.0, 0.0])),
                max_tries=10,
                sampling_radius_range=(0.0, 1.2),
                robot_safety_radius=0.15,
                check_camera_visibility=False,
            )

    class FakeThorMap:
        px_per_m = 10

        def get_free_points(self):
            return np.array(
                [
                    [0.1, 0.0, 0.0],
                    [0.2, 0.0, 0.0],
                    [1.1, 0.0, 0.0],
                    [1.5, 0.0, 0.0],
                ]
            )

    def place_robot_near(**kwargs):
        return False

    env = SimpleNamespace(
        place_robot_near=place_robot_near,
        get_thormap=lambda agent_radius, px_per_m: FakeThorMap(),
        object_managers=[],
        current_batch_index=0,
    )
    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(sampler)

    assert sampler._sample_and_place_robot(env) is False

    assert diagnostics["placement_scene_diagnostic_count"] == 1
    scene = diagnostics["last_placement_scene_diagnostic"]
    assert scene["schema"] == "planner_probe_placement_scene_diagnostic_v1"
    assert scene["target_name"] == "book/body"
    assert scene["valid_free_point_count"] == 3
    assert scene["nearest_free_point_distance_m"] == 0.1
    assert scene["radius_band_counts"][0]["free_point_count"] == 2
    assert diagnostics["place_robot_near_calls"][0]["scene_diagnostic"] == scene


def test_runner_records_post_placement_grasp_rejections() -> None:
    class FakeSampler:
        candidate_objects = [SimpleNamespace(name="book/body")]

        def __init__(self) -> None:
            self._grasp_failure_counts: dict[str, int] = {}

        def _sample_and_place_robot(self, env):
            return None

        def report_grasp_failure(self, obj_name, max_failures=2):
            self._grasp_failure_counts[obj_name] = self._grasp_failure_counts.get(obj_name, 0) + 1
            if self._grasp_failure_counts[obj_name] > max_failures:
                self.candidate_objects = []

    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(sampler)

    sampler.report_grasp_failure("book/body", max_failures=2)
    sampler.report_grasp_failure("book/body", max_failures=2)
    sampler.report_grasp_failure("book/body", max_failures=2)

    assert diagnostics["grasp_failure_count"] == 3
    assert diagnostics["grasp_failures"][-1]["object_name"] == "book/body"
    assert diagnostics["grasp_failures"][-1]["count_after"] == 3
    assert diagnostics["grasp_failures"][-1]["removed_candidate"] is True
    assert diagnostics["grasp_failures"][-1]["candidate_count_after"] == 0


def test_runner_records_ineffective_candidate_removal_calls() -> None:
    class FakeSampler:
        candidate_objects = [
            SimpleNamespace(name="bread/body"),
            SimpleNamespace(name="mug/body"),
        ]

        def __init__(self) -> None:
            self._grasp_failure_counts: dict[str, int] = {}

        def _remove_candidate_object(self, obj_name):
            self.candidate_objects = [
                item for item in self.candidate_objects if item.name != obj_name
            ]

        def report_grasp_failure(self, obj_name, max_failures=2):
            self._grasp_failure_counts[obj_name] = self._grasp_failure_counts.get(obj_name, 0) + 1
            if self._grasp_failure_counts[obj_name] > max_failures:
                self._remove_candidate_object(obj_name)

    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(sampler)

    sampler.report_grasp_failure("unknown/body", max_failures=0)

    assert diagnostics["candidate_removal_count"] == 1
    assert diagnostics["candidate_effective_removal_count"] == 0
    assert diagnostics["candidate_name_miss_count"] == 1
    removal = diagnostics["candidate_removals"][0]
    assert removal["candidate_name_present_before"] is False
    assert removal["effective_removal"] is False
    assert diagnostics["grasp_failures"][0]["threshold_exceeded"] is True
    assert diagnostics["grasp_failures"][0]["candidate_removal_call_count_delta"] == 1


def test_runner_records_grasp_collision_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("molmo_spaces.tasks.pick_task_sampler")

    def load_grasps_for_object(object_name, num_grasps=50):
        assert object_name == "asset-book"
        assert num_grasps == 512
        return "droid", np.zeros((4, 4, 4))

    def get_noncolliding_grasp_mask(mj_model, mj_data, grasp_poses_world, batch_size):
        assert batch_size == 64
        assert len(grasp_poses_world) == 4
        return np.array([False, False, True, False])

    module.load_grasps_for_object = load_grasps_for_object
    module.get_noncolliding_grasp_mask = get_noncolliding_grasp_mask
    monkeypatch.setitem(sys.modules, "molmo_spaces.tasks.pick_task_sampler", module)

    class FakeSampler:
        config = SimpleNamespace(task_config=SimpleNamespace(pickup_obj_name="book/body"))

        def _sample_and_place_robot(self, env):
            return None

    sampler = FakeSampler()
    diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(sampler)

    _, grasps = module.load_grasps_for_object("asset-book", 512)
    module.get_noncolliding_grasp_mask(None, None, grasps, 64)

    assert "grasp_collision_diagnostics" in diagnostics["hooks"]
    assert diagnostics["grasp_load_attempt_count"] == 1
    assert diagnostics["last_grasp_load_attempt"]["cached_grasp_count"] == 4
    assert diagnostics["grasp_collision_check_count"] == 1
    check = diagnostics["last_grasp_collision_check"]
    assert check["asset_uid"] == "asset-book"
    assert check["pickup_obj_name"] == "book/body"
    assert check["grasp_pose_count"] == 4
    assert check["noncolliding_grasp_count"] == 1
    assert check["colliding_grasp_count"] == 3
    assert check["zero_noncolliding"] is False


def test_checker_accepts_blocked_capability_only_when_explicit(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="franka",
        task="pick_and_place",
        probe_mode="config_import",
        blockers=[{"code": "execution_not_attempted", "message": "not attempted"}],
    )
    evidence["runtime_diagnostics"] = {
        "python_version": "3.11.8",
        "modules": {"curobo": {"available": False, "version": None}},
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(tmp_path, blocked=True, diagnostics=True),
    }

    checker._assert_probe_result(data, tmp_path, accept_blocked_capability=True)
    with pytest.raises(AssertionError):
        checker._assert_probe_result(data, tmp_path, accept_blocked_capability=False)


def test_checker_requires_cleanup_scene_bound_when_requested(tmp_path: Path) -> None:
    checker = _load_checker_module()
    scene_xml = tmp_path / "scene.xml"
    scene_xml.write_text("<mujoco/>", encoding="utf-8")
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "HouseInvalidForTask", "message": "physics blocked"}],
        execution_attempted=True,
    )
    evidence["cleanup_task_config"] = {
        "schema": "planner_probe_exact_cleanup_task_config_v1",
        "applied": True,
        "scene_xml": str(scene_xml),
        "planner_object_id": "pickup/body",
        "planner_target_receptacle_id": "sink/body",
        "blockers": [],
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(tmp_path, blocked=True, cleanup_binding=True),
    }

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        require_cleanup_scene_bound=True,
    )

    evidence["cleanup_task_config"]["scene_xml"] = str(tmp_path / "missing.xml")
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            require_cleanup_scene_bound=True,
        )

    evidence["cleanup_task_config"]["scene_xml"] = str(scene_xml)
    evidence["cleanup_task_config"]["blockers"] = [
        {"code": "cleanup_scene_xml_missing", "message": "missing scene"}
    ]
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        cleanup_binding=True,
        cleanup_config_blockers=True,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            require_cleanup_scene_bound=True,
        )


def test_checker_rejects_api_semantic_as_planner_proof(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="franka",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="PickAndPlacePlannerPolicy",
        steps_requested=2,
        steps_executed=2,
        max_abs_qpos_delta=0.01,
    )
    evidence["primitive_provenance"] = "api_semantic"
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "planner_backed",
        "primitive_provenance": "api_semantic",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(tmp_path),
    }

    with pytest.raises(AssertionError):
        checker._assert_probe_result(data, tmp_path, require_planner_backed=True)


def test_checker_accepts_strict_planner_backed_evidence(tmp_path: Path) -> None:
    checker = _load_checker_module()
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": planner_backed_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="franka",
            task="pick_and_place",
            probe_mode="execute",
            upstream_policy_class="PickAndPlacePlannerPolicy",
            steps_requested=2,
            steps_executed=2,
            max_abs_qpos_delta=0.01,
        ),
        "artifacts": _write_report_files(tmp_path),
    }

    checker._assert_probe_result(data, tmp_path, require_planner_backed=True)


def test_checker_can_require_planner_probe_proof_quality(tmp_path: Path) -> None:
    checker = _load_checker_module()
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": planner_backed_probe_evidence(
            backend="molmospaces_subprocess",
            embodiment="franka",
            task="pick_and_place",
            probe_mode="execute",
            upstream_policy_class="PickAndPlacePlannerPolicy",
            steps_requested=2,
            steps_executed=2,
            max_abs_qpos_delta=0.01,
        ),
        "artifacts": _write_report_files(tmp_path, proof_quality=True),
    }

    checker._assert_probe_result(
        data,
        tmp_path,
        require_planner_backed=True,
        require_proof_quality=True,
        require_proof_min_steps=2,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            require_planner_backed=True,
            require_proof_quality=True,
            require_proof_min_steps=3,
        )


def test_checker_requires_cleanup_binding_report_when_evidence_exists(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="CuroboPickAndPlacePlannerPolicy",
        steps_requested=2,
        steps_executed=2,
        max_abs_qpos_delta=0.01,
    )
    evidence["sampled_task_binding"] = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "pickup/body",
        "place_receptacle_name": "sink/body",
    }
    evidence["cleanup_primitive_binding"] = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "pickup/body",
        "target_receptacle_id": "sink/body",
        "tools": ["pick", "place"],
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(tmp_path),
    }

    with pytest.raises(AssertionError):
        checker._assert_probe_result(data, tmp_path, require_planner_backed=True)

    data["artifacts"] = _write_report_files(tmp_path, cleanup_binding=True)
    checker._assert_probe_result(data, tmp_path, require_planner_backed=True)


def test_checker_accepts_rby1m_curobo_blocked_gate(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="config_import",
        blockers=[{"code": "ModuleNotFoundError", "message": "No module named 'curobo'"}],
    )
    evidence["runtime_diagnostics"] = {
        "modules": {"curobo": {"available": False, "version": None}},
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            diagnostics=True,
            rby1m_gate=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            require_rby1m_curobo_ready=True,
        )


def test_checker_requires_worker_stage_report_when_stage_events_exist(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="config_import",
        blockers=[{"code": "timeout", "message": "Probe exceeded 300.0s"}],
    )
    evidence["runtime_diagnostics"] = {
        "modules": {"curobo": {"available": True, "version": None}},
    }
    evidence["worker_stage_events"] = [
        {"event": "worker_start", "stage": "worker_start", "elapsed_s": 0.01},
        {
            "event": "rby1m_config_import_start",
            "stage": "rby1m_config_import",
            "elapsed_s": 0.02,
        },
    ]
    evidence["last_worker_stage"] = "rby1m_config_import"
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            diagnostics=True,
            rby1m_gate=True,
            worker_stages=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        diagnostics=True,
        rby1m_gate=True,
        worker_stages=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
        )


def test_checker_requires_curobo_extension_cache_report_when_requested(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="config_import",
        blockers=[{"code": "timeout", "message": "Probe exceeded 300.0s"}],
    )
    evidence["runtime_diagnostics"] = {
        "curobo_extension_cache": {
            "configured_dir": str(tmp_path / "torch_extensions"),
            "extensions": {
                "lbfgs_step_cu": {
                    "build_dir": str(tmp_path / "torch_extensions" / "lbfgs_step_cu"),
                    "so_exists": False,
                    "lock_exists": True,
                    "files": [{"name": "lock", "size_bytes": 0}],
                }
            },
        }
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            diagnostics=True,
            rby1m_gate=True,
            curobo_cache=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
        require_curobo_extension_cache=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        diagnostics=True,
        rby1m_gate=True,
        curobo_cache=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
            require_curobo_extension_cache=True,
        )


def test_checker_requires_warp_compatibility_report_when_requested(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "AttributeError", "message": "module warp has no torch"}],
        execution_attempted=True,
    )
    evidence["runtime_diagnostics"] = {
        "warp_compatibility": {
            "available": True,
            "version": "1.13.0",
            "has_torch_attr": True,
            "has_device_from_torch": True,
            "adapter": {
                "applied": True,
                "provided": ["warp.torch.device_from_torch"],
            },
        }
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            diagnostics=True,
            rby1m_gate=True,
            warp_compatibility=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
        require_warp_compatibility=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        diagnostics=True,
        rby1m_gate=True,
        warp_compatibility=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
            require_warp_compatibility=True,
        )


def test_checker_requires_cuda_memory_report_when_requested(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "OutOfMemoryError", "message": "CUDA out of memory"}],
        execution_attempted=True,
    )
    evidence["runtime_diagnostics"] = {
        "cuda_memory": {
            "available": True,
            "device_count": 1,
            "current_device_index": 0,
            "current_snapshot": {
                "stage": "runtime_diagnostics",
                "device_index": 0,
                "device_name": "Fake GPU",
                "free_bytes": 268435456,
                "total_bytes": 1073741824,
                "torch_allocated_bytes": 536870912,
                "torch_reserved_bytes": 805306368,
            },
        }
    }
    evidence["cuda_memory_snapshots"] = [
        {
            "stage": "execute_policy_run_start",
            "device_index": 0,
            "device_name": "Fake GPU",
            "free_bytes": 268435456,
            "total_bytes": 1073741824,
            "torch_allocated_bytes": 536870912,
            "torch_reserved_bytes": 805306368,
        }
    ]
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            diagnostics=True,
            rby1m_gate=True,
            cuda_memory=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
        require_cuda_memory=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        diagnostics=True,
        rby1m_gate=True,
        cuda_memory=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
            require_cuda_memory=True,
        )


def test_checker_requires_curobo_memory_profile_report_when_requested(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "OutOfMemoryError", "message": "CUDA out of memory"}],
        execution_attempted=True,
    )
    evidence["curobo_memory_profile"] = {
        "profile": "low",
        "applied": True,
        "after": {
            "policy": {
                "batch_size": 1,
                "max_batch_plan_attempts": 1,
                "enable_collision_avoidance": True,
            },
            "planners": {
                "left": {
                    "num_trajopt_seeds": 1,
                    "num_ik_seeds": 16,
                    "max_attempts": 1,
                    "trajopt_tsteps": 24,
                    "enable_finetune_trajopt": False,
                }
            },
        },
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            rby1m_gate=True,
            curobo_memory_profile=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
        require_curobo_memory_profile=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        rby1m_gate=True,
        curobo_memory_profile=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
            require_curobo_memory_profile=True,
        )


def test_checker_requires_policy_exception_context_report_when_requested(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[
            {
                "code": "ValueError",
                "message": "_execute_trajectory was called with no planned trajectory",
            }
        ],
        execution_attempted=True,
    )
    evidence["policy_exception_context"] = {
        "schema": "planner_probe_policy_exception_context_v1",
        "stage": "execute_policy_run",
        "exception_type": "ValueError",
        "failure_kind": "curobo_no_planned_trajectory",
        "action_primitives": [
            {
                "primitive_class": "PickAndPlacePrimitive",
                "current_phase": "pre_grasp",
                "planned_trajectory_present": True,
                "planned_trajectory_len": 0,
                "trajectory_index": 0,
            }
        ],
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            rby1m_gate=True,
            policy_exception=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
        require_policy_exception_context=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        rby1m_gate=True,
        policy_exception=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
            require_policy_exception_context=True,
        )


def test_checker_requires_task_sampler_robot_placement_profile_report(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "HouseInvalidForTask", "message": "robot placement failed"}],
        execution_attempted=True,
    )
    evidence["task_sampler_robot_placement_profile"] = {
        "profile": "relaxed",
        "requested": True,
        "applied": True,
        "place_robot_near_overrides": {"max_tries": 50},
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            rby1m_gate=True,
            task_sampler_robot_placement_profile=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        rby1m_gate=True,
        task_sampler_robot_placement_profile=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
        )


def test_checker_requires_placement_scene_diagnostics_report(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "HouseInvalidForTask", "message": "robot placement failed"}],
        execution_attempted=True,
    )
    evidence["task_sampler_failure_diagnostics"] = {
        "applied": True,
        "task_sampler_class": "PickAndPlaceTaskSampler",
        "robot_placement_attempts": [],
        "placement_scene_diagnostics": [
            {
                "schema": "planner_probe_placement_scene_diagnostic_v1",
                "call_index": 1,
                "target_name": "book/body",
                "valid_free_point_count": 12,
                "valid_neighborhood_fraction": 0.012,
            }
        ],
        "last_placement_scene_diagnostic": {
            "target_name": "book/body",
            "valid_free_point_count": 12,
            "valid_neighborhood_fraction": 0.012,
        },
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            rby1m_gate=True,
            diagnostics=True,
            placement_scene_diagnostics=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        rby1m_gate=True,
        diagnostics=True,
        placement_scene_diagnostics=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
        )


def test_checker_requires_post_placement_rejection_report(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = blocked_planner_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="rby1m",
        task="pick_and_place",
        probe_mode="execute",
        blockers=[{"code": "HouseInvalidForTask", "message": "candidate removed"}],
        execution_attempted=True,
    )
    evidence["task_sampler_failure_diagnostics"] = {
        "applied": True,
        "task_sampler_class": "PickAndPlaceTaskSampler",
        "robot_placement_attempts": [],
        "grasp_failure_count": 3,
        "grasp_failures": [
            {
                "object_name": "book/body",
                "count_before": 2,
                "count_after": 3,
                "max_failures": 2,
                "candidate_count_before": 1,
                "candidate_count_after": 0,
                "removed_candidate": True,
            }
        ],
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "blocked_capability",
        "primitive_provenance": "blocked_capability",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(
            tmp_path,
            blocked=True,
            rby1m_gate=True,
            post_placement_rejections=True,
        ),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    checker._assert_probe_result(
        data,
        tmp_path,
        accept_blocked_capability=True,
        accept_rby1m_curobo_blocked=True,
    )
    data["artifacts"] = _write_report_files(
        tmp_path,
        blocked=True,
        rby1m_gate=True,
        post_placement_rejections=False,
    )
    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            accept_blocked_capability=True,
            accept_rby1m_curobo_blocked=True,
        )


def test_checker_rejects_franka_as_rby1m_curobo_ready(tmp_path: Path) -> None:
    checker = _load_checker_module()
    evidence = planner_backed_probe_evidence(
        backend="molmospaces_subprocess",
        embodiment="franka",
        task="pick_and_place",
        probe_mode="execute",
        upstream_policy_class="PickAndPlacePlannerPolicy",
        steps_requested=2,
        steps_executed=2,
        max_abs_qpos_delta=0.01,
    )
    evidence["runtime_diagnostics"] = {
        "modules": {"curobo": {"available": True, "version": "1.0.0"}},
    }
    data = {
        "contract": MANIPULATION_PROBE_CONTRACT,
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "manipulation_evidence": evidence,
        "artifacts": _write_report_files(tmp_path, diagnostics=True, rby1m_gate=True),
    }
    data["rby1m_curobo_gate"] = rby1m_curobo_gate_from_planner_probe(data)

    with pytest.raises(AssertionError):
        checker._assert_probe_result(
            data,
            tmp_path,
            require_planner_backed=True,
            require_rby1m_curobo_ready=True,
        )
