from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from roboclaws.household.planner_proof_quality import (
    planner_proof_quality_evidence,
)
from roboclaws.household.report_document import wrap_report_html
from roboclaws.household.report_sections_grasp_cache import (
    grasp_cache_availability_preflight_section,
    grasp_cache_generation_preflight_section,
)
from roboclaws.household.report_sections_grasp_generation import (
    grasp_cache_generation_report_sections,
    grasp_pose_policy_cache_report_sections,
)
from roboclaws.household.report_sections_probe import (
    planner_probe_cleanup_binding_section,
    planner_probe_quality_section,
    planner_probe_task_sampler_failure_section,
    planner_probe_task_sampler_robot_placement_profile_section,
    planner_probe_views_section,
)
from roboclaws.household.report_sections_probe_failures import (
    planner_probe_artifacts_section,
    planner_probe_blockers_section,
    planner_probe_placement_scene_diagnostics_section,
    planner_probe_policy_exception_section,
    planner_probe_post_placement_rejection_section,
    rby1m_curobo_gate_section,
)
from roboclaws.household.report_sections_probe_runtime import (
    planner_probe_cuda_memory_section,
    planner_probe_curobo_extension_cache_section,
    planner_probe_curobo_memory_profile_section,
    planner_probe_diagnostics_section,
    planner_probe_warp_compatibility_section,
    planner_probe_worker_stages_section,
)
from roboclaws.household.report_sections_proof import (
    manipulation_provenance_section,
)
from roboclaws.household.report_sections_proof_bundle import (
    cleanup_rerun_artifact_section,
    cleanup_rerun_command_section,
    grasp_feasibility_mitigation_decision_section,
    proof_bundle_commands_section,
    proof_bundle_local_runtime_preflight_section,
    proof_bundle_results_section,
    proof_bundle_warmup_section,
    proof_execution_horizon_section,
)
from roboclaws.household.report_sections_proof_selection import proof_request_selection_section
from roboclaws.household.report_styles import planner_report_css
from roboclaws.household.report_tables import badge, metric, path_table, present_sections


def render_planner_manipulation_report(
    *,
    run_dir: Path,
    run_result: dict[str, Any],
) -> Path:
    """Write a shared-underlay report for planner-backed manipulation probes."""
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.html"
    evidence = run_result.get("manipulation_evidence") or {}
    quality = planner_proof_quality_evidence(evidence)
    body = f"""
    <section class="summary">
      <div class="summary-head">
        <p class="eyebrow">Manipulation artifact</p>
        <h1>Planner-Backed Manipulation Probe</h1>
      </div>
      <div class="metric-grid">
        {metric("Status", run_result.get("status", "unknown"))}
        {metric("Embodiment", evidence.get("embodiment", "unknown"))}
        {metric("Policy", evidence.get("upstream_policy_class", "unknown"))}
        {metric("Proof Quality", quality.get("quality_tier", "unknown"))}
        {metric("Steps", evidence.get("steps_executed", "n/a"))}
        {metric("Qpos delta", evidence.get("max_abs_qpos_delta", "n/a"))}
        {metric("Containment proven", "yes" if quality.get("containment_proven") else "no")}
      </div>
      <div class="badges">
        {badge("Contract", run_result.get("contract", "unknown"))}
        {badge("Backend", run_result.get("backend", "unknown"))}
        {badge("Probe mode", evidence.get("probe_mode", "unknown"))}
        {badge("Provenance", evidence.get("primitive_provenance", "unknown"))}
        {badge("Planner backed", evidence.get("planner_backed", False))}
      </div>
    </section>
    {manipulation_provenance_section(run_result)}
    {planner_probe_quality_section(evidence)}
    {planner_probe_views_section(evidence)}
    {planner_probe_cleanup_binding_section(evidence)}
    {planner_probe_task_sampler_robot_placement_profile_section(evidence)}
    {planner_probe_task_sampler_failure_section(evidence)}
    {planner_probe_post_placement_rejection_section(evidence)}
    {planner_probe_placement_scene_diagnostics_section(evidence)}
    {planner_probe_diagnostics_section(evidence)}
    {planner_probe_cuda_memory_section(evidence)}
    {planner_probe_curobo_memory_profile_section(evidence)}
    {planner_probe_policy_exception_section(evidence)}
    {planner_probe_curobo_extension_cache_section(evidence)}
    {planner_probe_warp_compatibility_section(evidence)}
    {planner_probe_worker_stages_section(evidence)}
    {rby1m_curobo_gate_section(run_result)}
    {planner_probe_blockers_section(evidence)}
    {planner_probe_artifacts_section(run_result)}
    """
    report_path.write_text(wrap_report_html(body, extra_css=planner_report_css()), encoding="utf-8")
    return report_path


