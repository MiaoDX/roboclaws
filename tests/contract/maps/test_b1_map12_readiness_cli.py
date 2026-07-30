from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "roboclaws.backends.isaaclab.b1_readiness"


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "alignment artifact source must contain valid JSON object"),
        ("[]\n", "alignment artifact source must contain a JSON object"),
    ),
)
def test_readiness_cli_rejects_bad_alignment_artifact_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    b1_root = tmp_path / "b1"
    map12_root = _write_map12_root(tmp_path)
    alignment_path = tmp_path / "alignment_residuals.json"
    output_path = tmp_path / "readiness.json"
    alignment_path.write_text(source, encoding="utf-8")

    completed = _run_readiness(
        b1_root=b1_root,
        map12_root=map12_root,
        output_path=output_path,
        alignment_artifact=alignment_path,
    )

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(alignment_path) in completed.stderr
    assert not output_path.exists()


def test_readiness_cli_rejects_missing_alignment_artifact_source(tmp_path: Path) -> None:
    b1_root = tmp_path / "b1"
    map12_root = _write_map12_root(tmp_path)
    alignment_path = tmp_path / "missing_alignment_residuals.json"
    output_path = tmp_path / "readiness.json"

    completed = _run_readiness(
        b1_root=b1_root,
        map12_root=map12_root,
        output_path=output_path,
        alignment_artifact=alignment_path,
    )

    assert completed.returncode == 2
    assert "alignment artifact source is missing" in completed.stderr
    assert str(alignment_path) in completed.stderr
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "navigation artifact source must contain valid JSON object"),
        ("[]\n", "navigation artifact source must contain a JSON object"),
    ),
)
def test_readiness_cli_rejects_bad_navigation_artifact_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    b1_root = tmp_path / "b1"
    map12_root = _write_map12_root(tmp_path)
    navigation_path = tmp_path / "navigation_smoke.json"
    output_path = tmp_path / "readiness.json"
    navigation_path.write_text(source, encoding="utf-8")

    completed = _run_readiness(
        b1_root=b1_root,
        map12_root=map12_root,
        output_path=output_path,
        navigation_artifact=navigation_path,
    )

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(navigation_path) in completed.stderr
    assert not output_path.exists()


def test_readiness_cli_rejects_missing_navigation_artifact_source(tmp_path: Path) -> None:
    b1_root = tmp_path / "b1"
    map12_root = _write_map12_root(tmp_path)
    navigation_path = tmp_path / "missing_navigation_smoke.json"
    output_path = tmp_path / "readiness.json"

    completed = _run_readiness(
        b1_root=b1_root,
        map12_root=map12_root,
        output_path=output_path,
        navigation_artifact=navigation_path,
    )

    assert completed.returncode == 2
    assert "navigation artifact source is missing" in completed.stderr
    assert str(navigation_path) in completed.stderr
    assert not output_path.exists()


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("{not-json\n", "navigation_memory.json must contain valid JSON object"),
        ("[]\n", "navigation_memory.json must contain a JSON object"),
    ),
)
def test_readiness_cli_rejects_bad_navigation_memory_source(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    b1_root = tmp_path / "b1"
    map12_root = _write_map12_root(tmp_path)
    output_path = tmp_path / "readiness.json"
    memory_path = map12_root / "navigation_memory.json"
    memory_path.write_text(source, encoding="utf-8")

    completed = _run_readiness(
        b1_root=b1_root,
        map12_root=map12_root,
        output_path=output_path,
    )

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(memory_path) in completed.stderr
    assert not output_path.exists()


def _run_readiness(
    *,
    b1_root: Path,
    map12_root: Path,
    output_path: Path,
    alignment_artifact: Path | None = None,
    navigation_artifact: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        MODULE,
        "--b1-root",
        str(b1_root),
        "--map12-root",
        str(map12_root),
        "--output",
        str(output_path),
    ]
    if alignment_artifact is not None:
        command.extend(["--alignment-artifact", str(alignment_artifact)])
    if navigation_artifact is not None:
        command.extend(["--navigation-artifact", str(navigation_artifact)])
    return subprocess.run(command, capture_output=True, text=True)


def _write_map12_root(tmp_path: Path) -> Path:
    root = tmp_path / "map12"
    agibot = root / "agibot"
    agibot.mkdir(parents=True)
    (agibot / "nav2.yaml").write_text(
        "\n".join(
            [
                "image: occupancy.pgm",
                "mode: trinary",
                "resolution: 0.05",
                "origin: [0.0, 0.0, 0.0]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.196",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (agibot / "occupancy.pgm").write_text(
        "P2\n4 4\n255\n254 254 254 254\n254 0 0 254\n254 0 0 254\n254 254 254 254\n",
        encoding="ascii",
    )
    (root / "navigation_memory.json").write_text(
        json.dumps(
            {
                "schema_version": "agibot_navigation_memory_v1",
                "items": [
                    {
                        "id": "anchor_a",
                        "label": "Anchor A",
                        "pose": {"x": 0.2, "y": 0.2, "yaw": 0.0},
                        "nav_goal": {"x": 0.2, "y": 0.2, "yaw": 0.0},
                    },
                    {
                        "id": "anchor_b",
                        "label": "Anchor B",
                        "pose": {"x": 0.3, "y": 0.3, "yaw": 0.0},
                        "nav_goal": {"x": 0.3, "y": 0.3, "yaw": 0.0},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return root
