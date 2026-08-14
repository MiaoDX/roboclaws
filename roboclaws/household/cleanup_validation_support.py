from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.household import agent_view as agent_view_module
from roboclaws.household.household_runtime_contract import forbidden_agent_view_keys


def agent_view_runtime_metric_map(agent_view: dict[str, Any]) -> dict[str, Any]:
    if not agent_view:
        return {}
    return agent_view_module.runtime_metric_map(agent_view)


def agent_view_raw_fpv_observations(agent_view: dict[str, Any]) -> list[dict[str, Any]]:
    if not agent_view:
        return []
    return agent_view_module.raw_fpv_observations(agent_view)


def assert_no_forbidden_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        forbidden = forbidden_agent_view_keys().intersection(payload)
        assert not forbidden, (sorted(forbidden), payload)
        for value in payload.values():
            assert_no_forbidden_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            assert_no_forbidden_keys(value)


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    repo_path = Path(__file__).resolve().parents[2] / path
    if repo_path.exists():
        return repo_path
    return base / path
