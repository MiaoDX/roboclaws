from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.cleanup_validation_support import resolve_path


def assert_advisory_scoring(data: dict[str, Any], base: Path, report_text: str) -> None:
    advisory = data.get("advisory_evaluation") or {}
    assert advisory, data
    assert advisory.get("schema_version") == "advisory_cleanup_scoring_v1", advisory
    assert advisory.get("authoritative") is False, advisory
    assert advisory.get("status") == "ok", advisory
    reviews = advisory.get("object_reviews") or []
    if int(data.get("generated_mess_count") or 0) == 0:
        assert advisory.get("overall_verdict") == "no_targets", advisory
    else:
        assert reviews, advisory
    counts = advisory.get("counts") or {}
    assert int(counts.get("total_reviewed") or 0) == len(reviews), advisory
    artifacts = data.get("artifacts") or {}
    advisory_path = resolve_path(base, artifacts.get("advisory_evaluation", ""))
    loaded = read_json_object(advisory_path, label="advisory evaluation")
    assert loaded.get("authoritative") is False, loaded
    assert "Advisory Review" in report_text, report_text[:500]
