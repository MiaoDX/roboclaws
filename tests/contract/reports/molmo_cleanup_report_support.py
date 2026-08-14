from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from roboclaws.household.manipulation_contract import API_SEMANTIC_PROVENANCE
from roboclaws.household.report import (
    render_cleanup_report,
)
from roboclaws.household.report_snapshots import write_state_snapshot
from roboclaws.household.scenario import build_cleanup_scenario
from roboclaws.household.scoring import score_cleanup
from roboclaws.household.semantic_timeline import SEMANTIC_LOOP_DISPLAY_NOTE


def _robot_visual_timeline_report_context(tmp_path: Path) -> SimpleNamespace:
    scenario = build_cleanup_scenario(seed=7)
    score = score_cleanup(scenario.object_locations(), scenario.private_manifest)
    before = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "before.png",
        title="Before",
    )
    after = write_state_snapshot(
        scenario,
        scenario.object_locations(),
        tmp_path / "after.png",
        title="After",
    )
    for name in ("step.fpv.png", "step.chase.png", "step.topdown.png", "step.verify.png"):
        (tmp_path / "robot_views" / name).parent.mkdir(exist_ok=True)
        (tmp_path / "robot_views" / name).write_bytes(b"placeholder")
    return SimpleNamespace(
        scenario=scenario,
        before=before,
        after=after,
        run_result=_robot_visual_timeline_run_result(score),
    )


def _robot_visual_timeline_run_result(score: object) -> dict[str, object]:
    return {
        "cleanup_status": score.status,
        "primitive_provenance": API_SEMANTIC_PROVENANCE,
        "score": score.to_dict(),
        "robot_name": "rby1m",
        "semantic_substeps": [
            {
                "object_id": "mug_01",
                "source_receptacle_id": "table_01",
                "target_receptacle_id": "sink_01",
                "steps": [
                    {"phase": "navigate_to_object"},
                    {"phase": "pick"},
                    {"phase": "navigate_to_receptacle"},
                    {"phase": "place", "location_id": "sink_01"},
                    {
                        "phase": "object_done",
                        "location_id": "sink_01",
                        "location_relation": "on",
                    },
                ],
            },
        ],
    }


def _robot_visual_timeline_steps() -> list[dict[str, object]]:
    static_view_provenance = {
        "fpv": "isaac_lab_camera_rgb_static_robot_views:fpv",
        "topdown": "isaac_lab_camera_rgb_static_robot_views:topdown",
        "semantic_pose_state_refreshed": False,
        "evidence_note": "Robot-view images are static captures from the loaded USD scene.",
    }
    return [
        {
            "action": "before",
            "robot_pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
            "view_provenance": static_view_provenance,
            "views": {
                "fpv": "robot_views/step.fpv.png",
                "chase": "robot_views/step.chase.png",
                "topdown": "robot_views/step.topdown.png",
                "verify": "robot_views/bootstrap.verify.png",
            },
            "focus": {
                "has_focus": False,
                "fpv_visibility": {"status": "ok", "object_pixels": 0, "receptacle_pixels": 0},
                "visibility": {"status": "ok", "object_pixels": 0, "receptacle_pixels": 0},
            },
        },
        {
            "action": "goto sink",
            "semantic_phase": "navigate_to_receptacle",
            "view_provenance": static_view_provenance,
            "robot_pose": {
                "x": 1.0,
                "y": 2.0,
                "theta": 0.5,
                "theta_source": "target_facing_base_yaw",
                "head_pitch": 0.6,
                "head_pitch_source": "target_framing_head_pitch",
                "robot_room_id": "room_1",
                "target_room_id": "room_1",
                "same_room_as_target": True,
            },
            "views": {
                "fpv": "robot_views/step.fpv.png",
                "chase": "robot_views/step.chase.png",
                "topdown": "robot_views/step.topdown.png",
                "verify": "robot_views/step.verify.png",
            },
            "focus": {
                "has_focus": True,
                "object_label": "Mug mug",
                "receptacle_label": "Sink sink",
                "provenance": "public_mujoco_state_report_aid",
                "fpv_visibility": {"status": "ok", "object_pixels": 12, "receptacle_pixels": 80},
                "visibility": {"status": "ok", "object_pixels": 24, "receptacle_pixels": 120},
            },
        },
        _robot_visual_timeline_action_step("pick mug_01", "pick"),
        _robot_visual_timeline_action_step("place mug_01", "place"),
    ]


