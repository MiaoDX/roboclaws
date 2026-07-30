"""Isaac Lab backend runtime support."""

from __future__ import annotations

from typing import Any


def apply_isaac_capture_quality_overrides(
    *,
    settings: Any | None,
    setting_paths: dict[str, dict[str, tuple[str, ...]]],
    capture_quality_fields: dict[str, tuple[str, ...]],
    isaac_aa_op: int | None,
    isaac_tonemap_op: int | None = None,
    isaac_exposure_bias: float | None = None,
    isaac_colorcorr_gain: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    mutation = _initial_mutation()
    if not _has_requested_overrides(
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    ):
        mutation["status"] = "not_requested"
        return mutation
    mutation["settings_mutation_attempted"] = True
    requests = _capture_quality_requests(
        setting_paths=setting_paths,
        capture_quality_fields=capture_quality_fields,
        isaac_aa_op=isaac_aa_op,
        isaac_tonemap_op=isaac_tonemap_op,
        isaac_exposure_bias=isaac_exposure_bias,
        isaac_colorcorr_gain=isaac_colorcorr_gain,
    )
    if settings is None:
        mutation["status"] = "settings_api_unavailable"
        mutation["settings"] = {
            request["key"]: _setting_unavailable_row(
                name=str(request["name"]),
                requested_value=request["requested_value"],
                candidate_paths=tuple(request["candidate_paths"]),
            )
            for request in requests
        }
        return mutation
    for request in requests:
        mutation["settings"][request["key"]] = set_isaac_setting(
            settings,
            tuple(request["candidate_paths"]),
            request["requested_value"],
            name=str(request["name"]),
        )
    _set_mutation_status(mutation)
    return mutation


def restore_isaac_capture_quality_overrides(
    *,
    settings: Any | None,
    mutation: dict[str, Any],
) -> dict[str, Any]:
    if not mutation.get("settings_mutation_attempted"):
        mutation["restore_status"] = "not_needed"
        return mutation
    if settings is None:
        mutation["restore_status"] = "settings_api_unavailable"
        return mutation
    restored_any = False
    failed_any = False
    for row in _dict(mutation.get("settings")).values():
        if not isinstance(row, dict) or row.get("status") != "applied":
            continue
        path = str(row.get("setting_path") or "")
        if not path:
            continue
        try:
            settings.set(path, row.get("previous_value"))
        except Exception as exc:
            row["restore_status"] = "failed"
            row["restore_error"] = str(exc)
            failed_any = True
            continue
        row["restore_status"] = "restored"
        row["restored_value"] = json_safe_setting_value(row.get("previous_value"))
        restored_any = True
    if failed_any:
        mutation["restore_status"] = "restore_failed"
    elif restored_any:
        mutation["restore_status"] = "restored"
    else:
        mutation["restore_status"] = "not_needed"
    return mutation


def set_isaac_setting(
    settings: Any,
    candidate_paths: tuple[str, ...],
    requested_value: Any,
    *,
    name: str,
) -> dict[str, Any]:
    paths = list(candidate_paths)
    for path in candidate_paths:
        try:
            previous_value = settings.get(path)
        except Exception:
            continue
        if previous_value is None:
            continue
        try:
            settings.set(path, requested_value)
        except Exception as exc:
            return {
                "name": name,
                "status": "set_failed",
                "value": json_safe_setting_value(previous_value),
                "previous_value": json_safe_setting_value(previous_value),
                "requested_value": json_safe_setting_value(requested_value),
                "setting_path": path,
                "candidate_paths": paths,
                "default_render_settings_changed": False,
                "error": str(exc),
            }
        try:
            new_value = settings.get(path)
        except Exception:
            new_value = requested_value
        return {
            "name": name,
            "status": "applied",
            "value": json_safe_setting_value(new_value),
            "previous_value": json_safe_setting_value(previous_value),
            "requested_value": json_safe_setting_value(requested_value),
            "setting_path": path,
            "candidate_paths": paths,
            "default_render_settings_changed": True,
        }
    return _setting_unavailable_row(
        name=name,
        requested_value=requested_value,
        candidate_paths=candidate_paths,
    )


def json_safe_setting_value(value: Any) -> Any:
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    if isinstance(value, tuple):
        return [json_safe_setting_value(item) for item in value]
    if isinstance(value, list):
        return [json_safe_setting_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe_setting_value(item) for key, item in value.items()}
    return str(value)


def _initial_mutation() -> dict[str, Any]:
    return {
        "schema": "isaac_capture_quality_settings_mutation_v1",
        "settings_mutation_attempted": False,
        "default_render_settings_changed": False,
        "settings": {},
    }


def _has_requested_overrides(
    *,
    isaac_aa_op: int | None,
    isaac_tonemap_op: int | None,
    isaac_exposure_bias: float | None,
    isaac_colorcorr_gain: tuple[float, float, float] | None,
) -> bool:
    return any(
        item is not None
        for item in (
            isaac_aa_op,
            isaac_tonemap_op,
            isaac_exposure_bias,
            isaac_colorcorr_gain,
        )
    )


def _capture_quality_requests(
    *,
    setting_paths: dict[str, dict[str, tuple[str, ...]]],
    capture_quality_fields: dict[str, tuple[str, ...]],
    isaac_aa_op: int | None,
    isaac_tonemap_op: int | None,
    isaac_exposure_bias: float | None,
    isaac_colorcorr_gain: tuple[float, float, float] | None,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if isaac_aa_op is not None:
        requests.append(
            _request(
                key="anti_aliasing",
                name="anti_aliasing",
                requested_value=int(isaac_aa_op),
                candidate_paths=capture_quality_fields["anti_aliasing"],
            )
        )
    if isaac_tonemap_op is not None:
        requests.append(
            _request(
                key="tonemap_operator",
                name="tonemap_operator",
                requested_value=int(isaac_tonemap_op),
                candidate_paths=setting_paths["tone_mapping"]["operator"],
            )
        )
    if isaac_exposure_bias is not None:
        requests.append(
            _request(
                key="exposure_bias",
                name="exposure_bias",
                requested_value=float(isaac_exposure_bias),
                candidate_paths=setting_paths["tone_mapping"]["exposure_bias"],
            )
        )
    if isaac_colorcorr_gain is not None:
        requests.extend(
            [
                _request(
                    key="colorcorr_enabled",
                    name="colorcorr_enabled",
                    requested_value=True,
                    candidate_paths=setting_paths["color_correction"]["enabled"],
                ),
                _request(
                    key="colorcorr_gain",
                    name="colorcorr_gain",
                    requested_value=list(isaac_colorcorr_gain),
                    candidate_paths=setting_paths["color_correction"]["gain"],
                ),
            ]
        )
    return requests


def _request(
    *,
    key: str,
    name: str,
    requested_value: Any,
    candidate_paths: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "requested_value": requested_value,
        "candidate_paths": candidate_paths,
    }


def _setting_unavailable_row(
    *,
    name: str,
    requested_value: Any,
    candidate_paths: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "not_available",
        "value": None,
        "requested_value": json_safe_setting_value(requested_value),
        "setting_path": "",
        "candidate_paths": list(candidate_paths),
        "default_render_settings_changed": False,
    }


def _set_mutation_status(mutation: dict[str, Any]) -> None:
    statuses = [
        str(row.get("status") or "")
        for row in _dict(mutation.get("settings")).values()
        if isinstance(row, dict)
    ]
    mutation["default_render_settings_changed"] = any(status == "applied" for status in statuses)
    if any(status == "applied" for status in statuses):
        mutation["status"] = "applied"
    elif statuses:
        mutation["status"] = ",".join(statuses)
    else:
        mutation["status"] = "not_available"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
