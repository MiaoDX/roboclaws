from __future__ import annotations

import json
from pathlib import Path

from roboclaws.household.digital_twin_review_assets import attach_map12_review_assets

REPO_ROOT = Path(__file__).resolve().parents[3]
MAP12_CONTEXT = REPO_ROOT / "tests" / "fixtures" / "agibot_robot_map_12_context.completed.json"
MAP9_CONTEXT = REPO_ROOT / "tests" / "fixtures" / "agibot_robot_map_9_context.completed.json"


def test_map12_context_attaches_digital_twin_review_sidecar(tmp_path: Path) -> None:
    run_result = {"artifacts": {}}

    review = attach_map12_review_assets(
        tmp_path, json.loads(MAP12_CONTEXT.read_text(encoding="utf-8")), run_result
    )

    assert review["schema"] == "digital_twin_review_assets_v1"
    assert review["provenance"] == "b1_map12_digital_twin_operator_review"
    assert review["source_physical_world"] == "agibot-g2/map-12"
    assert review["agent_policy_input"] is False
    assert review["physical_sensor_evidence"] is False
    assert review["navigation_proof"] is False
    assert review["runtime_observation"] is False
    assert review["artifacts"] == {
        "map_preview": "digital_twin_review/b1-map12-map.png",
        "preview_metadata": "digital_twin_review/b1-map12-preview.json",
        "topdown": "digital_twin_review/b1-map12-topdown.png",
    }
    assert run_result["artifacts"]["digital_twin_review_manifest"] == (
        "digital_twin_review/manifest.json"
    )
    assert run_result["artifacts"]["digital_twin_base_metric_map_preview"] == (
        "digital_twin_review/b1-map12-map.png"
    )
    assert run_result["artifacts"]["digital_twin_topdown"] == (
        "digital_twin_review/b1-map12-topdown.png"
    )
    assert (tmp_path / "digital_twin_review" / "manifest.json").is_file()
    assert (tmp_path / "digital_twin_review" / "b1-map12-map.png").is_file()
    assert (tmp_path / "digital_twin_review" / "b1-map12-topdown.png").is_file()


def test_non_map12_context_does_not_attach_b1_review_assets(tmp_path: Path) -> None:
    run_result = {"artifacts": {}}

    review = attach_map12_review_assets(
        tmp_path, json.loads(MAP9_CONTEXT.read_text(encoding="utf-8")), run_result
    )

    assert review == {}
    assert run_result == {"artifacts": {}}
    assert not (tmp_path / "digital_twin_review").exists()
