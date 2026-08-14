from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from scripts.molmo_cleanup import (
    molmospaces_subprocess_worker,
    molmospaces_worker_cli,
    molmospaces_worker_protocol,
)


def _served_worker_packets(stdin_text: str) -> list[dict[str, object]]:
    stdout = io.StringIO()

    def never_run_state_command(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("malformed worker requests must not reach command dispatch")

    molmospaces_worker_protocol.serve_worker(
        Path("state.json"),
        run_state_command=never_run_state_command,
        ok=lambda tool: {"ok": True, "tool": tool},
        stdin=io.StringIO(stdin_text),
        stdout=stdout,
    )
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_molmospaces_worker_protocol_rejects_malformed_stdin_request() -> None:
    packets = _served_worker_packets("{not-json}\n")

    assert packets[0] == {"event": "ready", "ok": True, "tool": "serve"}
    assert packets[1]["ok"] is False
    assert packets[1]["id"] is None
    assert packets[1]["error_type"] == "ValueError"
    assert (
        packets[1]["error"]
        == "MolmoSpaces worker request source must contain valid JSON object: stdin"
    )


def test_molmospaces_worker_protocol_rejects_non_object_stdin_request() -> None:
    packets = _served_worker_packets("[]\n")

    assert packets[0] == {"event": "ready", "ok": True, "tool": "serve"}
    assert packets[1]["ok"] is False
    assert packets[1]["id"] is None
    assert packets[1]["error_type"] == "ValueError"
    assert (
        packets[1]["error"] == "MolmoSpaces worker request source must contain a JSON object: stdin"
    )


def test_molmospaces_worker_protocol_resolves_home_relative_command_paths() -> None:
    stdout = io.StringIO()
    captured: dict[str, object] = {}

    def run_state_command(_path: Path, command: str, kwargs: dict[str, object]):
        captured.update({"command": command, "kwargs": kwargs})
        return {"ok": True}

    request = json.dumps(
        {
            "id": "request-1",
            "command": "robot_views",
            "kwargs": {"output_dir": "~/operator-console/robot_views"},
        }
    )
    molmospaces_worker_protocol.serve_worker(
        Path("state.json"),
        run_state_command=run_state_command,
        ok=lambda tool: {"ok": True, "tool": tool},
        stdin=io.StringIO(request + "\n"),
        stdout=stdout,
    )

    assert captured == {
        "command": "robot_views",
        "kwargs": {"output_dir": str(Path.home() / "operator-console" / "robot_views")},
    }


def test_molmospaces_worker_protocol_rejects_non_object_inline_waypoint_json() -> None:
    with pytest.raises(
        ValueError,
        match=r"MolmoSpaces worker inline JSON source must contain a JSON object",
    ):
        molmospaces_worker_protocol.json_object_from_text("[]")


def test_molmospaces_worker_cli_routes_relative_pose_kwargs() -> None:
    parser = molmospaces_worker_cli.build_arg_parser(
        default_render_width=540,
        default_render_height=360,
    )

    args = parser.parse_args(
        [
            "--state-path",
            "state.json",
            "navigate_to_relative_pose",
            "--forward-m",
            "0.25",
            "--lateral-m",
            "-0.125",
            "--yaw-delta-deg",
            "15",
        ]
    )
    kwargs = molmospaces_worker_protocol.cli_command_kwargs(args)

    assert kwargs == {
        "forward_m": 0.25,
        "lateral_m": -0.125,
        "yaw_delta_deg": 15.0,
    }
    assert "navigate_to_relative_pose" in molmospaces_subprocess_worker._STATE_MUTATING_COMMANDS
    assert "navigate_to_relative_pose" in molmospaces_subprocess_worker._WORKER_COMMAND_HANDLERS


def test_molmospaces_worker_dispatches_relative_pose_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_navigate_to_relative_pose(
        state,  # noqa: ANN001
        *,
        forward_m: float,
        lateral_m: float,
        yaw_delta_deg: float,
    ) -> dict[str, object]:
        captured["state"] = state
        captured["forward_m"] = forward_m
        captured["lateral_m"] = lateral_m
        captured["yaw_delta_deg"] = yaw_delta_deg
        return {"ok": True, "tool": "navigate_to_relative_pose"}

    monkeypatch.setattr(
        molmospaces_subprocess_worker,
        "navigate_to_relative_pose",
        fake_navigate_to_relative_pose,
    )

    state = {"robot_pose": {"x": 0.0, "y": 0.0, "theta": 0.0}}
    result, should_write = molmospaces_subprocess_worker._run_loaded_state_command(
        state,
        "navigate_to_relative_pose",
        {"forward_m": "0.25", "lateral_m": "-0.125", "yaw_delta_deg": "15"},
    )

    assert result == {"ok": True, "tool": "navigate_to_relative_pose"}
    assert should_write is True
    assert captured == {
        "state": state,
        "forward_m": 0.25,
        "lateral_m": -0.125,
        "yaw_delta_deg": 15.0,
    }


def test_molmospaces_worker_rejects_invalid_relative_pose_kwargs() -> None:
    with pytest.raises(ValueError, match="forward_m must be a finite number; got 'oops'"):
        molmospaces_subprocess_worker._run_loaded_state_command(
            {"robot_pose": {"x": 0.0, "y": 0.0, "theta": 0.0}},
            "navigate_to_relative_pose",
            {"forward_m": "oops"},
        )


def test_molmospaces_worker_rejects_non_finite_relative_pose_kwargs() -> None:
    with pytest.raises(ValueError, match="yaw_delta_deg must be a finite number; got 'nan'"):
        molmospaces_subprocess_worker._run_loaded_state_command(
            {"robot_pose": {"x": 0.0, "y": 0.0, "theta": 0.0}},
            "navigate_to_relative_pose",
            {"yaw_delta_deg": "nan"},
        )


def test_molmospaces_worker_defaults_omitted_relative_pose_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_navigate_to_relative_pose(
        state,  # noqa: ANN001
        *,
        forward_m: float,
        lateral_m: float,
        yaw_delta_deg: float,
    ) -> dict[str, object]:
        captured["forward_m"] = forward_m
        captured["lateral_m"] = lateral_m
        captured["yaw_delta_deg"] = yaw_delta_deg
        return {"ok": True, "tool": "navigate_to_relative_pose"}

    monkeypatch.setattr(
        molmospaces_subprocess_worker,
        "navigate_to_relative_pose",
        fake_navigate_to_relative_pose,
    )

    result, should_write = molmospaces_subprocess_worker._run_loaded_state_command(
        {"robot_pose": {"x": 0.0, "y": 0.0, "theta": 0.0}},
        "navigate_to_relative_pose",
        {},
    )

    assert result == {"ok": True, "tool": "navigate_to_relative_pose"}
    assert should_write is True
    assert captured == {"forward_m": 0.0, "lateral_m": 0.0, "yaw_delta_deg": 0.0}


def test_molmospaces_worker_rejects_invalid_render_dimensions() -> None:
    with pytest.raises(ValueError, match="render_width must be a positive integer; got 'wide'"):
        molmospaces_subprocess_worker._run_loaded_state_command(
            {},
            "snapshot",
            {"output_path": "/tmp/snapshot.png", "render_width": "wide"},
        )


def test_molmospaces_worker_rejects_non_positive_render_dimensions() -> None:
    with pytest.raises(ValueError, match="render_height must be a positive integer; got 0"):
        molmospaces_subprocess_worker._run_loaded_state_command(
            {},
            "camera_views",
            {"output_dir": "/tmp/views", "render_height": 0},
        )


def test_molmospaces_worker_cli_rejects_non_positive_render_dimensions() -> None:
    parser = molmospaces_worker_cli.build_arg_parser(
        default_render_width=540,
        default_render_height=360,
    )

    for command, required_args, flag in (
        (
            "snapshot",
            ["--output-path", "/tmp/snapshot.png", "--title", "snapshot"],
            "--render-width",
        ),
        ("robot_views", ["--output-dir", "/tmp/views", "--label", "views"], "--render-height"),
        ("camera_views", ["--output-dir", "/tmp/cameras"], "--render-width"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(
                [
                    "--state-path",
                    "state.json",
                    command,
                    *required_args,
                    flag,
                    "0",
                ]
            )
        assert exc_info.value.code == 2


def test_molmospaces_worker_cli_accepts_positive_render_dimensions() -> None:
    parser = molmospaces_worker_cli.build_arg_parser(
        default_render_width=540,
        default_render_height=360,
    )

    args = parser.parse_args(
        [
            "--state-path",
            "state.json",
            "robot_views",
            "--output-dir",
            "/tmp/views",
            "--label",
            "views",
            "--render-width",
            "64",
            "--render-height",
            "48",
        ]
    )

    assert args.render_width == 64
    assert args.render_height == 48


def test_isaac_worker_cli_exposes_relative_pose_command() -> None:
    from scripts.isaac_lab_cleanup import isaac_lab_backend_worker

    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            "state.json",
            "navigate_to_relative_pose",
            "--forward-m",
            "0.25",
            "--lateral-m",
            "-0.125",
            "--yaw-delta-deg",
            "15",
        ]
    )

    assert args.command == "navigate_to_relative_pose"
    assert args.forward_m == pytest.approx(0.25)
    assert args.lateral_m == pytest.approx(-0.125)
    assert args.yaw_delta_deg == pytest.approx(15.0)
    assert "navigate_to_relative_pose" in isaac_lab_backend_worker._STATE_COMMANDS


@pytest.mark.parametrize(
    ("waypoint_json", "expected_message"),
    [
        ("{not-json}", "Isaac worker inline JSON source must contain valid JSON object"),
        ("[]", "Isaac worker inline JSON source must contain a JSON object"),
    ],
)
def test_isaac_worker_cli_rejects_bad_inline_waypoint_json(
    waypoint_json: str,
    expected_message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.isaac_lab_cleanup import isaac_lab_backend_worker

    with pytest.raises(SystemExit) as exc_info:
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                "state.json",
                "navigate_to_waypoint",
                "--waypoint-json",
                waypoint_json,
            ]
        )

    assert exc_info.value.code == 2
    assert expected_message in capsys.readouterr().err