def _robot_visual_timeline_action_step(action: str, phase: str) -> dict[str, object]:
    return {
        "action": action,
        "semantic_phase": phase,
        "robot_pose": {"x": 1.0, "y": 2.0, "theta": 0.5},
        "views": {
            "fpv": "robot_views/step.fpv.png",
            "verify": "robot_views/step.verify.png",
        },
        "focus": {"has_focus": True},
    }


def _assert_robot_visual_timeline_layout(html: str) -> None:
    assert "Robot View Timeline" in html
    assert 'data-report-tab-button="timeline"' in html
    assert html.index('data-report-tab-button="timeline"') < html.index(
        'data-report-tab-button="timing"'
    )
    assert '<details class="robot-timeline-details" open>' in html
    assert "captured robot-view" in html
    assert "Top-down Scene View" in html


def _assert_robot_visual_timeline_lightbox(html: str) -> None:
    assert "Pick/place visual checks" in html
    assert '<details class="comparison-item" open>' in html
    assert '<a class="image-link" href="robot_views/step.fpv.png" data-lightbox-image' in html
    assert (
        '<img src="robot_views/step.fpv.png" alt="Pick view" loading="lazy" decoding="async">'
        in html
    )
    assert '<img src="robot_views/step.verify.png" alt="Pick view">' not in html
    assert 'data-lightbox-caption="Pick view"' in html
    assert 'class="image-lightbox"' in html
    assert "Close image review" in html
    assert "sim-only-grid-single" in html


def _assert_robot_visual_timeline_semantic_substeps(html: str) -> None:
    assert "Semantic Substeps" in html
    assert '<details class="semantic-card">' in html
    assert "semantic-card-status" in html
    assert SEMANTIC_LOOP_DISPLAY_NOTE in html
    assert "<span>nav</span><small>object</small>" in html
    assert "<span>pick</span><small>object</small>" in html
    assert "<span>nav</span><small>target</small>" in html
    assert "<span>place</span><small>surface</small>" in html
    assert "Subphase" in html
    assert "Role" in html
    assert "object_done" not in html


def _assert_robot_visual_timeline_pose_and_focus(html: str) -> None:
    assert "rby1m" in html
    assert "robot_views/step.fpv.png" in html
    assert "robot_views/bootstrap.verify.png" not in html
    assert "Chase sim-only" in html
    assert "Top-view bbox verification sim-only" in html
    assert "object 0 px" not in html
    assert "navigate_to_receptacle" in html
    assert "Mug mug" in html
    assert "public_mujoco_state_report_aid" in html
    assert "target_facing_base_yaw" in html
    assert "target_framing_head_pitch" in html


def _assert_robot_visual_timeline_yaw_rendering(
    tmp_path: Path,
    context: SimpleNamespace,
) -> None:
    assert "yaw_deg=257.0" in render_cleanup_report(
        run_dir=tmp_path,
        scenario=context.scenario,
        run_result=context.run_result,
        trace_events=[],
        before_snapshot=context.before,
        after_snapshot=context.after,
        robot_view_steps=[
            {
                "action": "isaac waypoint",
                "robot_pose": {"x": 0.0, "y": 0.39, "yaw_deg": 257.0},
                "views": {
                    "fpv": "robot_views/isaac.fpv.png",
                    "topdown": "robot_views/isaac.topdown.png",
                },
            }
        ],
    ).read_text(encoding="utf-8")


def _assert_robot_visual_timeline_static_isaac_caveat(html: str) -> None:
    assert "FPV visibility" in html
    assert "same room" in html
    assert "object 24 px" in html
    assert "Isaac report-only view caveat" in html
    assert "static report-only" in html
    assert "Step render: <strong>not refreshed</strong>" in html
    assert "backend JSON as isaac_semantic_pose" in html
    assert "diagnostic-view" not in html
    assert "decision-card" not in html


def _assert_html_contains(html: str, fragments: tuple[str, ...]) -> None:
    missing = [fragment for fragment in fragments if fragment not in html]
    assert not missing, f"Missing expected HTML fragments: {missing}"


