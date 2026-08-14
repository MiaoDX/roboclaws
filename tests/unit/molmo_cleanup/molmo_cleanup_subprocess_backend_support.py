from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.molmospaces_worker_modules import load_molmospaces_worker_modules


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "justfile").is_file():
            return parent
    raise AssertionError("could not locate repo root")


REPO_ROOT = _repo_root()


def _load_worker_module():
    pytest.importorskip("mujoco")
    return load_molmospaces_worker_modules()


def _fake_topdown_render(worker, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "topdown_scene.png"
    worker.Image.new("RGB", (16, 12)).save(image_path)
    return {
        "ok": True,
        "images": {"topdown_scene": str(image_path)},
    }
