from __future__ import annotations

from pathlib import Path

from roboclaws.cli import household_agent_server as server_module


def test_realworld_agent_server_prints_agent_setup(
    tmp_path: Path,
    capsys,
) -> None:
    server_module.print_setup(
        tmp_path,
        "http://127.0.0.1:18788/mcp",
        "codex_agent",
    )

    output = capsys.readouterr().out
    assert "Molmo real-world cleanup MCP server is ready." in output
    assert "coding_agent_docker.sh" not in output
    assert "run codex mcp add" not in output
    assert "run claude mcp add" not in output
    assert "skills/household-world/SKILL.md" in output
    assert "roboclaws__metric_map" in output
    assert "scene_objects" in output
    assert "realworld_cleanup_v1" in output
    assert "household_world" in output
    assert "Backend       : api_semantic_synthetic" in output
    assert "Visual report : disabled" in output


def test_realworld_agent_server_prints_visual_setup(tmp_path: Path, capsys) -> None:
    server_module.print_setup(
        tmp_path,
        "http://127.0.0.1:18788/mcp",
        "codex_agent",
        backend="molmospaces_subprocess",
        record_robot_views=True,
    )

    output = capsys.readouterr().out
    assert "Backend       : molmospaces_subprocess" in output
    assert "Visual report : enabled" in output


def test_realworld_agent_server_open_ended_setup_does_not_prompt_full_sweep(
    tmp_path: Path,
    capsys,
) -> None:
    server_module.print_setup(
        tmp_path,
        "http://127.0.0.1:18788/mcp",
        "codex_agent",
        task_intent="open-ended",
    )

    output = capsys.readouterr().out
    assert "Treat the operator task as the authoritative goal scope." in output
    assert "Observe only as needed for the open-ended task" in output
    assert "Act only on task-relevant observed_* objects." in output
    assert "skills/household-world/SKILL.md" not in output
    assert "Sweep waypoints" not in output
    assert "Clean plausible observed_* objects with navigate->pick" not in output


def test_realworld_agent_server_accepts_generated_mess_manifest_path(tmp_path: Path) -> None:
    manifest_path = tmp_path / "generated_mess_manifest.json"

    args = server_module.parse_args(["--generated-mess-manifest-path", str(manifest_path)])

    assert args.generated_mess_manifest_path == manifest_path
