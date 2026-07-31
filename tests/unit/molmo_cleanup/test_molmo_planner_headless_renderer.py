from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from roboclaws.household import planner_manipulation_probe_result as probe_result
from roboclaws.household import planner_probe_execution as probe_execution
from roboclaws.household import planner_probe_memory as probe_memory
from roboclaws.household import planner_probe_runtime_diagnostics as runtime
from roboclaws.household import planner_probe_sampler_contract as sampler
from roboclaws.household import planner_probe_worker_diagnostics as worker_diagnostics


def test_renderer_device_id_only_applies_to_execute_mode() -> None:
    assert (
        runtime.renderer_device_id_for_probe(
            probe_mode="execute",
            renderer_device_id=0,
        )
        == 0
    )
    assert (
        runtime.renderer_device_id_for_probe(
            probe_mode="config_import",
            renderer_device_id=0,
        )
        is None
    )
    assert (
        runtime.renderer_device_id_for_probe(
            probe_mode="execute",
            renderer_device_id=-1,
        )
        is None
    )


def test_configure_headless_renderer_env_sets_egl(monkeypatch) -> None:
    monkeypatch.delenv("MUJOCO_GL", raising=False)
    monkeypatch.delenv("PYOPENGL_PLATFORM", raising=False)
    monkeypatch.delenv("ROBOCLAWS_MOLMOSPACES_RENDERER_DEVICE_ID", raising=False)

    runtime.configure_headless_renderer_env(Namespace(probe_mode="execute", renderer_device_id=0))

    assert "egl" == runtime.os.environ["MUJOCO_GL"]
    assert "egl" == runtime.os.environ["PYOPENGL_PLATFORM"]
    assert "0" == runtime.os.environ["ROBOCLAWS_MOLMOSPACES_RENDERER_DEVICE_ID"]


def test_patch_renderer_constructor_injects_missing_device_id() -> None:
    calls: list[dict[str, Any]] = []

    class FakeRenderer:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    env_module = SimpleNamespace(MjOpenGLRenderer=FakeRenderer)

    runtime.patch_renderer_constructor(env_module, renderer_device_id=0)

    env_module.MjOpenGLRenderer()
    env_module.MjOpenGLRenderer(device_id=None)
    env_module.MjOpenGLRenderer(device_id=2)

    assert calls[0]["device_id"] == 0
    assert calls[1]["device_id"] == 0
    assert calls[2]["device_id"] == 2
    assert env_module.MjOpenGLRenderer._roboclaws_renderer_adapter is True
    assert env_module.MjOpenGLRenderer._roboclaws_renderer_device_id == 0


def test_runtime_diagnostics_records_renderer_override(monkeypatch) -> None:
    probe = probe_memory
    monkeypatch.setenv("MUJOCO_GL", "egl")
    monkeypatch.setenv("PYOPENGL_PLATFORM", "egl")

    diagnostics = runtime.runtime_diagnostics(
        Namespace(
            embodiment="franka",
            probe_mode="execute",
            renderer_device_id=0,
        ),
        curobo_memory_profile_request=probe._curobo_memory_profile_request(
            Namespace(
                rby1m_curobo_memory_profile="none",
                curobo_policy_batch_size=None,
                curobo_max_batch_plan_attempts=None,
                curobo_num_trajopt_seeds=None,
                curobo_num_ik_seeds=None,
                curobo_max_attempts=None,
                curobo_trajopt_tsteps=None,
                curobo_disable_finetune_trajopt=False,
            )
        ),
    )

    assert diagnostics["renderer_adapter_enabled"] is True
    assert diagnostics["renderer_device_id"] == 0
    assert diagnostics["mujoco_gl_env"] == "egl"
    assert diagnostics["pyopengl_platform_env"] == "egl"


