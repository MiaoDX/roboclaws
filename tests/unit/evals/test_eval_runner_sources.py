from __future__ import annotations

import json
from pathlib import Path

from roboclaws.evals.runner import _load_optional_json_mapping, _load_required_json_mapping


def test_eval_runner_json_artifact_missing_policy(tmp_path: Path) -> None:
    optional_payload, optional_reason = _load_optional_json_mapping(tmp_path / "missing.json")
    required_payload, required_reason = _load_required_json_mapping(tmp_path / "missing.json")

    assert optional_payload == {}
    assert optional_reason == ""
    assert required_payload == {}
    assert required_reason == "missing"


def test_eval_runner_json_artifact_loads_object_for_required_and_optional(
    tmp_path: Path,
) -> None:
    path = tmp_path / "live_status.json"
    expected = {"status": "running"}
    path.write_text(json.dumps(expected), encoding="utf-8")

    optional_payload, optional_reason = _load_optional_json_mapping(path)
    required_payload, required_reason = _load_required_json_mapping(path)

    assert optional_payload == expected
    assert optional_reason == ""
    assert required_payload == expected
    assert required_reason == ""


def test_eval_runner_json_artifact_error_reason_policy(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    malformed_payload, malformed_reason = _load_optional_json_mapping(malformed)

    non_object = tmp_path / "non_object.json"
    non_object.write_text("[]", encoding="utf-8")
    non_object_payload, non_object_reason = _load_required_json_mapping(non_object)

    assert malformed_payload == {}
    assert malformed_reason.startswith(
        "invalid_json:Expecting property name enclosed in double quotes"
    )
    assert non_object_payload == {}
    assert non_object_reason == "invalid_json_object"
