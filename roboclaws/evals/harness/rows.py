"""Eval-harness row catalog projection."""

from __future__ import annotations

import json
import re
import shlex
from copy import deepcopy
from pathlib import Path
from typing import Any

from roboclaws.agents.skill_delivery import build_skill_delivery
from roboclaws.household.realworld_contract_payloads import (
    HOUSEHOLD_EPISODE_PROFILE,
    HOUSEHOLD_MANIPULATION_PROFILE,
    HOUSEHOLD_WORLD_PROFILE,
    contract_profile,
)
from roboclaws.worlds.molmospaces.catalog import sampler_world_id
from roboclaws.worlds.molmospaces.map_bundles import molmospaces_nav2_map_bundle_path
from roboclaws.worlds.molmospaces.world_ids import parse_molmospaces_world_id

ROW_SCHEMA = "roboclaws_eval_harness_row_v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = REPO_ROOT / "skills" / "eval-harness" / "catalog" / "rows.json"
DEFAULT_WORLD = "molmospaces/procthor-10k-val/0"
DEFAULT_SCENE_SOURCE = "procthor-10k-val"
DEFAULT_SCENE_INDEX = "0"
DEFAULT_BACKEND = "mujoco"
DEFAULT_SEED = "7"
DEFAULT_PROVIDER_PROFILE = "kimi-openai-chat"
SCENE_CASE_SCHEMA = "roboclaws_eval_harness_case_v1"
SCENE_SCOPE_SELECTED = "selected"
EXECUTION_TARGET_LOCAL = "local"
EXECUTION_TARGET_CLOUDML = "cloudml"
PROVIDER_NETWORK_SCOPES = {"internal", "external"}
EXECUTION_TARGETS = {EXECUTION_TARGET_LOCAL, EXECUTION_TARGET_CLOUDML}


def candidate_rows(
    *,
    output_dir: Path,
    explicit_axes: dict[str, list[str]],
    scenes: list[str] | tuple[str, ...] = (),
    runtime_map_prior: str = "",
) -> list[dict[str, Any]]:
    row_dir = output_dir / "rows"
    catalog = _catalog()
    provider_cell_count = sum(
        str(row.get("row_id", "")).startswith("map-build-consumer-openai-agents-sdk-")
        for row in catalog["rows"]
    )
    context = _render_context(
        output_dir=output_dir,
        explicit_axes=explicit_axes,
        runtime_map_prior=runtime_map_prior,
        provider_cell_count=provider_cell_count,
    )
    defaults = catalog.get("execution_defaults") or {}
    provider_policies = catalog.get("provider_execution_policies") or {}
    base_rows = [
        _row(
            raw,
            row_dir=row_dir,
            context=context,
            defaults=defaults,
            provider_policies=provider_policies,
        )
        for raw in catalog["rows"]
    ]
    return _expand_scene_cases(base_rows, scenes=scenes, row_root=row_dir)


def _catalog() -> dict[str, Any]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{CATALOG_PATH} must contain a rows list")
    return payload


def _render_context(
    *,
    output_dir: Path,
    explicit_axes: dict[str, list[str]],
    provider_cell_count: int,
    runtime_map_prior: str = "",
) -> dict[str, str]:
    provider_profiles = explicit_axes.get("provider_profile") or [DEFAULT_PROVIDER_PROFILE]
    agent_sdk_provider = next(
        (profile for profile in provider_profiles if profile != DEFAULT_PROVIDER_PROFILE),
        DEFAULT_PROVIDER_PROFILE,
    )
    return {
        "row_dir": str(output_dir / "rows"),
        "eval_output_root": str(output_dir / "evals"),
        "default_world": DEFAULT_WORLD,
        "default_backend": DEFAULT_BACKEND,
        "default_seed": DEFAULT_SEED,
        "default_provider": DEFAULT_PROVIDER_PROFILE,
        "agent_sdk_provider": agent_sdk_provider,
        "provider_cell_count": str(provider_cell_count),
        "map_build_consumer_parallel_group": "map_build_consumer_2026_06_24",
        "default_local_concurrency_width": "1",
        "concurrency_policy": "serial_by_default_for_single_molmospaces_visual_backend_slot",
        "runtime_map_prior": runtime_map_prior,
    }