def test_cuda_memory_diagnostics_from_torch_records_headroom(monkeypatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def device_count() -> int:
            return 1

        @staticmethod
        def current_device() -> int:
            return 0

        @staticmethod
        def get_device_properties(index: int) -> SimpleNamespace:
            assert index == 0
            return SimpleNamespace(
                name="Fake GPU",
                total_memory=1024,
                major=8,
                minor=9,
            )

        @staticmethod
        def mem_get_info(index: int) -> tuple[int, int]:
            assert index == 0
            return 256, 1024

        @staticmethod
        def memory_allocated(index: int) -> int:
            assert index == 0
            return 512

        @staticmethod
        def memory_reserved(index: int) -> int:
            assert index == 0
            return 768

        @staticmethod
        def max_memory_allocated(index: int) -> int:
            assert index == 0
            return 640

        @staticmethod
        def max_memory_reserved(index: int) -> int:
            assert index == 0
            return 896

    fake_torch = SimpleNamespace(
        cuda=FakeCuda(),
        version=SimpleNamespace(cuda="12.8"),
    )

    diagnostics = runtime.cuda_memory_diagnostics_from_torch(fake_torch)
    snapshot = runtime.cuda_memory_snapshot_from_torch(
        fake_torch,
        "execute_policy_run_start",
    )

    assert diagnostics["available"] is True
    assert diagnostics["device_count"] == 1
    assert diagnostics["devices"][0]["compute_capability"] == "8.9"
    assert diagnostics["cuda_visible_devices_env"] == "0"
    assert diagnostics["pytorch_cuda_alloc_conf_env"] == "expandable_segments:True"
    assert diagnostics["current_snapshot"]["free_bytes"] == 256
    assert snapshot["stage"] == "execute_policy_run_start"
    assert snapshot["free_bytes"] == 256
    assert snapshot["torch_reserved_bytes"] == 768


def test_rby1m_curobo_low_memory_profile_records_overrides() -> None:
    probe = probe_memory
    left = SimpleNamespace(
        num_trajopt_seeds=12,
        num_ik_seeds=128,
        max_attempts=15,
        trajopt_tsteps=48,
        enable_finetune_trajopt=True,
    )
    right = SimpleNamespace(
        num_trajopt_seeds=12,
        num_ik_seeds=128,
        max_attempts=15,
        trajopt_tsteps=48,
        enable_finetune_trajopt=True,
    )
    config = SimpleNamespace(
        policy_config=SimpleNamespace(
            batch_size=4,
            max_batch_plan_attempts=4,
            enable_collision_avoidance=True,
            left_curobo_planner_config=left,
            right_curobo_planner_config=right,
        )
    )
    args = Namespace(
        rby1m_curobo_memory_profile="low",
        curobo_policy_batch_size=None,
        curobo_max_batch_plan_attempts=None,
        curobo_num_trajopt_seeds=None,
        curobo_num_ik_seeds=None,
        curobo_max_attempts=None,
        curobo_trajopt_tsteps=None,
        curobo_disable_finetune_trajopt=False,
    )

    profile = probe._apply_rby1m_curobo_memory_profile(config, args)

    assert profile["applied"] is True
    assert profile["profile"] == "low"
    assert profile["before"]["policy"]["batch_size"] == 4
    assert profile["after"]["policy"]["batch_size"] == 1
    assert profile["after"]["policy"]["enable_collision_avoidance"] is True
    assert profile["after"]["planners"]["left"]["num_trajopt_seeds"] == 1
    assert profile["after"]["planners"]["left"]["num_ik_seeds"] == 16
    assert profile["after"]["planners"]["left"]["enable_finetune_trajopt"] is False
    assert right.trajopt_tsteps == 24


def test_process_output_text_handles_timeout_bytes() -> None:
    probe = probe_result

    assert probe.process_output_text(None) == ""
    assert probe.process_output_text("already text") == "already text"
    assert probe.process_output_text(b"byte text") == "byte text"
    assert "\ufffd" in probe.process_output_text(b"\xff")


def test_worker_payload_from_stdout_preserves_timeout_diagnostics() -> None:
    probe = probe_result

    payload = probe.worker_payload_from_stdout(
        'log line\n{"event": "runtime_diagnostics", "runtime_diagnostics": {"renderer": true}}\n'
    )

    assert payload["runtime_diagnostics"] == {"renderer": True}
    assert payload["last_worker_stage"] == "runtime_diagnostics"
    assert payload["worker_stage_events"][0]["event"] == "runtime_diagnostics"


def test_cleanup_primitive_binding_promotes_only_matching_sampled_task() -> None:
    requested = sampler.requested_cleanup_primitive_binding(
        Namespace(
            cleanup_object_id="pickup/body",
            cleanup_target_receptacle_id="target/body",
            cleanup_source_receptacle_id="source/body",
            cleanup_tools="navigate_to_object,pick,navigate_to_receptacle,place",
        )
    )
    sampled = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "pickup/body",
        "place_receptacle_name": "target/body",
        "place_target_name": "target/body",
    }

    result = sampler.cleanup_primitive_binding_from_sampled_task(requested, sampled)

    assert result["promoted"] is True
    binding = result["cleanup_primitive_binding"]
    assert binding["schema"] == "planner_probe_cleanup_primitive_binding_v1"
    assert binding["object_id"] == "pickup/body"
    assert binding["target_receptacle_id"] == "target/body"
    assert binding["source_receptacle_id"] == "source/body"
    assert binding["tools"] == [
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place",
    ]


