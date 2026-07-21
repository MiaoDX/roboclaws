#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[3]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[3]

HARNESS_SCHEMA = "roboclaws_eval_harness_manifest_v1"
DEFAULT_OUTPUT_ROOT = Path("output/eval-harness")
ROWS_MODULE_PATH = SCRIPT_DIR / "eval_harness_rows.py"
HARNESS_PROFILES = (
    "adaptive",
    "baseline-core",
    "baseline-live-default",
    "baseline-refresh",
)
_ROWS_SPEC = importlib.util.spec_from_file_location("eval_harness_rows", ROWS_MODULE_PATH)
if _ROWS_SPEC is None or _ROWS_SPEC.loader is None:
    raise RuntimeError(f"could not load eval harness rows at {ROWS_MODULE_PATH}")
eval_harness_rows = importlib.util.module_from_spec(_ROWS_SPEC)
_ROWS_SPEC.loader.exec_module(eval_harness_rows)

SIGNAL_RULES: tuple[dict[str, Any], ...] = (
    {
        "id": "eval_harness",
        "label": "Eval harness or suite",
        "patterns": (
            r"eval[-_]harness",
            r"agent::eval",
            r"roboclaws/evals/",
            r"\bevals/",
            r"eval suite",
            r"eval_suite",
            r"regression[-_]promotion",
            r"promote-regression",
        ),
    },
    {
        "id": "agent_sdk",
        "label": "Agent SDK",
        "patterns": (
            r"openai[_-]agents",
            r"agents/drivers/openai_agents_live\.py",
            r"run_live_openai_agents_cleanup\.py",
            r"agent_engine=.?openai-agents-sdk",
            r"Agents? SDK",
        ),
    },
    {
        "id": "cleanup_skill",
        "label": "Household-world skill or prompt",
        "patterns": (
            r"skills/household-world/",
            r"household_cleanup",
            r"household[-_]world",
            r"semantic_cleanup_loop",
            r"trace_preserving_cleanup",
            r"\bcleanup\b",
        ),
    },
    {
        "id": "open_ended",
        "label": "Open-ended household intent",
        "patterns": (
            r"open[-_]ended",
            r"goal_contract",
            r"task_intent",
            r"completion_claim",
            r"agent-declared",
        ),
    },
    {
        "id": "long_horizon",
        "label": "Long-horizon household tasks",
        "patterns": (
            r"long[-_]horizon",
            r"long_horizon_tasks",
            r"roboclaws/evals/long_horizon",
            r"evals/.*/long_horizon",
        ),
    },
    {
        "id": "mcp_checker",
        "label": "MCP/server/checker contract",
        "patterns": (
            r"realworld_mcp_server",
            r"realworld_mcp_semantic_tools",
            r"realworld_contract",
            r"\bdone\b",
            r"checker",
            r"report contract",
        ),
    },
    {
        "id": "agent_view_module",
        "label": "Agent View module contract",
        "patterns": (
            r"roboclaws/household/agent_view\.py",
            r"realworld_agent_view_contract",
            r"realworld_contract_payloads",
            r"agibot_cleanup_contract",
            r"agent_view\.json",
            r"\bagent view\b",
            r"Agent View",
        ),
    },
    {
        "id": "visual_grounding",
        "label": "Visual grounding or camera labeler",
        "patterns": (
            r"visual_grounding",
            r"camera_labeler",
            r"grounding[-_]dino",
            r"camera-grounded-labels",
            r"\bDINO\b",
        ),
    },
    {
        "id": "raw_fpv",
        "label": "RAW-FPV",
        "patterns": (
            r"raw[_-]fpv",
            r"camera-raw-fpv",
            r"RAW-FPV",
        ),
    },
    {
        "id": "map_build",
        "label": "Runtime map or actionability",
        "patterns": (
            r"semantic[-_]map",
            r"map-build",
            r"runtime_metric_map",
            r"runtime[_-]prior",
            r"runtime map",
            r"actionability",
            r"target_query",
            r"generated waypoint",
            r"waypoint",
        ),
    },
    {
        "id": "scene_sampler",
        "label": "MolmoSpaces scene sampler",
        "patterns": (
            r"scene[-_]sampler",
            r"scene sampling",
            r"scene_source",
            r"molmospaces/.*/",
            r"procthor-objaverse",
            r"holodeck-objaverse",
            r"\bithor\b",
        ),
    },
    {
        "id": "planner_proof",
        "label": "Planner proof",
        "patterns": (
            r"planner[-_]proof",
            r"planner proof",
            r"surface=planner-proof",
            r"intent=planner-proof",
            r"planner_proof",
        ),
    },
    {
        "id": "launch_catalog",
        "label": "Launch catalog or product route",
        "patterns": (
            r"roboclaws/launch/",
            r"just/",
            r"operator_console",
            r"provider_profile",
            r"run::surface",
            r"agent::harness",
            r"just/agent\.just",
            r"just/harness\.just",
        ),
    },
)

