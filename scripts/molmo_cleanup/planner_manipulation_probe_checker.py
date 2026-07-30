from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.household.manipulation_contract import (
    API_SEMANTIC_PROVENANCE,
    BLOCKED_CAPABILITY_PROVENANCE,
    MANIPULATION_PROBE_CONTRACT,
    PLANNER_BACKED_PROVENANCE,
)
from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
    validate_planner_proof_quality_evidence,
)
from roboclaws.household.rby1m_curobo_gate import (
    rby1m_curobo_gate_from_planner_probe,
    validate_rby1m_curobo_gate,
)


def assert_probe_result(
    data: dict[str, Any],
    base: Path,
    *,
    accept_blocked_capability: bool = False,
    require_planner_backed: bool = False,
    accept_rby1m_curobo_blocked: bool = False,
    require_rby1m_curobo_ready: bool = False,
    require_curobo_extension_cache: bool = False,
    require_warp_compatibility: bool = False,
    require_cuda_memory: bool = False,
    require_curobo_memory_profile: bool = False,
    require_cleanup_scene_bound: bool = False,
    require_policy_exception_context: bool = False,
    require_proof_quality: bool = False,
    require_proof_min_steps: int | None = None,
) -> None:
    assert data.get("contract") == MANIPULATION_PROBE_CONTRACT, data
    evidence = data.get("manipulation_evidence") or {}
    assert evidence, data
    _assert_public_provenance_boundary(data, evidence)
    report_text = _assert_artifacts(data, base)
    _assert_report_core(report_text)
    _assert_optional_report_sections(
        evidence,
        base,
        report_text,
        require_proof_quality=require_proof_quality,
        require_proof_min_steps=require_proof_min_steps,
    )
    _assert_required_capability_sections(
        data,
        evidence,
        report_text,
        require_cleanup_scene_bound=require_cleanup_scene_bound,
        require_curobo_extension_cache=require_curobo_extension_cache,
        require_warp_compatibility=require_warp_compatibility,
        require_cuda_memory=require_cuda_memory,
        require_curobo_memory_profile=require_curobo_memory_profile,
        require_policy_exception_context=require_policy_exception_context,
        accept_rby1m_curobo_blocked=accept_rby1m_curobo_blocked,
        require_rby1m_curobo_ready=require_rby1m_curobo_ready,
    )
    _assert_final_status(
        data,
        evidence,
        report_text,
        accept_blocked_capability=accept_blocked_capability,
        require_planner_backed=require_planner_backed,
    )


def _assert_public_provenance_boundary(data: dict[str, Any], evidence: dict[str, Any]) -> None:
    assert evidence.get("api_semantic_state_edits") is False, evidence
    assert evidence.get("primitive_provenance") != API_SEMANTIC_PROVENANCE, evidence
    assert data.get("primitive_provenance") != API_SEMANTIC_PROVENANCE, data


def _assert_artifacts(data: dict[str, Any], base: Path) -> str:
    artifacts = data.get("artifacts") or {}
    for key in ("stdout", "stderr", "report"):
        path = _resolve_path(base, artifacts.get(key, ""))
        assert path.is_file(), path
    return _resolve_path(base, artifacts["report"]).read_text(encoding="utf-8")


def _assert_report_core(report_text: str) -> None:
    assert "Planner-Backed Manipulation Probe" in report_text, report_text[:500]
    assert "Manipulation Provenance" in report_text, report_text[:500]


def _assert_optional_report_sections(
    evidence: dict[str, Any],
    base: Path,
    report_text: str,
    *,
    require_proof_quality: bool,
    require_proof_min_steps: int | None,
) -> None:
    if require_proof_quality or require_proof_min_steps is not None:
        _assert_proof_quality(
            evidence,
            report_text,
            min_steps_executed=require_proof_min_steps or 1,
        )
    _assert_runtime_diagnostics(evidence, report_text)
    _assert_policy_exception_if_present(evidence, report_text)
    _assert_robot_placement_profile(evidence, report_text)
    _assert_probe_views(evidence, base, report_text)
    _assert_task_sampler_failure_diagnostics(evidence, report_text)
    _assert_cleanup_binding_report(evidence, report_text)
    if evidence.get("worker_stage_events"):
        assert evidence.get("last_worker_stage"), evidence
        assert "Worker Stage Timeline" in report_text, report_text[:500]