def render_planner_proof_bundle_runner_report(
    *,
    output_dir: Path,
    manifest: dict[str, Any],
) -> Path:
    """Write a reviewable report for proof-bundle runner command manifests."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    commands = manifest.get("commands") or []
    cleanup_command = manifest.get("cleanup_command") or []
    cleanup_rerun = manifest.get("cleanup_rerun") or {}
    body = f"""
    <section class="summary">
      <div class="summary-head">
        <p class="eyebrow">Proof bundle runner artifact</p>
        <h1>Planner Proof Bundle Runner</h1>
      </div>
      <div class="metric-grid">
        {metric("Status", manifest.get("status", "unknown"))}
        {metric("Proof requests", manifest.get("proof_request_count", 0))}
        {metric("Ready requests", manifest.get("ready_request_count", 0))}
        {metric("Commands", manifest.get("command_count", len(commands)))}
      </div>
      <div class="badges">
        {badge("Schema", manifest.get("schema", "unknown"))}
        {badge("Output dir", manifest.get("output_dir", output_dir))}
      </div>
    </section>
    <section class="panel">
      <h2>Source Cleanup Artifact</h2>
      <p class="note">{html.escape(str(manifest.get("evidence_note", "")))}</p>
      {
        path_table(
            [
                ("Cleanup run result", manifest.get("cleanup_run_result", "")),
                (
                    "Planner scene XML",
                    (manifest.get("planner_scene") or {}).get("scene_xml", ""),
                ),
            ]
        )
    }
    </section>
    {proof_execution_horizon_section(manifest.get("proof_execution_horizon") or {})}
    {proof_request_selection_section(manifest.get("proof_request_selection") or {})}
    {
        grasp_feasibility_mitigation_decision_section(
            manifest.get("grasp_feasibility_mitigation_decision") or {}
        )
    }
    {
        grasp_cache_availability_preflight_section(
            manifest.get("grasp_cache_availability_preflight") or {}
        )
    }
    {
        grasp_cache_generation_preflight_section(
            manifest.get("grasp_cache_generation_preflight") or {}
        )
    }
    {proof_bundle_local_runtime_preflight_section(manifest.get("local_runtime_preflight") or {})}
    {
        proof_bundle_results_section(
            manifest.get("prior_proof_result_summary") or {},
            output_dir=output_dir,
            title="Prior Proof Evidence",
            section_class="prior-proof-evidence",
            default_note=(
                "Prior proof evidence consumed by selection. This keeps standalone "
                "probe and prior bundle visuals reviewable in the runner report."
            ),
        )
    }
    {proof_bundle_warmup_section(manifest.get("warmup") or {})}
    {proof_bundle_commands_section(commands)}
    {
        proof_bundle_results_section(
            manifest.get("proof_result_summary") or {}, output_dir=output_dir
        )
    }
    {cleanup_rerun_command_section(cleanup_command)}
    {cleanup_rerun_artifact_section(cleanup_rerun)}
    """
    report_path.write_text(wrap_report_html(body, extra_css=planner_report_css()), encoding="utf-8")
    return report_path


def render_grasp_cache_generation_report(
    *,
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write a reviewable report for MolmoSpaces grasp cache generation attempts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    body = "\n".join(present_sections(grasp_cache_generation_report_sections(result)))
    report_path.write_text(wrap_report_html(body, extra_css=planner_report_css()), encoding="utf-8")
    return report_path


def render_grasp_pose_policy_cache_report(
    *,
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write a reviewable report for validated pose-policy cache generation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"
    body = "\n".join(present_sections(grasp_pose_policy_cache_report_sections(result)))
    report_path.write_text(wrap_report_html(body, extra_css=planner_report_css()), encoding="utf-8")
    return report_path
