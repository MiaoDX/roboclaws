from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection, Mapping
from typing import Any

from roboclaws.household.types import CleanupScenario

PREFERRED = "preferred"
ACCEPTABLE = "acceptable"
QUESTIONABLE = "questionable"
WRONG = "wrong"
UNKNOWN = "unknown"

ACCEPTED_LEVELS = frozenset({PREFERRED, ACCEPTABLE})
SEMANTIC_LEVELS = (PREFERRED, ACCEPTABLE, QUESTIONABLE, WRONG, UNKNOWN)

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

_OBJECT_ALIASES = {
    "apple": "food",
    "bread": "food",
    "egg": "food",
    "potato": "food",
    "lettuce": "food",
    "food": "food",
    "bowl": "dish",
    "cup": "dish",
    "mug": "dish",
    "plate": "dish",
    "dish": "dish",
    "book": "book",
    "newspaper": "book",
    "pillow": "pillow",
    "teddybear": "pillow",
    "remotecontrol": "remotecontrol",
    "remote": "remotecontrol",
    "electronics": "remotecontrol",
    "linen": "linen",
    "towel": "linen",
    "toy": "toy",
    "toycar": "toy",
}

_RECEPTACLE_ALIASES = {
    "sink": "sink",
    "kitchensink": "sink",
    "counter": "countertop",
    "countertop": "countertop",
    "diningtable": "diningtable",
    "table": "diningtable",
    "fridge": "fridge",
    "refrigerator": "fridge",
    "shelvingunit": "shelvingunit",
    "shelf": "shelvingunit",
    "bookshelf": "shelvingunit",
    "desk": "desk",
    "bed": "bed",
    "sofa": "sofa",
    "couch": "sofa",
    "armchair": "armchair",
    "chair": "armchair",
    "tvstand": "tvstand",
    "stand": "tvstand",
    "coffeetable": "coffeetable",
    "laundryhamper": "laundryhamper",
    "hamper": "laundryhamper",
    "toybin": "toybin",
    "floor": "floor",
}

_RUBRIC = {
    "dish": {
        PREFERRED: frozenset({"sink", "countertop"}),
        ACCEPTABLE: frozenset({"diningtable"}),
        QUESTIONABLE: frozenset({"desk"}),
    },
    "book": {
        PREFERRED: frozenset({"shelvingunit"}),
        ACCEPTABLE: frozenset({"desk"}),
        QUESTIONABLE: frozenset({"bed", "sofa", "coffeetable"}),
    },
    "food": {
        PREFERRED: frozenset({"fridge"}),
        ACCEPTABLE: frozenset({"countertop", "diningtable"}),
        QUESTIONABLE: frozenset({"sink"}),
    },
    "remotecontrol": {
        PREFERRED: frozenset({"tvstand"}),
        ACCEPTABLE: frozenset({"desk", "sofa", "coffeetable"}),
        QUESTIONABLE: frozenset({"bed"}),
    },
    "pillow": {
        PREFERRED: frozenset({"bed"}),
        ACCEPTABLE: frozenset({"sofa", "armchair"}),
        QUESTIONABLE: frozenset({"desk"}),
    },
    "linen": {
        PREFERRED: frozenset({"laundryhamper"}),
        ACCEPTABLE: frozenset({"sink"}),
        QUESTIONABLE: frozenset({"sofa", "armchair", "bed"}),
    },
    "toy": {
        PREFERRED: frozenset({"toybin"}),
        ACCEPTABLE: frozenset({"floor"}),
        QUESTIONABLE: frozenset({"sofa", "coffeetable"}),
    },
}

_SEMANTIC_RANK = {
    WRONG: 0,
    QUESTIONABLE: 1,
    ACCEPTABLE: 2,
    PREFERRED: 3,
}


