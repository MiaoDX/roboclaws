from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from roboclaws.core.json_sources import read_json_object

ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA = "isaac_rby1m_robot_import_plan_v1"
ISAAC_RBY1M_ROBOT_USD_IMPORT_SCHEMA = "isaac_rby1m_robot_usd_import_v1"
ISAAC_RBY1M_ROBOT_USD_PATH = Path("output/isaaclab/robots/rby1m/rby1m_holobase_isaac.usda")
ISAAC_RBY1M_ROBOT_IMPORT_SUMMARY_PATH = Path(
    "output/isaaclab/robots/rby1m/rby1m_holobase_isaac.import_summary.json"
)


def robot_payload(robot_name: str, robot_import: dict[str, Any]) -> dict[str, Any]:
    imported = robot_import.get("status") == "imported"
    return {
        "robot_name": robot_name,
        "embodiment": "rby1m" if imported else "rby1m_head_camera_equivalent",
        "physical_robot": False,
        "planner_backed": False,
        "robot_import_status": robot_import.get("status") if robot_import else "not_requested",
        "robot_usd_path": robot_import.get("usd_path") if robot_import else "",
        "head_camera_prim_path": robot_import.get("head_camera_prim_path") if robot_import else "",
        "robot_mounted_head_camera": imported,
    }


def rby1m_robot_import_plan(
    robot_name: str,
    *,
    robot_usd_path: Path,
    import_summary_path: Path,
    find_urdf: Callable[[], Path | None],
    repo_path: Callable[[Path], Path],
    load_json_if_file: Callable[[Path], dict[str, Any]],
    head_camera_prim: str,
) -> dict[str, Any]:
    if robot_name not in {"rby1m", "rby1"}:
        return {
            "schema": ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA,
            "robot_name": robot_name,
            "status": "unsupported_robot",
            "head_camera_prim_path": "",
            "blockers": [f"unsupported Isaac robot import target: {robot_name}"],
        }
    urdf = find_urdf()
    usd_path = repo_path(robot_usd_path)
    summary_path = repo_path(import_summary_path)
    summary = load_json_if_file(summary_path)
    summary_ready = summary.get("schema") == ISAAC_RBY1M_ROBOT_USD_IMPORT_SCHEMA and (
        summary.get("status") == "ready"
    )
    imported = usd_path.is_file() and summary_ready
    blockers: list[str] = []
    if not urdf:
        blockers.append("RBY1M Isaac URDF not found in MolmoSpaces asset cache.")
    if not imported:
        if not usd_path.is_file():
            blockers.append(f"RBY1M Isaac robot USD import artifact is missing: {usd_path}")
        if not summary_ready:
            blockers.append(f"RBY1M Isaac robot import summary is not ready: {summary_path}")
    return {
        "schema": ISAAC_RBY1M_ROBOT_IMPORT_SCHEMA,
        "robot_name": robot_name,
        "status": "imported"
        if imported
        else ("pending_usd_conversion" if urdf else "missing_urdf"),
        "physical_robot": False,
        "importer": "isaacsim.asset.importer.urdf",
        "source_urdf": str(urdf) if urdf else "",
        "expected_usd_path": str(usd_path),
        "usd_path": str(usd_path) if imported else "",
        "import_summary_path": str(summary_path),
        "stage_prim_path": "/World/robot_0",
        "head_link_name": "link_head_2",
        "head_camera_prim_path": head_camera_prim,
        "head_camera_source": "rby1m_mujoco_robot_0/head_camera_extrinsics_and_fov",
        "head_camera_mounted": imported,
        "head_camera_equivalent": not imported,
        "required_joints": ["base_x", "base_y", "base_theta", "head_0", "head_1"],
        "blockers": blockers,
        "import_summary": summary if summary_ready else {},
        "evidence_note": (
            "Isaac imports the RBY1M holobase URDF to USD, references it at "
            "/World/robot_0, and uses a head_camera prim authored from the MuJoCo "
            "robot_0/head_camera extrinsics/FOV. If the import artifact is absent, "
            "Isaac FPV is reported as a head-camera-equivalent view instead of a "
            "robot-mounted camera."
        ),
    }


def repo_path(path: Path, *, anchor_file: str | Path) -> Path:
    return Path(anchor_file).resolve().parents[2] / path


def load_json_if_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json_object(path, label="Isaac robot import summary")
    except (OSError, ValueError):
        return {}


def find_rby1m_isaac_urdf() -> Path | None:
    candidates: list[Path] = []
    env_root = os.environ.get("MLSPACES_ASSETS_DIR")
    if env_root:
        candidates.append(
            Path(env_root).expanduser()
            / "robots"
            / "rby1m"
            / "curobo_config"
            / "urdf"
            / "model_holobase_isaac"
            / "model_holobase_isaac.urdf"
        )
    candidates.extend(
        (Path.home() / ".cache" / "molmospaces" / "assets").glob(
            "*/robots/rby1m/curobo_config/urdf/model_holobase_isaac/model_holobase_isaac.urdf"
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
