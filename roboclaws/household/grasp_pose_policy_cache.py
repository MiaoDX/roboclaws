from __future__ import annotations

from pathlib import Path
from typing import Any

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.grasp_cache_generation import (
    ensure_molmospaces_assets_symlink,
    generation_asset_result,
    generation_availability_after_install,
    generation_xml_path,
    objects_list_from_generation_preflight,
)
from roboclaws.household.grasp_probe_runtime import (
    PROBE_SCRIPT,
    run_molmospaces_probe_command,
)

GRASP_POSE_POLICY_CACHE_SCHEMA = "molmospaces_grasp_pose_policy_cache_v1"

DEFAULT_APPROACH_SIGN = 1
DEFAULT_APPROACH_DISTANCE = 0.8
DEFAULT_SETTLE_STEPS = 1


def load_initial_contact_result(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="grasp initial-contact result")


def _blocker(code: str, message: str, *, asset_uid: str | None = None) -> dict[str, Any]:
    result = {"code": code, "message": message}
    if asset_uid is not None:
        result["asset_uid"] = asset_uid
    return result


def _blocked_policy(blocker: dict[str, Any]) -> dict[str, Any]:
    return {"status": "blocked", "blockers": [blocker]}


def _blocked_generation_result(output_dir: Path, code: str, message: str) -> dict[str, Any]:
    return _blocked_result(output_dir=output_dir, blockers=[_blocker(code, message)])


