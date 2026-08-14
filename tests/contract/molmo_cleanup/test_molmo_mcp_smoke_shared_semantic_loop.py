from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from roboclaws.household.semantic_timeline import SEMANTIC_LOOP_VARIANT

REPO_ROOT = Path(__file__).resolve().parents[3]
REALWORLD_SMOKE_PATH = REPO_ROOT / "roboclaws" / "household" / "household_mcp_smoke.py"
PREBUILT_BUNDLE = REPO_ROOT / "assets" / "maps" / "molmospaces" / "procthor-10k-val" / "0"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_realworld_mcp_smoke_uses_shared_fixture_style_semantic_loop(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    module = _load_module(REALWORLD_SMOKE_PATH, "run_molmo_realworld_agent_mcp_shared_loop")
    original = module.run_semantic_cleanup_loop
    calls: list[dict[str, Any]] = []

    def wrapped_shared_loop(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(module, "run_semantic_cleanup_loop", wrapped_shared_loop)

    result = module.run_smoke(
        output_dir=tmp_path,
        seed=7,
        map_bundle_dir=PREBUILT_BUNDLE,
    )

    assert calls
    assert all(call["target_request_key"] == "fixture_id" for call in calls)
    assert all(call["include_object_id_in_receptacle_request"] is False for call in calls)
    assert all(call["include_object_id_in_target_requests"] is False for call in calls)
    assert result["semantic_loop_variant"] == SEMANTIC_LOOP_VARIANT
    assert all(
        step["phase"] != "object_done"
        for item in result["semantic_substeps"]
        for step in item["steps"]
    )
