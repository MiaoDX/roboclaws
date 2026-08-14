from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.generated_mess import GENERATED_MESS_MANIFEST_SCHEMA
from roboclaws.worlds.molmospaces.preparation_io import molmospaces_get_scenes_args


def load_generated_mess_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    manifest = read_json_object(path, label="generated mess manifest")
    if manifest.get("schema") != GENERATED_MESS_MANIFEST_SCHEMA:
        raise ValueError(
            "generated mess manifest schema mismatch: "
            f"{manifest.get('schema')} != {GENERATED_MESS_MANIFEST_SCHEMA}"
        )
    return manifest


def prepare_molmospaces_scene(
    *,
    scene_source: str,
    scene_index: int,
    get_scenes: Callable[..., Any],
    get_scenes_root: Callable[[], Any],
    install_scene_with_objects_and_grasps_from_path: Callable[[Path], Any],
) -> tuple[Path, dict[str, Any]]:
    scene_xml, resolution = resolve_molmospaces_scene_xml(
        scene_source=scene_source,
        scene_index=scene_index,
        get_scenes=get_scenes,
        scenes_root=Path(get_scenes_root()),
    )
    install_scene_with_objects_and_grasps_from_path(scene_xml)
    resolution["install_method"] = "install_scene_with_objects_and_grasps_from_path"
    return scene_xml, resolution


def source_room_labels(scene_xml: Path) -> dict[str, dict[str, str]]:
    scene_json = _source_scene_json_path(scene_xml)
    if scene_json is not None:
        rooms = _source_scene_json_rooms(scene_json)
        labels = {
            room_id: label
            for room in rooms
            for room_id, label in [_source_room_label(room, scene_json)]
        }
        if labels:
            return labels
        raise RuntimeError(f"source scene JSON has no room labels: {scene_json}")
    ithor_label = _ithor_room_label(scene_xml)
    if ithor_label:
        return {
            "room_0": {
                "room_id": "room_0",
                "room_label": ithor_label,
                "room_type": ithor_label,
                "room_label_provenance": "ithor_floorplan_id",
            }
        }
    raise RuntimeError(
        "missing source room labels for "
        f"{scene_xml}; expected adjacent scene JSON with rooms[].roomType"
    )


def resolve_molmospaces_scene_xml(
    *,
    scene_source: str,
    scene_index: int,
    get_scenes: Callable[..., Any],
    scenes_root: Path,
) -> tuple[Path, dict[str, Any]]:
    dataset_name, split = molmospaces_get_scenes_args(scene_source)
    mapping = get_scenes(dataset_name, split)
    if isinstance(mapping, tuple):
        mapping = mapping[0]
    split_mapping = mapping.get(split) if isinstance(mapping, dict) else None
    if not isinstance(split_mapping, dict):
        raise FileNotFoundError(
            f"MolmoSpaces get_scenes({dataset_name!r}, {split!r}) has no {split!r} map"
        )
    if scene_index not in split_mapping:
        raise FileNotFoundError(
            "MolmoSpaces scene index missing from get_scenes map: "
            f"scene_source={scene_source!r} scene_index={scene_index}"
        )
    raw_ref = split_mapping[scene_index]
    scene_xml, ref_role, path_was_relative = scene_xml_path_from_ref(
        raw_ref,
        scenes_root=scenes_root,
    )
    if scene_xml is None:
        raise FileNotFoundError(
            "MolmoSpaces get_scenes ref does not contain a scene XML path: "
            f"scene_source={scene_source!r} scene_index={scene_index} "
            f"raw_ref_type={type(raw_ref).__name__}"
        )
    return scene_xml, {
        "schema": "molmospaces_scene_resolution_v1",
        "scene_source": scene_source,
        "scene_index": scene_index,
        "dataset_name": dataset_name,
        "split": split,
        "raw_ref_type": type(raw_ref).__name__,
        "selected_ref_role": ref_role,
        "path_was_relative": path_was_relative,
        "scene_xml": str(scene_xml),
    }


