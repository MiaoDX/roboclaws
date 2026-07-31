from __future__ import annotations

import os
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab import (
    b1_navigation_proof,
    b1_navigation_smoke,
    rby1m_robot_usd,
    runtime_smoke,
)


def test_runtime_smoke_fails_closed_without_eula(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OMNI_KIT_ACCEPT_EULA", raising=False)
    called = False

    def unexpected_run(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(runtime_smoke, "_run_and_record", unexpected_run)

    request = runtime_smoke.RuntimeSmokeRequest(output_dir=tmp_path)
    assert runtime_smoke.run_runtime_smoke(request) == 2
    assert called is False


def test_runtime_smoke_owns_worker_and_checker_composition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OMNI_KIT_ACCEPT_EULA", raising=False)
    worker_commands: list[list[str]] = []
    checker_calls: list[runtime_smoke.smoke_checker.SmokeCheckRequest] = []

    def fake_run(
        command: list[str],
        *,
        output: Path,
        env: dict[str, str],
    ) -> int:
        assert env["OMNI_KIT_ACCEPT_EULA"] == "YES"
        worker_commands.append(command)
        output.write_text('{"ok": true}\n', encoding="utf-8")
        state_path = Path(command[command.index("--state-path") + 1])
        if "init" in command:
            state_path.write_text('{"backend": "isaaclab_subprocess"}\n', encoding="utf-8")
        return 0

    monkeypatch.setattr(runtime_smoke, "_run_and_record", fake_run)
    monkeypatch.setattr(
        runtime_smoke.smoke_checker,
        "check_runtime_smoke",
        lambda request: checker_calls.append(request) or 0,
    )

    result = runtime_smoke.run_runtime_smoke(
        runtime_smoke.RuntimeSmokeRequest(
            runtime_python=Path("/isaac/python"),
            output_dir=tmp_path,
            stamp="proof",
            scene_usd_path=Path("scene.usda"),
            enable_segmentation=True,
            segmentation_data_types=("semantic_segmentation",),
            accept_nvidia_eula=True,
        )
    )

    assert result == 0
    assert [command[2] for command in worker_commands] == [
        "roboclaws.backends.isaaclab.worker",
        "roboclaws.backends.isaaclab.worker",
    ]
    assert "init" in worker_commands[0]
    assert "--scene-usd-path" in worker_commands[0]
    assert "--enable-segmentation" in worker_commands[0]
    assert "robot_views" in worker_commands[1]
    assert checker_calls == [
        runtime_smoke.smoke_checker.SmokeCheckRequest(
            init_result=tmp_path / "proof" / "init_result.json",
            state_path=tmp_path / "proof" / "state.json",
            robot_views_result=tmp_path / "proof" / "robot_views_result.json",
            require_real_rendering=True,
            require_usd_stage_loaded=True,
            require_usd_scene_index=True,
            require_selected_usd_bindings=True,
            require_robot_view_images=True,
            require_nonblank_image=True,
        )
    ]


def test_b1_navigation_proof_fails_closed_without_eula(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OMNI_KIT_ACCEPT_EULA", raising=False)
    monkeypatch.setattr(
        b1_navigation_proof.b1_readiness,
        "run_b1_readiness",
        lambda request: pytest.fail(f"readiness should not run: {request}"),
    )

    request = b1_navigation_proof.B1NavigationProofRequest(output_dir=tmp_path)
    assert b1_navigation_proof.run_navigation_proof(request) == 2


def test_b1_navigation_proof_owns_full_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OMNI_KIT_ACCEPT_EULA", "NO")
    calls: list[tuple[str, object]] = []
    robot_usd = tmp_path / "missing-robot.usda"
    monkeypatch.setattr(b1_navigation_proof, "ISAAC_RBY1M_ROBOT_USD_PATH", robot_usd)
    monkeypatch.setattr(
        b1_navigation_proof.rby1m_robot_usd,
        "import_rby1m_robot_usd",
        lambda request: calls.append(("robot", request)) or {"status": "ready"},
    )
    monkeypatch.setattr(
        b1_navigation_proof.b1_readiness,
        "run_b1_readiness",
        lambda request: calls.append(("readiness", request)) or 0,
    )
    monkeypatch.setattr(
        b1_navigation_proof.b1_navigation_smoke,
        "run_navigation_smoke",
        lambda request: calls.append(("navigation", request)) or 0,
    )
    monkeypatch.setattr(
        b1_navigation_proof,
        "_run_project_stage",
        lambda command: (
            calls.append(
                (
                    "preview"
                    if "roboclaws.operator_console.scene_preview_cli" in command
                    else "report",
                    command,
                )
            )
            or 0
        ),
    )

    result = b1_navigation_proof.run_navigation_proof(
        b1_navigation_proof.B1NavigationProofRequest(
            output_dir=tmp_path,
            stamp="proof",
            accept_nvidia_eula=True,
        )
    )

    assert result == 0
    assert [name for name, _ in calls] == [
        "readiness",
        "robot",
        "navigation",
        "readiness",
        "report",
        "preview",
    ]
    readiness_before = calls[0][1]
    robot_request = calls[1][1]
    readiness_after = calls[3][1]
    assert isinstance(readiness_before, b1_navigation_proof.b1_readiness.B1ReadinessRequest)
    assert isinstance(robot_request, rby1m_robot_usd.Rby1mRobotUsdRequest)
    assert robot_request.output_usd_path == robot_usd
    assert robot_request.static_only is True
    assert isinstance(readiness_after, b1_navigation_proof.b1_readiness.B1ReadinessRequest)
    assert readiness_before.navigation_artifact is None
    assert readiness_after.navigation_artifact == tmp_path / "proof" / "navigation_smoke.json"
    assert readiness_after.require_navigation_success is True
    assert os.environ["OMNI_KIT_ACCEPT_EULA"] == "YES"


def test_b1_navigation_smoke_fails_closed_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OMNI_KIT_ACCEPT_EULA", raising=False)
    monkeypatch.setattr(
        b1_navigation_smoke,
        "load_or_build_readiness",
        lambda request: pytest.fail(f"runtime should not run: {request}"),
    )

    assert b1_navigation_smoke.main(["--output-dir", str(tmp_path)]) == 2


def test_nonstatic_robot_authoring_requires_eula(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNI_KIT_ACCEPT_EULA", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        rby1m_robot_usd.main([])

    assert exc_info.value.code == 2
