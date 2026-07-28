from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

DIGITAL_TWIN_REVIEW_MANIFEST_SCHEMA = "digital_twin_review_assets_v1"
DIGITAL_TWIN_REVIEW_PROVENANCE = "b1_map12_digital_twin_operator_review"

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_PREVIEW_ROOT = REPO_ROOT / "roboclaws" / "operator_console" / "static" / "previews"

AGIBOT_MAP12_ENVIRONMENT_ID = "agibot-robot-map-12"
AGIBOT_MAP12_SOURCE_NAMES = frozenset({"robot_map_12", "map_12", "12"})
B1_MAP12_REVIEW_ASSET_SOURCES = {
    "map_preview": STATIC_PREVIEW_ROOT / "b1-map12-map.png",
    "topdown": STATIC_PREVIEW_ROOT / "b1-map12-topdown.png",
    "preview_metadata": STATIC_PREVIEW_ROOT / "b1-map12-preview.json",
}


def attach_map12_review_assets(
    run_dir: Path, context: dict[str, Any], run_result: dict[str, Any]
) -> dict[str, Any]:
    """Copy B1/Map12 digital-twin review assets into a physical Map 12 run.

    The copied assets are operator-review sidecars. They are not FPV evidence,
    robot observations, navigation proof, or source-map mutation.
    """

    if not is_agibot_map12_context(context):
        return {}
    sources = {key: path for key, path in B1_MAP12_REVIEW_ASSET_SOURCES.items() if path.is_file()}
    if not sources:
        return {}

    review_dir = Path(run_dir) / "digital_twin_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    source_hashes: dict[str, str] = {}
    for key, source in sources.items():
        target_name = {
            "map_preview": "b1-map12-map.png",
            "topdown": "b1-map12-topdown.png",
            "preview_metadata": "b1-map12-preview.json",
        }[key]
        target = review_dir / target_name
        shutil.copy2(source, target)
        copied[key] = target.relative_to(run_dir).as_posix()
        source_hashes[key] = _file_sha256(source)

    manifest = {
        "schema": DIGITAL_TWIN_REVIEW_MANIFEST_SCHEMA,
        "provenance": DIGITAL_TWIN_REVIEW_PROVENANCE,
        "world_id": "b1-map12",
        "source_physical_world": "agibot-g2/map-12",
        "source_context_environment_id": str(context.get("environment_id") or ""),
        "source_context_map_name": _context_map_name(context),
        "artifact_role": "operator_review_sidecar",
        "agent_policy_input": False,
        "physical_sensor_evidence": False,
        "navigation_proof": False,
        "runtime_observation": False,
        "allowed_uses": [
            "operator_review",
            "same_scene_visual_context",
            "base_metric_map_preview_fallback",
            "topdown_scene_preview_fallback",
        ],
        "forbidden_uses": [
            "raw_fpv_observation",
            "visual_grounding_source",
            "physical_navigation_proof",
            "manipulation_readiness_claim",
            "source_map_semantics_mutation",
        ],
        "artifacts": copied,
        "source_hashes": source_hashes,
        "public_contract_note": (
            "These B1 / Map 12 digital-twin images are copied for operator review "
            "because the physical Agibot Map 12 run uses the same mapped scene. "
            "They do not replace physical robot observations or safety gates."
        ),
    }
    manifest_path = review_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    artifacts = run_result["artifacts"]
    artifacts["digital_twin_review_manifest"] = manifest_path.relative_to(run_dir).as_posix()
    if "map_preview" in copied:
        artifacts["digital_twin_base_metric_map_preview"] = copied["map_preview"]
    if "topdown" in copied:
        artifacts["digital_twin_topdown"] = copied["topdown"]

    run_result["digital_twin_review_assets"] = manifest
    return manifest


def is_agibot_map12_context(context: dict[str, Any]) -> bool:
    if str(context.get("environment_id") or "") == AGIBOT_MAP12_ENVIRONMENT_ID:
        return True
    return _context_map_name(context) in AGIBOT_MAP12_SOURCE_NAMES


def _context_map_name(context: dict[str, Any]) -> str:
    source = context.get("map_source") if isinstance(context.get("map_source"), dict) else {}
    raw_name = source.get("map_name") or source.get("name") or source.get("map_id") or ""
    return str(raw_name).strip().lower()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