def _source_scene_json_path(scene_xml: Path) -> Path | None:
    stem = scene_xml.stem
    for suffix in ("_ceiling", "_physics", "_mesh"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    candidates = [scene_xml.with_name(f"{stem}.json"), scene_xml.with_suffix(".json")]
    return next((path for path in candidates if path.is_file()), None)


def _source_scene_json_rooms(scene_json: Path) -> list[dict[str, Any]]:
    try:
        payload = read_json_object(scene_json, label="source scene JSON")
    except ValueError as exc:
        message = str(exc)
        if "must contain valid JSON object" in message:
            raise RuntimeError(f"malformed source scene JSON: {scene_json}") from exc
        if "must contain a JSON object" in message:
            raise RuntimeError(f"source scene JSON must be a JSON object: {scene_json}") from exc
        raise RuntimeError(message.replace("source scene JSON source", "source scene JSON", 1))
    rooms = payload.get("rooms")
    if not isinstance(rooms, list):
        raise RuntimeError(f"source scene JSON rooms must be a JSON array: {scene_json}")
    invalid_room = next((room for room in rooms if not isinstance(room, dict)), None)
    if invalid_room is not None:
        raise RuntimeError(
            "source scene JSON rooms must contain JSON objects: "
            f"{scene_json} entry_type={type(invalid_room).__name__}"
        )
    return rooms


def _source_room_label(room: dict[str, Any], scene_json: Path) -> tuple[str, dict[str, str]]:
    room_id = _source_room_id(str(room.get("id") or ""))
    room_type = str(room.get("roomType") or "").strip()
    if not room_type:
        raise RuntimeError(f"missing roomType for {room_id} in {scene_json}")
    return room_id, {
        "room_id": room_id,
        "room_label": _display_room_label(room_type),
        "room_type": room_type,
        "room_label_provenance": "source_scene_json",
    }


def _source_room_id(raw_id: str) -> str:
    if raw_id.startswith("room_"):
        return raw_id
    if "|" in raw_id:
        raw_id = raw_id.rsplit("|", 1)[1]
    else:
        match = re.match(r"^\D+(\d+)$", raw_id)
        if match:
            raw_id = match.group(1)
    if raw_id.isdigit():
        return f"room_{int(raw_id)}"
    raise RuntimeError(f"unsupported source room id: {raw_id!r}")


def _display_room_label(room_type: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", room_type).strip()


def _ithor_room_label(scene_xml: Path) -> str | None:
    match = re.search(r"FloorPlan(\d+)", scene_xml.stem)
    if not match:
        return None
    floorplan = int(match.group(1))
    if 1 <= floorplan < 200:
        return "Kitchen"
    if 200 <= floorplan < 300:
        return "Living Room"
    if 300 <= floorplan < 400:
        return "Bedroom"
    if 400 <= floorplan < 500:
        return "Bathroom"
    return None


def scene_xml_path_from_ref(
    raw_ref: Any,
    *,
    scenes_root: Path,
) -> tuple[Path | None, str, bool]:
    if isinstance(raw_ref, str | Path):
        path, path_was_relative = normalize_molmospaces_scene_ref_path(
            raw_ref,
            scenes_root=scenes_root,
        )
        if path.suffix == ".xml":
            return path, "path", path_was_relative
        return None, "path", path_was_relative
    if isinstance(raw_ref, dict):
        for role in ("base", "physics", "ceiling"):
            raw_path = raw_ref.get(role)
            path = scene_ref_candidate_xml_path(raw_path, scenes_root=scenes_root)
            if path is not None:
                return path[0], role, path[1]
        for role, raw_path in sorted(raw_ref.items()):
            path = scene_ref_candidate_xml_path(raw_path, scenes_root=scenes_root)
            if path is not None:
                return path[0], str(role), path[1]
    return None, "", False


def scene_ref_candidate_xml_path(
    raw_path: Any,
    *,
    scenes_root: Path,
) -> tuple[Path, bool] | None:
    if raw_path is None:
        return None
    path, path_was_relative = normalize_molmospaces_scene_ref_path(
        raw_path,
        scenes_root=scenes_root,
    )
    if path.suffix != ".xml":
        return None
    return path, path_was_relative


def normalize_molmospaces_scene_ref_path(
    raw_path: Any,
    *,
    scenes_root: Path,
) -> tuple[Path, bool]:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path, False
    return scenes_root / path, True


def scenario_id(*, scene_source: str, scene_index: int, seed: int) -> str:
    source_token = re.sub(r"[^A-Za-z0-9_.-]+", "-", scene_source).strip("-")
    return f"molmospaces-{source_token}-{scene_index}-{seed}"
