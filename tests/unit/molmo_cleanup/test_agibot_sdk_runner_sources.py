from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from roboclaws.household.agibot_sdk_runner import AgibotSDKRunnerAdapter


def _adapter(tmp_path: Path, context_path: Path) -> AgibotSDKRunnerAdapter:
    runner_script = tmp_path / "runner.py"
    runner_script.write_text("# synthetic runner\n", encoding="utf-8")
    map_dir = tmp_path / "map"
    map_dir.mkdir()
    return AgibotSDKRunnerAdapter(
        context_json=context_path,
        run_dir=tmp_path / "run",
        runner_script=runner_script,
        runner_python=sys.executable,
        agibot_map_artifact_dir=map_dir,
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "{not-json\n",
            "Agibot SDK runner artifact source must contain valid JSON object",
        ),
        ("[]\n", "Agibot SDK runner artifact source must contain a JSON object"),
    ],
)
def test_agibot_sdk_runner_context_source_rejects_malformed_json(
    tmp_path: Path, content: str, message: str
) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(content, encoding="utf-8")
    adapter = _adapter(tmp_path, context_path)

    with pytest.raises(ValueError, match=message):
        adapter.context_payload


def test_agibot_sdk_runner_context_source_loads_object_payload(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text('{"inspection_waypoints": []}\n', encoding="utf-8")
    adapter = _adapter(tmp_path, context_path)

    assert adapter.context_payload == {"inspection_waypoints": []}


def test_agibot_sdk_runner_redacts_injected_dependency_roots(tmp_path: Path) -> None:
    private_root = tmp_path / "private-dependency-canary"
    sdk_root = private_root / "sdk"
    sdk_root.mkdir(parents=True)
    runner_script = sdk_root / "runner.py"
    runner_script.write_text(
        """\
import json
import os
import sys
from pathlib import Path

print(sys.executable, __file__, os.getcwd(), *sys.argv)
output_dir = Path(sys.argv[sys.argv.index("--output-dir") + 1])
output_dir.mkdir(parents=True, exist_ok=True)
payload = {"ok": True, "stage": "probe", "inputs": sys.argv, "cwd": os.getcwd()}
(output_dir / "run_result.json").write_text(json.dumps(payload), encoding="utf-8")
(output_dir / "report.html").write_text(
    " ".join([__file__, os.getcwd(), *sys.argv]),
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    context_path = private_root / "context.json"
    context_path.write_text("{}\n", encoding="utf-8")
    map_dir = private_root / "map"
    map_dir.mkdir()
    run_dir = tmp_path / "public-output"
    adapter = AgibotSDKRunnerAdapter(
        context_json=context_path,
        run_dir=run_dir,
        runner_script=runner_script,
        runner_python=sys.executable,
        agibot_map_artifact_dir=map_dir,
    )

    result = adapter._run_stage(
        "probe",
        [
            "probe",
            "--context-json",
            str(context_path),
            "--agibot-map-artifact-dir",
            str(map_dir),
            "--output-dir",
            str(run_dir / "subphases" / "probe"),
        ],
    )

    assert "<runner-script>" in result["command"]
    canary = str(private_root)
    for path in run_dir.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".json", ".txt"}:
            assert canary not in path.read_text(encoding="utf-8")
    persisted = json.loads(
        (run_dir / "subphases" / "probe" / "run_result.json").read_text(encoding="utf-8")
    )
    assert "<runner-root>" in json.dumps(persisted)


def test_agibot_sdk_runner_rejects_missing_dependencies_before_subprocess(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text("{}\n", encoding="utf-8")
    map_dir = tmp_path / "map"
    map_dir.mkdir()

    with patch("roboclaws.household.agibot_sdk_stage_execution.subprocess.run") as run:
        with pytest.raises(Exception, match="invalid runner_script"):
            AgibotSDKRunnerAdapter(
                context_json=context_path,
                run_dir=tmp_path / "run",
                runner_script=tmp_path / "missing-runner.py",
                runner_python=sys.executable,
                agibot_map_artifact_dir=map_dir,
            )

    run.assert_not_called()