def _assert_html_omits(html: str, fragments: tuple[str, ...]) -> None:
    unexpected = [fragment for fragment in fragments if fragment in html]
    assert not unexpected, f"Unexpected HTML fragments: {unexpected}"


def _assert_planner_proof_bundle_runner_overview(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Planner Proof Bundle Runner",
            "Source Cleanup Artifact",
            "Proof Execution Horizon",
            "multi_step_motion",
            "Grasp Feasibility Mitigation Decision",
            "decision-card",
            "grasp_cache_mitigation",
            "mitigate_missing_grasp_cache_before_retry",
            "Grasp Cache Availability Preflight",
            "Grasp Cache Generation Preflight",
            "python_module_sklearn",
            "manifold_executable_missing",
            "run_rigid.py",
            "grasps/droid/Bread_1/Bread_1_grasps_filtered.npz",
            "has_grasp_folder_only",
            "objects/thor/Bread_1.xml",
            "available_for_unproven_requests",
            "RBY1M/CuRobo Warmup",
            "config_import",
            "torch_extensions",
            "Cleanup Rerun Command",
            "--planner-proof-run-result",
        ),
    )


def _assert_planner_proof_bundle_runner_selection(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Proof Request Selection",
            "dry_run",
            "proof_001",
            "proof_001_fallback_01",
            "observed_001",
            "sink/alt",
            "HouseInvalidForTask",
            "Fallback status",
            "generated",
            "Fallback required",
            "prior_task_feasibility_blocked",
            "Generated Fallback Requests",
            "Discovered Runtime Aliases",
            "Discovered aliases",
            "sink/body_alt",
            "valid_name_sibling_from_prior_keyerror",
            "Filtered Fallback Aliases",
            "Filtered aliases",
            "Sink|1|2",
            "not_exact_scene_runtime_alias",
            "Filtered Fallback Pairs",
            "Filtered pairs",
            "Target Feasibility Blockers",
            "Target blockers",
            "Grasp Feasibility Blockers",
            "Grasp Feasibility Blocker Matrix",
            "Grasp blockers",
            "Prior match",
            "request_id",
            "source_request",
            "fallback_pair",
            "worker_exception",
            "pickup/body",
            "prior_task_feasibility_blocked_pair",
            "fallback_generated",
        ),
    )


def _assert_planner_proof_bundle_runner_proof_results(html: str, tmp_path: Path) -> None:
    _assert_html_contains(
        html,
        (
            "Prior Proof Evidence",
            "Proof Probe Commands",
            "Semantic subphases",
            "surface / place",
            "Proof Probe Results",
            "Task feasibility",
            "blocked",
            "Grasp-feasible blocked",
            "Grasp Feasibility Signature Matrix",
            "Grasp-load failures",
            "grasp_cache_missing",
            "Bread_1",
            "PriorBread_1",
            "prior/pickup",
            "Diagnostic views",
            "Task feasibility blocker",
            "grasp_feasibility",
            "3 grasp failures; 1 candidate-removal calls",
            "standalone_observed_001_to_sink_01",
            "prior-proof/run_result.json",
            "prior-proof/report.html",
            "prior-proof/initial.png",
            "prior-proof/final.png",
            'src="prior-proof/initial.png"',
            'src="prior-proof/final.png"',
            'src="proofs/001/initial.png"',
            'src="proofs/001/final.png"',
        ),
    )
    _assert_html_omits(
        html,
        (
            f'src="{tmp_path}/prior-proof/initial.png"',
            f'src="{tmp_path}/proofs/001/initial.png"',
        ),
    )


def _assert_planner_proof_bundle_runner_sampler_diagnostics(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Robot placement profile",
            "relaxed",
            "place_robot_near max tries",
            "Exact sampler adapter applied",
            "Exact sampler adapter class",
            "PickAndPlaceTaskSampler",
            "Exact sampler adapter target",
            "Task sampler placement failures",
            "Task sampler asset failures",
            "Post-placement grasp failures",
            "Post-placement candidate name misses",
            "Post-Placement Rejection Views",
            "Post-placement rejection flow: pickup/body",
            "Placement free-space fraction",
            "0.000017",
            "Failed to place robot near object: pickup/body",
            "sink/body",
        ),
    )


