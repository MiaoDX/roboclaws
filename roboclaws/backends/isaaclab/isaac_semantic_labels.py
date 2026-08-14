"""Isaac Lab backend runtime support."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

type TargetPrimResolver = Callable[[Any], list[Any]]


def apply_scene_index_semantic_labels(
    *,
    stage_utils: Any,
    sim_utils: Any,
    scene_index_diagnostics: dict[str, Any] | None,
    target_prim_resolver: TargetPrimResolver | None = None,
) -> dict[str, Any]:
    get_current_stage = getattr(stage_utils, "get_current_stage", None)
    add_labels = getattr(sim_utils, "add_labels", None)
    if not callable(get_current_stage) or not callable(add_labels):
        return _unavailable_semantic_label_application(
            "Isaac semantic label utilities were unavailable."
        )
    stage = get_current_stage()
    if stage is None:
        return _unavailable_semantic_label_application(
            "No current Isaac stage was available for semantic labels."
        )
    state = _SemanticLabelApplication()
    resolver = target_prim_resolver or semantic_label_target_prims
    for raw_entry in _scene_index_entries(scene_index_diagnostics):
        state.process_entry(
            raw_entry,
            stage=stage,
            add_labels=add_labels,
            target_prim_resolver=resolver,
        )
    return state.payload()


def semantic_label_target_prims(prim: Any) -> list[Any]:
    try:
        from pxr import Usd, UsdGeom
    except Exception:
        return [prim]

    targets = _semantic_label_target_prims_once(prim, Usd=Usd, UsdGeom=UsdGeom)
    if any(_prim_is_gprim(target, UsdGeom=UsdGeom) for target in targets):
        return targets
    try:
        prim.Load()
    except Exception:
        return targets
    return _semantic_label_target_prims_once(prim, Usd=Usd, UsdGeom=UsdGeom)


def semantic_label_application_not_requested() -> dict[str, Any]:
    return {
        "schema": "isaac_scene_index_semantic_label_application_v1",
        "status": "not_requested",
        "applied_count": 0,
        "labeled_prim_count": 0,
        "descendant_label_count": 0,
        "gprim_label_count": 0,
        "mesh_label_count": 0,
        "failed_count": 0,
        "missing_prim_count": 0,
        "requested_prim_count": 0,
        "failed": [],
        "target_samples": [],
        "label_instances": [],
        "reason": "Segmentation was not requested.",
    }


class _SemanticLabelApplication:
    def __init__(self) -> None:
        self.applied = 0
        self.labeled_prim_count = 0
        self.descendant_label_count = 0
        self.gprim_label_count = 0
        self.mesh_label_count = 0
        self.missing = 0
        self.failed: list[dict[str, str]] = []
        self.target_samples: list[dict[str, str]] = []
        self.requested_count = 0

    def process_entry(
        self,
        raw_entry: Any,
        *,
        stage: Any,
        add_labels: Callable[..., None],
        target_prim_resolver: TargetPrimResolver,
    ) -> None:
        self.requested_count += 1
        entry = _dict(raw_entry)
        prim_path = str(entry.get("usd_prim_path") or "")
        if not prim_path:
            return
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            self.missing += 1
            return
        labels = _scene_index_semantic_labels(entry, prim_path)
        try:
            self._label_targets(
                source_prim=prim,
                source_prim_path=prim_path,
                labels=labels,
                add_labels=add_labels,
                targets=target_prim_resolver(prim),
            )
            self.applied += 1
        except Exception as exc:  # pragma: no cover - defensive around Isaac extension APIs
            self.failed.append({"prim_path": prim_path, "error": str(exc)})

    def _label_targets(
        self,
        *,
        source_prim: Any,
        source_prim_path: str,
        labels: dict[str, str],
        add_labels: Callable[..., None],
        targets: list[Any],
    ) -> None:
        for target in targets:
            for instance_name, label in labels.items():
                add_labels(target, labels=[label], instance_name=instance_name, overwrite=True)
            self.labeled_prim_count += 1
            if target != source_prim:
                self.descendant_label_count += 1
            self._record_classification(source_prim_path, target)

    def _record_classification(self, source_prim_path: str, target: Any) -> None:
        classification = _semantic_label_target_classification(target)
        if classification["is_gprim"]:
            self.gprim_label_count += 1
        if classification["type_name"] == "Mesh":
            self.mesh_label_count += 1
        if len(self.target_samples) >= 20:
            return
        self.target_samples.append(
            {
                "source_prim_path": source_prim_path,
                "target_prim_path": classification["path"],
                "target_type": classification["type_name"],
                "target_kind": classification["kind"],
            }
        )

    def payload(self) -> dict[str, Any]:
        return {
            "schema": "isaac_scene_index_semantic_label_application_v1",
            "status": self._status(),
            "applied_count": self.applied,
            "labeled_prim_count": self.labeled_prim_count,
            "descendant_label_count": self.descendant_label_count,
            "gprim_label_count": self.gprim_label_count,
            "mesh_label_count": self.mesh_label_count,
            "failed_count": len(self.failed),
            "missing_prim_count": self.missing,
            "requested_prim_count": self.requested_count,
            "failed": self.failed[:10],
            "target_samples": self.target_samples,
            "label_instances": ["class", "kind", "usd_prim_path"],
            "reason": (
                "Scene-index USD prims were labeled for Isaac camera segmentation."
                if self.applied
                else "No scene-index USD prims were labeled for Isaac camera segmentation."
            ),
        }

    def _status(self) -> str:
        if self.applied and not self.failed:
            return "applied"
        if self.applied:
            return "partial"
        return "unavailable"


def _unavailable_semantic_label_application(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "applied_count": 0,
        "failed_count": 0,
        "missing_prim_count": 0,
        "gprim_label_count": 0,
        "mesh_label_count": 0,
        "target_samples": [],
        "reason": reason,
    }


def _scene_index_entries(scene_index_diagnostics: dict[str, Any] | None) -> list[Any]:
    index = _dict(scene_index_diagnostics)
    return [
        *(_dict(index.get("object_index")).values()),
        *(_dict(index.get("receptacle_index")).values()),
    ]


def _semantic_label_target_classification(prim: Any) -> dict[str, Any]:
    try:
        from pxr import UsdGeom
    except Exception:
        UsdGeom = None

    try:
        path = str(prim.GetPath())
    except Exception:
        path = str(getattr(prim, "path", "") or "")
    try:
        type_name = str(prim.GetTypeName() or "")
    except Exception:
        type_name = str(getattr(prim, "type_name", "") or "")
    is_gprim = False
    if UsdGeom is not None:
        try:
            is_gprim = bool(prim.IsA(UsdGeom.Gprim))
        except Exception:
            is_gprim = False
    if not is_gprim and type_name in {"Mesh", "Cube", "Sphere", "Capsule", "Cone", "Cylinder"}:
        is_gprim = True
    kind = "gprim" if is_gprim else "prim"
    if type_name:
        kind = f"{kind}:{type_name}"
    return {
        "path": path,
        "type_name": type_name,
        "kind": kind,
        "is_gprim": is_gprim,
    }


def _semantic_label_target_prims_once(prim: Any, *, Usd: Any, UsdGeom: Any) -> list[Any]:
    targets = [prim]
    for descendant in Usd.PrimRange(prim):
        if descendant == prim:
            continue
        if _prim_is_gprim(descendant, UsdGeom=UsdGeom):
            targets.append(descendant)
    return targets


def _prim_is_gprim(prim: Any, *, UsdGeom: Any) -> bool:
    try:
        return bool(prim.IsA(UsdGeom.Gprim))
    except Exception:
        return False


def _scene_index_semantic_labels(entry: dict[str, Any], prim_path: str) -> dict[str, str]:
    category = str(entry.get("category") or entry.get("public_label") or Path(prim_path).name)
    kind = str(entry.get("kind") or "scene_prim")
    return {
        "class": category,
        "kind": kind,
        "usd_prim_path": prim_path,
    }


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
