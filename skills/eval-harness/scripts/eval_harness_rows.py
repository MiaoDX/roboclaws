from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

ROW_SCHEMA = "roboclaws_eval_harness_row_v1"
CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "rows.json"
DEFAULT_WORLD = "molmospaces/val_0"
DEFAULT_BACKEND = "mujoco"
DEFAULT_SEED = "7"
DEFAULT_PROVIDER_PROFILE = "codex-router-responses"
DEFAULT_AGENT_SDK_PROVIDER_PROFILE = "minimax-responses"


def candidate_rows(
    *, output_dir: Path, explicit_axes: dict[str, list[str]]
) -> list[dict[str, Any]]:
    row_dir = output_dir / "rows"
    context = _render_context(output_dir=output_dir, explicit_axes=explicit_axes)
    return [_row(raw, row_dir=row_dir, context=context) for raw in _catalog_rows()]


def _catalog_rows() -> list[dict[str, Any]]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{CATALOG_PATH} must contain a rows list")
    return rows


def _render_context(*, output_dir: Path, explicit_axes: dict[str, list[str]]) -> dict[str, str]:
    provider_profiles = explicit_axes.get("provider_profile") or [DEFAULT_PROVIDER_PROFILE]
    agent_sdk_provider = next(
        (profile for profile in provider_profiles if profile != DEFAULT_PROVIDER_PROFILE),
        DEFAULT_AGENT_SDK_PROVIDER_PROFILE,
    )
    return {
        "row_dir": str(output_dir / "rows"),
        "eval_output_root": str(output_dir / "evals"),
        "default_world": DEFAULT_WORLD,
        "default_backend": DEFAULT_BACKEND,
        "default_seed": DEFAULT_SEED,
        "default_provider": DEFAULT_PROVIDER_PROFILE,
        "agent_sdk_provider": agent_sdk_provider,
        "provider_cell_count": "4",
        "map_build_consumer_parallel_group": "map_build_consumer_2026_06_24",
        "default_local_concurrency_width": "1",
        "concurrency_policy": "serial_by_default_for_single_molmospaces_visual_backend_slot",
    }


def _row(raw: dict[str, Any], *, row_dir: Path, context: dict[str, str]) -> dict[str, Any]:
    row_id = str(raw["row_id"])
    command = _render_list(raw["command"], context)
    axes = _render_dict(raw.get("axes") or {}, context)
    return {
        "schema": ROW_SCHEMA,
        "row_id": row_id,
        "row_kind": str(raw["row_kind"]),
        "command": command,
        "command_display": shlex.join(command),
        "axes": axes,
        "reason_selected": str(raw["reason_selected"]),
        "selection_rule_ids": list(raw["selection_rule_ids"]),
        "source_signals": [],
        "selected": False,
        "requirement": str(raw.get("requirement") or "required"),
        "expense": str(raw["expense"]),
        "requires": list(raw.get("requires") or []),
        "profiles": list(raw.get("profiles") or []),
        "status": "skipped_irrelevant",
        "blocker_category": "",
        "skip_reason": "no matching source signal or explicit override",
        "output_artifacts": [],
        "row_dir": str(row_dir / row_id),
    }


def _render_list(values: list[Any], context: dict[str, str]) -> list[str]:
    return [_render_text(str(value), context) for value in values]


def _render_dict(values: dict[str, Any], context: dict[str, str]) -> dict[str, str]:
    return {str(key): _render_text(str(value), context) for key, value in values.items()}


def _render_text(value: str, context: dict[str, str]) -> str:
    for key, replacement in context.items():
        value = value.replace("{" + key + "}", replacement)
    return value
