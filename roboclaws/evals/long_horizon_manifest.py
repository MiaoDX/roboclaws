"""Private generated-mess manifests for long-horizon eval fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roboclaws.evals.models import EvalSample
from roboclaws.household.generated_mess import (
    GENERATED_MESS_MANIFEST_SCHEMA,
    generated_mess_success_threshold,
    receptacle_prefers_inside,
)


def generated_mess_manifest(sample: EvalSample, spec: Any) -> dict[str, Any]:
    """Build a private backend fixture manifest from a long-horizon task spec."""

    if not spec.target_object_ids:
        raise ValueError("long-horizon generated mess manifest requires target_object_ids")
    if not spec.accepted_destination_ids:
        raise ValueError("long-horizon generated mess manifest requires accepted_destination_ids")
    if not spec.source_receptacle_ids:
        raise ValueError("long-horizon generated mess manifest requires source_receptacle_ids")

    targets = [
        _manifest_target(spec, object_id=object_id, placement_index=index)
        for index, object_id in enumerate(spec.target_object_ids)
    ]
    return {
        "schema": GENERATED_MESS_MANIFEST_SCHEMA,
        "provenance": "long_horizon_task_private_goal_reference",
        "scene": {
            "scene_source": _scene_source_from_sample(sample),
            "scene_index": _scene_index_from_sample(sample),
            "scene_metadata_source": "long_horizon_task_spec",
        },
        "selection": {
            "selector": "roboclaws.evals.long_horizon_manifest.generated_mess_manifest",
            "task_id": spec.task_id,
            "sample_id": sample.sample_id,
            "seed": sample.seed,
        },
        "requested_generated_mess_count": len(targets),
        "generated_mess_count": len(targets),
        "success_threshold": generated_mess_success_threshold(len(targets)),
        "targets": targets,
    }


def write_generated_mess_manifest(sample: EvalSample, spec: Any, path: Path) -> Path:
    manifest = generated_mess_manifest(sample, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _manifest_target(spec: Any, *, object_id: str, placement_index: int) -> dict[str, Any]:
    start_receptacle_id = spec.source_receptacle_ids[
        placement_index % len(spec.source_receptacle_ids)
    ]
    return {
        "object_id": object_id,
        "category": _category_from_id(object_id),
        "target_receptacle_id": _selected_destination_id(
            spec,
            cold=object_id in spec.cold_object_ids,
        ),
        "valid_receptacle_ids": list(spec.accepted_destination_ids),
        "start_receptacle_id": start_receptacle_id,
        "relation": _relation_for_receptacle(start_receptacle_id),
        "placement_index": placement_index,
    }


def _selected_destination_id(spec: Any, *, cold: bool) -> str:
    if cold:
        for destination_id in spec.accepted_destination_ids:
            if "fridge" in destination_id.lower() or "refrigerator" in destination_id.lower():
                return destination_id
    for destination_id in spec.accepted_destination_ids:
        if not ("fridge" in destination_id.lower() or "refrigerator" in destination_id.lower()):
            return destination_id
    return spec.accepted_destination_ids[0]


def _relation_for_receptacle(receptacle_id: str) -> str:
    pseudo_receptacle = {
        "receptacle_id": receptacle_id,
        "category": _category_from_id(receptacle_id),
    }
    return "inside" if receptacle_prefers_inside(pseudo_receptacle) else "on"


def _category_from_id(value: str) -> str:
    prefix = str(value).split("_", 1)[0]
    return prefix[:1].upper() + prefix[1:] if prefix else ""


def _scene_source_from_sample(sample: EvalSample) -> str:
    value = (sample.launch_overrides or {}).get("scene_source", "procthor-10k-val")
    return str(value)


def _scene_index_from_sample(sample: EvalSample) -> int:
    value = (sample.launch_overrides or {}).get("scene_index", 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value)
    return 0
