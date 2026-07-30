from __future__ import annotations

import json
import shutil
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.operator_console.server import (
    ConsoleRequestHandler,
)
from roboclaws.operator_console.state import (
    derive_operator_state,
)
from tests.unit.operator_console.conftest import (  # noqa: F401  re-exported for tests
    AGIBOT_SDK_CLEANUP,
    AGIBOT_SDK_MAP_BUILD,
    AGIBOT_SDK_OPEN_TASK,
    B1_OPENAI_AGENTS_CAMERA_GROUNDED,
    B1_OPENAI_AGENTS_CLEANUP,
    B1_OPENAI_AGENTS_MAP_BUILD,
    B1_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_OPENAI_AGENTS_OPEN_TASK,
    MUJOCO_SDK_CLEANUP,
    MUJOCO_SDK_MAP_BUILD,
)

KIMI_ENV = {
    "KIMI_OPENAI_BASE_URL": "https://kimi.example.test/v1",
    "KIMI_API_KEY": "key",
}


def _free_port() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def _just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local" / "bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def _assert_registered_scene_preview_assets(registered_previews: set[str]) -> None:
    assert "molmospaces-procthor-objaverse-val-10-map.png" in registered_previews
    assert "molmospaces-procthor-objaverse-val-10-preview.json" in registered_previews
    assert "molmospaces-procthor-10k-val-11-map.png" in registered_previews
    assert "molmospaces-procthor-10k-val-11-preview.json" in registered_previews
    assert "b1-map12-map.png" not in registered_previews
    assert "b1-map12-topdown.png" not in registered_previews
    assert "b1-map12-fpv.png" not in registered_previews
    assert "b1-map12-chase.png" not in registered_previews
    assert "b1-map12-preview.json" not in registered_previews
    assert "molmospaces-val_6-map.png" not in registered_previews
    assert "molmospaces-val_8-map.png" not in registered_previews


def _assert_scene_preview_png_assets(base_url: str) -> None:
    for asset_name in (
        "molmospaces-procthor-objaverse-val-10-map.png",
        "molmospaces-procthor-objaverse-val-10-topdown.png",
        "molmospaces-procthor-objaverse-val-10-chase.png",
        "molmospaces-procthor-10k-val-11-map.png",
        "molmospaces-procthor-10k-val-11-topdown.png",
        "molmospaces-procthor-10k-val-11-chase.png",
    ):
        with urllib.request.urlopen(f"{base_url}/previews/{asset_name}") as response:
            assert response.headers["Content-Type"] == "image/png"
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"


def _assert_scene_preview_json_assets(base_url: str) -> None:
    with urllib.request.urlopen(
        f"{base_url}/previews/molmospaces-procthor-objaverse-val-10-preview.json"
    ) as response:
        preview = json.loads(response.read().decode("utf-8"))
        assert preview["views"]["chase"]["view"] == "chase_camera"


def _assert_scene_preview_rejects_invalid_paths(base_url: str) -> None:
    for path in (
        "/previews/../app.js",
        "/previews/molmospaces-val_6-map.png",
        "/previews/b1-map12-map.png",
        "/previews/b1-map12-preview.json",
        "/asset-previews/maps/../README.md",
    ):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{base_url}{path}")
        assert exc_info.value.code == 404


def _write_running_operator_control_state(tmp_path: Path, route, run_id: str) -> Path:
    run_dir = tmp_path / "output" / "operator-console" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "operator_state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "route": route.to_payload(),
                "phase": "running",
                "backend_lock": route.lock_name,
                "mcp_url": "http://127.0.0.1:19999/mcp",
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _operator_control_request(host: str, port: int, run_id: str, body: dict[str, object]):
    return urllib.request.Request(
        f"http://{host}:{port}/api/runs/{run_id}/control",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _post_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: dict[str, object],
) -> dict[str, object]:
    request = _operator_control_request(host, port, run_id, body)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def _blocked_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: dict[str, object],
) -> dict[str, object]:
    request = _operator_control_request(host, port, run_id, body)
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request)
    return json.loads(exc_info.value.read().decode("utf-8"))


def _blocked_raw_operator_control_payload(
    host: str,
    port: int,
    run_id: str,
    body: str,
) -> dict[str, object]:
    request = urllib.request.Request(
        f"http://{host}:{port}/api/runs/{run_id}/control",
        method="POST",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request)
    assert exc_info.value.code == 400
    return json.loads(exc_info.value.read().decode("utf-8"))


@contextmanager
def _console_server(root: Path, *, include_optional_worlds: bool = False):
    handler = partial(
        ConsoleRequestHandler,
        root=root,
        include_optional_worlds=include_optional_worlds,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _exercise_allowlisted_operator_control(
    root: Path, run_id: str
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:

    async def fake_call_mcp_tool(mcp_url, action, arguments):  # noqa: ANN001, ANN202
        assert mcp_url == "http://127.0.0.1:19999/mcp"
        assert action == "navigate_to_relative_pose"
        assert arguments == {"forward_m": 0.25, "lateral_m": 0.0, "yaw_delta_deg": 0.0}
        return {
            "ok": True,
            "tool": action,
            "status": "ok",
            "frame_id": "base_link",
            "applied_delta": dict(arguments),
            "requires_reobserve": True,
        }

    with _console_server(root) as (host, port):
        with patch("roboclaws.operator_console.control._call_mcp_tool", fake_call_mcp_tool):
            payload = _post_operator_control_payload(
                host,
                port,
                run_id,
                {
                    "action": "navigate_to_relative_pose",
                    "forward_m": 0.25,
                    "lateral_m": 0.0,
                    "yaw_delta_deg": 0.0,
                },
            )

        blocked_payload = _blocked_operator_control_payload(
            host,
            port,
            run_id,
            {"action": "shell", "command": "whoami"},
        )
        large_payload = _blocked_operator_control_payload(
            host,
            port,
            run_id,
            {
                "action": "navigate_to_relative_pose",
                "forward_m": 2.0,
            },
        )

    return payload, blocked_payload, large_payload


def _assert_allowlisted_operator_control_response(
    payload: dict[str, object],
    blocked_payload: dict[str, object],
    large_payload: dict[str, object],
) -> None:
    assert payload["ok"] is True
    assert payload["actor"] == "operator"
    assert payload["action"] == "navigate_to_relative_pose"
    assert payload["operator_interventions"]["count"] == 1
    assert payload["response"]["requires_reobserve"] is True
    assert blocked_payload["error"] == "unsupported control action: shell"
    assert large_payload["error"] == "relative movement request exceeds console limits"


def _assert_operator_control_artifacts(tmp_path: Path, run_dir: Path, route) -> None:
    rows = [
        json.loads(line)
        for line in (run_dir / "operator_control.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["event"] for row in rows] == ["request", "response"]
    assert {row["actor"] for row in rows} == {"operator"}
    persisted = json.loads((run_dir / "operator_state.json").read_text(encoding="utf-8"))
    assert persisted["operator_interventions"]["assisted"] is True
    assert persisted["operator_interventions"]["autonomous_behavior_proof"] is False
    interventions = json.loads(
        (run_dir / "operator_interventions.json").read_text(encoding="utf-8")
    )
    assert interventions["count"] == 1
    assert interventions["events"][0]["action"] == "navigate_to_relative_pose"
    state = derive_operator_state(tmp_path, run_dir, route)
    assert state["operator_interventions"]["count"] == 1
    assert any(item["label"] == "Operator Control" for item in state["artifact_paths"])
    assert any(item["label"] == "Operator Interventions" for item in state["artifact_paths"])
