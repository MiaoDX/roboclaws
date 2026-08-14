from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DURATION_MS = 900
DEFAULT_HOLD_MS = 1400
TOOLS = [
    ("observe", "Observe"),
    ("navigate_to_object", "Nav object"),
    ("pick", "Pick"),
    ("navigate_to_receptacle", "Nav receptacle"),
    ("open_receptacle", "Open"),
    ("place", "Place"),
    ("place_inside", "Place inside"),
    ("close_receptacle", "Close"),
    ("done", "Done"),
]
ACTION_ALIASES = {
    "navigate_object": "navigate_to_object",
    "navigate_receptacle": "navigate_to_receptacle",
}


@dataclass(frozen=True)
class FrameSpec:
    label: str
    chapter: str
    title: str
    subtitle: str
    active_tool: str
    duration_ms: int = DEFAULT_DURATION_MS


def load_steps(run_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_steps = run_result.get("robot_view_steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("run_result.json does not contain robot_view_steps")
    steps = {
        str(raw_step["label"]): raw_step
        for raw_step in raw_steps
        if isinstance(raw_step, dict) and raw_step.get("label")
    }
    if not steps:
        raise ValueError("robot_view_steps does not contain labeled frames")
    return steps


def build_frame_plan(
    *,
    run_dir: Path,
    run_result: dict[str, Any],
    steps: dict[str, dict[str, Any]],
    duration_ms: int = DEFAULT_DURATION_MS,
    hold_ms: int = DEFAULT_HOLD_MS,
    max_chain_frames: int = 0,
) -> list[FrameSpec]:
    ordered_steps = sorted(steps.values(), key=lambda step: _label_index(str(step["label"])))
    total_waypoints = _inspection_waypoint_count(run_result)
    observe_progress = _observe_progress_by_label(run_dir / "trace.jsonl", total_waypoints)
    specs: list[FrameSpec] = []

    before = _first_step_with_action(ordered_steps, "before")
    if before:
        specs.append(
            FrameSpec(
                label=before["label"],
                chapter="Task",
                title="Household cleanup starts",
                subtitle=_context_subtitle(run_result),
                active_tool="observe",
                duration_ms=hold_ms,
            )
        )
    specs.extend(
        _observe_sweep_specs(
            ordered_steps,
            observe_progress=observe_progress,
            total_waypoints=total_waypoints,
            duration_ms=duration_ms,
        )
    )
    for chain_index, chain in enumerate(_object_action_chains(ordered_steps), start=1):
        chain_steps = _trim_chain(chain, max_chain_frames)
        for action_index, step in enumerate(chain_steps, start=1):
            specs.append(
                _action_frame_spec(
                    step=step,
                    chain_index=chain_index,
                    action_index=action_index,
                    chain_total=len(chain_steps),
                    duration_ms=duration_ms,
                )
            )
    after = _first_step_with_action(ordered_steps, "after")
    if after:
        specs.append(
            FrameSpec(
                label=after["label"],
                chapter="Done",
                title="Cleanup complete",
                subtitle=_final_subtitle(run_result),
                active_tool="done",
                duration_ms=hold_ms,
            )
        )
    return _dedupe_specs(specs)


def evaluation_summary(run_result: dict[str, Any]) -> dict[str, Any]:
    score = run_result.get("score") or {}
    semantic = score.get("semantic_acceptability") or {}
    total = semantic.get("total_targets") or score.get("total_targets")
    return {
        "cleanup_status": run_result.get("cleanup_status") or score.get("status"),
        "completion_status": run_result.get("completion_status") or score.get("completion_status"),
        "semantic_accepted": semantic.get("accepted_count"),
        "semantic_total": total,
        "exact_restored": score.get("restored_count"),
        "exact_total": score.get("total_targets") or total,
        "disturbance_count": score.get("disturbance_count", run_result.get("disturbance_count")),
        "sweep_coverage_rate": run_result.get("sweep_coverage_rate")
        or score.get("sweep_coverage_rate"),
    }


def run_context(run_result: dict[str, Any]) -> dict[str, Any]:
    task_surface = str(run_result.get("task_surface") or "household-world")
    task_intent = str(run_result.get("task_intent") or "cleanup")
    return {
        "task_name": task_surface,
        "task_surface": task_surface,
        "task_intent": task_intent,
        "driver": _driver_name(run_result),
        "profile": run_result.get("evidence_lane")
        or run_result.get("cleanup_profile")
        or run_result.get("perception_mode")
        or "run",
        "backend": run_result.get("backend") or run_result.get("robot", {}).get("backend"),
        "seed": run_result.get("seed"),
    }


def _inspection_waypoint_count(run_result: dict[str, Any]) -> int:
    candidates = (
        run_result.get("agent_view", {})
        .get("metric_map", {})
        .get("generated_exploration_candidates", [])
    )
    if isinstance(candidates, list) and candidates:
        return len(candidates)
    candidates = run_result.get("runtime_metric_map", {}).get("inspection_waypoints", [])
    return len(candidates) if isinstance(candidates, list) and candidates else 0


def _observe_progress_by_label(trace_path: Path, total_waypoints: int) -> dict[str, dict[str, Any]]:
    if not trace_path.exists():
        return {}
    progress: dict[str, dict[str, Any]] = {}
    seen_waypoints: set[str] = set()
    pending: dict[str, Any] | None = None
    for _, event in _read_jsonl_object_rows(trace_path, label="showcase trace"):
        if event.get("event") == "response" and event.get("tool") == "observe":
            response = event.get("response", {})
            waypoint_id = response.get("waypoint_id") or response.get("inspection_waypoint_id")
            if waypoint_id:
                seen_waypoints.add(str(waypoint_id))
            pending = {
                "observed": len(seen_waypoints),
                "total": total_waypoints or None,
                "source_observation_id": response.get("source_observation_id"),
                "waypoint_id": waypoint_id,
            }
        elif event.get("event") == "robot_view_capture" and event.get("action") == "observe":
            label = str(event.get("label") or "")
            if pending and label:
                progress[label] = pending
                pending = None
    return progress


def _read_jsonl_object_rows(path: Path, *, label: str) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{label} source row must contain valid JSON object: "
                f"{path}:{line_number}: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(f"{label} source row must contain a JSON object: {path}:{line_number}")
        rows.append((line_number, row))
    return rows


def _observe_sweep_specs(
    ordered_steps: list[dict[str, Any]],
    *,
    observe_progress: dict[str, dict[str, Any]],
    total_waypoints: int,
    duration_ms: int,
) -> list[FrameSpec]:
    observe_steps = [
        step
        for step in ordered_steps
        if _base_action(step) == "observe" and _is_before_cleanup_actions(step, ordered_steps)
    ]
    if not observe_steps:
        return []
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if observe_progress and total_waypoints > 0:
        for threshold in [1, max(1, math.ceil(total_waypoints / 2)), total_waypoints]:
            for step in observe_steps:
                progress = observe_progress.get(str(step["label"]))
                if progress and int(progress.get("observed") or 0) >= threshold:
                    selected.append((step, progress))
                    break
    if not selected:
        indexes = sorted({0, len(observe_steps) // 2, len(observe_steps) - 1})
        selected = [(observe_steps[index], {}) for index in indexes]
    specs: list[FrameSpec] = []
    seen: set[str] = set()
    for step, progress in selected:
        label = str(step["label"])
        if label in seen:
            continue
        seen.add(label)
        observed = progress.get("observed")
        total = progress.get("total") or total_waypoints
        subtitle = (
            f"Observe sweep: {observed}/{total} public exploration waypoints"
            if observed and total
            else "Observe sweep: building public runtime evidence"
        )
        specs.append(
            FrameSpec(
                label, "Observe", "Agent observes the scene", subtitle, "observe", duration_ms
            )
        )
    return specs


def _is_before_cleanup_actions(step: dict[str, Any], ordered_steps: list[dict[str, Any]]) -> bool:
    first_action_index = min(
        (
            _label_index(str(candidate["label"]))
            for candidate in ordered_steps
            if _base_action(candidate) not in {"before", "observe", "after"}
        ),
        default=10**9,
    )
    return _label_index(str(step["label"])) < first_action_index


def _object_action_chains(ordered_steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    chains: list[list[dict[str, Any]]] = []
    current_key = ""
    current: list[dict[str, Any]] = []
    for step in ordered_steps:
        if _base_action(step) in {"before", "observe", "after"}:
            continue
        key = _object_key(step)
        if current and key and key != current_key:
            chains.append(current)
            current = []
        current.append(step)
        current_key = key or current_key
    if current:
        chains.append(current)
    return chains


def _trim_chain(chain: list[dict[str, Any]], max_chain_frames: int) -> list[dict[str, Any]]:
    if max_chain_frames <= 0 or len(chain) <= max_chain_frames:
        return chain
    required_actions = {
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "open_receptacle",
        "place",
        "place_inside",
        "close_receptacle",
    }
    selected = [step for step in chain if _base_action(step) in required_actions]
    if len(selected) <= max_chain_frames:
        return selected
    if max_chain_frames == 1:
        return [selected[-1]]
    indexes = sorted(
        {
            round(index * (len(selected) - 1) / (max_chain_frames - 1))
            for index in range(max_chain_frames)
        }
    )
    return [selected[index] for index in indexes]


def _action_frame_spec(
    *, step: dict[str, Any], chain_index: int, action_index: int, chain_total: int, duration_ms: int
) -> FrameSpec:
    action = _base_action(step)
    focus = step.get("focus", {})
    obj = _pretty_category(focus.get("object_category")) or _observed_token(str(step["label"]))
    receptacle = _pretty_category(focus.get("receptacle_category"))
    chapter = obj or f"Object {chain_index}"
    if action in {"navigate_to_object", "pick"}:
        title = f"{obj}: {dict(TOOLS).get(action, action)}"
        source = receptacle or "source surface"
        subtitle = f"Cleanup chain {chain_index}, step {action_index}/{chain_total}: from {source}"
    elif action in {"navigate_to_receptacle", "open_receptacle", "close_receptacle"}:
        title = f"{obj}: {dict(TOOLS).get(action, action)}"
        target = receptacle or "target receptacle"
        subtitle = (
            f"Cleanup chain {chain_index}, step {action_index}/{chain_total}: target {target}"
        )
    else:
        target = receptacle or "target receptacle"
        title = f"{obj}: place at {target}"
        subtitle = f"Cleanup chain {chain_index}, step {action_index}/{chain_total}: {action}"
    return FrameSpec(str(step["label"]), chapter, title, subtitle, action, duration_ms)


def _dedupe_specs(specs: list[FrameSpec]) -> list[FrameSpec]:
    output: list[FrameSpec] = []
    seen: set[str] = set()
    for spec in specs:
        key = f"{spec.label}:{spec.active_tool}:{spec.chapter}"
        if key not in seen:
            seen.add(key)
            output.append(spec)
    return output


def _first_step_with_action(steps: list[dict[str, Any]], action: str) -> dict[str, Any] | None:
    return next((step for step in steps if _base_action(step) == action), None)


def _base_action(step: dict[str, Any]) -> str:
    action = str(step.get("semantic_phase") or step.get("action") or "").split()[0]
    return ACTION_ALIASES.get(action, action)


def _object_key(step: dict[str, Any]) -> str:
    focus = step.get("focus", {})
    return str(
        focus.get("object_id")
        or _observed_token(str(step.get("label") or ""))
        or focus.get("object_category")
        or ""
    )


def _observed_token(label: str) -> str:
    match = re.search(r"(observed_\d+)", label)
    return match.group(1) if match else ""


def _label_index(label: str) -> int:
    match = re.match(r"(\d+)", label)
    return int(match.group(1)) if match else 10**8


def _driver_name(run_result: dict[str, Any]) -> str:
    policy = str(run_result.get("policy") or "")
    return (
        "Codex agent"
        if "codex" in policy.lower() or run_result.get("agent_driven")
        else policy or "agent"
    )


def _context_subtitle(run_result: dict[str, Any]) -> str:
    context = run_context(run_result)
    parts = ["bounded MCP tools", str(context.get("profile") or "cleanup")]
    if context.get("seed") is not None:
        parts.append(f"seed {context['seed']}")
    return " | ".join(parts)


def _final_subtitle(run_result: dict[str, Any]) -> str:
    reason = str(run_result.get("terminate_reason") or "").strip()
    status = run_result.get("completion_status") or run_result.get("cleanup_status") or "complete"
    return reason or f"Cleanup status: {status}"


def _pretty_category(value: Any) -> str:
    if not value:
        return ""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value).replace("_", " "))
    return " ".join(part.capitalize() for part in text.split())
