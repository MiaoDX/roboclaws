from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboclaws.backends.isaaclab.isaac_scenario_builders import (
    load_generated_mess_manifest,
    scenario_from_map_bundle,
)
from roboclaws.household.generated_mess import GENERATED_MESS_MANIFEST_SCHEMA


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"generated mess manifest source must contain valid JSON object: .*manifest\.json",
        ),
        (
            "[]\n",
            r"generated mess manifest source must contain a JSON object: .*manifest\.json",
        ),
    ],
)
def test_isaac_generated_mess_manifest_rejects_bad_json_sources(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_generated_mess_manifest(manifest_path)


def test_isaac_generated_mess_manifest_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(
        FileNotFoundError,
        match=r"generated mess manifest source is missing: .*missing_manifest\.json",
    ):
        load_generated_mess_manifest(tmp_path / "missing_manifest.json")


def test_isaac_generated_mess_manifest_preserves_schema_validation(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"schema": "wrong_schema"}), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            "generated mess manifest schema mismatch: "
            f"wrong_schema != {GENERATED_MESS_MANIFEST_SCHEMA}"
        ),
    ):
        load_generated_mess_manifest(manifest_path)


def test_isaac_generated_mess_manifest_loads_object_payload(tmp_path: Path) -> None:
    manifest = {"schema": GENERATED_MESS_MANIFEST_SCHEMA, "targets": []}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert load_generated_mess_manifest(manifest_path) == manifest


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "{not-json\n",
            r"Isaac map bundle semantics source must contain valid JSON object: .*semantics\.json",
        ),
        (
            "[]\n",
            r"Isaac map bundle semantics source must contain a JSON object: .*semantics\.json",
        ),
    ],
)
def test_isaac_map_bundle_scenario_rejects_bad_semantics_sources(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    (tmp_path / "semantics.json").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        scenario_from_map_bundle(tmp_path, seed=7, generated_mess_count=1)


def test_isaac_map_bundle_scenario_rejects_missing_semantics_source(tmp_path: Path) -> None:
    with pytest.raises(
        FileNotFoundError,
        match=r"Isaac map bundle semantics source is missing: .*semantics\.json",
    ):
        scenario_from_map_bundle(tmp_path, seed=7, generated_mess_count=1)


def test_isaac_map_bundle_scenario_preserves_empty_fixture_fallback(tmp_path: Path) -> None:
    (tmp_path / "semantics.json").write_text(json.dumps({"static_landmarks": []}), encoding="utf-8")

    scenario = scenario_from_map_bundle(tmp_path, seed=5, generated_mess_count=1)

    assert scenario.scenario_id == "molmo-cleanup-default-5"


def test_isaac_map_bundle_scenario_loads_map_aligned_semantics(tmp_path: Path) -> None:
    (tmp_path / "semantics.json").write_text(
        json.dumps(
            {
                "static_landmarks": [
                    {"fixture_id": "sink_01", "name": "kitchen sink", "category": "sink"},
                    {"fixture_id": "sofa_01", "name": "sofa", "category": "sofa"},
                ]
            }
        ),
        encoding="utf-8",
    )

    scenario = scenario_from_map_bundle(tmp_path, seed=11, generated_mess_count=2)

    assert scenario.scenario_id == f"isaac-map-aligned-{tmp_path.name}-11"
    assert [obj.object_id for obj in scenario.objects] == ["mug_01", "plate_01"]
    assert scenario.object_locations() == {"mug_01": "sofa_01", "plate_01": "sofa_01"}
    assert [target.to_private_dict() for target in scenario.private_manifest.targets] == [
        {"object_id": "mug_01", "valid_receptacle_ids": ["sink_01"]},
        {"object_id": "plate_01", "valid_receptacle_ids": ["sink_01"]},
    ]
