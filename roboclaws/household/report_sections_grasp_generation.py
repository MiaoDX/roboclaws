from __future__ import annotations

import html
from typing import Any


def grasp_cache_generation_report_sections(result: dict[str, Any]) -> list[str]:
    return [
        _grasp_cache_generation_summary_section(result),
        _grasp_cache_generation_assets_section(result.get("assets") or []),
        _grasp_cache_generation_command_section(result),
        _grasp_cache_generation_blockers_section(result.get("blockers") or []),
    ]


def grasp_pose_policy_cache_report_sections(result: dict[str, Any]) -> list[str]:
    return [
        _grasp_pose_policy_cache_summary_section(result),
        _grasp_pose_policy_cache_policy_section(result.get("pose_policy") or {}),
        _grasp_pose_policy_cache_artifacts_section(result),
        _grasp_cache_generation_assets_section(result.get("assets") or []),
        _grasp_cache_generation_command_section(result),
        _grasp_cache_generation_blockers_section(result.get("blockers") or []),
    ]


def _grasp_cache_generation_summary_section(result: dict[str, Any]) -> str:
    return (
        '<section class="summary grasp-cache-generation-result">'
        '<div class="summary-head">'
        '<p class="eyebrow">Grasp cache generation artifact</p>'
        "<h1>MolmoSpaces Grasp Cache Generation</h1>"
        "</div>"
        '<div class="metric-grid">'
        f"{_metric('Status', result.get('status', ''))}"
        f"{_metric('Assets', result.get('asset_count', 0))}"
        f"{_metric('Blockers', result.get('blocker_count', 0))}"
        f"{_metric('Ready', _yes_no(result.get('ready')))}"
        "</div>"
        '<div class="badges">'
        f"{_badge('Schema', result.get('schema', 'unknown'))}"
        f"{_badge('Objects list', result.get('objects_list_path', ''))}"
        f"{_badge('Assets symlink', _assets_symlink_summary(result.get('assets_symlink') or {}))}"
        "</div>"
        f'<p class="note">{html.escape(str(result.get("evidence_note") or ""))}</p>'
        "</section>"
    )


def _grasp_cache_generation_assets_section(assets: list[dict[str, Any]]) -> str:
    rows = []
    for asset in assets:
        generated = asset.get("generated_validation") or {}
        installed = asset.get("installed_validation") or {}
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(asset.get('asset_uid', '')))}</td>"
            f"<td>{html.escape(str(generated.get('validation_status', '')))}</td>"
            f"<td>{html.escape(str(generated.get('transform_count', 0)))}</td>"
            f"<td>{html.escape(_yes_no(asset.get('installed')))}</td>"
            f"<td>{html.escape(str(installed.get('validation_status', '')))}</td>"
            f"<td>{html.escape(str(installed.get('transform_count', 0)))}</td>"
            f"<td>{html.escape(str(asset.get('generated_npz_path', '')))}</td>"
            f"<td>{html.escape(str(asset.get('cache_target_path', '')))}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        '<section class="panel grasp-cache-generation-assets">'
        "<h2>Generated Cache Assets</h2>"
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Asset</th><th>Generated status</th><th>Generated transforms</th>"
        "<th>Installed</th><th>Installed status</th><th>Installed transforms</th>"
        "<th>Generated NPZ</th><th>Cache target</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        "</section>"
    )


def _grasp_cache_generation_command_section(result: dict[str, Any]) -> str:
    command = " ".join(str(part) for part in result.get("command") or [])
    command_result = result.get("command_result") or {}
    if not command:
        return ""
    rows = [
        ("Command status", command_result.get("status", "")),
        ("Return code", command_result.get("returncode", "")),
        ("Stdout tail", _tail_text(command_result.get("stdout", ""), limit=1600)),
        ("Stderr tail", _tail_text(command_result.get("stderr", ""), limit=1600)),
    ]
    table_rows = "".join(
        f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
        if value not in ("", None)
    )
    return (
        '<section class="panel grasp-cache-generation-command">'
        "<h2>Generation Command</h2>"
        f"<pre><code>{html.escape(command)}</code></pre>"
        '<div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th></tr></thead>'
        f"<tbody>{table_rows}</tbody></table></div>"
        "</section>"
    )


