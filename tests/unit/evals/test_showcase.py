import pytest

from roboclaws.evals.showcase import build_summary, derive_row, manifest_digest, validate_manifest


def manifest():
    return {
        "schema": "roboclaws_showcase_manifest_v1",
        "version": "1",
        "rows": [
            {
                "id": "a",
                "suite": "smoke",
                "version": "1",
                "seed": 1,
                "budget": "smoke",
                "timeout_s": 1,
                "execution_mode": "deterministic",
            }
        ],
    }


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
    assert second["last_success"]["a"]["commit"] == "abc"
    assert second["manifest_digest"] == manifest_digest(m)


def test_private_fields_are_rejected_recursively():
    m = manifest()
    with pytest.raises(ValueError, match="private field"):
        build_summary(
            m, [{"id": "a", "prompt": "secret", "status": "passed"}], commit="a", run_url="r"
        )


def test_manifest_rejects_duplicate_ids():
    m = manifest()
    m["rows"].append(dict(m["rows"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_manifest(m)