EXPLICIT_AXIS_SIGNAL_OVERRIDES: tuple[tuple[str, str, str], ...] = (
    ("agent_engine", "openai-agents-sdk", "agent_sdk"),
    ("intent", "open-ended", "open_ended"),
    ("intent", "planner-proof", "planner_proof"),
    ("preset", "cleanup", "cleanup_skill"),
    ("preset", "map-build", "map_build"),
    ("evidence_lane", "camera-grounded-labels", "visual_grounding"),
    ("evidence_lane", "camera-raw-fpv", "raw_fpv"),
    ("camera_labeler", "grounding-dino", "visual_grounding"),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select adaptive Roboclaws eval-harness rows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mode", choices=("recommend", "execute"), default="recommend")
    parser.add_argument("--budget", choices=("smoke", "focused", "full"), default="focused")
    parser.add_argument("--profile", choices=HARNESS_PROFILES, default="adaptive")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--since")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--agent-engine", default="")
    parser.add_argument("--provider-profile", default="")
    parser.add_argument("--intent", default="")
    parser.add_argument("--preset", default="")
    parser.add_argument("--evidence-lane", default="")
    parser.add_argument("--camera-labeler", default="")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = build_eval_harness(
        mode=args.mode,
        budget=args.budget,
        profile=args.profile,
        plan=args.plan,
        since=args.since,
        changed_files=_split_csv_values(args.changed_file),
        agent_engine=_split_csv(args.agent_engine),
        provider_profile=_split_csv(args.provider_profile),
        intent=_split_csv(args.intent),
        preset=_split_csv(args.preset),
        evidence_lane=_split_csv(args.evidence_lane),
        camera_labeler=_split_csv(args.camera_labeler),
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def build_eval_harness(
    *,
    mode: str = "recommend",
    budget: str = "focused",
    profile: str = "adaptive",
    plan: Path | None = None,
    since: str | None = None,
    changed_files: Sequence[str] = (),
    agent_engine: Sequence[str] = (),
    provider_profile: Sequence[str] = (),
    intent: Sequence[str] = (),
    preset: Sequence[str] = (),
    evidence_lane: Sequence[str] = (),
    camera_labeler: Sequence[str] = (),
    output_dir: Path | None = None,
) -> dict[str, Any]:
    plan_text, plan_path = _read_plan(plan)
    explicit_axes = {
        "agent_engine": _dedupe(agent_engine),
        "provider_profile": _dedupe(provider_profile),
        "intent": _dedupe(intent),
        "preset": _dedupe(preset),
        "evidence_lane": _dedupe(evidence_lane),
        "camera_labeler": _dedupe(camera_labeler),
    }
    if profile not in HARNESS_PROFILES:
        raise ValueError(f"profile must be one of {', '.join(HARNESS_PROFILES)}")
    if since:
        diff_files = _changed_files_from_git(since)
    elif (
        profile == "adaptive"
        and plan is None
        and not changed_files
        and not _has_explicit_axes(explicit_axes)
    ):
        diff_files = _changed_files_from_worktree()
    else:
        diff_files = []
    all_changed_files = _dedupe([*diff_files, *changed_files])
    signals = _detect_signals(
        plan_text=plan_text,
        changed_files=all_changed_files,
        explicit_axes=explicit_axes,
    )
    if profile != "adaptive":
        signals = _merge_signals([*signals, _profile_signal(profile)])
    output_dir = output_dir or _default_output_dir()
    rows = eval_harness_rows.candidate_rows(output_dir=output_dir, explicit_axes=explicit_axes)
    _apply_selection_rules(
        rows,
        signals=signals,
        budget=budget,
        profile=profile,
        explicit_axes=explicit_axes,
    )
    selected = [row for row in rows if row["selected"]]
    return {
        "schema": HARNESS_SCHEMA,
        "generated_at": _utc_timestamp(),
        "mode": mode,
        "budget": budget,
        "profile": profile,
        "plan": str(plan_path) if plan_path else "",
        "since": since or "",
        "changed_files": all_changed_files,
        "explicit_axes": explicit_axes,
        "signals": signals,
        "summary": {
            "row_count": len(rows),
            "selected_row_count": len(selected),
            "required_row_count": sum(1 for row in selected if row["requirement"] == "required"),
            "optional_row_count": sum(1 for row in selected if row["requirement"] != "required"),
            "budget_skipped_count": sum(1 for row in rows if row["status"] == "skipped_by_budget"),
            "eval_suite_row_count": sum(1 for row in selected if row["row_kind"] == "eval_suite"),
            "live_agent_eval_row_count": sum(
                1 for row in selected if row["row_kind"] == "live_agent_eval"
            ),
        },
        "output_dir": str(output_dir),
        "rows": rows,
    }


def _read_plan(plan: Path | None) -> tuple[str, Path | None]:
    if plan is None:
        return "", None
    plan_path = Path(plan)
    if not plan_path.is_absolute():
        plan_path = REPO_ROOT / plan_path
    return plan_path.read_text(encoding="utf-8"), plan_path.relative_to(REPO_ROOT)


def _changed_files_from_git(since: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", since, "--"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        message = f"git diff --name-only {since!r} failed"
        if detail:
            message = f"{message}: {detail}"
        raise RuntimeError(message)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _changed_files_from_worktree() -> list[str]:
    paths: list[str] = []
    for args in (["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]):
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            paths.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
    return _dedupe(paths)


def _detect_signals(
    *,
    plan_text: str,
    changed_files: Sequence[str],
    explicit_axes: dict[str, list[str]],
) -> list[dict[str, Any]]:
    signals = _rule_signals(plan_text=plan_text, changed_files=changed_files)
    signals.extend(_explicit_axis_signals(explicit_axes))
    return _merge_signals(signals)


def _rule_signals(*, plan_text: str, changed_files: Sequence[str]) -> list[dict[str, Any]]:
    haystacks = [plan_text, "\n".join(changed_files)]
    signals: list[dict[str, Any]] = []
    for rule in SIGNAL_RULES:
        matches = _matched_signal_patterns(rule["patterns"], haystacks)
        matched_files = _matched_signal_files(rule["patterns"], changed_files)
        if matches or matched_files:
            signals.append(
                {
                    "id": rule["id"],
                    "label": rule["label"],
                    "matched_patterns": matches,
                    "matched_files": matched_files,
                    "source": "plan_or_diff",
                }
            )
    return signals


def _matched_signal_patterns(patterns: Sequence[str], haystacks: Sequence[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        if any(regex.search(haystack) for haystack in haystacks):
            matches.append(pattern)
    return _dedupe(matches)


def _matched_signal_files(patterns: Sequence[str], changed_files: Sequence[str]) -> list[str]:
    return _dedupe(
        [
            path
            for path in changed_files
            if any(re.search(pattern, path, re.IGNORECASE) for pattern in patterns)
        ]
    )


def _explicit_axis_signals(explicit_axes: dict[str, list[str]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for axis, value, signal_id in EXPLICIT_AXIS_SIGNAL_OVERRIDES:
        if value in explicit_axes.get(axis, []):
            signals.append(_override_signal(signal_id, f"{axis}={value}"))
    return signals


def _apply_selection_rules(
    rows: list[dict[str, Any]],
    *,
    signals: list[dict[str, Any]],
    budget: str,
    profile: str,
    explicit_axes: dict[str, list[str]],
) -> None:
    signal_ids = {signal["id"] for signal in signals}
    signal_by_id = {signal["id"]: signal for signal in signals}
    for row in rows:
        if profile != "adaptive":
            if profile not in row.get("profiles", []):
                continue
            profile_signal_id = f"{profile.replace('-', '_')}_profile"
            matching = [profile_signal_id]
            row["source_signals"] = [signal_by_id[profile_signal_id]]
        else:
            if row.get("requirement") == "optional" and not _explicitly_matches_optional(
                row,
                explicit_axes,
            ):
                continue
            matching = [rule_id for rule_id in row["selection_rule_ids"] if rule_id in signal_ids]
            if _explicitly_matches(row, explicit_axes):
                matching.append("explicit_override")
            matching = _dedupe(matching)
            if not matching:
                continue
            row["source_signals"] = [
                signal_by_id[rule_id]
                for rule_id in matching
                if rule_id != "explicit_override" and rule_id in signal_by_id
            ]
            if "explicit_override" in matching:
                row["source_signals"].append(
                    {
                        "id": "explicit_override",
                        "label": "Explicit override",
                        "matched_patterns": [],
                        "matched_files": [],
                        "source": "user_override",
                    }
                )
        row["selected"] = True
        row["skip_reason"] = ""
        if profile == "adaptive" and budget == "smoke" and row["expense"] != "deterministic":
            row["status"] = "skipped_by_budget"
            row["skip_reason"] = "budget=smoke runs deterministic confidence only"
        else:
            row["status"] = "not_run"


def _explicitly_matches(row: dict[str, Any], explicit_axes: dict[str, list[str]]) -> bool:
    axes = row["axes"]
    for key, requested_values in explicit_axes.items():
        if requested_values and axes.get(key) in requested_values:
            return True
    return False


def _explicitly_matches_optional(row: dict[str, Any], explicit_axes: dict[str, list[str]]) -> bool:
    axes = row["axes"]
    provider_profiles = explicit_axes.get("provider_profile") or []
    return bool(provider_profiles and axes.get("provider_profile") in provider_profiles)


def _has_explicit_axes(explicit_axes: dict[str, list[str]]) -> bool:
    return any(values for values in explicit_axes.values())


def _override_signal(signal_id: str, value: str) -> dict[str, Any]:
    return {
        "id": signal_id,
        "label": f"Explicit {signal_id}",
        "matched_patterns": [value],
        "matched_files": [],
        "source": "user_override",
    }


def _profile_signal(profile: str) -> dict[str, Any]:
    return {
        "id": profile.replace("-", "_") + "_profile",
        "label": f"Harness profile {profile}",
        "matched_patterns": [f"profile={profile}"],
        "matched_files": [],
        "source": "profile",
    }


def _merge_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for signal in signals:
        current = merged.setdefault(
            signal["id"],
            {
                "id": signal["id"],
                "label": signal["label"],
                "matched_patterns": [],
                "matched_files": [],
                "source": signal["source"],
            },
        )
        current["matched_patterns"] = _dedupe(
            [*current["matched_patterns"], *signal.get("matched_patterns", [])]
        )
        current["matched_files"] = _dedupe(
            [*current["matched_files"], *signal.get("matched_files", [])]
        )
        if current["source"] != signal["source"]:
            current["source"] = "plan_or_diff_and_user_override"
    return list(merged.values())


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_csv_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(_split_csv(value))
    return result


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_output_dir() -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_ROOT / stamp


if __name__ == "__main__":
    raise SystemExit(main())
