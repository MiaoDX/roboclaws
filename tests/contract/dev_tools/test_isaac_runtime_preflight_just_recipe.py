from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
JUST_DIR = REPO_ROOT / "just"
HARNESS_JUST = JUST_DIR / "harness.just"


def just_bin() -> str:
    path = shutil.which("just")
    if path:
        return path
    local_path = Path.home() / ".local/bin" / "just"
    if local_path.exists():
        return str(local_path)
    pytest.skip("just binary is not available")


def trace_agent_harness(*args: str) -> list[str]:
    binary = just_bin()
    env = os.environ.copy()
    env["ROBOCLAWS_JUST_TRACE"] = "1"
    env["PATH"] = f"{Path(binary).parent}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        [binary, "agent::harness", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().split("\t")


def test_agent_harness_allows_isaac_runtime_preflight_target() -> None:
    harness_text = HARNESS_JUST.read_text(encoding="utf-8")

    assert re.search(r"^isaac-runtime-preflight \*overrides:", harness_text, re.MULTILINE)
    assert "check_isaac_lab_runtime.py" in harness_text
    recipe_match = re.search(
        r"^isaac-runtime-preflight \*overrides:\n"
        r"(?P<body>.*?)(?=^# Strict local Isaac Lab runtime smoke\.)",
        harness_text,
        re.MULTILINE | re.DOTALL,
    )
    assert recipe_match is not None
    assert 'accept_nvidia_eula="false"' in recipe_match.group("body")

    route = trace_agent_harness(
        "isaac-runtime-preflight",
        "output_dir=/tmp/roboclaws-isaac-preflight",
        "strict=true",
    )
    assert route == [
        "just",
        "harness::isaac-runtime-preflight",
        "output_dir=/tmp/roboclaws-isaac-preflight",
        "strict=true",
    ]


def test_agent_harness_allows_isaac_runtime_smoke_target() -> None:
    harness_text = HARNESS_JUST.read_text(encoding="utf-8")

    assert re.search(r"^isaac-runtime-smoke \*overrides:", harness_text, re.MULTILINE)
    assert "-m roboclaws.backends.isaaclab.worker" in harness_text
    assert "-m roboclaws.backends.isaaclab.smoke_checker" in harness_text
    assert "scene_usd_path" in harness_text
    assert "generated_scene_kind" in harness_text
    assert "--generated-scene-kind" in harness_text
    assert "--require-real-rendering" in harness_text
    assert "--require-usd-stage-loaded" in harness_text
    assert "--require-local-scene-usd" in harness_text
    assert "--require-usd-scene-index" in harness_text
    assert "--require-selected-usd-bindings" in harness_text
    assert "--require-robot-view-images" in harness_text
    assert "--require-segmentation-evidence" in harness_text
    assert "enable_segmentation" in harness_text
    assert "--enable-segmentation" in harness_text
    assert "segmentation_semantic_filter" in harness_text
    assert "--segmentation-semantic-filter" in harness_text
    assert '2>&1 | tee "$init_result"' in harness_text
    assert '2>&1 | tee "$robot_views_result"' in harness_text
    assert "robot_views_result.json" in harness_text
    assert "robot_views \\" in harness_text
    assert 'accept_nvidia_eula="false"' in harness_text
    assert 'OMNI_KIT_ACCEPT_EULA="YES"' in harness_text

    route = trace_agent_harness(
        "isaac-runtime-smoke",
        "output_dir=/tmp/roboclaws-isaac-smoke",
        "runtime_python=/tmp/isaac-python",
        "generated_scene_kind=isaac_official_blocks",
        "scene_usd_path=/tmp/molmospaces-scene.usd",
        "segmentation_semantic_filter=usd_prim_path",
        "accept_nvidia_eula=false",
    )
    assert route == [
        "just",
        "harness::isaac-runtime-smoke",
        "output_dir=/tmp/roboclaws-isaac-smoke",
        "runtime_python=/tmp/isaac-python",
        "generated_scene_kind=isaac_official_blocks",
        "scene_usd_path=/tmp/molmospaces-scene.usd",
        "segmentation_semantic_filter=usd_prim_path",
        "accept_nvidia_eula=false",
    ]


def test_agent_harness_removes_molmospaces_isaac_usd_reference_target() -> None:
    harness_text = HARNESS_JUST.read_text(encoding="utf-8")

    assert "install_molmospaces_usd_references.py" not in harness_text
    assert not re.search(r"^molmo-isaac-usd-references \*overrides:", harness_text, re.MULTILINE)
    assert not re.search(r"^isaac-usd-references \*overrides:", harness_text, re.MULTILINE)


def test_agent_harness_removes_molmospaces_isaac_cleanup_targets() -> None:
    harness_text = HARNESS_JUST.read_text(encoding="utf-8")

    assert not re.search(r"^molmo-isaac-cleanup-smoke \*overrides:", harness_text, re.MULTILINE)
    assert not re.search(
        r"^molmo-isaac-prepared-cleanup-smoke \*overrides:",
        harness_text,
        re.MULTILINE,
    )
    assert "prepare_molmospaces_flattened_semantic_usd.py" not in harness_text
    assert "just harness::molmo-isaac-cleanup-smoke" not in harness_text


def test_agent_harness_allows_b1_map12_navigation_smoke_target() -> None:
    harness_text = HARNESS_JUST.read_text(encoding="utf-8")

    assert re.search(r"^b1-map12-navigation-smoke \*overrides:", harness_text, re.MULTILINE)
    assert "roboclaws.backends.isaaclab.b1_readiness" in harness_text
    assert "roboclaws.backends.isaaclab.b1_navigation_smoke" in harness_text
    assert "import_rby1m_robot_usd.py --static-only" in harness_text
    assert 'require_navigation_success="true"' in harness_text
    assert 'accept_nvidia_eula="false"' in harness_text
    assert "--require-navigation-success" in harness_text
    assert 'OMNI_KIT_ACCEPT_EULA="YES"' in harness_text

    route = trace_agent_harness(
        "b1-map12-navigation-smoke",
        "output_dir=/tmp/roboclaws-b1-map12-navigation",
        "runtime_python=/tmp/isaac-python",
        "stamp=contract",
        "prepare_robot_usd=false",
        "require_navigation_success=false",
        "accept_nvidia_eula=false",
    )
    assert route == [
        "just",
        "harness::b1-map12-navigation-smoke",
        "output_dir=/tmp/roboclaws-b1-map12-navigation",
        "runtime_python=/tmp/isaac-python",
        "stamp=contract",
        "prepare_robot_usd=false",
        "require_navigation_success=false",
        "accept_nvidia_eula=false",
    ]