def annotate_score_with_semantic_acceptability(
    score: Mapping[str, Any],
    scenario: CleanupScenario | Mapping[str, Any],
) -> dict[str, Any]:
    """Annotate private exact-score rows with public semantic acceptability.

    This deliberately does not change ``restored`` or the exact private score.
    The semantic labels are a public-category review aid for judging whether an
    agent found a reasonable placement even when it missed the private target id.
    """
    objects = _objects_by_id(scenario)
    receptacles = _receptacles_by_id(scenario)
    annotated_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter({level: 0 for level in SEMANTIC_LEVELS})

    for row in score.get("object_results", []):
        annotated = dict(row)
        object_id = str(annotated.get("object_id", ""))
        actual_location_id = annotated.get("actual_location_id")
        exact_private_match = bool(annotated.get("restored", False))
        annotated["exact_private_match"] = exact_private_match

        obj = objects.get(object_id)
        receptacle = receptacles.get(str(actual_location_id)) if actual_location_id else None
        object_category = _category_text(obj, "category")
        receptacle_category = _category_text(receptacle, "category")
        if receptacle_category is None:
            receptacle_category = _category_text(receptacle, "name")

        semantic = _assess_semantic_acceptability(obj, receptacle, actual_location_id)
        annotated["object_category"] = object_category or UNKNOWN
        annotated["actual_receptacle_category"] = receptacle_category or UNKNOWN
        annotated["semantic_acceptability"] = semantic["level"]
        annotated["semantic_reason"] = semantic["reason"]
        counts[semantic["level"]] += 1
        annotated_rows.append(annotated)

    annotated_score = dict(score)
    annotated_score["object_results"] = annotated_rows
    accepted_object_ids = [
        str(row.get("object_id", ""))
        for row in annotated_rows
        if row.get("semantic_acceptability") in ACCEPTED_LEVELS
    ]
    total_targets = int(score.get("total_targets") or len(annotated_rows))
    accepted_count = len(accepted_object_ids)
    annotated_score["semantic_acceptability"] = {
        "accepted_count": accepted_count,
        "total_targets": total_targets,
        "accepted_levels": sorted(ACCEPTED_LEVELS),
        "counts": {level: counts[level] for level in SEMANTIC_LEVELS},
        "status": _status_for_semantic_count(
            accepted_count=accepted_count,
            total_targets=total_targets,
            success_threshold=int(score.get("success_threshold") or total_targets),
        ),
        "accepted_object_ids": accepted_object_ids,
        "questionable_object_ids": _object_ids_for_level(annotated_rows, QUESTIONABLE),
        "wrong_object_ids": _object_ids_for_level(annotated_rows, WRONG),
        "unknown_object_ids": _object_ids_for_level(annotated_rows, UNKNOWN),
    }
    return annotated_score


def semantic_disturbance_metrics(
    scenario: CleanupScenario | Mapping[str, Any],
    initial_locations: Mapping[str, str],
    final_locations: Mapping[str, str],
    *,
    excluded_object_ids: Collection[str] = (),
) -> dict[str, int]:
    """Count non-target moves and the subset that made placement semantics worse."""

    objects = _objects_by_id(scenario)
    receptacles = _receptacles_by_id(scenario)
    excluded = {str(item) for item in excluded_object_ids}
    location_change_count = 0
    disturbance_count = 0
    for object_id, initial_location_id in initial_locations.items():
        if object_id in excluded:
            continue
        final_location_id = final_locations.get(object_id)
        if final_location_id in {None, initial_location_id}:
            continue
        location_change_count += 1
        initial_level = _assess_semantic_acceptability(
            objects.get(object_id),
            receptacles.get(str(initial_location_id)),
            initial_location_id,
        )["level"]
        final_level = _assess_semantic_acceptability(
            objects.get(object_id),
            receptacles.get(str(final_location_id)),
            final_location_id,
        )["level"]
        initial_rank = _SEMANTIC_RANK.get(initial_level)
        final_rank = _SEMANTIC_RANK.get(final_level)
        if initial_rank is not None and final_rank is not None and final_rank < initial_rank:
            disturbance_count += 1
    return {
        "disturbance_count": disturbance_count,
        "non_target_location_change_count": location_change_count,
    }


