from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "harness" / "visual_grounding" / "smoke_corpus.json"
RUNNER_MODULE = "roboclaws.evals.visual_grounding_benchmark.runner"


def test_visual_grounding_runner_rejects_missing_corpus_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing-corpus.json"

    result = _run_runner(
        tmp_path,
        "--corpus",
        str(missing),
    )

    assert result.returncode == 1
    assert "visual grounding benchmark corpus source is missing" in result.stderr
    assert str(missing) in result.stderr
    assert not (tmp_path / "visual_grounding_benchmark_result.json").exists()
    assert "Traceback" not in result.stderr


def test_visual_grounding_runner_rejects_malformed_corpus_source(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.json"
    corpus.write_text("{not json", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        "--corpus",
        str(corpus),
    )

    assert result.returncode == 1
    assert (
        "visual grounding benchmark corpus source must contain valid JSON object" in result.stderr
    )
    assert str(corpus) in result.stderr
    assert not (tmp_path / "visual_grounding_benchmark_result.json").exists()
    assert "Traceback" not in result.stderr


def test_visual_grounding_runner_rejects_non_object_matrix_source(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    matrix.write_text("[]", encoding="utf-8")

    result = _run_runner(
        tmp_path,
        "--matrix",
        str(matrix),
    )

    assert result.returncode == 1
    assert "visual grounding benchmark matrix source must contain a JSON object" in result.stderr
    assert str(matrix) in result.stderr
    assert not (tmp_path / "visual_grounding_benchmark_result.json").exists()
    assert "Traceback" not in result.stderr


def test_visual_grounding_runner_rejects_wrong_shaped_matrix_rows(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema": "visual_grounding_benchmark_matrix_v1",
                "rows": {},
            }
        ),
        encoding="utf-8",
    )

    result = _run_runner(
        tmp_path,
        "--matrix",
        str(matrix),
    )

    assert result.returncode == 1
    assert "benchmark matrix rows must be a list" in result.stderr
    assert str(matrix) in result.stderr
    assert not (tmp_path / "visual_grounding_benchmark_result.json").exists()
    assert "Traceback" not in result.stderr


def test_visual_grounding_runner_rejects_non_object_matrix_row(tmp_path: Path) -> None:
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps(
            {
                "schema": "visual_grounding_benchmark_matrix_v1",
                "rows": ["grounding-dino"],
            }
        ),
        encoding="utf-8",
    )

    result = _run_runner(
        tmp_path,
        "--matrix",
        str(matrix),
    )

    assert result.returncode == 1
    assert "benchmark matrix rows must contain JSON objects" in result.stderr
    assert str(matrix) in result.stderr
    assert not (tmp_path / "visual_grounding_benchmark_result.json").exists()
    assert "Traceback" not in result.stderr


def _run_runner(output_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            RUNNER_MODULE,
            "--corpus",
            str(CORPUS),
            "--output-dir",
            str(output_dir),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
