"""Source-aware MolmoSpaces scene sampler contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.worlds.molmospaces.catalog import (
    SCANNER_READY_METADATA,
    SCENE_SAMPLER_SELECTION_SEED,
    SCENE_SAMPLER_SELECTION_STRATEGY,
    SOURCE_EVAL_CANDIDATE_INDICES,
    SOURCE_UI_CANDIDATE_INDICES,
    admitted_sources,
    category_manifest,
    category_provenance,
    known_indices_for_source,
    sampler_world_id,
    scanner_metadata,
    source_eval_indices,
    source_selection_metadata,
    source_ui_indices,
    uses_legacy_preview_assets,
)
from roboclaws.worlds.molmospaces.contracts import (
    EVAL_STRESS_LANE,
    READINESS_BLOCKED,
    READINESS_READY,
    READINESS_REJECTED,
    SAMPLER_GENERATOR_VERSION,
    UI_LANE,
    SceneSamplerRow,
)
from roboclaws.worlds.molmospaces.map_bundles import (
    SIM_MAP_BUNDLE_ASSET_ROOT,
    molmospaces_nav2_map_bundle_path,
)
from roboclaws.worlds.molmospaces.scanner import scanner_admission_row
from roboclaws.worlds.molmospaces.scanner_evidence import (
    coverage_score as _scanner_coverage_score,
)
from roboclaws.worlds.molmospaces.scanner_evidence import (
    scanner_candidate_packet,
    scanner_preview_assets,
    scanner_preview_metadata,
    scanner_product_smoke_artifacts,
    scanner_required_gates,
    world_id_slug,
)
from roboclaws.worlds.molmospaces.world_ids import SUPPORTED_SCENE_SOURCES

SAMPLER_MANIFEST_SCHEMA = "molmospaces_scene_sampler_manifest_v1"
SAMPLER_LABEL_MANIFEST_SCHEMA = "molmospaces_scene_room_labels_v1"
SAMPLER_PROJECTION_SCHEMA = "molmospaces_scene_sampler_projection_v1"
PRIMARY_MOLMOSPACES_BACKEND = "mujoco"
UI_TARGET_PER_SCENE_SOURCE = 3
EVAL_TARGET_PER_SCENE_SOURCE = 10
_PREVIEW_ROOT = Path(__file__).resolve().parents[2] / "operator_console" / "static" / "previews"
_CANONICAL_SCANNER_PREVIEW_ROOT = Path("output") / "scene-sampler-scanner" / "previews"
_SCANNER_OUTPUT_ROOT = Path("output") / "scene-sampler-scanner"
_SCANNER_PREVIEW_ROOT = _SCANNER_OUTPUT_ROOT / "previews"
_SCANNER_PRODUCT_SMOKE_ROOT = _SCANNER_OUTPUT_ROOT / "product-smoke"
_LABEL_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "molmospaces"
    / ("scene_sampler_room_labels.json")
)


def sampler_manifest() -> dict[str, Any]:
    """Return the canonical source-aware MolmoSpaces sampler manifest."""

    rows = [row.to_dict() for row in sampler_rows()]
    return {
        "schema": SAMPLER_MANIFEST_SCHEMA,
        "generator_version": SAMPLER_GENERATOR_VERSION,
        "primary_backend": PRIMARY_MOLMOSPACES_BACKEND,
        "ui_target_per_scene_source": UI_TARGET_PER_SCENE_SOURCE,
        "eval_target_per_scene_source": EVAL_TARGET_PER_SCENE_SOURCE,
        "supported_scene_sources": list(SUPPORTED_SCENE_SOURCES),
        "room_label_manifest": str(_LABEL_MANIFEST_PATH.relative_to(_repo_root())),
        "selection_policy": _sampler_selection_policy(),
        "rows": rows,
        "projections": {
            "ui_world_ids": [row.world_id for row in ui_sampler_rows()],
            "eval_sample_ids": [eval_sample_id(row) for row in eval_sampler_rows()],
            "blocked_scene_sources": [
                row.scene_source
                for row in sampler_rows()
                if row.readiness_status == READINESS_BLOCKED
            ],
        },
    }


def sampler_rows() -> tuple[SceneSamplerRow, ...]:
    """Return all known source rows, including blocked source-family packets."""

    rows: list[SceneSamplerRow] = []
    sources = admitted_sources(supported_sources=SUPPORTED_SCENE_SOURCES)
    for source in sources:
        rows.extend(
            _ready_row(source=source, scene_index=index)
            for index in known_indices_for_source(source)
        )
    rows.extend(
        _blocked_source_row(scene_source)
        for scene_source in SUPPORTED_SCENE_SOURCES
        if scene_source not in sources
    )
    return tuple(rows)


def ui_sampler_rows() -> tuple[SceneSamplerRow, ...]:
    """Return exactly the UI-visible MolmoSpaces sampler rows."""

    return tuple(row for row in sampler_rows() if row.ui_ready)


def eval_sampler_rows() -> tuple[SceneSamplerRow, ...]:
    """Return rows admitted to the static eval-stress projection."""

    return tuple(row for row in sampler_rows() if row.eval_ready)


def sampler_blocked_rows() -> tuple[SceneSamplerRow, ...]:
    """Return blocked or partial rows used by reports and eval-harness metadata."""

    return tuple(row for row in sampler_rows() if row.readiness_status != READINESS_READY)


def ui_molmospaces_world_ids() -> tuple[str, ...]:
    """Return the curated operator-console world ids."""

    return tuple(row.world_id for row in ui_sampler_rows())


def eval_sample_id(row: SceneSamplerRow) -> str:
    if row.scene_index is None:
        return f"scene_sampler.{row.scene_source}.blocked"
    return f"scene_sampler.{row.scene_source}.{row.scene_index}.map_build"


def _blocked_source_row(scene_source: str) -> SceneSamplerRow:
    family, split = _family_split(scene_source)
    return SceneSamplerRow(
        scene_family=family,
        scene_split=split,
        scene_source=scene_source,
        scene_index=None,
        backend=PRIMARY_MOLMOSPACES_BACKEND,
        readiness_status=READINESS_BLOCKED,
        lanes=(),
        world_id=f"molmospaces/{scene_source}/blocked",
        room_count=0,
        waypoint_count=0,
        category_provenance="unavailable",
        category_manifest="",
        preview_assets=(),
        selected_reason="blocked_until_assets_and_preview_readiness_exist",
        blocked_reason=(
            "MolmoSpaces source assets or loader metadata are not locally verified by the "
            "no-download sampler fixture; run scene preparation before admission."
        ),
        failure_class="environment_blocked",
    )


def _ready_row(*, source: str, scene_index: int) -> SceneSamplerRow:
    metadata = scanner_metadata(source=source, scene_index=scene_index)
    preview = _ready_row_preview_metadata(source=source, scene_index=scene_index)
    bundle_counts = _base_metric_map_bundle_counts(source=source, scene_index=scene_index)
    room_ids = _room_ids(preview)
    room_count = int((metadata or {}).get("room_count") or bundle_counts[0] or len(room_ids))
    waypoint_count = int(
        (metadata or {}).get("waypoint_count") or bundle_counts[1] or _waypoint_count(preview)
    )
    view_statuses = _view_statuses(preview)
    all_views_reviewable = all(
        view_statuses.get(view) == "reviewable" for view in _required_views()
    )
    ui_ready = scene_index in source_ui_indices(source)
    eval_ready = scene_index in source_eval_indices(source)
    rejected_reason = str((metadata or {}).get("blocked_reason") or "")
    if room_count < 3 and not rejected_reason:
        rejected_reason = "fewer_than_three_public_navigation_areas"
    elif not all_views_reviewable and not rejected_reason:
        rejected_reason = "preview_not_reviewable"
    status = (
        READINESS_READY if (ui_ready or eval_ready) and not rejected_reason else READINESS_REJECTED
    )
    lanes: list[str] = []
    if ui_ready and status == READINESS_READY:
        lanes.append(UI_LANE)
    if eval_ready and status == READINESS_READY:
        lanes.append(EVAL_STRESS_LANE)
    selected_reason = (
        "selected_by_preview_scanner_for_source_diversity_and_map_actionability_seed"
        if lanes
        else rejected_reason or "candidate_not_selected"
    )
    failure_class = str((metadata or {}).get("failure_class") or "")
    if rejected_reason and not failure_class:
        failure_class = "map_actionability_failure"
    return SceneSamplerRow(
        scene_family=_family_split(source)[0],
        scene_split=_family_split(source)[1],
        scene_source=source,
        scene_index=scene_index,
        backend=PRIMARY_MOLMOSPACES_BACKEND,
        readiness_status=status,
        lanes=tuple(lanes),
        world_id=sampler_world_id(source=source, scene_index=scene_index),
        room_count=room_count,
        waypoint_count=waypoint_count,
        category_provenance=category_provenance(source),
        category_manifest=category_manifest(
            source,
            default_manifest=str(_LABEL_MANIFEST_PATH.relative_to(_repo_root())),
        ),
        preview_assets=_ready_row_preview_assets(source=source, scene_index=scene_index),
        selected_reason=selected_reason,
        blocked_reason=rejected_reason,
        failure_class=failure_class,
        quality_score=float((metadata or {}).get("quality_score") or _quality_score(preview)),
        coverage_score=float(
            (metadata or {}).get("coverage_score")
            or _coverage_score(room_count=room_count, waypoint_count=waypoint_count)
        ),
    )


def _preview_metadata(scene_index: int) -> dict[str, Any]:
    path = _PREVIEW_ROOT / f"molmospaces-val_{scene_index}-preview.json"
    try:
        payload = read_json_object(path, label="scene sampler preview metadata")
    except FileNotFoundError as exc:
        raise ValueError(f"missing preview metadata for scene {scene_index}: {path}") from exc
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if payload.get("scene_source") != "procthor-10k-val":
        raise ValueError(f"preview {path} is not procthor-10k-val")
    if payload.get("backend") != PRIMARY_MOLMOSPACES_BACKEND:
        raise ValueError(f"preview {path} is not for backend={PRIMARY_MOLMOSPACES_BACKEND}")
    return payload


def _ready_row_preview_metadata(*, source: str, scene_index: int) -> dict[str, Any]:
    if source != "procthor-10k-val" or scene_index in SCANNER_READY_METADATA.get(source, {}):
        preview = _scanner_preview_metadata(source, scene_index)
        return preview or _static_scanner_preview_metadata(source=source, scene_index=scene_index)
    return _preview_metadata(scene_index)


def _static_scanner_preview_metadata(*, source: str, scene_index: int) -> dict[str, Any]:
    metadata = scanner_metadata(source=source, scene_index=scene_index)
    room_count = int(metadata["room_count"])
    waypoint_count = int(metadata["waypoint_count"])
    views = {
        view: {"image_diagnostics": {"visual_status": "reviewable"}} for view in _required_views()
    }
    return {
        "scene_source": source,
        "scene_index": scene_index,
        "backend": PRIMARY_MOLMOSPACES_BACKEND,
        "room_count": room_count,
        "waypoint_count": waypoint_count,
        "views": views,
    }


def _view_statuses(preview: dict[str, Any]) -> dict[str, str]:
    views = preview.get("views") if isinstance(preview.get("views"), dict) else {}
    return {
        view: str((payload.get("image_diagnostics") or {}).get("visual_status") or "")
        for view, payload in views.items()
        if isinstance(payload, dict)
    }


def _room_ids(preview: dict[str, Any]) -> tuple[str, ...]:
    count = int(preview.get("room_count") or 0)
    return tuple(f"room_{index}" for index in range(count))


def _waypoint_count(preview: dict[str, Any]) -> int:
    return int(preview.get("waypoint_count") or 0)


def _quality_score(preview: dict[str, Any]) -> float:
    statuses = _view_statuses(preview)
    reviewable_count = sum(1 for view in _required_views() if statuses.get(view) == "reviewable")
    return round(reviewable_count / len(_required_views()), 3)


def _coverage_score(*, room_count: int, waypoint_count: int) -> float:
    return _scanner_coverage_score(room_count=room_count, waypoint_count=waypoint_count)


def _preview_assets(scene_index: int) -> tuple[tuple[str, str], ...]:
    scene_name = f"val_{scene_index}"
    return (
        ("fpv", f"/previews/molmospaces-{scene_name}-fpv.png"),
        ("map", f"/previews/molmospaces-{scene_name}-map.png"),
        ("chase", f"/previews/molmospaces-{scene_name}-chase.png"),
        ("topdown", f"/previews/molmospaces-{scene_name}-topdown.png"),
    )


def _ready_row_preview_assets(*, source: str, scene_index: int) -> tuple[tuple[str, str], ...]:
    if uses_legacy_preview_assets(source=source, scene_index=scene_index):
        return _preview_assets(scene_index)
    static_assets = _static_console_preview_assets(source=source, scene_index=scene_index)
    if static_assets:
        return static_assets
    bundle_preview = _base_metric_map_bundle_preview_asset(source=source, scene_index=scene_index)
    if bundle_preview and scene_index in source_ui_indices(source):
        return (("map", bundle_preview),)
    if scene_index in source_ui_indices(source):
        slug = _world_id_slug(f"molmospaces/{source}/{scene_index}")
        return tuple((view, f"/previews/{slug}-{view}.png") for view in _required_views())
    slug = _world_id_slug(f"molmospaces/{source}/{scene_index}")
    return tuple(
        (view, str(_CANONICAL_SCANNER_PREVIEW_ROOT / f"{slug}-{view}.png"))
        for view in _required_views()
    )


def _required_views() -> tuple[str, ...]:
    return ("fpv", "map", "chase", "topdown")


def _static_console_preview_assets(
    *,
    source: str,
    scene_index: int,
) -> tuple[tuple[str, str], ...]:
    slug = _world_id_slug(f"molmospaces/{source}/{scene_index}")
    assets = tuple((view, f"/previews/{slug}-{view}.png") for view in _required_views())
    if all((_PREVIEW_ROOT / Path(path).name).is_file() for _view, path in assets):
        return assets
    return ()


def _base_metric_map_bundle_counts(*, source: str, scene_index: int) -> tuple[int, int]:
    bundle_dir = molmospaces_nav2_map_bundle_path(
        scene_source=source,
        scene_index=scene_index,
    )
    semantics_path = _repo_root() / bundle_dir / "semantics.json"
    try:
        semantics = read_json_object(semantics_path, label="Base Metric Map semantics")
    except (FileNotFoundError, ValueError):
        return (0, 0)
    contract = semantics.get("base_metric_map_contract")
    if not isinstance(contract, dict):
        return (0, 0)
    return (
        int(contract.get("navigation_area_count") or 0),
        int(contract.get("inspection_waypoint_count") or 0),
    )


def _base_metric_map_bundle_preview_asset(*, source: str, scene_index: int) -> str:
    bundle_dir = molmospaces_nav2_map_bundle_path(
        scene_source=source,
        scene_index=scene_index,
    )
    preview_path = _repo_root() / bundle_dir / "preview.png"
    if not preview_path.is_file():
        return ""
    asset_relative = bundle_dir.relative_to(SIM_MAP_BUNDLE_ASSET_ROOT)
    return f"/asset-previews/maps/{asset_relative.as_posix()}/preview.png"


def _family_split(scene_source: str) -> tuple[str, str]:
    if scene_source == "ithor":
        return "ithor", "not_applicable"
    for split in ("-train", "-val", "-test"):
        if scene_source.endswith(split):
            return scene_source[: -len(split)], split.removeprefix("-")
    return scene_source, "not_applicable"


def _scanner_required_gates() -> tuple[str, ...]:
    return scanner_required_gates()


def _scanner_admission_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return scanner_admission_row(candidate=candidate, required_views=_required_views())


def _world_id_slug(world_id: str) -> str:
    return world_id_slug(world_id)


def _scanner_preview_metadata(source: str, scene_index: int) -> dict[str, Any] | None:
    return scanner_preview_metadata(
        source=source,
        scene_index=scene_index,
        preview_root=_SCANNER_PREVIEW_ROOT,
        backend=PRIMARY_MOLMOSPACES_BACKEND,
    )


def _scanner_product_smoke_artifacts(source: str, scene_index: int) -> dict[str, Any]:
    return scanner_product_smoke_artifacts(
        source=source,
        scene_index=scene_index,
        product_smoke_root=_SCANNER_PRODUCT_SMOKE_ROOT,
    )


def _scanner_candidate_packet(
    *,
    packet: dict[str, Any],
    preview: dict[str, Any],
    smoke: dict[str, Any],
) -> dict[str, Any]:
    return scanner_candidate_packet(
        packet=packet,
        preview=preview,
        smoke=smoke,
        preview_root=_SCANNER_PREVIEW_ROOT,
        required_views=_required_views(),
    )


def _sampler_selection_policy() -> dict[str, Any]:
    return {
        "schema": "molmospaces_scene_sampler_selection_policy_v1",
        "selection_seed": SCENE_SAMPLER_SELECTION_SEED,
        "selection_strategy": SCENE_SAMPLER_SELECTION_STRATEGY,
        "ui_target_per_scene_source": UI_TARGET_PER_SCENE_SOURCE,
        "eval_target_per_scene_source": EVAL_TARGET_PER_SCENE_SOURCE,
        "sources": {
            source: {
                "ui": source_selection_metadata(
                    source=source,
                    lane=UI_LANE,
                    target_count=UI_TARGET_PER_SCENE_SOURCE,
                    candidates=SOURCE_UI_CANDIDATE_INDICES.get(source, ()),
                ),
                "eval_stress": source_selection_metadata(
                    source=source,
                    lane=EVAL_STRESS_LANE,
                    target_count=EVAL_TARGET_PER_SCENE_SOURCE,
                    candidates=SOURCE_EVAL_CANDIDATE_INDICES.get(source, ()),
                ),
            }
            for source in SUPPORTED_SCENE_SOURCES
        },
    }


def _rank_selection_candidates(
    *,
    source: str,
    lane: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metadata = source_selection_metadata(
        source=source,
        lane=lane,
        target_count=len(candidates),
        candidates=tuple(int(candidate.get("scene_index") or 0) for candidate in candidates),
    )
    rank = {scene_index: offset for offset, scene_index in enumerate(metadata["selected_indices"])}
    return sorted(
        candidates,
        key=lambda item: (
            rank.get(int(item.get("scene_index") or 0), len(rank)),
            int(item.get("scene_index") or 0),
        ),
    )


def _scanner_execution_candidate_indices(
    *,
    candidate_indices: tuple[int, ...],
    source_prep: dict[str, Any],
) -> tuple[int, ...]:
    indices = {int(index) for index in candidate_indices}
    for source in source_prep.get("sources", {}).values():
        if not isinstance(source, dict):
            continue
        for candidate in source.get("install_candidates") or []:
            if not isinstance(candidate, dict) or candidate.get("scene_index") is None:
                continue
            indices.add(int(candidate["scene_index"]))
    return tuple(sorted(indices))


def _assign_dynamic_candidate_lanes(
    *,
    source: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    static_ui_ids = set(source_ui_indices(source))
    static_eval_ids = set(source_eval_indices(source))
    if static_ui_ids or static_eval_ids:
        return _assign_candidate_lanes(
            candidates=candidates,
            ui_ids=static_ui_ids,
            eval_ids=static_eval_ids,
        )
    eligible = [
        candidate
        for candidate in candidates
        if candidate.get("readiness_status") == READINESS_READY
        and candidate.get("eval_ready")
        and candidate.get("scene_index") is not None
    ]
    eligible = _rank_selection_candidates(
        source=source,
        lane=EVAL_STRESS_LANE,
        candidates=eligible,
    )
    ui_ids = {
        int(candidate.get("scene_index") or 0)
        for candidate in _rank_selection_candidates(
            source=source,
            lane=UI_LANE,
            candidates=eligible,
        )[:UI_TARGET_PER_SCENE_SOURCE]
        if len(eligible) >= UI_TARGET_PER_SCENE_SOURCE
    }
    eval_ids = {
        int(candidate.get("scene_index") or 0)
        for candidate in eligible[:EVAL_TARGET_PER_SCENE_SOURCE]
    }
    return _assign_candidate_lanes(
        candidates=candidates,
        ui_ids=ui_ids,
        eval_ids=eval_ids,
    )


def _assign_candidate_lanes(
    *,
    candidates: list[dict[str, Any]],
    ui_ids: set[int],
    eval_ids: set[int],
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for candidate in candidates:
        scene_index = candidate.get("scene_index")
        lanes: list[str] = []
        if candidate.get("readiness_status") == READINESS_READY and scene_index is not None:
            parsed_index = int(scene_index)
            if parsed_index in ui_ids:
                lanes.append(UI_LANE)
            if parsed_index in eval_ids:
                lanes.append(EVAL_STRESS_LANE)
        updated.append(
            {
                **candidate,
                "lanes": lanes,
                "ui_ready": UI_LANE in lanes,
                "eval_ready": EVAL_STRESS_LANE in lanes,
            }
        )
    return updated


def _scanner_preview_assets(source: str, scene_index: int) -> list[dict[str, str]]:
    return scanner_preview_assets(
        source=source,
        scene_index=scene_index,
        preview_root=_SCANNER_PREVIEW_ROOT,
        required_views=_required_views(),
    )


def _candidate_packet_from_sampler_row(row: SceneSamplerRow) -> dict[str, Any]:
    preview_statuses: dict[str, str] = {}
    if row.scene_index is not None:
        preview_statuses = _view_statuses(
            _ready_row_preview_metadata(source=row.scene_source, scene_index=row.scene_index)
        )
    metadata = (
        scanner_metadata(source=row.scene_source, scene_index=row.scene_index)
        if row.scene_index is not None
        else {}
    )
    return {
        "scene_family": row.scene_family,
        "scene_split": row.scene_split,
        "scene_source": row.scene_source,
        "scene_index": row.scene_index,
        "backend": row.backend,
        "world_id": row.world_id,
        "readiness_status": row.readiness_status,
        "lanes": list(row.lanes),
        "ui_ready": row.ui_ready,
        "eval_ready": row.eval_ready,
        "room_count": row.room_count,
        "waypoint_count": row.waypoint_count,
        "category_provenance": row.category_provenance,
        "category_manifest": row.category_manifest,
        "preview_statuses": preview_statuses,
        "preview_assets": [{"view": view, "path": path} for view, path in row.preview_assets],
        "selected_reason": row.selected_reason,
        "blocked_reason": row.blocked_reason,
        "failure_class": row.failure_class,
        "quality_score": row.quality_score,
        "coverage_score": row.coverage_score,
        "source_outcome": str(metadata.get("source_outcome") or ""),
        "prefilter_status": str(metadata.get("prefilter_status") or ""),
        "prefilter_reason": str(metadata.get("prefilter_reason") or ""),
        "cheap_room_count": int(metadata.get("cheap_room_count") or 0),
        "product_smoke_run_dir": str(metadata.get("product_smoke_run_dir") or ""),
    }


def _blocked_candidate_packet(
    *,
    source: str,
    scene_index: int,
    source_availability: dict[str, Any],
) -> dict[str, Any]:
    family, split = _family_split(source)
    candidate_file = next(
        (
            item
            for item in source_availability.get("candidate_files") or []
            if item.get("scene_index") == scene_index
        ),
        {},
    )
    blocked_reason = str(source_availability.get("blocked_reason") or "")
    if not blocked_reason:
        blocked_reason = (
            f"{source}/{scene_index} has no sampler preview, room, waypoint, or "
            "map-build readiness packet yet; run scene preparation before admission."
        )
    packet = {
        "scene_family": family,
        "scene_split": split,
        "scene_source": source,
        "scene_index": scene_index,
        "backend": PRIMARY_MOLMOSPACES_BACKEND,
        "world_id": f"molmospaces/{source}/{scene_index}",
        "readiness_status": READINESS_BLOCKED,
        "lanes": [],
        "ui_ready": False,
        "eval_ready": False,
        "room_count": 0,
        "waypoint_count": 0,
        "category_provenance": "unavailable",
        "category_manifest": "",
        "preview_statuses": {},
        "preview_assets": [],
        "selected_reason": "blocked_until_candidate_readiness_packet_exists",
        "blocked_reason": blocked_reason,
        "failure_class": "environment_blocked",
        "quality_score": 0.0,
        "coverage_score": 0.0,
        "source_availability_status": source_availability.get("status"),
        "candidate_file": candidate_file,
    }
    if not isinstance(candidate_file, dict) or not candidate_file.get("exists"):
        return packet
    preview = _scanner_preview_metadata(source, scene_index)
    if preview is None:
        return packet
    return _scanner_candidate_packet(
        packet=packet,
        preview=preview,
        smoke=_scanner_product_smoke_artifacts(source, scene_index),
    )


def _parse_scene_index(raw_value: str, *, world_id: str) -> int:
    try:
        scene_index = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"unsupported MolmoSpaces scene index {raw_value!r}: {world_id}") from exc
    if scene_index < 0:
        raise ValueError(f"unsupported negative MolmoSpaces scene index {scene_index}: {world_id}")
    return scene_index


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
