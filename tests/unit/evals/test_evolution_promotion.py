from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from roboclaws.agents.evolution_optimizer import OptimizerOutcome
from roboclaws.evals.evolution_campaign import run_skill_campaign
from roboclaws.evals.evolution_promotion import apply_evolution_promotion
from tests.unit.evals.test_evolution_campaign import _setup, _trial


def _accepted_report(tmp_path: Path) -> tuple[Path, object, str]:
    repo, campaign, patch = _setup(tmp_path)

    def optimizer(*_args: object, **_kwargs: object) -> OptimizerOutcome:
        return OptimizerOutcome(
            "Clarify order.",
            patch,
            {
                "agent_engine": "openai-agents-sdk",
                "role": "optimizer",
                "model": "gpt-5.5",
            },
            {"tokens": 10, "cost_usd": 0.01},
            "trace-1",
        )

    def matrix(_campaign: object, workspace: Path | None, _lane: str) -> list[dict[str, object]]:
        return [_trial("scene-1", 0.9 if workspace else 0.7)]

    report = run_skill_campaign(
        campaign,
        repo_root=repo,
        output_root=tmp_path / "output",
        optimizer_runner=optimizer,
        matrix_runner=matrix,
    )
    return repo, report, patch


def _manifest(
    tmp_path: Path,
    report: dict[str, object],
    *,
    approved: bool = True,
    mutable_path: str = "skills/example/SKILL.md",
) -> Path:
    report_path = Path(str(report["report_path"]))
    path = tmp_path / "promotion.json"
    path.write_text(
        json.dumps(
            {
                "schema": "eval_evolution_promotion_manifest_v1",
                "campaign_id": report["campaign_id"],
                "candidate_id": report["candidate_id"],
                "maintainer_approved": approved,
                "bindings": {
                    "selection_report_sha256": sha256(report_path.read_bytes()).hexdigest(),
                    "patch_sha256": report["digests"]["patch_sha256"],  # type: ignore[index]
                    "materialized_sha256": report["digests"]["materialized_sha256"],  # type: ignore[index]
                    "mutable_paths": [mutable_path],
                },
                "reviewer": {
                    "identity": "maintainer",
                    "reviewed_at": "2026-08-05T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_approved_promotion_applies_only_reviewed_patch_without_commit(tmp_path: Path) -> None:
    repo, report, _patch = _accepted_report(tmp_path)
    manifest = _manifest(tmp_path, report)  # type: ignore[arg-type]

    result = apply_evolution_promotion(
        report_path=Path(report["report_path"]),  # type: ignore[index]
        manifest_path=manifest,
        repo_root=repo,  # type: ignore[arg-type]
    )
    assert result["status"] == "applied"
    assert result["committed"] is False
    assert (repo / "skills/example/SKILL.md").read_text(encoding="utf-8").endswith("Improved.\n")


def test_promotion_fails_closed_without_approval_or_with_dirty_target(tmp_path: Path) -> None:
    repo, report, _patch = _accepted_report(tmp_path)
    with pytest.raises(ValueError, match="maintainer_approved=true"):
        apply_evolution_promotion(
            report_path=Path(report["report_path"]),  # type: ignore[index]
            manifest_path=_manifest(tmp_path, report, approved=False),  # type: ignore[arg-type]
            repo_root=repo,  # type: ignore[arg-type]
        )

    target = repo / "skills/example/SKILL.md"  # type: ignore[operator]
    target.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="target digest changed|dirty or mixed"):
        apply_evolution_promotion(
            report_path=Path(report["report_path"]),  # type: ignore[index]
            manifest_path=_manifest(tmp_path, report),  # type: ignore[arg-type]
            repo_root=repo,  # type: ignore[arg-type]
        )


def test_promotion_rejects_clean_same_digest_path_not_changed_by_candidate(
    tmp_path: Path,
) -> None:
    repo, report, _patch = _accepted_report(tmp_path)

    with pytest.raises(ValueError, match="mutable paths do not match"):
        apply_evolution_promotion(
            report_path=Path(report["report_path"]),  # type: ignore[index]
            manifest_path=_manifest(
                tmp_path,
                report,  # type: ignore[arg-type]
                mutable_path="skills/other/SKILL.md",
            ),
            repo_root=repo,  # type: ignore[arg-type]
        )


def test_promotion_rejects_candidate_record_path_not_changed_by_patch(tmp_path: Path) -> None:
    repo, report, _patch = _accepted_report(tmp_path)
    candidate_path = (
        Path(report["report_path"]).parent  # type: ignore[index]
        / "candidates"
        / "by-sha256"
        / str(report["digests"]["patch_sha256"])  # type: ignore[index]
        / "candidate.json"
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["mutable_paths"] = ["skills/other/SKILL.md"]
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(ValueError, match="patch paths do not match"):
        apply_evolution_promotion(
            report_path=Path(report["report_path"]),  # type: ignore[index]
            manifest_path=_manifest(
                tmp_path,
                report,  # type: ignore[arg-type]
                mutable_path="skills/other/SKILL.md",
            ),
            repo_root=repo,  # type: ignore[arg-type]
        )