def _assess_semantic_acceptability(
    obj: Mapping[str, Any] | Any | None,
    receptacle: Mapping[str, Any] | Any | None,
    actual_location_id: Any,
) -> dict[str, str]:
    if not actual_location_id:
        return {
            "level": WRONG,
            "reason": "object was not left on a known final location",
        }
    if obj is None:
        return {
            "level": UNKNOWN,
            "reason": "object id is not present in the public scenario",
        }
    if receptacle is None:
        return {
            "level": WRONG,
            "reason": "final location is not a public receptacle",
        }

    object_category = _canonical_object_category(obj)
    receptacle_category = _canonical_receptacle_category(receptacle)
    if object_category is None:
        return {
            "level": UNKNOWN,
            "reason": "object category has no semantic cleanup rubric",
        }
    if receptacle_category is None:
        return {
            "level": UNKNOWN,
            "reason": "receptacle category has no semantic cleanup rubric",
        }

    rule = _RUBRIC.get(object_category)
    if rule is None:
        return {
            "level": UNKNOWN,
            "reason": f"{object_category} has no semantic cleanup rubric",
        }
    for level in (PREFERRED, ACCEPTABLE, QUESTIONABLE):
        if receptacle_category in rule[level]:
            return {
                "level": level,
                "reason": f"{object_category} on {receptacle_category} is {level}",
            }
    return {
        "level": WRONG,
        "reason": f"{object_category} on {receptacle_category} is not a cleanup placement",
    }


def _objects_by_id(
    scenario: CleanupScenario | Mapping[str, Any],
) -> dict[str, Mapping[str, Any] | Any]:
    return {
        str(_field(item, "object_id")): item
        for item in _sequence_field(scenario, "objects")
        if _field(item, "object_id") is not None
    }


def _receptacles_by_id(
    scenario: CleanupScenario | Mapping[str, Any],
) -> dict[str, Mapping[str, Any] | Any]:
    return {
        str(_field(item, "receptacle_id")): item
        for item in _sequence_field(scenario, "receptacles")
        if _field(item, "receptacle_id") is not None
    }


def _sequence_field(source: Mapping[str, Any] | Any, key: str) -> list[Any]:
    if isinstance(source, Mapping):
        value = source.get(key, [])
    else:
        value = getattr(source, key, [])
    return list(value or [])


def _canonical_object_category(item: Mapping[str, Any] | Any) -> str | None:
    for key in ("category", "name", "object_id"):
        alias = _lookup_alias(_OBJECT_ALIASES, _field(item, key))
        if alias is not None:
            return alias
    return None


def _canonical_receptacle_category(item: Mapping[str, Any] | Any) -> str | None:
    for key in ("category", "name", "receptacle_id"):
        alias = _lookup_alias(_RECEPTACLE_ALIASES, _field(item, key))
        if alias is not None:
            return alias
    return None


def _category_text(item: Mapping[str, Any] | Any | None, key: str) -> str | None:
    if item is None:
        return None
    value = _field(item, key)
    if value is None or value == "":
        return None
    return str(value)


def _field(item: Mapping[str, Any] | Any | None, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _normalize(value: Any) -> str:
    return _NORMALIZE_RE.sub("", str(value or "").lower())


def _lookup_alias(aliases: Mapping[str, str], value: Any) -> str | None:
    normalized = _normalize(value)
    if not normalized:
        return None
    exact = aliases.get(normalized)
    if exact is not None:
        return exact
    for key, alias in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if normalized.startswith(key) or key in normalized:
            return alias
    return None


def _object_ids_for_level(rows: list[dict[str, Any]], level: str) -> list[str]:
    return [
        str(row.get("object_id", "")) for row in rows if row.get("semantic_acceptability") == level
    ]


def _status_for_semantic_count(
    *,
    accepted_count: int,
    total_targets: int,
    success_threshold: int,
) -> str:
    if accepted_count >= max(0, success_threshold):
        return "success"
    if accepted_count > 0:
        return "partial_success"
    if total_targets == 0:
        return "success"
    return "failed"
