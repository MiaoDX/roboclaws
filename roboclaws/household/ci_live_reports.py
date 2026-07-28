from __future__ import annotations

import datetime as dt
import html
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object

MANIFEST_SCHEMA = "molmo_live_ci_report_manifest_v1"
STATUS_SCHEMA = "molmo_live_ci_entry_status_v1"
COMMON_DIAGNOSTIC_FILES = (
    "live_status.json",
    "claude-command.txt",
    "claude-version.txt",
    "claude-events.jsonl",
    "claude.stderr.log",
    "driver.log",
    "openai-agents-events.jsonl",
    "openai-agents-trace.json",
    "openai-agents-spans.jsonl",
    "openai-agents-server.log",
    "openai-agents-skill-context.json",
    "checker.log",
    "server.pid",
    "trace.jsonl",
    "run_result.json",
    "report.html",
    "agent_view.json",
    "private_evaluation.json",
    "advisory_evaluation.json",
    "planner_proof_requests.json",
)


@dataclass(frozen=True)
class MolmoLiveModelEntry:
    name: str
    label: str
    agent_engine: str
    provider_profile: str
    model: str
    secret_env: str
    profile: str


MODEL_ENTRIES: tuple[MolmoLiveModelEntry, ...] = (
    MolmoLiveModelEntry(
        name="agents-sdk-mimo-v2.5",
        label="OpenAI Agents SDK + MiMo v2.5",
        agent_engine="openai-agents-sdk",
        provider_profile="mimo-tp-openai-chat",
        model="mimo-v2.5",
        secret_env="MIMO_TP_KEY",
        profile="world-public-labels",
    ),
    MolmoLiveModelEntry(
        name="agents-sdk-kimi-k2.7-code",
        label="OpenAI Agents SDK + Kimi K2.7 Code",
        agent_engine="openai-agents-sdk",
        provider_profile="kimi-openai-chat",
        model="kimi-k2.7-code",
        secret_env="KIMI_API_KEY",
        profile="world-public-labels",
    ),
)


def entry_names() -> list[str]:
    return [entry.name for entry in MODEL_ENTRIES]


def entry_by_name(name: str) -> MolmoLiveModelEntry:
    for entry in MODEL_ENTRIES:
        if entry.name == name:
            return entry
    expected = ", ".join(entry_names())
    raise KeyError(f"unknown Molmo live model entry {name!r}; expected one of: {expected}")


def utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def base_status(
    entry: MolmoLiveModelEntry,
    *,
    seed: int,
    generated_mess_count: int,
    profile: str,
    task: str,
) -> dict[str, Any]:
    return {
        "schema": STATUS_SCHEMA,
        "entry": entry.name,
        "label": entry.label,
        "agent_engine": entry.agent_engine,
        "provider_profile": entry.provider_profile,
        "model": entry.model,
        "secret_env": entry.secret_env,
        "driver": entry.agent_engine,
        "profile": profile,
        "seed": seed,
        "generated_mess_count": generated_mess_count,
        "task": task,
        "created_at": utc_timestamp(),
        "status": "pending",
        "reason": "",
        "report_path": "",
        "run_dir": "",
        "diagnostic_path": "",
        "diagnostic_dir": "",
    }