def test_isaac_worker_cli_rejects_non_positive_render_dimensions() -> None:
    from scripts.isaac_lab_cleanup import isaac_lab_backend_worker

    for command, required_args, flag in (
        (
            "snapshot",
            ["--output-path", "/tmp/snapshot.png", "--title", "snapshot"],
            "--render-width",
        ),
        ("robot_views", ["--output-dir", "/tmp/views", "--label", "views"], "--render-height"),
        ("camera_views", ["--output-dir", "/tmp/cameras"], "--render-width"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            isaac_lab_backend_worker.parse_args(
                [
                    "--state-path",
                    "state.json",
                    command,
                    *required_args,
                    flag,
                    "0",
                ]
            )
        assert exc_info.value.code == 2


def test_isaac_worker_cli_rejects_negative_render_settle_frames() -> None:
    from scripts.isaac_lab_cleanup import isaac_lab_backend_worker

    with pytest.raises(SystemExit) as exc_info:
        isaac_lab_backend_worker.parse_args(
            [
                "--state-path",
                "state.json",
                "robot_views",
                "--output-dir",
                "/tmp/views",
                "--label",
                "views",
                "--render-settle-frames",
                "-1",
            ]
        )

    assert exc_info.value.code == 2


def test_isaac_worker_cli_accepts_positive_render_config() -> None:
    from scripts.isaac_lab_cleanup import isaac_lab_backend_worker

    args = isaac_lab_backend_worker.parse_args(
        [
            "--state-path",
            "state.json",
            "robot_views",
            "--output-dir",
            "/tmp/views",
            "--label",
            "views",
            "--render-width",
            "64",
            "--render-height",
            "48",
            "--render-settle-frames",
            "0",
        ]
    )

    assert args.render_width == 64
    assert args.render_height == 48
    assert args.render_settle_frames == 0