def test_cleanup_primitive_binding_promotes_observed_handle_with_planner_aliases() -> None:
    requested = sampler.requested_cleanup_primitive_binding(
        Namespace(
            cleanup_object_id="observed_001",
            cleanup_target_receptacle_id="sink_01",
            cleanup_source_receptacle_id="counter_01",
            cleanup_planner_object_id="pickup/body",
            cleanup_planner_target_receptacle_id="sink/body",
            cleanup_tools="pick,place",
        )
    )
    sampled = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "pickup/body",
        "place_receptacle_name": "sink/body",
        "place_target_name": "sink/body",
    }

    result = sampler.cleanup_primitive_binding_from_sampled_task(requested, sampled)

    assert result["promoted"] is True
    binding = result["cleanup_primitive_binding"]
    assert binding["object_id"] == "observed_001"
    assert binding["target_receptacle_id"] == "sink_01"
    assert binding["planner_object_id"] == "pickup/body"
    assert binding["planner_target_receptacle_id"] == "sink/body"


def test_cleanup_primitive_binding_blocks_sampled_task_mismatch() -> None:
    requested = sampler.requested_cleanup_primitive_binding(
        Namespace(
            cleanup_object_id="observed_001",
            cleanup_target_receptacle_id="sink_01",
            cleanup_source_receptacle_id="counter_01",
            cleanup_tools="place",
        )
    )
    sampled = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "different_object",
        "place_receptacle_name": "different_target",
        "place_target_name": "different_target",
    }

    result = sampler.cleanup_primitive_binding_from_sampled_task(requested, sampled)

    assert result["promoted"] is False
    assert result["cleanup_primitive_binding"] is None
    assert [item["code"] for item in result["blockers"]] == [
        "cleanup_binding_object_mismatch",
        "cleanup_binding_target_mismatch",
    ]


def test_cleanup_primitive_binding_blocks_planner_alias_mismatch() -> None:
    requested = sampler.requested_cleanup_primitive_binding(
        Namespace(
            cleanup_object_id="observed_001",
            cleanup_target_receptacle_id="sink_01",
            cleanup_source_receptacle_id="counter_01",
            cleanup_planner_object_id="pickup/body",
            cleanup_planner_target_receptacle_id="sink/body",
            cleanup_tools="pick,place",
        )
    )

    result = sampler.cleanup_primitive_binding_from_sampled_task(
        requested,
        {
            "schema": "planner_probe_sampled_task_binding_v1",
            "pickup_obj_name": "other/body",
            "place_receptacle_name": "other/target",
        },
    )

    assert result["promoted"] is False
    assert [item["code"] for item in result["blockers"]] == [
        "cleanup_binding_object_mismatch",
        "cleanup_binding_target_mismatch",
    ]