def _assert_runtime_diagnostics(evidence: dict[str, Any], report_text: str) -> None:
    if evidence.get("runtime_diagnostics"):
        assert "Runtime Diagnostics" in report_text, report_text[:500]
        cache = (evidence.get("runtime_diagnostics") or {}).get("curobo_extension_cache") or {}
        if cache.get("extensions"):
            assert "CuRobo Extension Cache" in report_text, report_text[:500]
        warp = (evidence.get("runtime_diagnostics") or {}).get("warp_compatibility") or {}
        if warp:
            assert "Warp Compatibility" in report_text, report_text[:500]
        cuda_memory = (evidence.get("runtime_diagnostics") or {}).get("cuda_memory") or {}
        if cuda_memory:
            assert "CUDA Memory Headroom" in report_text, report_text[:500]
    if evidence.get("curobo_memory_profile"):
        assert "CuRobo Memory Profile" in report_text, report_text[:500]


def _assert_policy_exception_if_present(evidence: dict[str, Any], report_text: str) -> None:
    policy_exception_context = evidence.get("policy_exception_context") or {}
    if policy_exception_context:
        _assert_policy_exception_context_report(policy_exception_context, report_text)


def _assert_robot_placement_profile(evidence: dict[str, Any], report_text: str) -> None:
    robot_placement_profile = evidence.get("task_sampler_robot_placement_profile") or {}
    if not robot_placement_profile:
        return
    assert "Task Sampler Robot Placement Profile" in report_text, report_text[:500]
    profile = str(robot_placement_profile.get("profile") or "")
    if profile:
        assert profile in report_text, ("task_sampler_robot_placement_profile", report_text[:500])
    overrides = robot_placement_profile.get("place_robot_near_overrides") or {}
    max_tries = str(overrides.get("max_tries") or "")
    if max_tries:
        assert max_tries in report_text, ("place_robot_near_overrides", report_text[:500])


def _assert_probe_views(evidence: dict[str, Any], base: Path, report_text: str) -> None:
    task_sampler_failure = evidence.get("task_sampler_failure_diagnostics") or {}
    image_artifacts = evidence.get("image_artifacts") or {}
    if image_artifacts:
        assert "Planner Probe Views" in report_text, report_text[:500]
        for label, value in image_artifacts.items():
            path = _resolve_path(base, str(value))
            assert path.is_file(), path
            assert str(value) in report_text, (label, report_text[:500])
    elif task_sampler_failure:
        assert "Planner Probe Diagnostic Views" in report_text, report_text[:500]


def _assert_task_sampler_failure_diagnostics(
    evidence: dict[str, Any],
    report_text: str,
) -> None:
    task_sampler_failure = evidence.get("task_sampler_failure_diagnostics") or {}
    if not task_sampler_failure:
        return
    assert "Task Sampler Failure Diagnostics" in report_text, report_text[:500]
    _assert_placement_scene_diagnostics(task_sampler_failure, report_text)
    _assert_post_placement_rejections(task_sampler_failure, report_text)
    _assert_grasp_collision_diagnostics(task_sampler_failure, report_text)
    _assert_task_sampler_identity(task_sampler_failure, report_text)
    _assert_robot_placement_attempts(task_sampler_failure, report_text)


def _assert_placement_scene_diagnostics(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    if not task_sampler_failure.get("placement_scene_diagnostics"):
        return
    assert "Placement Scene Diagnostics" in report_text, report_text[:500]
    last_scene = task_sampler_failure.get("last_placement_scene_diagnostic") or {}
    for key in ("target_name", "valid_free_point_count"):
        value = str(last_scene.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])


