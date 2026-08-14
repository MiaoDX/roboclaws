from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "roboclaws.maps.b1_alignment"
RAW_MAP12_BUNDLE = REPO_ROOT / "assets" / "maps" / "agibot-robot-map-12"


@pytest.mark.parametrize(
    ("filename", "source", "message"),
    (
        (
            "scene_correspondences.json",
            "{not-json\n",
            "correspondence manifest source must contain valid JSON object",
        ),
        (
            "scene_correspondences.json",
            "[]\n",
            "correspondence manifest source must contain a JSON object",
        ),
    ),
)
def test_alignment_fit_cli_rejects_bad_correspondence_manifest(
    tmp_path: Path,
    filename: str,
    source: str,
    message: str,
) -> None:
    manifest_path = tmp_path / filename
    output_dir = tmp_path / "alignment"
    manifest_path.write_text(source, encoding="utf-8")

    completed = _run_alignment_cli(manifest_path=manifest_path, output_dir=output_dir)

    assert completed.returncode == 2
    assert message in completed.stderr
    assert str(manifest_path) in completed.stderr
    assert not (output_dir / "alignment_residuals.json").exists()


def test_alignment_fit_cli_rejects_missing_correspondence_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "missing_scene_correspondences.json"
    output_dir = tmp_path / "alignment"

    completed = _run_alignment_cli(manifest_path=manifest_path, output_dir=output_dir)

    assert completed.returncode == 2
    assert "correspondence manifest source is missing" in completed.stderr
    assert str(manifest_path) in completed.stderr
    assert not (output_dir / "alignment_residuals.json").exists()


def _run_alignment_cli(
    *,
    manifest_path: Path,
    output_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            MODULE,
            "--correspondences",
            str(manifest_path),
            "--map-bundle",
            str(RAW_MAP12_BUNDLE),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
    )
