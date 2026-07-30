from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "skills" / "visual-result-showcase" / "scripts" / "render_household_cleanup_showcase.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_household_cleanup_showcase", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_showcase(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _write_view_set(robot_views: Path, label: str, action: str, *, obj: str = "") -> dict[str, str]:
    views: dict[str, str] = {}
    for view, color in {
        "fpv": "#3b82f6",
        "chase": "#14b8a6",
        "map": "#f97316",
        "verify": "#64748b",
    }.items():
        image = Image.new("RGB", (180, 120), color)
        draw = ImageDraw.Draw(image)
        draw.text((8, 8), f"{label} {view}", fill="#ffffff")
        path = robot_views / f"{label}.{view}.png"
        image.save(path)
        views[view] = f"robot_views/{path.name}"
    if action not in {"before", "observe", "after"}:
        bbox = Image.new("RGB", (180, 120), "#1d4ed8")
        draw = ImageDraw.Draw(bbox)
        draw.rectangle((24, 24, 132, 92), outline="#facc15", width=4)
        draw.text((8, 8), f"{obj} bbox", fill="#ffffff")
        bbox.save(robot_views / f"{label}.fpv.bbox.png")
    return views


def _synthetic_step(
    robot_views: Path,
    label: str,
    action: str,
    *,
    obj: str = "",
    receptacle: str = "",
) -> dict[str, object]:
    return {
        "label": label,
        "action": action,
        "semantic_phase": None if action in {"before", "observe", "after"} else action,
        "focus": {
            "object_id": f"{obj.lower()}_001" if obj else None,
            "object_category": obj,
            "receptacle_category": receptacle,
        },
        "views": _write_view_set(robot_views, label, action, obj=obj),
    }


def _write_synthetic_run(run_dir: Path) -> None:
    robot_views = run_dir / "robot_views"
    robot_views.mkdir(parents=True)
    steps = [
        _synthetic_step(robot_views, "0000_before", "before"),
        _synthetic_step(robot_views, "0001_observe", "observe"),
        _synthetic_step(robot_views, "0002_observe", "observe"),
        _synthetic_step(robot_views, "0003_observe", "observe"),
        _synthetic_step(
            robot_views,
            "0004_navigate_object_observed_001",
            "navigate_to_object",
            obj="Potato",
            receptacle="CounterTop",
        ),
        _synthetic_step(
            robot_views,
            "0005_pick_observed_001",
            "pick",
            obj="Potato",
            receptacle="CounterTop",
        ),
        _synthetic_step(
            robot_views,
            "0006_navigate_receptacle_anchor_fixture_001",
            "navigate_to_receptacle",
            obj="Potato",
            receptacle="Fridge",
        ),
        _synthetic_step(
            robot_views,
            "0007_place_inside_observed_001",
            "place_inside",
            obj="Potato",
            receptacle="Fridge",
        ),
        _synthetic_step(robot_views, "0008_after", "after"),
    ]
    run_result = {
        "agent_driven": True,
        "task_name": "household-world",
        "task_surface": "household-world",
        "task_intent": "cleanup",
        "evidence_lane": "world-public-labels",
        "cleanup_status": "success",
        "completion_status": "success",
        "seed": 7,
        "sweep_coverage_rate": 1.0,
        "terminate_reason": "Observed all generated waypoints and cleaned the potato.",
        "agent_view": {
            "metric_map": {
                "generated_exploration_candidates": [
                    {"waypoint_id": "generated_exploration_001"},
                    {"waypoint_id": "generated_exploration_002"},
                    {"waypoint_id": "generated_exploration_003"},
                ]
            }
        },
        "score": {
            "disturbance_count": 0,
            "restored_count": 1,
            "total_targets": 1,
            "semantic_acceptability": {"accepted_count": 1, "total_targets": 1},
        },
        "robot_view_steps": steps,
    }
    (run_dir / "run_result.json").write_text(json.dumps(run_result), encoding="utf-8")
    trace_events = [
        {
            "event": "response",
            "tool": "observe",
            "response": {"waypoint_id": f"generated_exploration_{index:03d}"},
        }
        for index in range(1, 4)
    ]
    lines: list[str] = []
    for index, event in enumerate(trace_events, start=1):
        lines.append(json.dumps(event))
        lines.append(
            json.dumps(
                {
                    "event": "robot_view_capture",
                    "action": "observe",
                    "label": f"000{index}_observe",
                }
            )
        )
    (run_dir / "trace.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_household_cleanup_showcase_rejects_malformed_run_result_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_result = run_dir / "run_result.json"
    run_result.write_text("{bad json\n", encoding="utf-8")

    completed = _run_showcase(
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(tmp_path / "out"),
        "--skip-gif",
    )

    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "run_result.json source must contain valid JSON object" in completed.stderr
    assert str(run_result) in completed.stderr


def test_household_cleanup_showcase_rejects_malformed_trace_source(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_synthetic_run(run_dir)
    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text('{"event": "response"}\n{bad json}\n', encoding="utf-8")

    completed = _run_showcase(
        "--run-dir",
        str(run_dir),
        "--out-dir",
        str(tmp_path / "out"),
        "--skip-gif",
    )

    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "showcase trace source row must contain valid JSON object" in completed.stderr
    assert f"{trace_path}:2" in completed.stderr


def test_household_cleanup_showcase_renderer_writes_reviewable_outputs(tmp_path: Path) -> None:
    module = _load_script()
    run_dir = tmp_path / "run"
    out_dir = tmp_path / "out"
    run_dir.mkdir()
    _write_synthetic_run(run_dir)

    manifest = module.render_showcase(
        run_dir=run_dir,
        out_dir=out_dir,
        size=(640, 360),
        duration_ms=80,
        hold_ms=100,
    )

    assert manifest["schema"] == "roboclaws_visual_showcase_v1"
    assert "profile" not in manifest
    assert manifest["context"]["task_name"] == "household-world"
    assert manifest["context"]["task_surface"] == "household-world"
    assert manifest["context"]["task_intent"] == "cleanup"
    assert manifest["eval_summary"]["semantic_accepted"] == 1
    assert manifest["eval_summary"]["exact_restored"] == 1
    assert "Scores are post-run evaluation" in manifest["public_private_boundary"]
    assert "RPV/chase/map panels are report-only evidence" in manifest["public_private_boundary"]
    assert (out_dir / "showcase.gif").exists()
    assert (out_dir / "contact_sheet.png").exists()
    assert (out_dir / "manifest.json").exists()
    assert len(list((out_dir / "frames").glob("*.png"))) == manifest["frame_count"]
    assert [frame["active_tool"] for frame in manifest["selected_frames"]] == [
        "observe",
        "observe",
        "observe",
        "observe",
        "navigate_to_object",
        "pick",
        "navigate_to_receptacle",
        "place_inside",
        "done",
    ]
