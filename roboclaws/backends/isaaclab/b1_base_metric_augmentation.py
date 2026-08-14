#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parents[3]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
else:
    REPO_ROOT = Path(__file__).resolve().parents[3]

from roboclaws.backends.isaaclab.b1_readiness_validation import (
    DEFAULT_B1_VISUAL_ROUTE_SCENE_USD,
    NAVIGATION_PROVENANCE,
    validate_alignment_residual_artifact,
    validate_navigation_smoke_artifact,
)
from roboclaws.core.json_sources import read_json_object
from roboclaws.maps.bundle import (
    validate_base_metric_map_v1_bundle,
    validate_nav2_map_bundle,
    write_source_frame_bundle_preview,
)

B1_MAP12_BASE_METRIC_SIDECAR_SCHEMA = "b1_map12_base_metric_sidecar_v1"
B1_ROBOT_CONSUMPTION_MANIFEST_SCHEMA = "b1_map12_robot_consumption_manifest_v1"
DEFAULT_BASE_MAP_BUNDLE = Path("output/b1-map12/base-metric-map")
DEFAULT_OUTPUT_DIR = Path("output/b1-map12/base-metric-map-with-proof")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a generated B1 / Map 12 Base Metric Map bundle and add "
            "explicit Digital Twin robot-consumption proof sidecars."
        )
    )
    parser.add_argument("--base-map-bundle", type=Path, default=DEFAULT_BASE_MAP_BUNDLE)
    parser.add_argument("--alignment-artifact", type=Path)
    parser.add_argument("--navigation-artifact", type=Path)
    parser.add_argument("--allow-blocked-proof", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = augment_base_metric_map_bundle(
            base_map_bundle=args.base_map_bundle,
            alignment_artifact_path=args.alignment_artifact,
            navigation_artifact_path=args.navigation_artifact,
            allow_blocked_proof=args.allow_blocked_proof,
            output_dir=args.output_dir,
        )
    except (FileNotFoundError, ValueError, AssertionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def augment_base_metric_map_bundle(
    *,
    base_map_bundle: Path,
    output_dir: Path,
    alignment_artifact_path: Path | None = None,
    navigation_artifact_path: Path | None = None,
    allow_blocked_proof: bool = False,
) -> dict[str, Any]:
    base_map_bundle = Path(base_map_bundle)
    output_dir = Path(output_dir)
    validation = validate_nav2_map_bundle(base_map_bundle)
    validation.raise_for_errors()
    base_validation = validate_base_metric_map_v1_bundle(base_map_bundle)
    base_validation.raise_for_errors()
    semantics = read_json_object(base_map_bundle / "semantics.json", label="base map semantics")
    _assert_base_metric_semantics(semantics, base_map_bundle=base_map_bundle)
    base_manifest = read_json_object(
        base_map_bundle / "base_metric_map_manifest.json",
        label="base metric map manifest",
    )
    _assert_base_metric_manifest(base_manifest)
    proof = verified_robot_consumption_proof(
        alignment_artifact_path=alignment_artifact_path,
        navigation_artifact_path=navigation_artifact_path,
        allow_blocked_proof=allow_blocked_proof,
    )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(base_map_bundle, output_dir)
    sidecar_semantics = dict(semantics)
    sidecar_semantics["digital_twin_capabilities"] = {
        "robot_consumption_proof": proof,
        "render_observation_proof": render_observation_proof(proof),
        "room_semantic_projection_proof": blocked_room_semantic_projection_proof(),
    }
    sidecar_semantics["provenance"] = {
        **dict(sidecar_semantics.get("provenance") or {}),
        "b1_base_metric_sidecar": _repo_relative_path(Path(__file__)),
        "contains_verified_robot_consumption_proof": bool(proof.get("robot_navigation_supported")),
        "contains_verified_room_semantics": False,
        "contains_runtime_observations": False,
        "contains_private_scoring_truth": False,
    }
    (output_dir / "semantics.json").write_text(
        json.dumps(sidecar_semantics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_source_frame_bundle_preview(output_dir)
    sidecar_validation = validate_nav2_map_bundle(output_dir)
    sidecar_validation.raise_for_errors()
    sidecar_base_validation = validate_base_metric_map_v1_bundle(output_dir)
    sidecar_base_validation.raise_for_errors()
    room_semantic_projection_proof = sidecar_semantics["digital_twin_capabilities"][
        "room_semantic_projection_proof"
    ]
    manifest = b1_robot_consumption_manifest(
        output_dir=output_dir,
        robot_consumption_proof=proof,
        room_semantic_projection_proof=room_semantic_projection_proof,
        semantic_label_count=len(sidecar_semantics.get("rooms") or []),
        navigation_area_count=int(
            (sidecar_semantics.get("base_metric_map_contract") or {}).get("navigation_area_count")
            or 0
        ),
        inspection_waypoint_count=len(sidecar_semantics.get("inspection_waypoints") or []),
    )
    (output_dir / "b1_robot_consumption_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    provenance = sidecar_provenance(
        base_map_bundle=base_map_bundle,
        output_dir=output_dir,
        base_manifest=base_manifest,
        robot_consumption_proof=proof,
        validation=sidecar_base_validation.as_dict(),
    )
    (output_dir / "b1_base_metric_sidecar.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "schema": B1_MAP12_BASE_METRIC_SIDECAR_SCHEMA,
        "status": "augmented",
        "output_dir": str(output_dir),
        "robot_consumption_manifest": str(output_dir / "b1_robot_consumption_manifest.json"),
        "provenance": str(output_dir / "b1_base_metric_sidecar.json"),
        "robot_navigation_supported": bool(proof.get("robot_navigation_supported")),
        "validation": sidecar_base_validation.as_dict(),
    }


def _assert_base_metric_semantics(
    semantics: dict[str, Any],
    *,
    base_map_bundle: Path,
) -> None:
    if semantics.get("schema") != "nav2_cleanup_semantics_v1":
        raise ValueError("base map semantics must use schema nav2_cleanup_semantics_v1")
    contract = semantics.get("base_metric_map_contract")
    if not isinstance(contract, dict) or contract.get("schema") != "base_metric_map_v1":
        raise ValueError("base map semantics must include base_metric_map_contract")
    if contract.get("consumer_scope") != "real_robot_and_digital_twin":
        raise ValueError(
            "base_metric_map_contract.consumer_scope must be real_robot_and_digital_twin"
        )
    provenance = (
        semantics.get("provenance") if isinstance(semantics.get("provenance"), dict) else {}
    )
    if provenance.get("uses_navigation_memory_as_waypoint_source") is not False:
        raise ValueError("base map must not use navigation_memory as waypoint source")
    if provenance.get("contains_static_fixtures") is not False:
        raise ValueError("base map must not include static fixture truth")
    if provenance.get("contains_movable_objects") is not False:
        raise ValueError("base map must not include movable object truth")
    if "digital_twin_capabilities" in semantics:
        raise ValueError("base map bundle already contains digital_twin_capabilities")
    if not (base_map_bundle / "base_metric_map_manifest.json").is_file():
        raise ValueError("base map bundle missing base_metric_map_manifest.json")


def _assert_base_metric_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != "b1_map12_base_metric_map_manifest_v1":
        raise ValueError("base metric map manifest has unexpected schema")
    if manifest.get("status") != "generated":
        raise ValueError("base metric map manifest status must be generated")
    policy = manifest.get("policy") if isinstance(manifest.get("policy"), dict) else {}
    if policy.get("shared_by_real_robot_and_digital_twin") is not True:
        raise ValueError("base metric map manifest must be shared by real robot and Digital Twin")
    if policy.get("does_not_use_navigation_memory_as_waypoint_source") is not True:
        raise ValueError("base metric map manifest must reject navigation_memory waypoints")


def verified_robot_consumption_proof(
    *,
    alignment_artifact_path: Path | None,
    navigation_artifact_path: Path | None,
    allow_blocked_proof: bool,
) -> dict[str, Any]:
    if alignment_artifact_path is None or navigation_artifact_path is None:
        if (
            allow_blocked_proof
            and alignment_artifact_path is None
            and navigation_artifact_path is None
        ):
            return _blocked_robot_consumption_proof()
        raise ValueError(
            "B1 robot-consumption sidecar requires explicit --alignment-artifact "
            "and --navigation-artifact"
        )
    alignment_artifact_path, alignment = _verified_alignment_artifact(alignment_artifact_path)
    navigation_artifact_path, navigation = _verified_navigation_artifact(
        navigation_artifact_path,
        alignment_artifact_path=alignment_artifact_path,
    )
    proof = _blocked_robot_consumption_proof()
    proof.update(_verified_alignment_proof(alignment_artifact_path, alignment))
    proof.update(_verified_navigation_proof(navigation_artifact_path, navigation))
    return proof


def _blocked_robot_consumption_proof() -> dict[str, Any]:
    return {
        "schema": "b1_map12_robot_consumption_proof_v1",
        "status": "blocked_missing_verified_alignment",
        "alignment_status": "not_provided",
        "navigation_status": "not_provided",
        "alignment_artifact": "",
        "navigation_artifact": "",
        "robot_navigation_supported": False,
        "robot_navigation_provenance": "pending_local_isaac_b1_map12_navigation_smoke",
        "navigation_waypoint_count": 0,
        "robot_view_evidence_status": "not_available",
        "planner_backed": False,
        "physical_robot": False,
        "manipulation_supported": False,
        "object_receptacle_usd_binding_status": "blocked_out_of_scope",
        "policy": {
            "requires_explicit_alignment_artifact": True,
            "requires_explicit_navigation_artifact": True,
            "rejects_missing_or_invalid_artifacts": True,
            "no_output_directory_autodiscovery": True,
        },
    }


def _verified_alignment_artifact(alignment_artifact_path: Path) -> tuple[Path, dict[str, Any]]:
    alignment_artifact_path = Path(alignment_artifact_path)
    alignment = read_json_object(alignment_artifact_path, label="alignment artifact")
    alignment_errors = validate_alignment_residual_artifact(alignment)
    if alignment_errors:
        raise ValueError("invalid alignment artifact: " + "; ".join(alignment_errors))
    if alignment.get("global_alignment_status") != "verified":
        raise ValueError("alignment artifact must be globally verified")
    return alignment_artifact_path, alignment


def _verified_alignment_proof(
    alignment_artifact_path: Path,
    alignment: dict[str, Any],
) -> dict[str, Any]:
    residual = _dict(alignment.get("residual_evidence"))
    return {
        "status": "verified_alignment_navigation_pending",
        "alignment_status": "verified",
        "alignment_artifact": str(alignment_artifact_path),
        "alignment_transform_source": str(residual.get("transform_source") or ""),
        "selected_transform_type": str(alignment.get("selected_transform_type") or ""),
        "matched_anchor_count": int(residual.get("matched_anchor_count") or 0),
        "mean_residual_m": residual.get("mean_residual_m"),
        "p90_residual_m": residual.get("p90_residual_m"),
        "max_residual_m": residual.get("max_residual_m"),
    }


def _verified_navigation_artifact(
    navigation_artifact_path: Path,
    *,
    alignment_artifact_path: Path,
) -> tuple[Path, dict[str, Any]]:
    navigation_artifact_path = Path(navigation_artifact_path)
    navigation = read_json_object(navigation_artifact_path, label="navigation artifact")
    navigation_errors = validate_navigation_smoke_artifact(navigation, require_files=True)
    if navigation_errors:
        raise ValueError("invalid navigation artifact: " + "; ".join(navigation_errors))
    if str(navigation.get("alignment_artifact") or "") != str(alignment_artifact_path):
        raise ValueError("navigation artifact alignment_artifact must match --alignment-artifact")
    if navigation.get("robot_navigation_supported") is not True:
        raise ValueError("navigation artifact must claim robot_navigation_supported=true")
    return navigation_artifact_path, navigation


def _verified_navigation_proof(
    navigation_artifact_path: Path,
    navigation: dict[str, Any],
) -> dict[str, Any]:
    waypoint_evidence = [
        item for item in navigation.get("waypoint_evidence") or [] if isinstance(item, dict)
    ]
    return {
        "status": "robot_navigation_verified",
        "navigation_status": "verified",
        "navigation_artifact": str(navigation_artifact_path),
        "render_scene_usd": str(navigation.get("b1_scene_usd") or ""),
        "visual_route": _dict(navigation.get("visual_route")),
        "robot_navigation_supported": True,
        "robot_navigation_provenance": NAVIGATION_PROVENANCE,
        "navigation_waypoint_count": int(navigation.get("navigation_waypoint_count") or 0),
        "robot_view_evidence_status": str(navigation.get("robot_view_evidence_status") or ""),
        "navigation_provenance": str(navigation.get("navigation_provenance") or ""),
        "same_pose_views": _same_pose_view_support(waypoint_evidence),
        "waypoint_ids": [str(item.get("waypoint_id") or "") for item in waypoint_evidence],
    }


def _same_pose_view_support(waypoint_evidence: list[dict[str, Any]]) -> dict[str, bool]:
    if not waypoint_evidence:
        return {"fpv": False, "chase": False, "topdown": False}

    def has_view(item: dict[str, Any], *view_names: str) -> bool:
        views = item.get("views") if isinstance(item.get("views"), dict) else {}
        return any(bool(views.get(view_name)) for view_name in view_names)

    return {
        "fpv": all(has_view(item, "fpv") for item in waypoint_evidence),
        "chase": all(has_view(item, "chase") for item in waypoint_evidence),
        "topdown": all(has_view(item, "topdown", "map") for item in waypoint_evidence),
    }


def render_observation_proof(robot_consumption_proof: dict[str, Any]) -> dict[str, Any]:
    navigation_ready = bool(robot_consumption_proof.get("robot_navigation_supported"))
    robot_view_ready = (
        str(robot_consumption_proof.get("robot_view_evidence_status") or "") == "available"
    )
    same_pose_views = (
        robot_consumption_proof.get("same_pose_views")
        if isinstance(robot_consumption_proof.get("same_pose_views"), dict)
        else {}
    )
    render_ready = navigation_ready and robot_view_ready
    render_scene_usd = str(robot_consumption_proof.get("render_scene_usd") or "")
    selected_v1_route = render_ready and render_scene_usd == str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD)
    return {
        "schema": "b1_map12_render_observation_proof_v1",
        "status": "same_pose_render_observation_verified"
        if render_ready
        else "blocked_missing_verified_same_pose_render_evidence",
        "render_observation_supported": render_ready,
        "render_provenance": str(robot_consumption_proof.get("robot_navigation_provenance") or ""),
        "navigation_artifact": str(robot_consumption_proof.get("navigation_artifact") or ""),
        "alignment_artifact": str(robot_consumption_proof.get("alignment_artifact") or ""),
        "same_pose_fpv_supported": render_ready and bool(same_pose_views.get("fpv")),
        "same_pose_chase_supported": render_ready and bool(same_pose_views.get("chase")),
        "same_pose_topdown_supported": render_ready and bool(same_pose_views.get("topdown")),
        "view_evidence_status": str(
            robot_consumption_proof.get("robot_view_evidence_status") or ""
        ),
        "default_visual_route": {
            "scene_id": "B1_floor2_slow",
            "scene_root": "data/robot-data-lab/scene-engine/data/B1_floor2_slow",
            "scene_usd": str(DEFAULT_B1_VISUAL_ROUTE_SCENE_USD),
            "selected": selected_v1_route,
            "status": "selected_verified_same_pose_render_route"
            if selected_v1_route
            else "blocked_missing_verified_b1_floor2_slow_render_proof",
            "reason": (
                "B1_floor2_slow has verified same-pose FPV/Chase/topdown render evidence "
                "for the accepted Map12 frame."
                if selected_v1_route
                else (
                    "B1_floor2_slow has not been verified against the accepted Map12 "
                    "frame with same-pose FPV/Chase/topdown render evidence."
                )
            ),
        },
        "policy": {
            "requires_explicit_same_pose_render_artifact": True,
            "does_not_select_unverified_b1_floor2_slow": True,
            "no_output_directory_autodiscovery": True,
        },
    }


def blocked_room_semantic_projection_proof() -> dict[str, Any]:
    return {
        "schema": "b1_map12_room_semantics_proof_v1",
        "status": "base_metric_map_semantics_only",
        "semantic_projection_artifact": "",
        "room_semantics_supported": True,
        "room_projection_count": 0,
        "semantic_anchor_count": 0,
        "object_projection_status": "blocked_until_object_semantic_anchors",
        "object_semantics_supported": False,
        "policy": {
            "uses_base_metric_map_room_labels": True,
            "requires_no_separate_digital_twin_runtime_projection": True,
            "object_labels_are_not_inferred_from_room_anchors": True,
        },
    }


def b1_robot_consumption_manifest(
    *,
    output_dir: Path,
    robot_consumption_proof: dict[str, Any],
    room_semantic_projection_proof: dict[str, Any],
    semantic_label_count: int,
    navigation_area_count: int,
    inspection_waypoint_count: int,
) -> dict[str, Any]:
    navigation_ready = bool(robot_consumption_proof.get("robot_navigation_supported"))
    room_semantics_ready = bool(room_semantic_projection_proof.get("room_semantics_supported"))
    object_semantics_ready = bool(room_semantic_projection_proof.get("object_semantics_supported"))
    return {
        "schema": B1_ROBOT_CONSUMPTION_MANIFEST_SCHEMA,
        "status": "robot_navigation_ready" if navigation_ready else "blocked",
        "map_bundle": str(output_dir),
        "consumer_contract": "base_metric_map_plus_runtime_map_prior_snapshot_v1",
        "required_primary_artifacts": {
            "map_yaml": "map.yaml",
            "occupancy_image": "map.pgm",
            "semantics": "semantics.json",
            "robot_profile": "profiles/rby1m.yaml",
            "costmap_params": "costmaps/rby1m.costmap_params.yaml",
        },
        "optional_product_artifacts": {
            "runtime_map_prior_snapshot": "../runtime_map_prior_snapshot.json",
            "runtime_map_prior_targets": "../runtime_map_prior_targets.json",
        },
        "navigation": {
            "status": robot_consumption_proof.get("status"),
            "ready": navigation_ready,
            "alignment_status": robot_consumption_proof.get("alignment_status"),
            "navigation_status": robot_consumption_proof.get("navigation_status"),
            "alignment_artifact": robot_consumption_proof.get("alignment_artifact"),
            "navigation_artifact": robot_consumption_proof.get("navigation_artifact"),
            "robot_navigation_provenance": robot_consumption_proof.get(
                "robot_navigation_provenance"
            ),
            "navigation_waypoint_count": robot_consumption_proof.get("navigation_waypoint_count"),
            "waypoint_ids": list(robot_consumption_proof.get("waypoint_ids") or []),
        },
        "semantics": {
            "source": "base_metric_map",
            "semantic_label_count": int(semantic_label_count),
            "navigation_area_count": int(navigation_area_count),
            "room_semantics_ready": room_semantics_ready,
            "room_semantic_projection_status": room_semantic_projection_proof.get("status"),
            "semantic_projection_artifact": "",
            "room_projection_count": room_semantic_projection_proof.get("room_projection_count"),
            "object_semantics_ready": object_semantics_ready,
            "object_projection_status": room_semantic_projection_proof.get(
                "object_projection_status"
            ),
        },
        "capabilities": {
            "robot_navigation": navigation_ready,
            "room_semantics": room_semantics_ready,
            "object_semantics": object_semantics_ready,
            "manipulation": bool(robot_consumption_proof.get("manipulation_supported")),
        },
        "blocked_capabilities": _blocked_consumption_capabilities(
            robot_consumption_proof=robot_consumption_proof,
            room_semantic_projection_proof=room_semantic_projection_proof,
        ),
        "inspection_waypoint_count": int(inspection_waypoint_count),
        "policy": {
            "base_metric_map_is_required_source": True,
            "explicit_alignment_artifact_required": True,
            "explicit_navigation_artifact_required": True,
            "no_output_directory_autodiscovery": True,
            "object_labels_are_not_inferred_from_room_anchors": True,
            "does_not_use_navigation_memory_as_waypoint_source": True,
        },
    }


def _blocked_consumption_capabilities(
    *,
    robot_consumption_proof: dict[str, Any],
    room_semantic_projection_proof: dict[str, Any],
) -> list[dict[str, Any]]:
    blocked = []
    if not robot_consumption_proof.get("robot_navigation_supported"):
        blocked.append(
            {
                "capability": "robot_navigation",
                "status": robot_consumption_proof.get("status"),
            }
        )
    if not room_semantic_projection_proof.get("room_semantics_supported"):
        blocked.append(
            {
                "capability": "room_semantics",
                "status": room_semantic_projection_proof.get("status"),
            }
        )
    if not room_semantic_projection_proof.get("object_semantics_supported"):
        blocked.append(
            {
                "capability": "object_semantics",
                "status": room_semantic_projection_proof.get("object_projection_status"),
            }
        )
    if not robot_consumption_proof.get("manipulation_supported"):
        blocked.append(
            {
                "capability": "manipulation",
                "status": robot_consumption_proof.get("object_receptacle_usd_binding_status"),
            }
        )
    return blocked


def sidecar_provenance(
    *,
    base_map_bundle: Path,
    output_dir: Path,
    base_manifest: dict[str, Any],
    robot_consumption_proof: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    source_files = [
        base_map_bundle / "map.yaml",
        base_map_bundle / "map.pgm",
        base_map_bundle / "semantics.json",
        base_map_bundle / "base_metric_map_manifest.json",
    ]
    for field in ("alignment_artifact", "navigation_artifact"):
        artifact = str(robot_consumption_proof.get(field) or "")
        if artifact:
            source_files.append(Path(artifact))
    return {
        "schema": B1_MAP12_BASE_METRIC_SIDECAR_SCHEMA,
        "status": "augmented",
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "sidecar": _repo_relative_path(Path(__file__)),
        "source_assets": {
            "base_map_bundle": str(base_map_bundle),
            "base_metric_map_schema": str(base_manifest.get("schema") or ""),
            "base_metric_map_status": str(base_manifest.get("status") or ""),
        },
        "output_dir": str(output_dir),
        "source_file_hashes": {
            str(path): _file_sha256(path) for path in source_files if path.is_file()
        },
        "robot_consumption_proof": {
            "status": robot_consumption_proof["status"],
            "alignment_artifact": robot_consumption_proof["alignment_artifact"],
            "navigation_artifact": robot_consumption_proof["navigation_artifact"],
            "robot_navigation_supported": robot_consumption_proof["robot_navigation_supported"],
        },
        "validation": validation,
        "policy": {
            "sidecar_only_augments_existing_base_metric_map": True,
            "does_not_generate_rooms_or_waypoints": True,
            "does_not_read_navigation_memory": True,
            "does_not_apply_separate_runtime_semantic_projection": True,
        },
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _repo_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
