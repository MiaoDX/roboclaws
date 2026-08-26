import json
from pathlib import Path

import pytest

from roboclaws.evals.showcase import (
    build_summary,
    derive_row,
    execute_manifest,
    manifest_digest,
    validate_manifest,
)


def manifest():
    source = json.loads(
        (Path(__file__).resolve().parents[3] / "config/showcase-manifest.json").read_text()
    )
    return {**source, "rows": [source["rows"][0]]}


def test_summary_preserves_last_success_per_row_and_is_sanitized():
    m = manifest()
    passed = derive_row(m["rows"][0], {"aggregate": {"total": 1, "passed": 1, "pass_at_1": 1.0}})
    first = build_summary(
        m, [passed], commit="abc", run_url="run", attempted_at="2026-01-01T00:00:00Z"
    )
    blocked = derive_row(m["rows"][0], None)
    second = build_summary(
        m,
        [blocked],
        commit="def",
        run_url="run2",
        attempted_at="2026-01-02T00:00:00Z",
        previous=first,
    )
    assert second["rows"][0]["status"] == "blocked"
    assert second["last_success"]["household_world.smoke_regression"]["commit"] == "abc"
    assert second["manifest_digest"] == manifest_digest(m)


def test_private_fields_are_rejected_recursively():
    m = manifest()
    with pytest.raises(ValueError, match="private field"):
        build_summary(
            m,
            [{"id": "household_world.smoke_regression", "prompt": "secret", "status": "passed"}],
            commit="a",
            run_url="r",
        )


def test_manifest_rejects_duplicate_ids():
    m = manifest()
    m["rows"].append(dict(m["rows"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(m)


def test_empty_attempt_is_blocked_not_passed():
    m = manifest()
    row = derive_row(m["rows"][0], {"aggregate": {}})
    assert row["status"] == "blocked"
    assert row["reason"] == "incomplete_attempt"


def test_manifest_matches_canonical_suite_fixtures():
    root = Path(__file__).resolve().parents[3]
    validate_manifest(json.loads((root / "config/showcase-manifest.json").read_text()))


def test_execute_manifest_blocks_live_rows_without_provider_call(tmp_path):
    root = Path(__file__).resolve().parents[3]
    m = json.loads((root / "config/showcase-manifest.json").read_text())
    m["rows"] = [m["rows"][-1]]
    result = execute_manifest(m, output_dir=tmp_path, live_execution="blocked")
    assert result["results"] == {}
    assert result["attempts"] == [
        {
            "id": "household_world.open_ended_goals",
            "state": "blocked",
            "reason": "live_execution_not_requested",
        }
    ]
