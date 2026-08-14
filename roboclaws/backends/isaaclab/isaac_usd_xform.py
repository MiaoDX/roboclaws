"""Isaac Lab backend runtime support."""

from __future__ import annotations

from typing import Any


def set_usd_xform_translate(
    *,
    UsdGeom: Any,
    Gf: Any,
    prim: Any,
    translate: tuple[float, float, float],
) -> dict[str, str]:
    value = Gf.Vec3d(*translate)
    xformable_type = getattr(UsdGeom, "Xformable", None)
    if callable(xformable_type):
        xformable = xformable_type(prim)
        ordered_ops = _ordered_xform_ops(xformable)
        existing = _set_existing_named_translate(ordered_ops, value)
        if existing is not None:
            return existing
        existing = _set_existing_type_translate(ordered_ops, UsdGeom=UsdGeom, value=value)
        if existing is not None:
            return existing
        added = _set_added_translate_op(xformable, value)
        if added is not None:
            return added

    common_api_type = getattr(UsdGeom, "XformCommonAPI", None)
    if callable(common_api_type):
        result = common_api_type(prim).SetTranslate(value)
        if result is False:
            raise RuntimeError("USD XformCommonAPI refused xformOp:translate value")
        return {"method": "xform_common_api", "xform_op": "xform_common_api"}
    raise RuntimeError("USD prim has no translate-authoring API")


def _ordered_xform_ops(xformable: Any) -> list[Any]:
    try:
        return list(xformable.GetOrderedXformOps())
    except Exception:
        return []


def _set_existing_named_translate(ordered_ops: list[Any], value: Any) -> dict[str, str] | None:
    for op in ordered_ops:
        get_name = getattr(op, "GetOpName", None)
        if callable(get_name) and str(get_name()) == "xformOp:translate":
            _set_xform_op_value(op, value)
            return {"method": "existing_xformOp_translate", "xform_op": str(get_name())}
    return None


def _set_existing_type_translate(
    ordered_ops: list[Any],
    *,
    UsdGeom: Any,
    value: Any,
) -> dict[str, str] | None:
    type_translate = getattr(getattr(UsdGeom, "XformOp", None), "TypeTranslate", None)
    if type_translate is None:
        return None
    for op in ordered_ops:
        get_type = getattr(op, "GetOpType", None)
        is_inverse = getattr(op, "IsInverseOp", None)
        if not (callable(get_type) and get_type() == type_translate):
            continue
        if callable(is_inverse) and is_inverse():
            continue
        get_name = getattr(op, "GetOpName", None)
        op_name = str(get_name()) if callable(get_name) else "translate"
        _set_xform_op_value(op, value)
        return {"method": "existing_translate_op", "xform_op": op_name}
    return None


def _set_added_translate_op(xformable: Any, value: Any) -> dict[str, str] | None:
    add_translate_op = getattr(xformable, "AddTranslateOp", None)
    if not callable(add_translate_op):
        return None
    op = add_translate_op()
    _set_xform_op_value(op, value)
    get_name = getattr(op, "GetOpName", None)
    op_name = str(get_name()) if callable(get_name) else "xformOp:translate"
    return {"method": "added_xformOp_translate", "xform_op": op_name}


def _set_xform_op_value(op: Any, value: Any) -> None:
    set_value = getattr(op, "Set", None)
    if not callable(set_value):
        raise RuntimeError("USD translate op does not expose Set")
    result = set_value(value)
    if result is False:
        raise RuntimeError("USD translate op refused authored value")
