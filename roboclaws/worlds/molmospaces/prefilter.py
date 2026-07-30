"""Scene-only prefilter helpers for the MolmoSpaces scene sampler."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.worlds.molmospaces.catalog import (
    SCENE_SAMPLER_SELECTION_SEED,
    source_selection_metadata,
)
from roboclaws.worlds.molmospaces.contracts import READINESS_BLOCKED, SAMPLER_GENERATOR_VERSION

SCENE_PREFILTER_EXPENSIVE_PROOF_TARGET_PER_SOURCE = 5
SCENE_PREFILTER_LANE = "scene_only_prefilter"
SCENE_PREFILTER_MIN_HIGH_CONFIDENCE_ROOMS = 3


def scene_only_prefilter_report(
    *,
    candidate_profile: dict[str, Any],
    supported_sources: tuple[str, ...],
    candidate_indices: tuple[int, ...],
    selection_policy: dict[str, Any],
) -> dict[str, Any]:
    """Return no-download scene-only ranking before expensive source prep.

    The prefilter never admits a scene. It only narrows metadata worklists to a
    capped subset that is worth object/grasp installation plus scanner proof.
    """

    sources: dict[str, dict[str, Any]] = {}
    for source in supported_sources:
        source_profile = candidate_profile["sources"][source]
        rows = [
            _scene_prefilter_row(row)
            for row in source_profile.get("metadata_worklist_candidates") or []
            if isinstance(row, dict)
        ]
        high_confidence = _rank_scene_prefilter_rows(source=source, rows=rows)
        expensive_rows = high_confidence[:SCENE_PREFILTER_EXPENSIVE_PROOF_TARGET_PER_SOURCE]
        expensive_ids = {
            int(row["scene_index"]) for row in expensive_rows if row.get("scene_index") is not None
        }
        candidates = [
            {
                **row,
                "expensive_proof_selected": (
                    row.get("prefilter_status") == "high_confidence"
                    and int(row.get("scene_index") or -1) in expensive_ids
                ),
                "next_action": (
                    "run_expensive_proof"
                    if (
                        row.get("prefilter_status") == "high_confidence"
                        and int(row.get("scene_index") or -1) in expensive_ids
                    )
                    else _scene_prefilter_row_next_action(row)
                ),
            }
            for row in rows
        ]
        sources[source] = {
            "scene_source": source,
            "scene_family": source_profile.get("scene_family", ""),
            "scene_split": source_profile.get("scene_split", ""),
            "candidate_profile_status": source_profile.get("profile_status", ""),
            "metadata_worklist_candidate_count": int(
                source_profile.get("metadata_worklist_candidate_count") or 0
            ),
            "prefilter_status": _scene_prefilter_source_status(
                source_profile=source_profile,
                candidates=candidates,
            ),
            "next_action": _scene_prefilter_source_next_action(
                source_profile=source_profile,
                candidates=candidates,
            ),
            "candidate_count": len(candidates),
            "high_confidence_candidate_count": sum(
                1 for row in candidates if row.get("prefilter_status") == "high_confidence"
            ),
            "expensive_proof_candidate_count": sum(
                1 for row in candidates if row.get("expensive_proof_selected")
            ),
            "expensive_proof_world_ids": [
                row["world_id"] for row in candidates if row.get("expensive_proof_selected")
            ],
            "inconclusive_candidate_count": sum(
                1 for row in candidates if row.get("prefilter_status") == "inconclusive"
            ),
            "low_confidence_candidate_count": sum(
                1 for row in candidates if row.get("prefilter_status") == "low_confidence"
            ),
            "candidates": candidates,
        }
    return {
        "schema": "molmospaces_scene_sampler_scene_prefilter_v1",
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "probe_mode": "no_download_no_backend_no_vlm",
        "download_policy": "manual_operator_only",
        "prefilter_policy": _scene_prefilter_policy(),
        "candidate_indices": list(candidate_indices),
        "selection_policy": selection_policy,
        "summary": _scene_prefilter_summary(sources),
        "sources": sources,
    }


def scene_prefilter_expensive_proof_candidates(
    source_prefilter: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in source_prefilter.get("candidates") or []:
        if not isinstance(row, dict) or not row.get("expensive_proof_selected"):
            continue
        candidate_file = row.get("candidate_file")
        if not isinstance(candidate_file, dict):
            candidate_file = {}
        has_concrete_scene_ref = bool(
            candidate_file.get("path")
            or candidate_file.get("paths")
            or candidate_file.get("missing_paths")
        )
        if not has_concrete_scene_ref:
            continue
        candidates.append(
            {
                "scene_source": row.get("scene_source", ""),
                "scene_index": row.get("scene_index"),
                "world_id": row.get("world_id", ""),
                "readiness_status": READINESS_BLOCKED,
                "failure_class": row.get("known_failure_class", "") or "environment_blocked",
                "blocked_reason": row.get("known_blocked_reason", ""),
                "source_availability_status": "",
                "candidate_file": candidate_file,
                "prefilter_status": row.get("prefilter_status", ""),
                "prefilter_reason": row.get("prefilter_reason", ""),
                "prefilter_score": int(row.get("prefilter_score") or 0),
                "cheap_room_count": int(row.get("cheap_room_count") or 0),
            }
        )
    return candidates


def _scene_prefilter_policy() -> dict[str, Any]:
    return {
        "schema": "molmospaces_scene_sampler_scene_prefilter_policy_v1",
        "selection_seed": SCENE_SAMPLER_SELECTION_SEED,
        "selection_strategy": (
            "cheap_scene_metadata_room_count_desc_then_deterministic_seeded_tiebreak"
        ),
        "lane": SCENE_PREFILTER_LANE,
        "min_high_confidence_room_count": SCENE_PREFILTER_MIN_HIGH_CONFIDENCE_ROOMS,
        "expensive_proof_target_per_scene_source": (
            SCENE_PREFILTER_EXPENSIVE_PROOF_TARGET_PER_SOURCE
        ),
        "probe_mode": "no_download_no_backend_no_vlm",
        "download_policy": "manual_operator_only",
        "admission_effect": "none_prefilter_only",
        "allowed_evidence": [
            "already_available_scene_descriptor_json",
            "already_available_scene_metadata_json",
            "already_available_scene_xml_header_or_mesh_names",
            "source_index_references",
        ],
        "forbidden_side_effects": [
            "install_scene_with_objects_and_grasps_from_path",
            "preview_render",
            "map_build_product_smoke",
        ],
    }


def _scene_prefilter_row(row: dict[str, Any]) -> dict[str, Any]:
    candidate_file = row.get("candidate_file")
    if not isinstance(candidate_file, dict):
        candidate_file = {}
    evidence = _scene_prefilter_evidence(candidate_file)
    cheap_room_count = int(evidence.get("cheap_room_count") or 0)
    observed_paths = [
        str(item.get("path") or "")
        for item in evidence.get("field_provenance") or []
        if isinstance(item, dict) and item.get("path")
    ]
    status, reason = _scene_prefilter_candidate_status(
        cheap_room_count=cheap_room_count,
        observed_paths=observed_paths,
        candidate_file=candidate_file,
    )
    return {
        **row,
        "prefilter_status": status,
        "prefilter_reason": reason,
        "prefilter_score": cheap_room_count,
        "cheap_room_count": cheap_room_count,
        "scene_descriptor_room_count": int(evidence.get("scene_descriptor_room_count") or 0),
        "scene_metadata_room_count": int(evidence.get("scene_metadata_room_count") or 0),
        "xml_room_mesh_count": int(evidence.get("xml_room_mesh_count") or 0),
        "scene_descriptor_path": evidence.get("scene_descriptor_path", ""),
        "scene_metadata_path": evidence.get("scene_metadata_path", ""),
        "xml_path": evidence.get("xml_path", ""),
        "field_provenance": evidence.get("field_provenance", []),
        "download_policy": "manual_operator_only",
        "admission_effect": "none_prefilter_only",
    }


def _scene_prefilter_candidate_status(
    *,
    cheap_room_count: int,
    observed_paths: list[str],
    candidate_file: dict[str, Any],
) -> tuple[str, str]:
    if cheap_room_count >= SCENE_PREFILTER_MIN_HIGH_CONFIDENCE_ROOMS:
        return "high_confidence", "likely_multi_area"
    if cheap_room_count > 0:
        return "low_confidence", "single_room_likely"
    if observed_paths:
        return "inconclusive", "prefilter_inconclusive"
    if (
        candidate_file.get("path")
        or candidate_file.get("paths")
        or candidate_file.get("missing_paths")
    ):
        return "inconclusive", "descriptor_missing"
    return "inconclusive", "source_index_reference_missing"


def _scene_prefilter_evidence(candidate_file: dict[str, Any]) -> dict[str, Any]:
    primary_path = Path(str(candidate_file.get("path") or ""))
    candidate_paths = _scene_prefilter_candidate_paths(candidate_file, primary_path=primary_path)
    descriptor_counts: list[int] = []
    metadata_counts: list[int] = []
    xml_counts: list[int] = []
    descriptor_path = ""
    metadata_path = ""
    xml_path = ""
    provenance: list[dict[str, Any]] = []
    for path in candidate_paths:
        suffix = path.suffix.lower()
        name = path.name.lower()
        if suffix == ".xml":
            count = _scene_prefilter_room_count_from_xml(path)
            if count > 0 and not xml_path:
                xml_path = str(path)
            if count > 0:
                xml_counts.append(count)
                provenance.append({"field": "xml_room_mesh_count", "path": str(path)})
            continue
        if suffix != ".json":
            continue
        payload = _read_json_if_exists(path)
        if not payload:
            continue
        count = _scene_prefilter_room_count_from_json(payload)
        if count <= 0:
            continue
        if name.endswith("_metadata.json"):
            metadata_counts.append(count)
            metadata_path = metadata_path or str(path)
            provenance.append({"field": "scene_metadata_room_count", "path": str(path)})
        else:
            descriptor_counts.append(count)
            descriptor_path = descriptor_path or str(path)
            provenance.append({"field": "scene_descriptor_room_count", "path": str(path)})
    descriptor_count = max(descriptor_counts, default=0)
    metadata_count = max(metadata_counts, default=0)
    xml_count = max(xml_counts, default=0)
    return {
        "scene_descriptor_room_count": descriptor_count,
        "scene_metadata_room_count": metadata_count,
        "xml_room_mesh_count": xml_count,
        "cheap_room_count": max(descriptor_count, metadata_count, xml_count),
        "scene_descriptor_path": descriptor_path,
        "scene_metadata_path": metadata_path,
        "xml_path": xml_path,
        "field_provenance": provenance,
    }


def _scene_prefilter_candidate_paths(
    candidate_file: dict[str, Any],
    *,
    primary_path: Path,
) -> list[Path]:
    paths: list[Path] = []
    if primary_path.as_posix() not in {"", "."}:
        paths.append(primary_path)
        paths.extend(
            [
                primary_path.with_suffix(".json"),
                primary_path.with_name(f"{primary_path.stem}_metadata.json"),
            ]
        )
    for entry in candidate_file.get("paths") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        path = Path(str(entry["path"]))
        paths.append(path)
        if path.suffix.lower() == ".xml":
            paths.extend([path.with_suffix(".json"), path.with_name(f"{path.stem}_metadata.json")])
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key and key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _scene_prefilter_room_count_from_json(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    candidates = [
        payload.get("rooms"),
        payload.get("roomSpec"),
        payload.get("room_spec"),
        payload.get("proceduralParameters", {}).get("rooms")
        if isinstance(payload.get("proceduralParameters"), dict)
        else None,
    ]
    house = payload.get("house")
    if isinstance(house, dict):
        candidates.extend([house.get("rooms"), house.get("roomSpec"), house.get("room_spec")])
    counts = [_room_collection_count(item) for item in candidates]
    return max(counts, default=0)


def _room_collection_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("rooms", "roomTypes", "room_types"):
            nested = value.get(key)
            if isinstance(nested, (list, dict)):
                return _room_collection_count(nested)
        if value:
            return len(value)
    return 0


def _scene_prefilter_room_count_from_xml(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    names = {
        match.group(1)
        for match in re.finditer(r'\bname=["\']([^"\']*room[^"\']*)["\']', text, re.IGNORECASE)
    }
    if names:
        indexed_rooms = {
            match.group(1)
            for name in names
            for match in [re.search(r"\broom[_-]?(\d+)\b", name, re.IGNORECASE)]
            if match
        }
        return len(indexed_rooms) if indexed_rooms else len(names)
    indexed_mentions = set(re.findall(r"\broom[_-]?(\d+)\b", text, re.IGNORECASE))
    return len(indexed_mentions)


def _rank_scene_prefilter_rows(
    *,
    source: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    high_confidence = [row for row in rows if row.get("prefilter_status") == "high_confidence"]
    if not high_confidence:
        return []
    metadata = source_selection_metadata(
        source=source,
        lane=SCENE_PREFILTER_LANE,
        target_count=len(high_confidence),
        candidates=tuple(
            int(row.get("scene_index") or 0)
            for row in high_confidence
            if row.get("scene_index") is not None
        ),
    )
    seeded_rank = {
        int(index): offset for offset, index in enumerate(metadata.get("selected_indices") or [])
    }
    ranked = sorted(
        high_confidence,
        key=lambda row: (
            seeded_rank.get(int(row.get("scene_index") or 0), len(seeded_rank)),
            int(row.get("scene_index") or 0),
        ),
    )
    first_by_room_count: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    seen_room_counts: set[int] = set()
    for row in ranked:
        room_count = int(row.get("cheap_room_count") or 0)
        if room_count not in seen_room_counts:
            seen_room_counts.add(room_count)
            first_by_room_count.append(row)
        else:
            remaining.append(row)
    return [
        *sorted(first_by_room_count, key=lambda row: -int(row.get("cheap_room_count") or 0)),
        *remaining,
    ]


def _scene_prefilter_row_next_action(row: dict[str, Any]) -> str:
    status = str(row.get("prefilter_status") or "")
    if status == "high_confidence":
        return "skip_expensive_proof_batch_cap"
    if status == "low_confidence":
        return "do_not_run_expensive_proof_without_gate_change"
    return "inspect_scene_descriptor_or_choose_curated_source"


def _scene_prefilter_source_status(
    *,
    source_profile: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    if source_profile.get("profile_status") == "complete":
        return "complete"
    if not candidates:
        return "no_metadata_worklist"
    if any(row.get("expensive_proof_selected") for row in candidates):
        return "high_confidence_ready"
    if any(row.get("prefilter_status") == "high_confidence" for row in candidates):
        return "high_confidence_batch_capped"
    if any(row.get("prefilter_status") == "low_confidence" for row in candidates):
        return "low_confidence_only"
    return "prefilter_inconclusive"


def _scene_prefilter_source_next_action(
    *,
    source_profile: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str:
    status = _scene_prefilter_source_status(source_profile=source_profile, candidates=candidates)
    if status == "complete":
        return "none"
    if status in {"high_confidence_ready", "high_confidence_batch_capped"}:
        return "run_expensive_proof_for_prefiltered_candidates"
    if status == "no_metadata_worklist":
        return str(source_profile.get("next_action") or "inspect_candidate_profile")
    return "stop_prefilter_inconclusive"


def _scene_prefilter_summary(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    worklist = [
        _scene_prefilter_worklist_item(source)
        for source in sources.values()
        if source.get("next_action") != "none"
    ]
    return {
        "source_count": len(sources),
        "complete_source_count": sum(
            1 for source in sources.values() if source.get("prefilter_status") == "complete"
        ),
        "metadata_worklist_source_count": sum(
            1
            for source in sources.values()
            if int(source.get("metadata_worklist_candidate_count") or 0) > 0
        ),
        "candidate_count": sum(
            int(source.get("candidate_count") or 0) for source in sources.values()
        ),
        "high_confidence_candidate_count": sum(
            int(source.get("high_confidence_candidate_count") or 0) for source in sources.values()
        ),
        "expensive_proof_candidate_count": sum(
            int(source.get("expensive_proof_candidate_count") or 0) for source in sources.values()
        ),
        "inconclusive_candidate_count": sum(
            int(source.get("inconclusive_candidate_count") or 0) for source in sources.values()
        ),
        "low_confidence_candidate_count": sum(
            int(source.get("low_confidence_candidate_count") or 0) for source in sources.values()
        ),
        "next_actions": _selection_action_counts(worklist),
        "worklist": worklist,
    }


def _scene_prefilter_worklist_item(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_source": source.get("scene_source", ""),
        "prefilter_status": source.get("prefilter_status", ""),
        "next_action": source.get("next_action", ""),
        "metadata_worklist_candidate_count": int(
            source.get("metadata_worklist_candidate_count") or 0
        ),
        "candidate_count": int(source.get("candidate_count") or 0),
        "high_confidence_candidate_count": int(source.get("high_confidence_candidate_count") or 0),
        "expensive_proof_candidate_count": int(source.get("expensive_proof_candidate_count") or 0),
        "expensive_proof_world_ids": source.get("expensive_proof_world_ids") or [],
    }


def _selection_action_counts(worklist: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in worklist:
        action = str(item.get("next_action") or "")
        if action:
            counts[action] = counts.get(action, 0) + 1
    return counts


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path, label="scene sampler optional JSON")
    except (FileNotFoundError, OSError, ValueError):
        return {}