def test_worker_exception_context_preserves_policy_failure_state() -> None:
    probe = worker_diagnostics
    probe._WORKER_EXCEPTION_CONTEXT.clear()
    profile = {"schema": "rby1m_curobo_memory_profile_v1", "applied": True, "profile": "low"}
    sampled = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": "bread/body",
        "place_receptacle_name": "fridge/body",
        "place_target_name": "fridge/body",
    }
    cleanup_binding = {
        "schema": "planner_probe_cleanup_primitive_binding_v1",
        "object_id": "observed_001",
        "planner_object_id": "bread/body",
        "target_receptacle_id": "refrigerator",
        "planner_target_receptacle_id": "fridge/body",
        "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place_inside"],
    }
    policy_exception = {
        "schema": "planner_probe_policy_exception_context_v1",
        "failure_kind": "curobo_no_planned_trajectory",
        "stage": "execute_policy_run",
    }

    probe._record_worker_exception_context(
        curobo_memory_profile=profile,
        sampled_task_binding=sampled,
        cleanup_primitive_binding=cleanup_binding,
        cleanup_primitive_binding_blockers=[],
        policy_exception_context=policy_exception,
    )

    context = probe._worker_exception_probe_context(
        Namespace(
            cleanup_object_id="observed_001",
            cleanup_target_receptacle_id="refrigerator",
            cleanup_source_receptacle_id="countertop",
            cleanup_planner_object_id="bread/body",
            cleanup_planner_target_receptacle_id="fridge/body",
            cleanup_scene_xml="",
            cleanup_tools="navigate_to_object,pick,navigate_to_receptacle,place_inside",
            task_sampler_robot_placement_profile="wide",
        )
    )

    assert context["curobo_memory_profile"] == profile
    assert context["sampled_task_binding"] == sampled
    assert context["cleanup_primitive_binding"] == cleanup_binding
    assert context["cleanup_primitive_binding_blockers"] == []
    assert context["policy_exception_context"] == policy_exception


def test_policy_exception_context_classifies_no_planned_trajectory() -> None:
    probe = probe_execution

    class FakePrimitive:
        planned_trajectory: list[object] = []
        trajectory_index = 0

        @staticmethod
        def get_current_phase() -> str:
            return "pre_grasp"

    class FakePolicy:
        action_primitives = [FakePrimitive()]

    context = probe._policy_exception_context(
        FakePolicy(),
        ValueError(
            "_execute_trajectory was called with no planned trajectory or trajectory "
            "index >= len(planned_trajectory)"
        ),
        stage="execute_policy_run",
        steps_requested=1,
    )

    assert context["schema"] == "planner_probe_policy_exception_context_v1"
    assert context["failure_kind"] == "curobo_no_planned_trajectory"
    assert context["no_planned_trajectory"] is True
    assert context["stage"] == "execute_policy_run"
    primitive = context["action_primitives"][0]
    assert primitive["current_phase"] == "pre_grasp"
    assert primitive["planned_trajectory_present"] is True
    assert primitive["planned_trajectory_len"] == 0
    assert primitive["trajectory_index"] == 0


def test_cleanup_primitive_binding_no_request_stays_generic() -> None:
    requested = sampler.requested_cleanup_primitive_binding(
        Namespace(
            cleanup_object_id="",
            cleanup_target_receptacle_id="",
            cleanup_source_receptacle_id="",
            cleanup_tools="",
        )
    )

    result = sampler.cleanup_primitive_binding_from_sampled_task(
        requested,
        {"pickup_obj_name": "pickup/body", "place_receptacle_name": "target/body"},
    )

    assert requested["requested"] is False
    assert result["promoted"] is False
    assert result["blockers"] == []
    assert result["cleanup_primitive_binding"] is None


def test_curobo_extension_cache_entry_records_lock_and_binary(tmp_path: Path) -> None:
    build_dir = tmp_path / "lbfgs_step_cu"
    build_dir.mkdir()
    (build_dir / "lbfgs_step_cu.so").write_bytes(b"binary")
    (build_dir / "lock").write_text("", encoding="utf-8")
    (build_dir / "build.ninja").write_text("rule build\n", encoding="utf-8")

    entry = runtime.curobo_extension_cache_entry("lbfgs_step_cu", build_dir)

    assert entry["exists"] is True
    assert entry["so_exists"] is True
    assert entry["lock_exists"] is True
    assert {item["name"] for item in entry["files"]} == {
        "build.ninja",
        "lbfgs_step_cu.so",
        "lock",
    }


def test_warp_torch_adapter_adds_minimal_namespace() -> None:
    def device_from_torch(value: object) -> object:
        return value

    fake_warp = SimpleNamespace(
        __version__="1.13.0",
        device_from_torch=device_from_torch,
        from_torch=lambda value: value,
        stream_from_torch=lambda value: value,
    )

    adapter = runtime.apply_warp_torch_adapter_to_module(fake_warp)
    diagnostics = runtime.warp_compatibility_from_module(fake_warp, adapter)

    assert adapter["applied"] is True
    assert fake_warp.torch.device_from_torch("cuda:0") == "cuda:0"
    assert diagnostics["has_torch_attr"] is True
    assert diagnostics["adapter"]["provided"] == ["warp.torch.device_from_torch"]