def write_status(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_status(path: Path) -> dict[str, Any]:
    payload = read_json_object(path, label="Molmo live CI status")
    if payload.get("schema") != STATUS_SCHEMA:
        raise ValueError(f"{path} is not a {STATUS_SCHEMA} document")
    return payload


def status_path_for_entry(root: Path, entry_name: str) -> Path:
    return root / entry_name / "status.json"


def latest_seed_run_dir(entry_output_dir: Path, *, seed: int) -> Path | None:
    candidates = sorted(
        path
        for path in entry_output_dir.glob(f"*/seed-{seed}")
        if (path / "run_result.json").is_file()
    )
    return candidates[-1] if candidates else None


def latest_seed_artifact_dir(entry_output_dir: Path, *, seed: int) -> Path | None:
    candidates = sorted(
        path
        for path in entry_output_dir.glob(f"*/seed-{seed}")
        if path.is_dir() and _has_diagnostic_artifact(path)
    )
    return candidates[-1] if candidates else None


def publish_seed_run(
    *,
    source_seed_dir: Path,
    publish_root: Path,
    entry_name: str,
    seed: int,
) -> Path:
    destination = publish_root / entry_name / f"seed-{seed}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_seed_dir, destination)
    return destination


def publish_diagnostic_seed_run(
    *,
    source_seed_dir: Path,
    publish_root: Path,
    entry_name: str,
    seed: int,
) -> Path:
    destination = publish_root / entry_name / "diagnostics" / f"seed-{seed}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_seed_dir, destination)
    _write_diagnostic_index(destination)
    return destination


def report_path_for_entry(entry_name: str, *, seed: int) -> str:
    return f"{entry_name}/seed-{seed}/report.html"


def diagnostic_path_for_entry(entry_name: str, *, seed: int) -> str:
    return f"{entry_name}/diagnostics/seed-{seed}/diagnostics.html"


def _write_diagnostic_index(seed_dir: Path) -> Path:
    links = []
    for relative in COMMON_DIAGNOSTIC_FILES:
        path = seed_dir / relative
        if not path.is_file():
            continue
        size = path.stat().st_size
        links.append(
            "<li>"
            f'<a href="{html.escape(relative, quote=True)}">{html.escape(relative)}</a>'
            f" <span>{size} bytes</span>"
            "</li>"
        )
    if not links:
        links.append("<li>No common diagnostic files were found in this partial run.</li>")
    body = "\n".join(links)
    path = seed_dir / "diagnostics.html"
    path.write_text(
        "\n".join(
            [
                "<!doctype html>",
                '<meta charset="utf-8">',
                "<title>Molmo Live Cleanup Diagnostics</title>",
                "<h1>Molmo Live Cleanup Diagnostics</h1>",
                "<p>This directory is a partial seed run captured after a live CI failure.</p>",
                f"<ul>{body}</ul>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _has_diagnostic_artifact(seed_dir: Path) -> bool:
    return any((seed_dir / relative).is_file() for relative in COMMON_DIAGNOSTIC_FILES)


def collect_entry_statuses(root: Path) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for entry in MODEL_ENTRIES:
        path = status_path_for_entry(root, entry.name)
        if path.is_file():
            statuses.append(read_status(path))
    return statuses


def write_manifest(root: Path, statuses: list[dict[str, Any]] | None = None) -> Path:
    if statuses is None:
        statuses = collect_entry_statuses(root)
    payload = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": utc_timestamp(),
        "entries": statuses,
        "known_entries": [asdict(entry) for entry in MODEL_ENTRIES],
    }
    path = root / "live-report-manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_live_index(root: Path, statuses: list[dict[str, Any]] | None = None) -> Path:
    """Write the dedicated ``/molmo/live/`` Pages index."""
    if statuses is None:
        statuses = collect_entry_statuses(root)

    if statuses:
        rows = "\n".join(_live_index_row(status) for status in statuses)
    else:
        rows = (
            '<tr><td colspan="7">No MolmoSpaces live cleanup statuses were '
            "published in this Pages build.</td></tr>"
        )

    path = root / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "<!doctype html>",
                '<meta charset="utf-8">',
                "<title>MolmoSpaces Live Cleanup Reports</title>",
                "<style>",
                "body{font-family:system-ui,sans-serif;max-width:960px;margin:3rem auto;"
                "padding:0 1rem;color:#1a1a2e;background:#f5f6fa}",
                "table{border-collapse:collapse;width:100%;background:#fff}",
                "th,td{border:1px solid #d9dde8;padding:.65rem;text-align:left;vertical-align:top}",
                "th{background:#eef1f8}",
                "a{color:#2952cc;text-decoration:none;font-weight:600}",
                "a:hover{text-decoration:underline}",
                "code{background:#eef1f8;padding:1px 4px;border-radius:4px}",
                "td code{overflow-wrap:anywhere;white-space:pre-wrap}",
                ".sub{color:#555}",
                "</style>",
                "<h1>MolmoSpaces Live Cleanup Reports</h1>",
                '<p class="sub">Published by GitHub Actions for main-only / opt-in '
                "MolmoSpaces cleanup runs. Each row links to the report or diagnostics "
                "for one provider-backed live-agent run.</p>",
                "<table>",
                "<thead><tr><th>Model</th><th>Status</th><th>Profile</th><th>Report</th>"
                "<th>Provider</th><th>Rerun locally</th><th>Reason</th></tr></thead>",
                f"<tbody>{rows}</tbody>",
                "</table>",
                '<p><a href="../../">&larr; Back to RoboClaws reports</a></p>',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _live_index_row(status: dict[str, Any]) -> str:
    label = html.escape(str(status.get("label") or status.get("entry") or "Molmo live run"))
    state = html.escape(str(status.get("status") or "unknown"))
    provider = html.escape(str(status.get("provider_profile") or "unknown provider"))
    agent_engine = html.escape(str(status.get("agent_engine") or status.get("driver") or "unknown"))
    model = html.escape(str(status.get("model") or "unknown model"))
    profile = html.escape(str(status.get("profile") or "unknown profile"))
    reason = html.escape(str(status.get("reason") or ""))
    report_path = str(status.get("report_path") or "")
    diagnostic_path = str(status.get("diagnostic_path") or "")
    rerun_command = html.escape(str(status.get("rerun_command") or ""))

    if status.get("status") == "success" and report_path:
        href = html.escape(report_path, quote=True)
        report = f'<a href="{href}">report.html</a>'
    elif diagnostic_path:
        href = html.escape(diagnostic_path, quote=True)
        report = f'<a href="{href}">diagnostics.html</a>'
    else:
        report = "No report artifact"

    return (
        "<tr>"
        f"<td>{label}<br><code>{model}</code></td>"
        f"<td><code>{state}</code></td>"
        f"<td><code>{profile}</code></td>"
        f"<td>{report}</td>"
        f"<td><code>{agent_engine}</code><br><code>{provider}</code></td>"
        f"<td><code>{rerun_command}</code></td>"
        f"<td>{reason}</td>"
        "</tr>"
    )
