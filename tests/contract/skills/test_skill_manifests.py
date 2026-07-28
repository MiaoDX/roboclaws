from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.mcp.profiles import contract_profile, contract_profile_names

ROOT = Path(__file__).resolve().parents[3]
SKILL_SCHEMA = "roboclaws_skill_manifest_v1"


def _tracked_skill_dirs() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "skills/*/SKILL.md"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    skill_paths = (ROOT / line for line in result.stdout.splitlines() if line.strip())
    return sorted(path.parent for path in skill_paths if path.exists())


def _load_manifest(skill_dir: Path) -> dict[str, Any]:
    manifest_path = skill_dir / "skill.json"
    assert manifest_path.exists(), f"missing manifest for {skill_dir.relative_to(ROOT)}"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_every_tracked_skill_has_a_manifest_with_core_fields() -> None:
    skill_dirs = _tracked_skill_dirs()
    assert skill_dirs

    for skill_dir in skill_dirs:
        manifest = _load_manifest(skill_dir)
        assert manifest["schema"] == SKILL_SCHEMA
        assert manifest["name"] == skill_dir.name
        assert manifest["abstraction_level"] == "agent_skill"
        assert manifest["status"] in {"active", "legacy", "experimental"}
        assert manifest["summary"]
        assert isinstance(manifest["evidence_outputs"], list)
        assert manifest["evidence_outputs"]
        assert "mcp" in manifest
        assert "lifecycle" in manifest


def test_manifest_mcp_tools_match_declared_profiles() -> None:
    profile_names = set(contract_profile_names())

    for skill_dir in _tracked_skill_dirs():
        manifest = _load_manifest(skill_dir)
        mcp = manifest["mcp"]
        profiles = mcp.get("profiles", [])
        assert isinstance(profiles, list)
        public_names: set[str] = set()
        privileged_names: set[str] = set()
        for profile_id in profiles:
            assert profile_id in profile_names
            profile = contract_profile(profile_id)
            public_names.update(profile.public_tool_names())
            privileged_names.update(profile.privileged_tool_names())
        assert set(mcp.get("required_tools", [])) <= public_names
        assert set(mcp.get("optional_tools", [])) <= public_names
        assert set(mcp.get("privileged_tools", [])) <= privileged_names


def test_manifest_scripts_exist_and_respect_declared_owner() -> None:
    for skill_dir in _tracked_skill_dirs():
        manifest = _load_manifest(skill_dir)
        for script in manifest.get("scripts", []):
            script_path = (skill_dir / script["path"]).resolve()
            assert script_path.exists()
            owner = script.get("owner", "skill")
            if owner == "skill":
                assert skill_dir.resolve() in script_path.parents
            elif owner == "repo":
                assert ROOT.resolve() in script_path.parents
            else:
                raise AssertionError(f"unknown script owner {owner!r} in {skill_dir}")


def test_active_skills_use_public_surface_run_commands() -> None:
    for skill_dir in _tracked_skill_dirs():
        manifest = _load_manifest(skill_dir)
        if manifest["status"] != "active":
            continue

        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "just task::run" not in skill_text
