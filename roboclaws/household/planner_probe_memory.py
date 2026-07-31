from __future__ import annotations

import argparse
from typing import Any

CUROBO_LOW_MEMORY_PROFILE: dict[str, dict[str, Any]] = {
    "policy": {"batch_size": 1, "max_batch_plan_attempts": 1},
    "planner": {
        "num_trajopt_seeds": 1,
        "num_ik_seeds": 16,
        "max_attempts": 1,
        "trajopt_tsteps": 24,
        "enable_finetune_trajopt": False,
    },
}


def _curobo_memory_profile_request(args: argparse.Namespace) -> dict[str, Any]:
    explicit = _explicit_curobo_memory_overrides(args)
    profile = getattr(args, "rby1m_curobo_memory_profile", "none")
    return {
        "profile": profile,
        "profile_defaults": (
            CUROBO_LOW_MEMORY_PROFILE if profile == "low" else {"policy": {}, "planner": {}}
        ),
        "explicit_overrides": explicit,
        "requested": profile != "none" or bool(explicit["policy"]) or bool(explicit["planner"]),
    }


def _explicit_curobo_memory_overrides(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    policy: dict[str, Any] = {}
    planner: dict[str, Any] = {}
    if getattr(args, "curobo_policy_batch_size", None) is not None:
        policy["batch_size"] = args.curobo_policy_batch_size
    if getattr(args, "curobo_max_batch_plan_attempts", None) is not None:
        policy["max_batch_plan_attempts"] = args.curobo_max_batch_plan_attempts
    if getattr(args, "curobo_num_trajopt_seeds", None) is not None:
        planner["num_trajopt_seeds"] = args.curobo_num_trajopt_seeds
    if getattr(args, "curobo_num_ik_seeds", None) is not None:
        planner["num_ik_seeds"] = args.curobo_num_ik_seeds
    if getattr(args, "curobo_max_attempts", None) is not None:
        planner["max_attempts"] = args.curobo_max_attempts
    if getattr(args, "curobo_trajopt_tsteps", None) is not None:
        planner["trajopt_tsteps"] = args.curobo_trajopt_tsteps
    if getattr(args, "curobo_disable_finetune_trajopt", False):
        planner["enable_finetune_trajopt"] = False
    return {"policy": policy, "planner": planner}


def _apply_rby1m_curobo_memory_profile(config: Any, args: argparse.Namespace) -> dict[str, Any]:
    request = _curobo_memory_profile_request(args)
    before = _rby1m_curobo_memory_profile_values(config)
    overrides = _merged_curobo_memory_overrides(args)
    policy_config = config.policy_config
    for name, value in overrides["policy"].items():
        setattr(policy_config, name, value)
    for planner_config in _rby1m_curobo_planner_configs(policy_config).values():
        for name, value in overrides["planner"].items():
            setattr(planner_config, name, value)
    after = _rby1m_curobo_memory_profile_values(config)
    return {
        "schema": "rby1m_curobo_memory_profile_v1",
        "profile": args.rby1m_curobo_memory_profile,
        "requested": request["requested"],
        "applied": bool(overrides["policy"] or overrides["planner"]),
        "request": request,
        "applied_overrides": overrides,
        "before": before,
        "after": after,
    }


def _merged_curobo_memory_overrides(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    policy: dict[str, Any] = {}
    planner: dict[str, Any] = {}
    if getattr(args, "rby1m_curobo_memory_profile", "none") == "low":
        policy.update(CUROBO_LOW_MEMORY_PROFILE["policy"])
        planner.update(CUROBO_LOW_MEMORY_PROFILE["planner"])
    explicit = _explicit_curobo_memory_overrides(args)
    policy.update(explicit["policy"])
    planner.update(explicit["planner"])
    return {"policy": policy, "planner": planner}


def _rby1m_curobo_memory_profile_values(config: Any) -> dict[str, Any]:
    policy_config = config.policy_config
    return {
        "policy": {
            "batch_size": getattr(policy_config, "batch_size", None),
            "max_batch_plan_attempts": getattr(policy_config, "max_batch_plan_attempts", None),
            "enable_collision_avoidance": getattr(
                policy_config,
                "enable_collision_avoidance",
                None,
            ),
        },
        "planners": {
            name: _curobo_planner_memory_values(planner_config)
            for name, planner_config in _rby1m_curobo_planner_configs(policy_config).items()
        },
    }


def _rby1m_curobo_planner_configs(policy_config: Any) -> dict[str, Any]:
    return {
        name: planner_config
        for name, planner_config in {
            "left": getattr(policy_config, "left_curobo_planner_config", None),
            "right": getattr(policy_config, "right_curobo_planner_config", None),
        }.items()
        if planner_config is not None
    }


def _curobo_planner_memory_values(planner_config: Any) -> dict[str, Any]:
    return {
        "num_trajopt_seeds": getattr(planner_config, "num_trajopt_seeds", None),
        "num_ik_seeds": getattr(planner_config, "num_ik_seeds", None),
        "max_attempts": getattr(planner_config, "max_attempts", None),
        "trajopt_tsteps": getattr(planner_config, "trajopt_tsteps", None),
        "enable_finetune_trajopt": getattr(planner_config, "enable_finetune_trajopt", None),
    }
