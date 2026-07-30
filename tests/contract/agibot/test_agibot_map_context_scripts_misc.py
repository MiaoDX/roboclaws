from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from tests.contract.agibot.agibot_map_context_scripts_support import (
    GENERATOR_PATH,
    NAV_ARTIFACTS_PATH,
    _completed_context,
    _load_module,
)


def test_reachability_unverified_does_not_pass_as_verified(tmp_path: Path) -> None:
    generator = _load_module(GENERATOR_PATH, "generate_metric_map_from_context_unverified")
    context = _completed_context()
    context["inspection_waypoints"][0]["reachability_status"] = "unverified"
    context["inspection_waypoints"][0].pop("verification")
    context_path = tmp_path / "agibot_map_context.completed.json"
    output_dir = tmp_path / "generated"
    context_path.write_text(json.dumps(context), encoding="utf-8")

    generator.main([str(context_path), "--output-dir", str(output_dir)])

    metric_map = json.loads((output_dir / "metric_map.json").read_text(encoding="utf-8"))
    assert metric_map["inspection_waypoints"][0]["reachability_status"] == "unverified"


def test_agibot_nav_raw_map_source_rejects_malformed_gzip_json(tmp_path: Path) -> None:
    nav_artifacts = _load_module(NAV_ARTIFACTS_PATH, "agibot_nav_artifacts_source_errors")
    raw_map_path = tmp_path / "raw_map.json.gz"
    with gzip.open(raw_map_path, "wt", encoding="utf-8") as handle:
        handle.write("{bad json\n")

    with pytest.raises(
        SystemExit,
        match=r"Agibot raw map source must contain valid JSON object: .*raw_map\.json\.gz",
    ):
        nav_artifacts.read_gzip_json(raw_map_path)


def test_agibot_nav_raw_map_source_rejects_non_object_gzip_json(tmp_path: Path) -> None:
    nav_artifacts = _load_module(NAV_ARTIFACTS_PATH, "agibot_nav_artifacts_non_object")
    raw_map_path = tmp_path / "raw_map.json.gz"
    with gzip.open(raw_map_path, "wt", encoding="utf-8") as handle:
        json.dump([], handle)

    with pytest.raises(
        SystemExit,
        match=r"Agibot raw map source must contain a JSON object: .*raw_map\.json\.gz",
    ):
        nav_artifacts.read_gzip_json(raw_map_path)


def test_agibot_nav_raw_map_source_rejects_plain_json_file(tmp_path: Path) -> None:
    nav_artifacts = _load_module(NAV_ARTIFACTS_PATH, "agibot_nav_artifacts_plain_json")
    raw_map_path = tmp_path / "raw_map.json.gz"
    raw_map_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match=r"Agibot raw map source cannot be read as gzip JSON: .*raw_map\.json\.gz",
    ):
        nav_artifacts.read_gzip_json(raw_map_path)


def test_agibot_nav_json_artifact_source_rejects_invalid_payloads(tmp_path: Path) -> None:
    nav_artifacts = _load_module(NAV_ARTIFACTS_PATH, "agibot_nav_artifacts_json_source")
    malformed = tmp_path / "candidate.malformed.json"
    non_object = tmp_path / "candidate.array.json"
    malformed.write_text("{bad json\n", encoding="utf-8")
    non_object.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match=(
            r"Agibot JSON artifact source must contain valid JSON object: "
            r".*candidate\.malformed\.json"
        ),
    ):
        nav_artifacts.read_json(malformed)
    with pytest.raises(
        SystemExit,
        match=r"Agibot JSON artifact source must contain a JSON object: .*candidate\.array\.json",
    ):
        nav_artifacts.read_json(non_object)
