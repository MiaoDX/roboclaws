"""Markdown and HTML rendering for observability decision reports."""

from __future__ import annotations

import html
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
    projection = row.get("phoenix_projection")
    if isinstance(projection, dict):
        lines.append(f"- Phoenix projection: `{projection['state']}` ({projection['reason']})")
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
        if row.get("phoenix_run"):
            links.append(f"[Phoenix]({row['phoenix_run']})")
        if links:
            lines.append(f"  Evidence: {', '.join(links)}")
    return lines


def _coverage_markdown(report: dict[str, Any]) -> list[str]:
    return [
        f"- {name.replace('_', ' ').title()}: `{cell['numerator']}/{cell['denominator']}`"
        for name, cell in report["telemetry_coverage"].items()
        if name != "by_provider"
    ]


def render_observability_html(report: Any) -> str:
    if not isinstance(report, dict):
        return ""
    if report["state"] == "not_applicable":
        return (
            "<section><h2>Observability Decision Report</h2>"
            f"<p>Not applicable: <code>{html.escape(str(report['reason']))}</code></p></section>"
        )
    health = report["harness_health"]
    return (
        "<section><h2>Observability Decision Report</h2>"
        f'<p class="banner">State: <code>{html.escape(report["state"])}</code></p>'
        '<h3>Capability Health And Regression</h3><div class="summary">'
        f"<p><strong>{health['passed']}</strong> passed</p>"
        f"<p><strong>{health['failed']}</strong> failed</p>"
        f"<p><strong>{health['blocked']}</strong> blocked</p>"
        f"<p>{health['total']} selected rows</p></div>"
        + _baseline_html(report["capability_health"]["baseline_regressions"])
        + _slices_html(report["capability_health"]["slices"])
        + _provider_comparison_html(report)
        + _triage_html(report)
        + _coverage_html(report)
        + "</section>"
    )


def _provider_comparison_html(report: dict[str, Any]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(', '.join('/'.join(map(str, value)) for value in cohort['treatments']))}"
        "</td>"
        f"<td>{html.escape(cohort['claims']['quality']['state'])}</td>"
        f"<td>{html.escape(cohort['claims']['model_work']['state'])}</td>"
        f"<td>{html.escape(cohort['claims']['latency']['state'])}</td>"
        f"<td>{html.escape(cohort['claims']['latency']['reason'])}</td>"
        f"<td>{_cohort_metric_summary(cohort['metrics'])}</td></tr>"
        for cohort in report["provider_comparison"]["cohorts"]
    )
    return (
        '<h3>Fair Provider Comparison</h3><div class="table-wrap"><table><thead><tr>'
        "<th>Treatment</th><th>Quality</th><th>Model work</th><th>Latency</th><th>Reason</th>"
        f"<th>Metrics</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _triage_html(report: dict[str, Any]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['row_id'])}</td>"
        f"<td>{html.escape(row.get('trial_id') or 'row')}</td>"
        f"<td>{html.escape(row.get('outcome') or '')}</td>"
        f"<td>{html.escape(row.get('failure_class') or '')}</td>"
        f"<td>{html.escape(row.get('terminal_reason') or '')}</td>"
        f"<td>{_triage_detail_html(row)}</td><td>{_triage_links_html(row)}</td></tr>"
        for row in report["triage"]["rows"]
        if row.get("outcome") in {"failed", "blocked", "inconclusive"}
    )
    return (
        '<h3>Failure And Stall Triage</h3><div class="table-wrap"><table><thead><tr>'
        "<th>Row</th><th>Trial</th><th>Outcome</th><th>Failure owner</th><th>Reason</th>"
        "<th>Attempts / Tools</th><th>Evidence</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _coverage_html(report: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(name.replace('_', ' ').title())}</td>"
        f"<td>{cell['numerator']}/{cell['denominator']}</td></tr>"
        for name, cell in report["telemetry_coverage"].items()
        if name != "by_provider"
    )
    return (
        '<h3>Telemetry Coverage</h3><div class="table-wrap"><table><thead><tr>'
        f"<th>Evidence</th><th>Coverage</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _baseline_html(baselines: list[dict[str, Any]]) -> str:
    if not baselines:
        return "<p>No explicit prior baseline attached.</p>"
    return "".join(
        f"<p>Baseline <code>{html.escape(item['label'])}</code>: "
        f"{html.escape(', '.join(item['regressed_row_ids']) or 'no regressions')}</p>"
        for item in baselines
    )


def _slices_html(slices: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(dimension.replace('_', ' ').title())}</td>"
        f"<td>{html.escape(value)}</td><td>{counts['passed']}</td>"
        f"<td>{counts['failed']}</td><td>{counts['blocked']}</td></tr>"
        for dimension, values in slices.items()
        for value, counts in values.items()
    )
    return (
        '<details><summary>Capability slices</summary><div class="table-wrap"><table>'
        "<thead><tr><th>Dimension</th><th>Value</th><th>Passed</th><th>Failed</th>"
        f"<th>Blocked</th></tr></thead><tbody>{rows}</tbody></table></div></details>"
    )


def _cohort_metric_summary(metrics: dict[str, Any]) -> str:
    names = (
        "wall_time_s",
        "observed_model_time_s",
        "model_call_count",
        "tool_call_count",
        "input_tokens",
        "uncached_input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    return "<br>".join(_metric_html(name, metrics[name]) for name in names)


def _metric_html(name: str, cell: dict[str, Any]) -> str:
    coverage = cell["coverage"]
    return (
        f"{html.escape(name)}={html.escape(str(cell['value']))} "
        f"({coverage['numerator']}/{coverage['denominator']})"
    )


def _triage_detail_html(row: dict[str, Any]) -> str:
    attempts = row.get("model_attempts") or {}
    parts = [
        f"attempts={attempts.get('attempt_count', 'unavailable')}",
        f"failures={attempts.get('failure_count', 'unavailable')}",
        f"longest_model_call_s={row.get('longest_model_call_s')}",
        f"tools={row.get('tool_call_count')}",
    ]
    if row.get("timeout_budget_s") is not None:
        parts.append(f"timeout={row['timeout_budget_s']}s/{row.get('timeout_signal') or 'unknown'}")
    breakdown = row.get("tool_breakdown") or {}
    if breakdown:
        parts.append(
            "tool_breakdown="
            + ", ".join(f"{key}:{value}" for key, value in sorted(breakdown.items()))
        )
    return "<br>".join(html.escape(str(value)) for value in parts)


def _triage_links_html(row: dict[str, Any]) -> str:
    links = [
        f'<a href="{html.escape(str(target), quote=True)}">{html.escape(str(name))}</a>'
        for name, target in row.get("local_artifacts", {}).items()
        if target
    ]
    if row.get("phoenix_run"):
        links.append(f'<a href="{html.escape(str(row["phoenix_run"]), quote=True)}">Phoenix</a>')
    return "<br>".join(links) or "unavailable"
