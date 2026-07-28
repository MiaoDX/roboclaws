from __future__ import annotations

from pathlib import Path

import pytest

from roboclaws.household.household_world_episode import _load_runtime_map_prior


def test_runtime_map_prior_loader_rejects_missing_source(tmp_path: Path) -> None:
    prior_path = tmp_path / "missing_runtime_map_prior.json"

    with pytest.raises(
        FileNotFoundError,
        match=r"runtime map prior source is missing: .*missing_runtime_map_prior\.json",
    ):
        _load_runtime_map_prior(prior_path)


def test_runtime_map_prior_loader_rejects_malformed_source(tmp_path: Path) -> None:
    prior_path = tmp_path / "runtime_metric_map.json"
    prior_path.write_text("{not-json\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=(
            r"runtime map prior source must contain valid JSON object: "
            r".*runtime_metric_map\.json"
        ),
    ):
        _load_runtime_map_prior(prior_path)


def test_runtime_map_prior_loader_rejects_non_object_source(tmp_path: Path) -> None:
    prior_path = tmp_path / "runtime_metric_map.json"
    prior_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"runtime map prior source must contain a JSON object: .*runtime_metric_map\.json",
    ):
        _load_runtime_map_prior(prior_path)