def run_grasp_pose_policy_cache_generation(
    *,
    generation_preflight: dict[str, Any],
    output_dir: Path,
    candidate_grasps_path: Path,
    initial_contact_result_path: Path | None = None,
    molmospaces_python: Path | None = None,
    approach_sign: int | None = None,
    approach_distance: float | None = None,
    settle_steps: int | None = None,
    max_candidates: int = 0,
    approach_steps: int = 30,
    post_approach_steps: int = 300,
    close_steps: int = 300,
    timeout_s: float = 900.0,
    install: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if generation_preflight.get("status") != "ready":
        return _blocked_generation_result(
            output_dir,
            "generation_preflight_not_ready",
            "Pose-policy cache generation requires a ready generation preflight.",
        )

    objects = objects_list_from_generation_preflight(generation_preflight)
    if not objects:
        return _blocked_generation_result(
            output_dir,
            "no_generation_objects",
            "Generation preflight did not expose any rigid objects.",
        )

    candidate_grasps_path = Path(candidate_grasps_path).resolve()
    if not dry_run and not candidate_grasps_path.is_file():
        return _blocked_generation_result(
            output_dir,
            "candidate_grasps_missing",
            f"Candidate grasp JSON is missing: {candidate_grasps_path}",
        )

    policy = resolve_pose_policy(
        initial_contact_result_path=initial_contact_result_path,
        approach_sign=approach_sign,
        approach_distance=approach_distance,
        settle_steps=settle_steps,
    )
    if policy.get("status") == "blocked":
        return _blocked_result(output_dir=output_dir, blockers=policy.get("blockers") or [])

    target_object = objects[0]
    object_name = str(target_object["name"])
    xml_path = generation_xml_path(str(target_object["xml"]))
    python = Path(molmospaces_python or generation_preflight.get("molmospaces_python") or "python")
    working_dir = Path(str(generation_preflight.get("working_dir") or ""))
    artifact_dir = (output_dir / "grasp_pose_policy_cache" / object_name).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    generated_npz_path = artifact_dir / f"{object_name}_grasps_filtered.npz"
    probe_script_path = artifact_dir / "pose_policy_cache_probe.py"
    probe_output_path = artifact_dir / "pose_policy_cache_probe_result.json"

    assets_symlink = ensure_molmospaces_assets_symlink(
        generation_preflight,
        working_dir=working_dir,
        dry_run=dry_run,
    )
    command = [
        str(python),
        str(probe_script_path),
        "--object-name",
        object_name,
        "--object-xml",
        str(xml_path),
        "--candidate-grasps",
        str(candidate_grasps_path),
        "--output",
        str(probe_output_path),
        "--cache-output",
        str(generated_npz_path),
        "--max-candidates",
        str(max_candidates),
        "--approach-signs",
        str(policy["approach_sign"]),
        "--approach-distances",
        f"{float(policy['approach_distance']):g}",
        "--settle-steps",
        str(policy["settle_steps"]),
        "--approach-steps",
        str(approach_steps),
        "--post-approach-steps",
        str(post_approach_steps),
        "--close-steps",
        str(close_steps),
    ]
    command_result: dict[str, Any] = {
        "status": "not_run",
        "returncode": "",
        "stdout": "",
        "stderr": "",
    }
    probe_payload: dict[str, Any] = {"candidate_count": 0, "variants": []}
    if not dry_run:
        probe_script_path.write_text(PROBE_SCRIPT, encoding="utf-8")
        command_result = run_molmospaces_probe_command(
            command,
            cwd=working_dir,
            molmospaces_python=python,
            timeout_s=timeout_s,
        )
        if probe_output_path.is_file():
            probe_payload = load_initial_contact_result(probe_output_path)

    asset = {
        **_asset_for_object(generation_preflight, object_name),
        "asset_uid": object_name,
        "generated_npz_path": str(generated_npz_path),
    }
    assets = [
        _dry_run_asset_result(asset, generated_npz_path)
        if dry_run
        else generation_asset_result(asset, install=install)
    ]
    generated_validation = assets[0].get("generated_validation") or {}
    successful_transform_count = int(generated_validation.get("transform_count", 0) or 0)

    blockers = _pose_policy_cache_blockers(
        assets_symlink=assets_symlink,
        command_result=command_result,
        probe_payload=probe_payload,
        generated_validation=generated_validation,
        asset=assets[0],
        object_name=object_name,
        install=install,
        dry_run=dry_run,
    )
    availability_after_install = {}
    if install and not dry_run:
        availability_after_install = generation_availability_after_install(generation_preflight)
        if availability_after_install.get("status") != "ready":
            blockers.append(
                _blocker(
                    "availability_preflight_not_ready_after_install",
                    "Installed grasp cache did not pass availability preflight.",
                )
            )

    status = "dry_run" if dry_run else ("blocked" if blockers else "ready")
    return {
        "schema": GRASP_POSE_POLICY_CACHE_SCHEMA,
        "status": status,
        "ready": status == "ready",
        "output_dir": str(output_dir),
        "object_name": object_name,
        "object_xml": str(xml_path),
        "artifact_dir": str(artifact_dir),
        "candidate_grasps_path": str(candidate_grasps_path),
        "candidate_count": int(probe_payload.get("candidate_count") or 0),
        "max_candidates": max_candidates,
        "pose_policy": policy,
        "assets_symlink": assets_symlink,
        "probe_script_path": str(probe_script_path),
        "probe_output_path": str(probe_output_path),
        "generated_npz_path": str(generated_npz_path),
        "command": command,
        "command_result": command_result,
        "probe_result": probe_payload,
        "assets": assets,
        "asset_count": len(assets),
        "successful_transform_count": successful_transform_count,
        "availability_after_install": availability_after_install,
        "install_requested": install,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "evidence_note": (
            "Generates a MolmoSpaces droid loader NPZ from preserved candidate grasps "
            "using the validated positive-standoff pose policy, then reuses the shared "
            "cache validation and optional install gate."
        ),
    }


def resolve_pose_policy(
    *,
    initial_contact_result_path: Path | None = None,
    approach_sign: int | None = None,
    approach_distance: float | None = None,
    settle_steps: int | None = None,
) -> dict[str, Any]:
    explicit_values = [approach_sign, approach_distance, settle_steps]
    if any(value is not None for value in explicit_values):
        if not all(value is not None for value in explicit_values):
            return _blocked_policy(
                _blocker(
                    "incomplete_explicit_pose_policy",
                    "Explicit pose policy requires approach sign, approach distance, "
                    "and settle steps.",
                )
            )
        return {
            "status": "ready",
            "source": "explicit_cli",
            "name": _policy_name(
                approach_sign=int(approach_sign),
                approach_distance=float(approach_distance),
                settle_steps=int(settle_steps),
            ),
            "approach_sign": int(approach_sign),
            "approach_distance": float(approach_distance),
            "settle_steps": int(settle_steps),
            "source_success_count": "",
        }

    if initial_contact_result_path is not None:
        initial_contact_result_path = Path(initial_contact_result_path)
        if not initial_contact_result_path.is_file():
            return _blocked_policy(
                _blocker(
                    "initial_contact_result_missing",
                    f"Initial-contact result is missing: {initial_contact_result_path}",
                )
            )
        result = load_initial_contact_result(initial_contact_result_path)
        best = result.get("best_variant") or {}
        success_count = int(best.get("success_count") or 0)
        if success_count <= 0:
            return _blocked_policy(
                _blocker(
                    "initial_contact_policy_has_no_successes",
                    "Initial-contact result does not contain a successful best variant.",
                )
            )
        return {
            "status": "ready",
            "source": str(initial_contact_result_path),
            "name": str(best.get("name") or ""),
            "approach_sign": int(best.get("approach_sign")),
            "approach_distance": float(best.get("approach_distance")),
            "settle_steps": int(best.get("settle_steps")),
            "source_success_count": success_count,
        }

    return {
        "status": "ready",
        "source": "phase121_default_positive_standoff",
        "name": _policy_name(
            approach_sign=DEFAULT_APPROACH_SIGN,
            approach_distance=DEFAULT_APPROACH_DISTANCE,
            settle_steps=DEFAULT_SETTLE_STEPS,
        ),
        "approach_sign": DEFAULT_APPROACH_SIGN,
        "approach_distance": DEFAULT_APPROACH_DISTANCE,
        "settle_steps": DEFAULT_SETTLE_STEPS,
        "source_success_count": "",
    }


def _policy_name(*, approach_sign: int, approach_distance: float, settle_steps: int) -> str:
    return f"sign_{approach_sign}_dist_{approach_distance:g}_settle_{settle_steps}"


def _asset_for_object(generation_preflight: dict[str, Any], object_name: str) -> dict[str, Any]:
    for asset in generation_preflight.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        entry = asset.get("objects_list_entry") or {}
        asset_uid = str(asset.get("asset_uid") or entry.get("name") or "")
        if asset_uid == object_name or str(entry.get("name") or "") == object_name:
            return dict(asset)
    return {"asset_uid": object_name}


def _dry_run_asset_result(asset: dict[str, Any], generated_npz_path: Path) -> dict[str, Any]:
    target_path = Path(
        str(asset.get("cache_target_resolved_path") or asset.get("cache_target_path") or "")
    )
    return {
        "asset_uid": str(asset.get("asset_uid") or ""),
        "generated_npz_path": str(generated_npz_path),
        "cache_target_path": str(target_path),
        "generated_validation": {},
        "generated_valid": False,
        "installed_validation_before": {},
        "installed_validation": {},
        "installed_valid": False,
        "installed": False,
    }


def _pose_policy_cache_blockers(
    *,
    assets_symlink: dict[str, Any],
    command_result: dict[str, Any],
    probe_payload: dict[str, Any],
    generated_validation: dict[str, Any],
    asset: dict[str, Any],
    object_name: str,
    install: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if assets_symlink.get("status") == "blocked":
        blockers.append(
            _blocker(
                "molmospaces_assets_symlink_blocked",
                assets_symlink.get("message") or "assets symlink setup failed",
            )
        )
    if command_result.get("status") == "blocked":
        blockers.append(
            _blocker(
                "pose_policy_cache_probe_failed",
                command_result.get("stderr")
                or command_result.get("stdout")
                or "Pose-policy cache probe failed.",
            )
        )
    if probe_payload.get("status") == "blocked":
        blockers.append(
            _blocker(
                "pose_policy_cache_probe_blocked",
                probe_payload.get("error") or "Pose-policy cache probe reported blocked.",
            )
        )
    if dry_run:
        return blockers
    if not generated_validation.get("valid"):
        blockers.append(
            _blocker(
                "pose_policy_cache_invalid",
                "Pose-policy probe did not produce a non-empty loader-compatible NPZ.",
                asset_uid=object_name,
            )
        )
    if install and not asset.get("installed_valid"):
        blockers.append(
            _blocker(
                "installed_grasp_cache_invalid",
                f"Installed grasp cache invalid for {object_name}",
                asset_uid=object_name,
            )
        )
    return blockers


def _blocked_result(*, output_dir: Path, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": GRASP_POSE_POLICY_CACHE_SCHEMA,
        "status": "blocked",
        "ready": False,
        "output_dir": str(output_dir),
        "object_name": "",
        "object_xml": "",
        "artifact_dir": "",
        "candidate_grasps_path": "",
        "candidate_count": 0,
        "max_candidates": 0,
        "pose_policy": {},
        "assets_symlink": {},
        "probe_script_path": "",
        "probe_output_path": "",
        "generated_npz_path": "",
        "command": [],
        "command_result": {},
        "probe_result": {},
        "assets": [],
        "asset_count": 0,
        "successful_transform_count": 0,
        "availability_after_install": {},
        "install_requested": False,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }
