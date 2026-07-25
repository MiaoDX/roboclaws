from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dev" / "build_public_candidate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_public_candidate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_build_candidate_uses_source_commit_and_public_membership(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q", "--initial-branch=main")
    _git(source, "config", "user.name", "Test")
    _git(source, "config", "user.email", "test@example.com")
    (source / "README.md").write_text("public\n", encoding="utf-8")
    (source / "docs" / "plans").mkdir(parents=True)
    (source / "docs" / "plans" / "private.md").write_text("private\n", encoding="utf-8")
    (source / ".gitmodules").write_text("private source config\n", encoding="utf-8")
    _git(source, "add", "README.md", "docs/plans/private.md", ".gitmodules")
    _git(source, "commit", "-q", "-m", "source")
    source_commit = _git(source, "rev-parse", "HEAD")
    _git(
        source,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{source_commit},vendors/molmospaces",
    )
    _git(source, "commit", "-q", "-m", "public submodule")

    output = tmp_path / "candidate"
    result = module.build_candidate(source, output, "HEAD")

    assert (output / "README.md").read_text(encoding="utf-8") == "public\n"
    assert not (output / "docs" / "plans").exists()
    assert "github.com/allenai/molmospaces.git" in (output / ".gitmodules").read_text()
    manifest = json.loads((output / module.MANIFEST_PATH).read_text(encoding="utf-8"))
    assert manifest["source_commit"] == _git(source, "rev-parse", "HEAD")
    assert manifest["membership_sha256"] == result["membership_sha256"]
    assert _git(output, "rev-list", "--count", "HEAD") == "1"
    assert _git(output, "remote") == ""
    assert _git(output, "ls-files", "-s", "vendors/molmospaces").startswith("160000 ")
    assert _git(output, "status", "--porcelain") == ""


def test_private_optional_world_content_is_excluded() -> None:
    module = _load_module()

    excluded = (
        "vendors/agibot_sdk",
        "assets/maps/b1-map12-room-semantics.json",
        "tests/fixtures/agibot_map_context.completed.json",
        "tests/fixtures/runtime_map_prior/robot_map_12/agibot/source.json",
        "docs/status/active/private-proof.md",
        "docs/ai/generated-update.md",
        "sidecars/visual-grounding/uv.lock",
        "tests/contract/maps/test_robot_map12_consistency.py",
        "tests/contract/maps/test_b1_map12_label_tool.py",
        "tests/contract/maps/test_base_waypoint_builder.py",
        "tests/contract/skills/test_scene_gaussian_map_alignment_skill.py",
    )
    for path in excluded:
        assert not module._included(module.TreeEntry("100644", "blob", "0" * 40, path))
