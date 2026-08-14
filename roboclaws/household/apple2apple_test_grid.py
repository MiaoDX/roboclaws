from __future__ import annotations

import datetime as dt
import html
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from roboclaws.agents.provider_registry import (
    PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
    provider_route_spec,
)
from roboclaws.core.rerun import shell_join
from roboclaws.household.household_runtime_contract import DEFAULT_REALWORLD_TASK

GRID_SCHEMA = "molmo_apple2apple_test_grid_v1"
ROW_SCHEMA = "molmo_apple2apple_test_grid_row_v1"
DEFAULT_MAP_BUNDLE = "assets/maps/molmospaces/procthor-10k-val/0"
RUNTIME_MAP_PRIOR_PLACEHOLDER = "${ROBOCLAWS_RUNTIME_MAP_PRIOR}"


@dataclass(frozen=True)
class AgentRoute:
    route_id: str
    label: str
    driver: str
    agent_engine: str
    provider_profile: str
    env: dict[str, str]
    required_env: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceLane:
    lane_id: str
    label: str
    profile: str
    camera_labeler: str
    input_mode: str


AGENT_ROUTES: tuple[AgentRoute, ...] = (
    AgentRoute(
        route_id="agents-sdk-kimi",
        label="OpenAI Agents SDK Kimi",
        driver="openai-agents-sdk",
        agent_engine="openai-agents-sdk",
        provider_profile=PROVIDER_PROFILE_KIMI_OPENAI_CHAT,
        env={"ROBOCLAWS_PROVIDER_PROFILE": PROVIDER_PROFILE_KIMI_OPENAI_CHAT},
        required_env=provider_route_spec(PROVIDER_PROFILE_KIMI_OPENAI_CHAT).required_env_keys,
    ),
)

EVIDENCE_LANES: tuple[EvidenceLane, ...] = (
    EvidenceLane(
        lane_id="camera-grounded-labels-grounding-dino",
        label="Grounding DINO camera labels",
        profile="camera-grounded-labels",
        camera_labeler="grounding-dino",
        input_mode="camera_labels",
    ),
)

PRIOR_MODES = ("online", "offline")


def build_apple2apple_test_grid(
    *,
    output_dir: Path,
    seed: int = 7,
    generated_mess_count: int = 10,
    task: str = DEFAULT_REALWORLD_TASK,
    map_bundle: str = DEFAULT_MAP_BUNDLE,
    runtime_map_prior: str = "",
    visual_grounding_timeout_s: str = "auto",
) -> dict[str, Any]:
    """Build the requested MolmoSpaces apple-to-apple cleanup test grid."""
    output_dir = Path(output_dir)
    prior_value = runtime_map_prior or RUNTIME_MAP_PRIOR_PLACEHOLDER
    setup_rows = [
        _runtime_map_prior_row(
            output_dir=output_dir,
            seed=seed,
            generated_mess_count=generated_mess_count,
            task=task,
            map_bundle=map_bundle,
        )
    ]
    rows: list[dict[str, Any]] = []
    for prior_mode in PRIOR_MODES:
        for agent_route in AGENT_ROUTES:
            for lane in EVIDENCE_LANES:
                rows.append(
                    _cleanup_grid_row(
                        output_dir=output_dir,
                        seed=seed,
                        generated_mess_count=generated_mess_count,
                        task=task,
                        map_bundle=map_bundle,
                        prior_mode=prior_mode,
                        agent_route=agent_route,
                        lane=lane,
                        runtime_map_prior=prior_value if prior_mode == "offline" else "",
                        visual_grounding_timeout_s=visual_grounding_timeout_s,
                    )
                )

    return {
        "schema": GRID_SCHEMA,
        "generated_at": _utc_timestamp(),
        "name": "molmospaces_apple2apple_g2_grid",
        "description": (
            "Apple-to-apple MolmoSpaces cleanup grid for online/offline Runtime "
            "Metric Map comparison through the OpenAI Agents SDK Kimi Chat route, "
            "with Grounding DINO evidence."
        ),
        "seed": seed,
        "generated_mess_count": generated_mess_count,
        "task": task,
        "map_bundle": map_bundle,
        "runtime_map_prior": runtime_map_prior,
        "runtime_map_prior_placeholder": RUNTIME_MAP_PRIOR_PLACEHOLDER,
        "axes": {
            "prior_modes": list(PRIOR_MODES),
            "agent_routes": [asdict(item) for item in AGENT_ROUTES],
            "evidence_lanes": [asdict(item) for item in EVIDENCE_LANES],
        },
        "setup_rows": setup_rows,
        "rows": rows,
    }


