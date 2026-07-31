"""Robot-view capture policy projection for Agent SDK profiles."""

from __future__ import annotations

import argparse
from typing import Any

from roboclaws.agents.drivers.openai_agents_profile_settings import _string_setting
from roboclaws.core.robot_view_capture import (
    ROBOT_VIEW_CAPTURE_POLICIES,
    ROBOT_VIEW_CAPTURE_POLICY_FULL,
)

ROBOT_VIEW_CAPTURE_POLICY_ENV = "ROBOCLAWS_OPENAI_AGENTS_ROBOT_VIEW_CAPTURE_POLICY"


def _robot_view_capture_policy_profile(
    args: argparse.Namespace,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    default_config = (
        defaults.get("robot_view_capture_policy")
        if isinstance(defaults.get("robot_view_capture_policy"), dict)
        else {}
    )
    policy = _string_setting(
        args,
        "robot_view_capture_policy",
        ROBOT_VIEW_CAPTURE_POLICY_ENV,
        default=str(default_config.get("policy") or ROBOT_VIEW_CAPTURE_POLICY_FULL),
        allowed=set(ROBOT_VIEW_CAPTURE_POLICIES),
    )
    enabled = policy != ROBOT_VIEW_CAPTURE_POLICY_FULL
    return {
        "schema": "agent_sdk_robot_view_capture_policy_v1",
        "policy": policy,
        "candidate_ids": ["F"] if enabled else [],
        "scope": "report-only robot-view capture",
        "hook": "cleanup MCP server --robot-view-capture-policy",
        "private_artifact_policy": (
            "SDK-private report-capture reduction; before/after snapshots, cleanup action "
            "views, raw-FPV observe artifacts, traces, and reports remain complete"
            if enabled
            else "full report robot-view capture; default public route behavior unchanged"
        ),
    }
