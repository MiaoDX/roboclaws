from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from roboclaws.evals.harness import runner, selector
from roboclaws.household.visual_grounding import DEFAULT_VISUAL_GROUNDING_BASE_URL


def test_failed_dino_readiness_is_classified_as_environment_blocked() -> None:
    row = {"exit_code": 1}

    runner._classify_failed_row(
        row,
        stderr=(
            "visual grounding sidecar is not ready for product runs: timeout. "
            "visual grounding service timed out"
        ),
        stdout="",
    )

    assert row["status"] == "blocked"
    assert row["outcome"] == "blocked"
    assert row["blocker_category"] == "environment_blocked"


def test_dino_sidecar_requirement_uses_strict_managed_http_readiness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    created: list[object] = []

    class FakeManagedSidecar:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self.last_readiness = None
            self.log_metadata = None
            created.append(self)

        def ensure_ready(self, run_dir: Path) -> dict[str, object]:
            assert run_dir == tmp_path / "sidecars" / "visual-grounding"
            self.last_readiness = {
                "schema": "visual_grounding_readiness_v1",
                "ok": True,
                "base_url": DEFAULT_VISUAL_GROUNDING_BASE_URL,
                "pipeline_id": "grounding-dino",
                "require_real_adapter": True,
            }
            return self.last_readiness

        def close(self) -> None:
            return None

    monkeypatch.delenv("VISUAL_GROUNDING_BASE_URL", raising=False)
    monkeypatch.delenv("ROBOCLAWS_EVAL_HARNESS_AUTOSTART_DINO_SIDECAR", raising=False)
    monkeypatch.setattr(runner, "ManagedVisualGroundingProcess", FakeManagedSidecar)
    monkeypatch.setattr(runner, "_MANAGED_DINO_SIDECAR", None)
    manifest = {"output_dir": str(tmp_path)}

    assert runner._ensure_dino_sidecar(manifest) is True
    assert len(created) == 1
    assert created[0].kwargs == {
        "pipeline_id": "grounding-dino",
        "autostart": True,
        "startup_timeout_s": runner.DINO_SIDECAR_STARTUP_TIMEOUT_S,
    }
    assert manifest["dino_sidecar_readiness"]["require_real_adapter"] is True


def test_dino_sidecar_requirement_autostarts_default_service(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls = {"created": 0, "ensured": 0, "closed": 0}

    class FakeManagedSidecar:
        def __init__(self, **kwargs: object) -> None:
            calls["created"] += 1
            assert kwargs["autostart"] is True
            self.last_readiness = None
            self.log_metadata = None

        def ensure_ready(self, run_dir: Path) -> dict[str, object]:
            calls["ensured"] += 1
            self.last_readiness = {
                "schema": "visual_grounding_readiness_v1",
                "ok": True,
                "require_real_adapter": True,
            }
            self.log_metadata = {
                "base_url": DEFAULT_VISUAL_GROUNDING_BASE_URL,
                "command": ["python", "-m", "roboclaws.household.visual_grounding_sidecar.service"],
                "stdout": str(run_dir / "visual_grounding_sidecar" / "stdout.log"),
                "stderr": str(run_dir / "visual_grounding_sidecar" / "stderr.log"),
            }
            return self.last_readiness

        def close(self) -> None:
            calls["closed"] += 1

    monkeypatch.delenv("ROBOCLAWS_EVAL_HARNESS_AUTOSTART_DINO_SIDECAR", raising=False)
    monkeypatch.setattr(runner, "ManagedVisualGroundingProcess", FakeManagedSidecar)
    monkeypatch.setattr(runner, "_MANAGED_DINO_SIDECAR", None)
    monkeypatch.setattr(
        runner,
        "_run_row",
        lambda row, manifest: row.update({"status": "ran", "outcome": "passed", "exit_code": 0}),
    )
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["roboclaws/household/visual_grounding.py"],
        output_dir=tmp_path,
    )

    runner._execute_harness(manifest)

    row = next(
        row
        for row in manifest["rows"]
        if row["selected"] and row["row_id"] == "direct-camera-grounded-grounding-dino"
    )
    assert row["status"] == "ran"
    assert row["outcome"] == "passed"
    assert calls == {"created": 1, "ensured": 2, "closed": 1}
    assert manifest["dino_sidecar_autostart"]["base_url"] == (DEFAULT_VISUAL_GROUNDING_BASE_URL)
    assert manifest["dino_sidecar_autostart"]["stdout"].endswith(
        "sidecars/visual-grounding/visual_grounding_sidecar/stdout.log"
    )
    assert manifest["dino_sidecar_readiness"]["ok"] is True


def test_dino_sidecar_autostart_can_be_disabled(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    class FakeManagedSidecar:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["autostart"] is False
            self.last_readiness = {
                "schema": "visual_grounding_readiness_v1",
                "ok": False,
                "reason": "connection_error",
                "require_real_adapter": True,
            }
            self.log_metadata = None

        def ensure_ready(self, _run_dir: Path) -> dict[str, object]:
            raise RuntimeError("visual grounding connection error")

        def close(self) -> None:
            return None

    monkeypatch.setenv("ROBOCLAWS_EVAL_HARNESS_AUTOSTART_DINO_SIDECAR", "0")
    monkeypatch.setattr(runner, "ManagedVisualGroundingProcess", FakeManagedSidecar)
    monkeypatch.setattr(runner, "_MANAGED_DINO_SIDECAR", None)
    manifest = selector.build_eval_harness(
        mode="execute",
        budget="focused",
        changed_files=["roboclaws/household/visual_grounding.py"],
        output_dir=tmp_path,
    )
    row = next(
        row
        for row in manifest["rows"]
        if row["selected"] and row["row_id"] == "direct-camera-grounded-grounding-dino"
    )

    blockers = runner._row_blockers(row, manifest)

    assert blockers == [
        {
            "category": "environment_blocked",
            "detail": "Grounding DINO visual-grounding sidecar is not reachable",
        }
    ]
    assert manifest["dino_sidecar_readiness"]["reason"] == "connection_error"