def write_grid_manifest(grid: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "apple2apple_test_grid.json"
    path.write_text(json.dumps(grid, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_grid_report(grid: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(_render_row(row) for row in grid.get("rows") or [])
    setup_rows = "\n".join(_render_row(row) for row in grid.get("setup_rows") or [])
    if not rows:
        rows = '<tr><td colspan="10">No cleanup rows were generated.</td></tr>'
    if not setup_rows:
        setup_rows = '<tr><td colspan="10">No setup rows were generated.</td></tr>'
    path = output_dir / "apple2apple_test_grid.html"
    path.write_text(
        "\n".join(
            [
                "<!doctype html>",
                '<meta charset="utf-8">',
                "<title>MolmoSpaces Apple-To-Apple Test Grid</title>",
                "<style>",
                "body{font-family:system-ui,sans-serif;max-width:1180px;margin:2rem auto;"
                "padding:0 1rem;color:#202331;background:#f7f8fb}",
                "table{border-collapse:collapse;width:100%;background:white;margin:1rem 0}",
                "th,td{border:1px solid #d9dee8;padding:.55rem;text-align:left;vertical-align:top}",
                "th{background:#edf1f7}",
                "code{background:#f0f3f8;padding:1px 4px;border-radius:4px;white-space:pre-wrap}",
                ".sub{color:#5f6675}",
                "</style>",
                "<h1>MolmoSpaces Apple-To-Apple Test Grid</h1>",
                f'<p class="sub">{html.escape(str(grid.get("description") or ""))}</p>',
                "<h2>Setup Rows</h2>",
                f"<table>{_thead()}{setup_rows}</table>",
                "<h2>Cleanup Rows</h2>",
                f"<table>{_thead()}{rows}</table>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def mark_grid_dry_run(grid: dict[str, Any]) -> dict[str, Any]:
    for row in [*(grid.get("setup_rows") or []), *(grid.get("rows") or [])]:
        row["status"] = "dry_run"
        row["reason"] = "dry run requested; command was not executed"
        row["updated_at"] = _utc_timestamp()
    return grid


def row_rerun_command(row: dict[str, Any]) -> str:
    env = row.get("env") or {}
    env_prefix = " ".join(f"{key}={value}" for key, value in sorted(env.items()))
    command = shell_join(row.get("command") or [])
    return f"{env_prefix} {command}".strip()


def _runtime_map_prior_row(
    *,
    output_dir: Path,
    seed: int,
    generated_mess_count: int,
    task: str,
    map_bundle: str,
) -> dict[str, Any]:
    row_output_dir = output_dir / "_offline-runtime-map-prior"
    command = [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=map-build",
        "agent_engine=direct-runner",
        "evidence_lane=world-public-labels",
        "scenario_setup=baseline",
        f"seed={seed}",
        f"output_dir={row_output_dir}",
        f"prompt={task}",
        f"map_bundle={map_bundle}",
    ]
    return _row_payload(
        row_id="setup-offline-runtime-map-prior",
        label="Offline Runtime Metric Map prior",
        grid_role="setup",
        command=command,
        output_dir=row_output_dir,
        axes={
            "prior_mode": "offline-prior-build",
            "agent_route": "direct",
            "evidence_lane": "world-public-labels",
        },
        env={},
        required_env=(),
        requires_runtime_map_prior=False,
        expected_artifacts=["runtime_metric_map.json", "report.html"],
    )


def _cleanup_grid_row(
    *,
    output_dir: Path,
    seed: int,
    generated_mess_count: int,
    task: str,
    map_bundle: str,
    prior_mode: str,
    agent_route: AgentRoute,
    lane: EvidenceLane,
    runtime_map_prior: str,
    visual_grounding_timeout_s: str,
) -> dict[str, Any]:
    row_id = f"{prior_mode}-{agent_route.route_id}-{lane.lane_id}"
    row_output_dir = output_dir / row_id
    command = [
        "just",
        "run::surface",
        "surface=household-world",
        "world=molmospaces/procthor-10k-val/0",
        "backend=mujoco",
        "intent=cleanup",
        f"agent_engine={agent_route.agent_engine}",
        f"provider_profile={agent_route.provider_profile}",
        f"evidence_lane={lane.profile}",
        f"seed={seed}",
        "scenario_setup=relocate-cleanup-related-objects",
        f"relocation_count={generated_mess_count}",
        f"output_dir={row_output_dir}",
        f"prompt={task}",
        f"map_bundle={map_bundle}",
    ]
    if lane.camera_labeler:
        command.append(f"camera_labeler={lane.camera_labeler}")
    if visual_grounding_timeout_s != "auto":
        command.append(f"visual_grounding_timeout_s={visual_grounding_timeout_s}")
    if runtime_map_prior:
        command.append(f"runtime_map_prior={runtime_map_prior}")
    return _row_payload(
        row_id=row_id,
        label=f"{prior_mode} {agent_route.label} {lane.label}",
        grid_role="cleanup",
        command=command,
        output_dir=row_output_dir,
        axes={
            "prior_mode": prior_mode,
            "agent_route": agent_route.route_id,
            "evidence_lane": lane.profile,
            "camera_labeler": lane.camera_labeler,
            "input_mode": lane.input_mode,
        },
        env=agent_route.env,
        required_env=agent_route.required_env,
        requires_runtime_map_prior=bool(runtime_map_prior),
        expected_artifacts=["run_result.json", "report.html", "runtime_metric_map.json"],
    )


def _row_payload(
    *,
    row_id: str,
    label: str,
    grid_role: str,
    command: list[str],
    output_dir: Path,
    axes: dict[str, str],
    env: dict[str, str],
    required_env: tuple[str, ...],
    requires_runtime_map_prior: bool,
    expected_artifacts: list[str],
) -> dict[str, Any]:
    row = {
        "schema": ROW_SCHEMA,
        "row_id": row_id,
        "label": label,
        "grid_role": grid_role,
        "axes": axes,
        "command": [str(item) for item in command],
        "env": dict(env),
        "required_env": list(required_env),
        "output_dir": str(output_dir),
        "requires_runtime_map_prior": requires_runtime_map_prior,
        "expected_artifacts": expected_artifacts,
        "status": "pending",
        "reason": "",
        "run_dir": "",
        "report_path": "",
    }
    row["rerun_command"] = row_rerun_command(row)
    return row


def _thead() -> str:
    return (
        "<thead><tr><th>Row</th><th>Status</th><th>Prior</th><th>Agent</th>"
        "<th>Evidence Lane</th><th>Camera Labeler</th><th>Env</th><th>Command</th>"
        "<th>Report</th><th>Reason</th></tr></thead>"
    )


def _render_row(row: dict[str, Any]) -> str:
    axes = row.get("axes") or {}
    env = "<br>".join(
        f"<code>{html.escape(key)}={html.escape(value)}</code>"
        for key, value in sorted((row.get("env") or {}).items())
    )
    if not env:
        env = "none"
    report_path = str(row.get("report_path") or "")
    if report_path:
        report = f'<a href="{html.escape(report_path, quote=True)}">report.html</a>'
    else:
        report = "pending"
    return (
        "<tr>"
        f"<td>{html.escape(str(row.get('label') or row.get('row_id') or 'row'))}"
        f"<br><code>{html.escape(str(row.get('row_id') or ''))}</code></td>"
        f"<td><code>{html.escape(str(row.get('status') or 'pending'))}</code></td>"
        f"<td><code>{html.escape(str(axes.get('prior_mode') or ''))}</code></td>"
        f"<td><code>{html.escape(str(axes.get('agent_route') or ''))}</code></td>"
        f"<td><code>{html.escape(str(axes.get('evidence_lane') or ''))}</code></td>"
        f"<td><code>{html.escape(str(axes.get('camera_labeler') or 'none'))}</code></td>"
        f"<td>{env}</td>"
        f"<td><code>{html.escape(str(row.get('rerun_command') or ''))}</code></td>"
        f"<td>{report}</td>"
        f"<td>{html.escape(str(row.get('reason') or ''))}</td>"
        "</tr>"
    )


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
