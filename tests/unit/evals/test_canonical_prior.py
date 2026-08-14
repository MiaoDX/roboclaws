import json
from pathlib import Path

import pytest

from roboclaws.evals.canonical_prior import (
    CANONICAL_PRIOR_PROMOTION_MANIFEST_SCHEMA,
    IDENTITY_FIELDS,
    promote_canonical_runtime_prior,
)
from roboclaws.evals.runtime_prior_selection import RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    prior = tmp_path / "prior.json"
    prior.write_text('{"schema":"runtime_map_prior_snapshot_v1"}\n', encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "schema": RUNTIME_PRIOR_SELECTION_REPORT_SCHEMA,
                "status": "accepted",
                "selected_candidate_id": "candidate-1",
                "catalog_entry": {"id": "scene", "path": str(prior), "status": "accepted"},
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "promotion.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": CANONICAL_PRIOR_PROMOTION_MANIFEST_SCHEMA,
                "maintainer_approved": True,
                "identity": {
                    "world": "molmospaces/procthor-10k-val/0",
                    "scene_identity": "val_0",
                    "source_map_identity": "map-sha256:abc",
                    "backend": "mujoco",
                    "builder_provider": "codex-responses",
                    "builder_model": "custom",
                    "prompt_or_skill_version": "household-world-v1",
                    "evidence_lane": "camera-grounded-labels",
                    "camera_labeler": "grounding-dino",
                    "seed": 7,
                    "map_schema_version": "runtime_map_prior_snapshot_v1",
                },
            }
        ),
        encoding="utf-8",
    )
    return report, manifest


def test_canonical_prior_promotion_is_reusable_and_content_addressed(tmp_path: Path) -> None:
    report, manifest = _write_inputs(tmp_path)
    first = promote_canonical_runtime_prior(
        selection_report_path=report, promotion_manifest_path=manifest, output_root=tmp_path / "out"
    )
    second = promote_canonical_runtime_prior(
        selection_report_path=report, promotion_manifest_path=manifest, output_root=tmp_path / "out"
    )

    assert first == second
    assert first["canonical_digest"] in first["prior"]
    assert Path(first["prior"]).is_file()


@pytest.mark.parametrize("field", IDENTITY_FIELDS)
def test_canonical_prior_cache_invalidates_for_every_identity_axis(
    tmp_path: Path, field: str
) -> None:
    report, manifest = _write_inputs(tmp_path)
    first = promote_canonical_runtime_prior(
        selection_report_path=report, promotion_manifest_path=manifest, output_root=tmp_path / "out"
    )
    payload = json.loads(manifest.read_text())
    payload["identity"][field] = 8 if field == "seed" else f"changed-{field}"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    second = promote_canonical_runtime_prior(
        selection_report_path=report, promotion_manifest_path=manifest, output_root=tmp_path / "out"
    )

    assert first["canonical_digest"] != second["canonical_digest"]


def test_canonical_prior_promotion_requires_explicit_approval(tmp_path: Path) -> None:
    report, manifest = _write_inputs(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["maintainer_approved"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="maintainer_approved=true"):
        promote_canonical_runtime_prior(
            selection_report_path=report,
            promotion_manifest_path=manifest,
            output_root=tmp_path / "out",
        )


def test_canonical_prior_promotion_rejects_no_accepted_candidate(tmp_path: Path) -> None:
    report, manifest = _write_inputs(tmp_path)
    payload = json.loads(report.read_text())
    payload["status"] = "no_accepted_candidate"
    payload["selected_candidate_id"] = ""
    payload["catalog_entry"] = None
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="accepted selector report"):
        promote_canonical_runtime_prior(
            selection_report_path=report,
            promotion_manifest_path=manifest,
            output_root=tmp_path / "out",
        )


def test_canonical_prior_promotion_rejects_mutated_cached_artifact(tmp_path: Path) -> None:
    report, manifest = _write_inputs(tmp_path)
    promoted = promote_canonical_runtime_prior(
        selection_report_path=report,
        promotion_manifest_path=manifest,
        output_root=tmp_path / "out",
    )
    Path(promoted["prior"]).write_text("mutated\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cache artifact was mutated"):
        promote_canonical_runtime_prior(
            selection_report_path=report,
            promotion_manifest_path=manifest,
            output_root=tmp_path / "out",
        )