def _assert_post_placement_rejections(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    if not task_sampler_failure.get("grasp_failures"):
        return
    assert "Post-Placement Candidate Rejections" in report_text, report_text[:500]
    assert "Post-Placement Rejection Views" in report_text, report_text[:500]
    if "candidate_effective_removal_count" in task_sampler_failure:
        assert "Effective removals" in report_text, report_text[:500]
    if "candidate_name_miss_count" in task_sampler_failure:
        assert "Candidate name misses" in report_text, report_text[:500]
    for item in task_sampler_failure.get("grasp_failures") or []:
        value = str(item.get("object_name") or "")
        if value:
            assert value in report_text, ("grasp_failures", report_text[:500])


def _assert_grasp_collision_diagnostics(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    if not (
        task_sampler_failure.get("grasp_load_attempts")
        or task_sampler_failure.get("grasp_collision_checks")
    ):
        return
    assert "Grasp Collision Diagnostics" in report_text, report_text[:500]
    last_check = task_sampler_failure.get("last_grasp_collision_check") or {}
    last_load = task_sampler_failure.get("last_grasp_load_attempt") or {}
    for key in ("asset_uid", "noncolliding_grasp_count", "cached_grasp_count"):
        value = str(last_check.get(key) or last_load.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])


def _assert_task_sampler_identity(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    for key in ("task_sampler_class",):
        value = str(task_sampler_failure.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])


def _assert_robot_placement_attempts(
    task_sampler_failure: dict[str, Any],
    report_text: str,
) -> None:
    for item in task_sampler_failure.get("robot_placement_attempts") or []:
        for key in ("pickup_obj_name", "message"):
            value = str(item.get(key) or "")
            if value:
                assert value in report_text, (key, report_text[:500])


def _assert_cleanup_binding_report(evidence: dict[str, Any], report_text: str) -> None:
    if not (
        evidence.get("sampled_task_binding")
        or evidence.get("requested_cleanup_primitive_binding")
        or evidence.get("cleanup_primitive_binding")
        or evidence.get("cleanup_primitive_binding_blockers")
        or evidence.get("cleanup_task_config")
        or evidence.get("cleanup_task_sampler_adapter")
    ):
        return
    assert "Planner Probe Cleanup Binding" in report_text, report_text[:500]
    _assert_exact_pickup_binding(evidence, report_text)
    _assert_cleanup_config_blockers(evidence, report_text)


def _assert_exact_pickup_binding(evidence: dict[str, Any], report_text: str) -> None:
    adapter = evidence.get("cleanup_task_sampler_adapter") or {}
    pickup_binding = adapter.get("exact_pickup_candidate_binding") or {}
    if not pickup_binding:
        return
    assert "Exact pickup candidate action" in report_text, report_text[:500]
    if pickup_binding.get("retry_budget") is not None:
        assert "Exact pickup retry budget" in report_text, report_text[:500]
    for key in ("action", "planner_object_id"):
        value = str(pickup_binding.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])


def _assert_cleanup_config_blockers(evidence: dict[str, Any], report_text: str) -> None:
    config = evidence.get("cleanup_task_config") or {}
    config_blockers = config.get("blockers") or []
    if not config_blockers:
        return
    assert "Exact task config blockers" in report_text, report_text[:500]
    for blocker in config_blockers:
        value = str(blocker.get("code") or "")
        if value:
            assert value in report_text, (value, report_text[:500])


def _assert_required_capability_sections(
    data: dict[str, Any],
    evidence: dict[str, Any],
    report_text: str,
    *,
    require_cleanup_scene_bound: bool,
    require_curobo_extension_cache: bool,
    require_warp_compatibility: bool,
    require_cuda_memory: bool,
    require_curobo_memory_profile: bool,
    require_policy_exception_context: bool,
    accept_rby1m_curobo_blocked: bool,
    require_rby1m_curobo_ready: bool,
) -> None:
    if require_cleanup_scene_bound:
        _assert_cleanup_scene_bound(evidence)
    _assert_required_runtime_diagnostics(
        evidence,
        report_text,
        require_curobo_extension_cache=require_curobo_extension_cache,
        require_warp_compatibility=require_warp_compatibility,
        require_cuda_memory=require_cuda_memory,
        require_curobo_memory_profile=require_curobo_memory_profile,
    )
    if require_policy_exception_context:
        policy_exception_context = evidence.get("policy_exception_context") or {}
        assert policy_exception_context, evidence
        _assert_policy_exception_context_report(policy_exception_context, report_text)
    if accept_rby1m_curobo_blocked or require_rby1m_curobo_ready:
        _assert_rby1m_curobo_gate(
            data,
            report_text,
            accept_blocked=accept_rby1m_curobo_blocked,
            require_ready=require_rby1m_curobo_ready,
        )