def _row(
    raw: dict[str, Any],
    *,
    row_dir: Path,
    context: dict[str, str],
    defaults: dict[str, Any],
    provider_policies: dict[str, Any],
) -> dict[str, Any]:
    row_id = str(raw["row_id"])
    command = _render_list(raw["command"], context)
    axes = _render_dict(raw.get("axes") or {}, context)
    expense = str(raw["expense"])
    execution = defaults.get(expense) or {}
    execution_requirements = list(
        raw.get("execution_requirements", execution.get("execution_requirements")) or []
    )
    provider_profile = str(axes.get("provider_profile") or "")
    provider_network_scope = ""
    allowed_execution_targets: list[str] = []
    if provider_profile:
        provider_policy = _provider_execution_policy(
            provider_profile,
            provider_policies=provider_policies,
        )
        provider_network_scope = str(provider_policy["provider_network_scope"])
        allowed_execution_targets = list(provider_policy["allowed_execution_targets"])
        execution_requirements.append(f"provider:{provider_profile}")
        execution_requirements.extend(provider_policy["execution_requirements"])
    delivery_cell = str(raw.get("skill_delivery_cell") or "")
    return {
        "schema": ROW_SCHEMA,
        "row_id": row_id,
        "row_kind": str(raw["row_kind"]),
        "command": command,
        "command_display": shlex.join(command),
        "axes": axes,
        "skill_delivery_cell": delivery_cell,
        "skill_delivery_identity": _skill_delivery_identity(delivery_cell, axes=axes),
        "base_row_id": row_id,
        "case_id": row_id,
        "case": _case_payload(row_id=row_id, row_kind=str(raw["row_kind"]), axes=axes),
        "scene_scope": str(raw.get("scene_scope") or "global"),
        "scene_group": "",
        "packing_group": "",
        "reason_selected": str(raw["reason_selected"]),
        "selection_rule_ids": list(raw["selection_rule_ids"]),
        "source_signals": [],
        "selected": False,
        "requirement": str(raw.get("requirement") or "required"),
        "expense": expense,
        "requires": list(raw.get("requires") or []),
        "execution_requirements": _dedupe(execution_requirements),
        "provider_network_scope": provider_network_scope,
        "allowed_execution_targets": allowed_execution_targets,
        "depends_on": list(raw.get("depends_on") or []),
        "timeout_s": int(raw.get("timeout_s", execution.get("timeout_s")) or 0),
        "concurrency_group": str(
            raw.get("concurrency_group", execution.get("concurrency_group")) or ""
        ),
        "profiles": list(raw.get("profiles") or []),
        "status": "skipped_irrelevant",
        "blocker_category": "",
        "skip_reason": "no matching source signal or explicit override",
        "output_artifacts": [],
        "row_dir": str(row_dir / row_id),
    }


def _skill_delivery_identity(cell: str, *, axes: dict[str, str]) -> dict[str, Any]:
    if not cell:
        return {}
    skill_path = REPO_ROOT / "skills" / "household-world" / "SKILL.md"
    delivery = build_skill_delivery(
        cell,
        full_content=skill_path.read_text(encoding="utf-8"),
        intent=str(axes.get("intent") or "cleanup"),
        evidence_lane=str(axes.get("evidence_lane") or "world-public-labels"),
    )
    tool_surface = tuple(
        name
        for profile_id in (
            HOUSEHOLD_WORLD_PROFILE,
            HOUSEHOLD_MANIPULATION_PROFILE,
            HOUSEHOLD_EPISODE_PROFILE,
        )
        for name in contract_profile(profile_id).public_tool_names()
    )
    return delivery.artifact(tool_surface=tool_surface)


def _provider_execution_policy(
    provider_profile: str,
    *,
    provider_policies: dict[str, Any],
) -> dict[str, Any]:
    policy = provider_policies.get(provider_profile)
    if not isinstance(policy, dict):
        raise ValueError(f"provider profile {provider_profile!r} must declare an execution policy")
    network_scope = str(policy.get("provider_network_scope") or "")
    if network_scope not in PROVIDER_NETWORK_SCOPES:
        raise ValueError(
            f"provider profile {provider_profile!r} has invalid provider_network_scope "
            f"{network_scope!r}"
        )
    allowed_targets = _dedupe(policy.get("allowed_execution_targets") or [])
    if not allowed_targets or any(target not in EXECUTION_TARGETS for target in allowed_targets):
        raise ValueError(
            f"provider profile {provider_profile!r} must declare allowed execution targets from "
            f"{sorted(EXECUTION_TARGETS)}"
        )
    if network_scope == "external" and allowed_targets != [EXECUTION_TARGET_LOCAL]:
        raise ValueError(
            f"external provider profile {provider_profile!r} must be restricted to local execution"
        )
    return {
        "provider_network_scope": network_scope,
        "allowed_execution_targets": allowed_targets,
        "execution_requirements": _dedupe(policy.get("execution_requirements") or []),
    }


def _render_list(values: list[Any], context: dict[str, str]) -> list[str]:
    return [_render_text(str(value), context) for value in values]


def _render_dict(values: dict[str, Any], context: dict[str, str]) -> dict[str, str]:
    return {str(key): _render_text(str(value), context) for key, value in values.items()}


