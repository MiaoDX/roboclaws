from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from roboclaws.household.household_runtime_contract import (
    _assert_no_forbidden_agent_view_keys,
    forbidden_agent_view_keys,
)
from roboclaws.household.realworld_run_artifacts import _merge_run_metadata
from roboclaws.launch.environment_setup_metadata import (
    ENVIRONMENT_SETUP_METADATA_ENV,
    environment_setup_run_metadata_from_env,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts" / "molmo_cleanup" / "check_molmo_realworld_cleanup_result.py"


def _load_checker_module():
    spec = importlib.util.spec_from_file_location(
        "check_molmo_realworld_cleanup_result",
        CHECKER_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_environment_setup_terms_are_forbidden_in_agent_view() -> None:
    expected = {
        "environment_setup",
        "relocation_policy",
        "relocation_count",
        "relocated_object_ids",
        "relocated_objects",
        "before_relocation_positions",
        "after_relocation_positions",
    }

    assert expected.issubset(forbidden_agent_view_keys())
    with pytest.raises(AssertionError, match="environment_setup"):
        _assert_no_forbidden_agent_view_keys(
            {
                "schema": "agent_view_v1",
                "runtime_metric_map": {
                    "environment_setup": "relocate-cleanup-related-objects",
                },
            }
        )


def test_setup_provenance_can_be_merged_into_private_report_metadata() -> None:
    run_result = {
        "agent_view": {"schema": "agent_view_v1"},
        "private_evaluation": {
            "generated_mess_count": 3,
            "generated_mess_set": ["mug_01"],
        },
    }

    merged = _merge_run_metadata(
        run_result,
        {
            "environment_setup": {
                "mode": "relocate-cleanup-related-objects",
                "seed": 7,
                "relocation_count": 3,
                "relocation_policy": "cleanup-related-objects",
                "relocated_objects": [
                    {
                        "object_id": "mug_01",
                        "before": "sink_01",
                        "after": "desk_01",
                    }
                ],
                "feeds_cleanup_scoring": True,
            },
            "private_evaluation": {
                "environment_setup": {
                    "mode": "relocate-cleanup-related-objects",
                    "relocation_count": 3,
                }
            },
        },
    )

    assert "environment_setup" not in merged["agent_view"]
    assert merged["environment_setup"]["mode"] == "relocate-cleanup-related-objects"
    assert merged["environment_setup"]["relocated_objects"][0]["object_id"] == "mug_01"
    assert merged["private_evaluation"]["generated_mess_count"] == 3
    assert merged["private_evaluation"]["environment_setup"] == {
        "mode": "relocate-cleanup-related-objects",
        "relocation_count": 3,
    }


def test_setup_provenance_env_builds_private_report_metadata() -> None:
    metadata = environment_setup_run_metadata_from_env(
        {
            ENVIRONMENT_SETUP_METADATA_ENV: (
                '{"feeds_cleanup_scoring":true,'
                '"mode":"relocate-cleanup-related-objects",'
                '"relocated_objects":[],'
                '"relocation_count":3,'
                '"relocation_policy":"cleanup-related-objects",'
                '"seed":7}'
            )
        }
    )

    assert metadata == {
        "environment_setup": {
            "feeds_cleanup_scoring": True,
            "mode": "relocate-cleanup-related-objects",
            "relocated_objects": [],
            "relocation_count": 3,
            "relocation_policy": "cleanup-related-objects",
            "seed": 7,
        },
        "private_evaluation": {
            "environment_setup": {
                "feeds_cleanup_scoring": True,
                "mode": "relocate-cleanup-related-objects",
                "relocated_objects": [],
                "relocation_count": 3,
                "relocation_policy": "cleanup-related-objects",
                "seed": 7,
            },
        },
    }


def test_setup_provenance_env_missing_stays_empty() -> None:
    assert environment_setup_run_metadata_from_env({}) == {}
    assert environment_setup_run_metadata_from_env({ENVIRONMENT_SETUP_METADATA_ENV: "  "}) == {}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("{not-json\n", r"ROBOCLAWS_ENVIRONMENT_SETUP_JSON source must contain valid JSON object"),
        ("[]\n", r"ROBOCLAWS_ENVIRONMENT_SETUP_JSON source must contain a JSON object"),
    ],
)
def test_setup_provenance_env_rejects_bad_present_metadata(
    source: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        environment_setup_run_metadata_from_env({ENVIRONMENT_SETUP_METADATA_ENV: source})


def test_zero_target_advisory_scoring_accepts_empty_object_reviews(tmp_path: Path) -> None:
    checker = _load_checker_module()
    advisory = {
        "schema_version": "advisory_cleanup_scoring_v1",
        "authoritative": False,
        "status": "ok",
        "overall_verdict": "no_targets",
        "counts": {
            "total_reviewed": 0,
            "supports_exact": 0,
            "benign_disagreement": 0,
            "needs_review": 0,
            "disagrees": 0,
        },
        "object_reviews": [],
    }
    (tmp_path / "advisory_evaluation.json").write_text(
        json.dumps(advisory),
        encoding="utf-8",
    )

    checker._assert_advisory_scoring(
        {
            "generated_mess_count": 0,
            "advisory_evaluation": advisory,
            "artifacts": {"advisory_evaluation": "advisory_evaluation.json"},
        },
        tmp_path,
        "<h2>Advisory Review</h2>",
    )


def test_nonzero_target_advisory_scoring_still_requires_object_reviews(
    tmp_path: Path,
) -> None:
    checker = _load_checker_module()
    advisory = {
        "schema_version": "advisory_cleanup_scoring_v1",
        "authoritative": False,
        "status": "ok",
        "overall_verdict": "supports_deterministic_score",
        "counts": {
            "total_reviewed": 0,
            "supports_exact": 0,
            "benign_disagreement": 0,
            "needs_review": 0,
            "disagrees": 0,
        },
        "object_reviews": [],
    }
    (tmp_path / "advisory_evaluation.json").write_text(
        json.dumps(advisory),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError):
        checker._assert_advisory_scoring(
            {
                "generated_mess_count": 1,
                "advisory_evaluation": advisory,
                "artifacts": {"advisory_evaluation": "advisory_evaluation.json"},
            },
            tmp_path,
            "<h2>Advisory Review</h2>",
        )