def _assert_required_runtime_diagnostics(
    evidence: dict[str, Any],
    report_text: str,
    *,
    require_curobo_extension_cache: bool,
    require_warp_compatibility: bool,
    require_cuda_memory: bool,
    require_curobo_memory_profile: bool,
) -> None:
    diagnostics = evidence.get("runtime_diagnostics") or {}
    if require_curobo_extension_cache:
        cache = diagnostics.get("curobo_extension_cache") or {}
        assert cache.get("extensions"), diagnostics
        assert "CuRobo Extension Cache" in report_text, report_text[:500]
    if require_warp_compatibility:
        warp = diagnostics.get("warp_compatibility") or {}
        assert warp, diagnostics
        assert "Warp Compatibility" in report_text, report_text[:500]
    if require_cuda_memory:
        cuda_memory = diagnostics.get("cuda_memory") or {}
        snapshots = evidence.get("cuda_memory_snapshots") or []
        assert cuda_memory or snapshots, diagnostics
        assert "CUDA Memory Headroom" in report_text, report_text[:500]
    if require_curobo_memory_profile:
        profile = evidence.get("curobo_memory_profile") or {}
        assert profile, evidence
        assert profile.get("applied") is True, profile
        assert "CuRobo Memory Profile" in report_text, report_text[:500]


def _assert_final_status(
    data: dict[str, Any],
    evidence: dict[str, Any],
    report_text: str,
    *,
    accept_blocked_capability: bool,
    require_planner_backed: bool,
) -> None:
    if require_planner_backed:
        _assert_planner_backed(data, evidence)
        return
    if data.get("status") == BLOCKED_CAPABILITY_PROVENANCE:
        assert accept_blocked_capability, data
        assert evidence.get("planner_backed") is False, evidence
        assert evidence.get("strict_proof_eligible") is False, evidence
        assert evidence.get("blockers"), evidence
        assert "Capability Blockers" in report_text, report_text[:500]
        return
    if data.get("status") == PLANNER_BACKED_PROVENANCE:
        _assert_planner_backed(data, evidence)
        return
    raise AssertionError(data)


def _assert_planner_backed(data: dict[str, Any], evidence: dict[str, Any]) -> None:
    assert data.get("status") == PLANNER_BACKED_PROVENANCE, data
    assert data.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE, data
    assert evidence.get("primitive_provenance") == PLANNER_BACKED_PROVENANCE, evidence
    assert evidence.get("planner_backed") is True, evidence
    assert evidence.get("strict_proof_eligible") is True, evidence
    assert evidence.get("execution_attempted") is True, evidence
    assert int(evidence.get("steps_executed") or 0) >= 1, evidence
    assert float(evidence.get("max_abs_qpos_delta") or 0.0) > 0.0, evidence
    assert not evidence.get("blockers"), evidence
    assert evidence.get("upstream_policy_class"), evidence


def _assert_proof_quality(
    evidence: dict[str, Any],
    report_text: str,
    *,
    min_steps_executed: int,
) -> None:
    quality = planner_proof_quality_evidence(evidence)
    validate_planner_proof_quality_evidence(quality, min_steps_executed=min_steps_executed)
    assert "Planner Proof Quality" in report_text, report_text[:500]
    assert "Proof Quality" in report_text, report_text[:500]
    assert str(quality.get("quality_tier") or "") in report_text, report_text[:500]


def _assert_cleanup_scene_bound(evidence: dict[str, Any]) -> None:
    config = evidence.get("cleanup_task_config") or {}
    assert config.get("applied") is True, config
    scene_xml = str(config.get("scene_xml") or "")
    assert scene_xml, config
    assert Path(scene_xml).is_file(), config
    blocker_codes = {
        str(item.get("code") or "")
        for item in config.get("blockers") or []
        if isinstance(item, dict)
    }
    assert "cleanup_scene_xml_missing" not in blocker_codes, config


def _assert_rby1m_curobo_gate(
    data: dict[str, Any],
    report_text: str,
    *,
    accept_blocked: bool = False,
    require_ready: bool = False,
) -> None:
    gate = data.get("rby1m_curobo_gate") or rby1m_curobo_gate_from_planner_probe(data)
    validate_rby1m_curobo_gate(
        gate,
        accept_blocked=accept_blocked,
        require_ready=require_ready,
    )
    assert "RBY1M CuRobo Gate" in report_text, report_text[:500]


def _assert_policy_exception_context_report(
    context: dict[str, Any],
    report_text: str,
) -> None:
    assert "Policy Exception Diagnostics" in report_text, report_text[:500]
    for key in ("failure_kind", "stage", "exception_type"):
        value = str(context.get(key) or "")
        if value:
            assert value in report_text, (key, report_text[:500])
    for primitive in context.get("action_primitives") or []:
        for key in ("primitive_class", "current_phase"):
            value = str(primitive.get(key) or "")
            if value:
                assert value in report_text, (key, report_text[:500])


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base / path
