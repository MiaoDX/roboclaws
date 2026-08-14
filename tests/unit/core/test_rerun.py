from __future__ import annotations

from roboclaws.core.rerun import format_rerun_command_for_display, render_rerun_panel


def test_format_rerun_command_splits_surface_args_for_review() -> None:
    command = (
        "just run::surface surface=household-world agent_engine=openai-agents-sdk "
        "provider_profile=kimi-openai-chat evidence_lane=world-public-labels seed=7 "
        'prompt="find something useful to drink"'
    )

    display = format_rerun_command_for_display(command)

    assert display.startswith("just run::surface \\\n")
    assert "  surface=household-world \\\n" in display
    assert "  agent_engine=openai-agents-sdk \\\n" in display
    assert "  provider_profile=kimi-openai-chat \\\n" in display
    assert "  'prompt=find something useful to drink'" in display


def test_format_rerun_command_keeps_short_commands_single_line() -> None:
    command = "just agent::verify"
    assert format_rerun_command_for_display(command) == command


def test_render_rerun_panel_uses_wrapping_command_class() -> None:
    html = render_rerun_panel(
        "just run::surface surface=household-world agent_engine=direct-runner"
    )

    assert 'class="rerun-command"' in html
    assert "just run::surface \\\n" in html
