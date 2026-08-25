"""Markdown rendering for observability decision reports."""

from __future__ import annotations

from typing import Any


def render_harness_row_markdown(row: dict[str, Any]) -> list[str]:
    selected = "selected" if row.get("selected") else "skipped"
    lines = [
        f"### {row['row_id']}",
        "",
        f"- Kind: `{row['row_kind']}`",
        f"- Status: `{row['status']}`",
    ]
    for key, label in (
        ("outcome", "Outcome"),
        ("failure_class", "Failure class"),
        ("blocker_category", "Blocker"),
        ("reason_selected", "Rationale"),
        ("skip_reason", "Skip reason"),
    ):
        if row.get(key):
            value = row[key] if key == "reason_selected" else f"`{row[key]}`"
            lines.append(f"- {label}: {value}")
    projection = row.get("opik_projection")
    if isinstance(projection, dict):
        lines.append(f"- Opik projection: `{projection['state']}` ({projection['reason']})")
    lines.append(f"- Selection: `{selected}`")
    artifacts = ", ".join(
        str(item)
        for item in row.get("output_artifacts") or []
        if "/tmp/roboclaws-cloudml/" not in str(item)
    )
    if artifacts:
        lines.append(f"- Artifacts: {artifacts}")
    lines.extend([f"- Command: `{row['command_display']}`", ""])
    return lines


def render_observability_markdown(report: Any) -> list[str]:
    if not isinstance(report, dict):
        return []
    lines = ["", "## Observability Decision Report", "", f"- State: `{report['state']}`"]
    if report["state"] == "not_applicable":
        return [*lines, f"- Reason: `{report['reason']}`"]
    health = report["harness_health"]
    return [
        *lines,
        "",
        "### Capability Health And Regression",
        "",
        f"- Harness rows: `{health['passed']}` passed, `{health['failed']}` failed, "
        f"`{health['blocked']}` blocked (`{health['total']}` total)",
        f"- Candidate status: `{health['candidate_status']}`",
        "",
        "### Fair Provider Comparison",
        "",
        *_comparison_markdown(report),
        "",
        "### Failure And Stall Triage",
        "",
        *_triage_markdown(report),
        "",
        "### Telemetry Coverage",
        "",
        *_coverage_markdown(report),
    ]


def _comparison_markdown(report: dict[str, Any]) -> list[str]:
    lines = [
        f"- {dimension.replace('_', ' ').title()}: {len(values)} slices"
        for dimension, values in report["capability_health"]["slices"].items()
    ]
    for baseline in report["capability_health"]["baseline_regressions"]:
        rows = ", ".join(f"`{value}`" for value in baseline["regressed_row_ids"]) or "none"
        lines.append(f"- Baseline `{baseline['label']}` regressions: {rows}")
    for cohort in report["provider_comparison"]["cohorts"]:
        claims = cohort["claims"]
        treatments = ", ".join("/".join(map(str, item)) for item in cohort["treatments"])
        lines.append(
            f"- {treatments or 'no provider treatment'}: quality `{claims['quality']['state']}`, "
            f"model work `{claims['model_work']['state']}`, latency `{claims['latency']['state']}` "
            f"({claims['latency']['reason']})"
        )
    return lines


def _triage_markdown(report: dict[str, Any]) -> list[str]:
    lines = []
    for row in report["triage"]["rows"]:
        if row.get("outcome") not in {"failed", "blocked", "inconclusive"}:
            continue
        detail = row.get("terminal_reason") or row.get("failure_class") or "unclassified"
        lines.append(f"- `{row['row_id']}` / `{row.get('trial_id') or 'row'}`: {detail}")
        links = [
            f"[{name}]({target})"
            for name, target in row.get("local_artifacts", {}).items()
            if target
        ]
        if row.get("opik_run"):
            links.append(f"[Opik]({row['opik_run']})")
        if links:
            lines.append(f"  Evidence: {', '.join(links)}")
    return lines


def _coverage_markdown(report: dict[str, Any]) -> list[str]:
    return [
        f"- {name.replace('_', ' ').title()}: `{cell['numerator']}/{cell['denominator']}`"
        for name, cell in report["telemetry_coverage"].items()
        if name != "by_provider"
    ]