def _render_text(value: str, context: dict[str, str]) -> str:
    for key, replacement in context.items():
        value = value.replace("{" + key + "}", replacement)
    return value


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def parse_scene_refs(values: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            continue
        world_ref = value if value.startswith("molmospaces/") else f"molmospaces/{value}"
        parsed = parse_molmospaces_world_id(world_ref)
        scene_id = f"{parsed.scene_source}/{parsed.scene_index}"
        if any(ref["scene_id"] == scene_id for ref in refs):
            continue
        refs.append(
            {
                "scene_id": scene_id,
                "scene_source": parsed.scene_source,
                "scene_index": parsed.scene_index,
                "world": sampler_world_id(
                    source=parsed.scene_source,
                    scene_index=parsed.scene_index,
                ),
                "map_bundle": molmospaces_nav2_map_bundle_path(
                    scene_source=parsed.scene_source,
                    scene_index=parsed.scene_index,
                ).as_posix(),
            }
        )
    return refs


def _expand_scene_cases(
    rows: list[dict[str, Any]],
    *,
    scenes: list[str] | tuple[str, ...],
    row_root: Path,
) -> list[dict[str, Any]]:
    explicit_refs = parse_scene_refs(scenes)
    refs = explicit_refs or parse_scene_refs([f"{DEFAULT_SCENE_SOURCE}/{DEFAULT_SCENE_INDEX}"])
    expanded: list[dict[str, Any]] = []
    case_ids: dict[tuple[str, str], str] = {}
    for row in rows:
        if row["scene_scope"] != SCENE_SCOPE_SELECTED:
            expanded.append(row)
            continue
        for scene in refs:
            scene_row = _scene_case_row(
                row,
                scene=scene,
                row_root=row_root,
                suffix_id=bool(explicit_refs),
            )
            expanded.append(scene_row)
            case_ids[(str(row["base_row_id"]), str(scene["scene_id"]))] = str(scene_row["row_id"])

    for row in expanded:
        scene = (row.get("case") or {}).get("scene") or {}
        scene_id = str(scene.get("scene_id") or "")
        if not scene_id:
            continue
        row["depends_on"] = [
            case_ids.get((str(dependency), scene_id), str(dependency))
            for dependency in row.get("depends_on") or []
        ]
    return expanded


def _scene_case_row(
    row: dict[str, Any],
    *,
    scene: dict[str, Any],
    row_root: Path,
    suffix_id: bool,
) -> dict[str, Any]:
    case_row = deepcopy(row)
    base_row_id = str(row["base_row_id"])
    row_id = base_row_id
    if suffix_id:
        row_id = f"{base_row_id}--scene-{_scene_slug(str(scene['scene_id']))}"
    axes = dict(case_row.get("axes") or {})
    axes.update(
        {
            "world": str(scene["world"]),
            "scene_source": str(scene["scene_source"]),
            "scene_index": str(scene["scene_index"]),
            "map_bundle": str(scene["map_bundle"]),
        }
    )
    command = _scene_command(
        list(case_row["command"]),
        base_row_id=base_row_id,
        row_id=row_id,
        scene=scene,
    )
    case_row.update(
        {
            "row_id": row_id,
            "case_id": row_id,
            "case": _case_payload(
                row_id=row_id,
                row_kind=str(case_row["row_kind"]),
                axes=axes,
                scene=scene,
            ),
            "command": command,
            "command_display": shlex.join(command),
            "axes": axes,
            "scene_group": f"scene:{scene['scene_id']}",
            "row_dir": str(row_root / row_id),
        }
    )
    return case_row


def _scene_command(
    command: list[str],
    *,
    base_row_id: str,
    row_id: str,
    scene: dict[str, Any],
) -> list[str]:
    rewritten = [value.replace(base_row_id, row_id) for value in command]
    rewritten = [
        f"world={scene['world']}" if value.startswith("world=") else value for value in rewritten
    ]
    if rewritten[:5] == [
        ".venv/bin/python",
        "-m",
        "roboclaws.cli.main",
        "run",
        "surface",
    ]:
        rewritten.extend(
            [
                f"scene_source={scene['scene_source']}",
                f"scene_index={scene['scene_index']}",
                f"map_bundle={scene['map_bundle']}",
            ]
        )
    return rewritten


def _case_payload(
    *,
    row_id: str,
    row_kind: str,
    axes: dict[str, str],
    scene: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": SCENE_CASE_SCHEMA,
        "case_id": row_id,
        "row_kind": row_kind,
        "scene": dict(scene or {}),
        "provider_profile": str(axes.get("provider_profile") or ""),
        "seed": str(axes.get("seed") or ""),
    }


def _scene_slug(scene_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", scene_id.lower()).strip("-")