def _grasp_cache_generation_blockers_section(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return (
            '<section class="panel"><h2>Generation Blockers</h2>'
            '<p class="note">No generation blockers recorded.</p></section>'
        )
    rows = []
    for blocker in blockers:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(blocker.get('code', '')))}</td>"
            f"<td>{html.escape(str(blocker.get('asset_uid', '')))}</td>"
            f"<td>{html.escape(str(blocker.get('message', '')))}</td>"
            "</tr>"
        )
    return (
        '<section class="panel grasp-cache-generation-blockers">'
        "<h2>Generation Blockers</h2>"
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Code</th><th>Asset</th><th>Message</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        "</section>"
    )


def _grasp_pose_policy_cache_summary_section(result: dict[str, Any]) -> str:
    policy = result.get("pose_policy") or {}
    return (
        '<section class="summary grasp-pose-policy-cache-result">'
        '<div class="summary-head">'
        '<p class="eyebrow">Pose-policy cache artifact</p>'
        "<h1>MolmoSpaces Pose Policy Grasp Cache</h1>"
        "</div>"
        '<div class="metric-grid">'
        f"{_metric('Status', result.get('status', ''))}"
        f"{_metric('Object', result.get('object_name', ''))}"
        f"{_metric('Candidates', result.get('candidate_count', 0))}"
        f"{_metric('Generated transforms', result.get('successful_transform_count', 0))}"
        f"{_metric('Installed', _yes_no((result.get('assets') or [{}])[0].get('installed')))}"
        f"{_metric('Blockers', result.get('blocker_count', 0))}"
        "</div>"
        '<div class="badges">'
        f"{_badge('Schema', result.get('schema', 'unknown'))}"
        f"{_badge('Policy', policy.get('name', ''))}"
        f"{_badge('Install requested', _yes_no(result.get('install_requested')))}"
        f"{_badge('Assets symlink', _assets_symlink_summary(result.get('assets_symlink') or {}))}"
        "</div>"
        f'<p class="note">{html.escape(str(result.get("evidence_note") or ""))}</p>'
        "</section>"
    )


def _grasp_pose_policy_cache_policy_section(policy: dict[str, Any]) -> str:
    if not policy:
        return ""
    rows = [
        ("Policy name", policy.get("name", "")),
        ("Source", policy.get("source", "")),
        ("Approach sign", policy.get("approach_sign", "")),
        ("Approach distance", policy.get("approach_distance", "")),
        ("Settle steps", policy.get("settle_steps", "")),
        ("Source success count", policy.get("source_success_count", "")),
    ]
    table_rows = "".join(
        f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
        if value not in ("", None)
    )
    return (
        '<section class="panel grasp-pose-policy-cache-policy">'
        "<h2>Pose Policy</h2>"
        '<div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th></tr></thead>'
        f"<tbody>{table_rows}</tbody></table></div>"
        "</section>"
    )


def _grasp_pose_policy_cache_artifacts_section(result: dict[str, Any]) -> str:
    command_result = result.get("command_result") or {}
    rows = [
        ("Candidate grasps", result.get("candidate_grasps_path", "")),
        ("Object XML", result.get("object_xml", "")),
        ("Artifact dir", result.get("artifact_dir", "")),
        ("Probe script", result.get("probe_script_path", "")),
        ("Probe result", result.get("probe_output_path", "")),
        ("Generated NPZ", result.get("generated_npz_path", "")),
        ("Command status", command_result.get("status", "")),
        ("Command return", command_result.get("returncode", "")),
        (
            "Command output tail",
            _tail_text(command_result.get("stderr") or command_result.get("stdout"), limit=500),
        ),
    ]
    table_rows = "".join(
        f"<tr><td>{html.escape(str(label))}</td><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
        if value not in ("", None)
    )
    return (
        '<section class="panel grasp-pose-policy-cache-artifacts">'
        "<h2>Cache Artifacts</h2>"
        '<div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th></tr></thead>'
        f"<tbody>{table_rows}</tbody></table></div>"
        "</section>"
    )


def _assets_symlink_summary(symlink: dict[str, Any]) -> str:
    if not symlink:
        return ""
    return (
        f"{symlink.get('status', '')}; path={symlink.get('path', '')}; "
        f"target={symlink.get('target', '')}; created={_yes_no(symlink.get('created'))}"
    )


def _badge(label: str, value: Any) -> str:
    return (
        f'<span class="badge">{html.escape(str(label))}: '
        f"<strong>{html.escape(str(value))}</strong></span>"
    )


def _metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{html.escape(str(label))}</span>"
        f"<strong>{html.escape(str(value))}</strong>"
        "</div>"
    )


def _tail_text(value: Any, *, limit: int) -> str:
    text = str(value or "")
    return text[-limit:] if len(text) > limit else text


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"