def _assert_planner_proof_bundle_runner_artifacts(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Timeouts",
            "Config-import timeouts",
            "Last worker stage",
            "rby1m_config_import",
            "Worker stages",
            "planner_probe_stdout.txt",
            "planner_probe_stderr.txt",
            "initial.png",
            "final.png",
            "report.html",
        ),
    )


def _proof_attachment(proof_id: str, object_id: str, target_id: str) -> dict[str, object]:
    return {
        "schema": "planner_backed_cleanup_attachment_v1",
        "proof_id": proof_id,
        "status": "planner_backed",
        "primitive_provenance": "planner_backed",
        "planner_backed": True,
        "strict_proof_eligible": True,
        "embodiment": "rby1m",
        "task": "pick_and_place",
        "probe_mode": "execute",
        "upstream_policy_class": "CuroboPickAndPlacePlannerPolicy",
        "steps_executed": 2,
        "max_abs_qpos_delta": 0.01,
        "runtime_diagnostics": {"modules": {"curobo": {"available": True}}},
        "image_artifacts": {
            "initial": f"planner_proof/{proof_id}/initial.png",
            "final": f"planner_proof/{proof_id}/final.png",
        },
        "cleanup_primitive_binding": {
            "schema": "planner_probe_cleanup_primitive_binding_v1",
            "object_id": object_id,
            "target_receptacle_id": target_id,
            "tools": ["navigate_to_object", "pick", "navigate_to_receptacle", "place"],
        },
    }


def _assert_planner_manipulation_probe_overview(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Planner-Backed Manipulation Probe",
            "Manipulation Provenance",
            "Planner Proof Quality",
            "Runtime Diagnostics",
            "Planner Probe Diagnostic Views",
            "Task sampler diagnostic: pickup/body",
            "Planner Probe Cleanup Binding",
            "Capability Blockers",
            "RBY1M CuRobo Gate",
            "wrong_embodiment",
        ),
    )


def _assert_planner_manipulation_probe_cleanup_binding(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Task Sampler Robot Placement Profile",
            "relaxed",
            "place_robot_near max tries",
            "Exact task config applied",
            "Exact task config blockers",
            "cleanup_scene_xml_missing",
            "Exact sampler adapter class",
            "Exact sampler adapter object",
            "Exact pickup candidate action",
            "Exact pickup retry budget",
            "injected_requested_candidate_name",
            "PickAndPlaceTaskSampler",
            "pickup/body",
            "sink/body",
            "Planner object alias",
            "navigate_to_receptacle",
        ),
    )


def _assert_planner_manipulation_probe_sampler_failures(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "Task Sampler Failure Diagnostics",
            "Placement failures",
            "Effective max tries",
            "Post-Placement Candidate Rejections",
            "Post-Placement Rejection Views",
            "Post-placement rejection flow: pickup/body",
            "Removed by grasp threshold",
            "Candidate Removal Effectiveness",
            "Effective removals",
            "Candidate name misses",
            "Removal-call delta",
            "Placement Scene Diagnostics",
            "Free-space fraction",
            "0.000017",
            "Nearest free distance",
            "Failed to place robot near object: pickup/body",
            "asset-book",
        ),
    )


def _assert_planner_manipulation_probe_runtime_diagnostics(html: str) -> None:
    _assert_html_contains(
        html,
        (
            "CUDA Memory Headroom",
            "CuRobo Memory Profile",
            "Policy Exception Diagnostics",
            "curobo_no_planned_trajectory",
            "_execute_trajectory was called with no planned trajectory",
            "pre_grasp",
            "Trajectory len",
            "CuRobo Extension Cache",
            "lbfgs_step_cu",
            "Warp Compatibility",
            "Adapter applied",
            "Worker Stage Timeline",
            "PickAndPlacePlannerPolicy",
            "rby1m_config_import_start",
            "rby1m_config_import",
            "faulthandler=True",
            "renderer_adapter=True",
            "MUJOCO_GL=egl",
            "CUDA_HOME=/usr/local/cuda",
            "torch_cuda_available=True",
            "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
            "execute_policy_run_start",
            "num_ik_seeds",
            "Collision avoidance",
            "10.6 GiB",
            "curobo",
        ),
    )
