from __future__ import annotations


def household_cleanup_args(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> tuple[str, ...]:
    return household_surface_args(
        "cleanup",
        agent_engine,
        evidence_lane,
        *overrides,
    )


def household_map_build_args(
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> tuple[str, ...]:
    return household_surface_args(
        "map-build",
        agent_engine,
        evidence_lane,
        *overrides,
    )


def household_surface_args(
    preset: str,
    agent_engine: str,
    evidence_lane: str = "",
    *overrides: str,
) -> tuple[str, ...]:
    args = [
        "surface=household-world",
        f"preset={preset}",
        f"agent_engine={_agent_engine_id(agent_engine)}",
    ]
    if evidence_lane:
        if evidence_lane == "smoke":
            args.extend(("run_preset=smoke", "evidence_lane=world-public-labels"))
        else:
            args.append(f"evidence_lane={evidence_lane}")
    args.extend(_surface_overrides(overrides))
    return tuple(args)


def _agent_engine_id(agent_engine: str) -> str:
    engine_map = {
        "codex": "openai-agents-sdk",
        "claude": "openai-agents-sdk",
        "openai-agents-live": "openai-agents-sdk",
        "direct": "direct-runner",
        "mcp-smoke": "direct-runner",
        "openclaw": "openclaw-gateway",
    }
    return engine_map.get(agent_engine, agent_engine)


def _surface_overrides(overrides: tuple[str, ...]) -> list[str]:
    normalized_overrides: list[str] = []
    for override in overrides:
        if override == "backend=molmospaces_subprocess":
            normalized_overrides.append("world=molmospaces/procthor-10k-val/0")
            normalized_overrides.append("backend=mujoco")
        elif override == "backend=agibot_gdk":
            normalized_overrides.append("world=agibot-g2/map-12")
            normalized_overrides.append("backend=agibot-gdk")
        elif override == "backend=agibot_molmospaces_sim":
            normalized_overrides.append("world=agibot-g2/map-12")
            normalized_overrides.append("backend=agibot-gdk")
            normalized_overrides.append("backend_implementation=agibot_molmospaces_sim")
        elif override.startswith("environment_setup="):
            normalized_overrides.append(
                override.replace("environment_setup=", "scenario_setup=", 1)
            )
        else:
            normalized_overrides.append(override)
    return normalized_overrides
