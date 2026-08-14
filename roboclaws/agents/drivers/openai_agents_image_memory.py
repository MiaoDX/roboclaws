"""Raw-FPV image-memory retention for OpenAI Agents model input."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import re
from typing import Any

from roboclaws.agents.drivers.openai_agents_event_projection import _json_size_bytes, _to_jsonable
from roboclaws.agents.drivers.openai_agents_setting_values import _bool_setting, _positive_int

RAW_FPV_OBSERVATION_ID_RE = re.compile(r"raw_fpv_\d+")
RAW_FPV_RETAINED_JPEG_QUALITY = 75


def _raw_fpv_image_memory_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else {}
    enabled = _bool_setting(config.get("enabled"), "raw_fpv_image_memory.enabled", default=False)
    if enabled:
        retained = _positive_int(
            config.get("retained_full_frame_limit"),
            default=1,
            setting_name="raw_fpv_image_memory.retained_full_frame_limit",
        )
    else:
        retained = 0
    return {
        "schema": "agent_sdk_raw_fpv_image_memory_policy_v1",
        "enabled": enabled,
        "mode": str(config.get("mode") or ("retain_latest_full_frame" if enabled else "off")),
        "retained_full_frame_limit": retained,
        "summary_kind": "raw_fpv_evicted_image_frame_summary_v1",
        "candidate_ids": ["AA"] if enabled else [],
        "private_artifact_policy": (
            "model-facing raw-FPV image memory only; MCP traces, reports, and image artifacts "
            "remain complete"
        ),
    }


def _new_raw_fpv_image_memory_metrics(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_fpv_image_memory_enabled": bool(policy.get("enabled")),
        "raw_fpv_image_memory_mode": str(policy.get("mode") or "off"),
        "raw_fpv_image_retained_limit": int(policy.get("retained_full_frame_limit") or 0),
        "raw_fpv_image_item_count": 0,
        "raw_fpv_image_retained_count": 0,
        "raw_fpv_image_evicted_count": 0,
        "raw_fpv_image_transcoded_count": 0,
        "raw_fpv_image_bytes_before": 0,
        "raw_fpv_image_bytes_after": 0,
        "raw_fpv_image_bytes_reduced": 0,
    }


def _raw_fpv_image_memory_plan(
    items: list[Any],
    policy: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    if not policy.get("enabled"):
        return {}
    candidates = []
    last_observation_id = ""
    for index, item in enumerate(items):
        item_text = json.dumps(_to_jsonable(item), sort_keys=True)
        matches = RAW_FPV_OBSERVATION_ID_RE.findall(item_text)
        if matches:
            last_observation_id = matches[-1]
        info = _raw_fpv_image_info(item)
        if info is not None:
            if not info.get("observation_id"):
                info["observation_id"] = last_observation_id
            candidates.append((index, info))
    retain_limit = int(policy.get("retained_full_frame_limit") or 0)
    retained = {index for index, _info in candidates[-retain_limit:]} if retain_limit > 0 else set()
    return {
        index: {
            **info,
            "retain_full_frame": index in retained,
        }
        for index, info in candidates
    }


def _raw_fpv_image_info(item: Any) -> dict[str, Any] | None:
    payload = _to_jsonable(item)
    if not isinstance(payload, dict):
        return None
    output_key = "output" if "output" in payload else "content" if "content" in payload else ""
    output = payload.get(output_key) if output_key else None
    if isinstance(output, list):
        for content_index, content in enumerate(output):
            if not isinstance(content, dict) or str(content.get("type") or "") not in {
                "image",
                "input_image",
            }:
                continue
            image_url = str(content.get("image_url") or "")
            if not image_url:
                continue
            mime = ""
            if image_url.startswith("data:") and ";base64," in image_url:
                mime = image_url[5:].split(";", 1)[0]
            material = image_url.encode("utf-8")
            text = json.dumps(payload, sort_keys=True)
            matches = RAW_FPV_OBSERVATION_ID_RE.findall(text)
            return {
                "observation_id": matches[-1] if matches else "",
                "mime_type": mime or "image/unknown",
                "format": mime.removeprefix("image/") if mime.startswith("image/") else "",
                "data_bytes": len(material),
                "item_bytes": _json_size_bytes(payload),
                "sha256": hashlib.sha256(material).hexdigest(),
                "nested_output_key": output_key,
                "nested_content_index": content_index,
            }
    data = payload.get("data")
    if isinstance(data, (bytes, bytearray)):
        data_len = len(data)
    else:
        data_text = str(data or "")
        data_len = len(data_text.encode("utf-8")) if data_text else 0
    if data_len <= 0:
        return None
    mime = str(payload.get("_mime_type") or payload.get("mime_type") or payload.get("mime") or "")
    fmt = str(payload.get("_format") or payload.get("format") or "")
    if "image" not in mime and fmt.lower() not in {"png", "jpg", "jpeg", "webp"}:
        return None
    material = json.dumps(payload, sort_keys=True).encode("utf-8")
    text = material.decode("utf-8", errors="ignore")
    matches = RAW_FPV_OBSERVATION_ID_RE.findall(text)
    observation_id = matches[-1] if matches else ""
    return {
        "observation_id": observation_id,
        "mime_type": mime or (f"image/{fmt.lower()}" if fmt else "image/unknown"),
        "format": fmt,
        "data_bytes": data_len,
        "item_bytes": len(material),
        "sha256": hashlib.sha256(material).hexdigest(),
    }


def _raw_fpv_image_memory_candidate(
    item: Any,
    *,
    image_info: dict[str, Any],
    policy: dict[str, Any],
    metrics: dict[str, Any],
) -> tuple[Any | None, str]:
    metrics["raw_fpv_image_item_count"] += 1
    metrics["raw_fpv_image_bytes_before"] += _json_size_bytes(item)
    if image_info.get("retain_full_frame"):
        metrics["raw_fpv_image_retained_count"] += 1
        transcoded = _transcode_retained_raw_fpv_image(item, image_info=image_info)
        if transcoded is not None and _json_size_bytes(transcoded) < _json_size_bytes(item):
            metrics["raw_fpv_image_transcoded_count"] += 1
            metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(transcoded)
            metrics["raw_fpv_image_bytes_reduced"] = max(
                0,
                metrics["raw_fpv_image_bytes_before"] - metrics["raw_fpv_image_bytes_after"],
            )
            return transcoded, "raw_fpv_retained_frame_jpeg"
        metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(item)
        return None, ""
    summary = {
        "schema": "raw_fpv_evicted_image_frame_summary_v1",
        "observation_id": image_info.get("observation_id") or "",
        "mime_type": image_info.get("mime_type") or "",
        "format": image_info.get("format") or "",
        "original_data_bytes": image_info.get("data_bytes") or 0,
        "original_item_bytes": image_info.get("item_bytes") or 0,
        "original_sha256": image_info.get("sha256") or "",
        "retention_policy": {
            "mode": policy.get("mode"),
            "retained_full_frame_limit": policy.get("retained_full_frame_limit"),
        },
        "summary": (
            "Older raw-FPV image frame compacted before this SDK model call. "
            "Use the latest retained frame and current raw-FPV MCP tools for visual work; "
            "Roboclaws trace/report artifacts retain complete image evidence."
        ),
        "private_artifact_policy": policy.get("private_artifact_policy"),
    }
    nested_output_key = str(image_info.get("nested_output_key") or "")
    nested_content_index = image_info.get("nested_content_index")
    if nested_output_key and isinstance(nested_content_index, int):
        candidate = copy.deepcopy(_to_jsonable(item))
        output = candidate.get(nested_output_key) if isinstance(candidate, dict) else None
        if isinstance(output, list) and 0 <= nested_content_index < len(output):
            output[nested_content_index] = {
                "type": "input_text",
                "text": json.dumps(summary, sort_keys=True),
            }
        else:
            candidate = summary
    else:
        candidate = summary
    if _json_size_bytes(candidate) >= _json_size_bytes(item):
        metrics["raw_fpv_image_retained_count"] += 1
        metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(item)
        return None, ""
    metrics["raw_fpv_image_evicted_count"] += 1
    metrics["raw_fpv_image_bytes_after"] += _json_size_bytes(candidate)
    metrics["raw_fpv_image_bytes_reduced"] = max(
        0,
        metrics["raw_fpv_image_bytes_before"] - metrics["raw_fpv_image_bytes_after"],
    )
    return candidate, "raw_fpv_image_memory"


def _transcode_retained_raw_fpv_image(
    item: Any,
    *,
    image_info: dict[str, Any],
) -> Any | None:
    nested_output_key = str(image_info.get("nested_output_key") or "")
    nested_content_index = image_info.get("nested_content_index")
    if not nested_output_key or not isinstance(nested_content_index, int):
        return None
    candidate = copy.deepcopy(_to_jsonable(item))
    output = candidate.get(nested_output_key) if isinstance(candidate, dict) else None
    if not isinstance(output, list) or not 0 <= nested_content_index < len(output):
        return None
    content = output[nested_content_index]
    if not isinstance(content, dict):
        return None
    image_url = str(content.get("image_url") or "")
    if not image_url.startswith("data:image/") or ";base64," not in image_url:
        return None
    header, encoded = image_url.split(",", 1)
    if not header.lower().startswith(("data:image/png;", "data:image/webp;", "data:image/jpeg;")):
        return None
    try:
        from PIL import Image

        source = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(source)) as image:
            rgb = image.convert("RGB")
            destination = io.BytesIO()
            rgb.save(
                destination,
                format="JPEG",
                quality=RAW_FPV_RETAINED_JPEG_QUALITY,
                optimize=True,
            )
    except Exception:
        return None
    jpeg = destination.getvalue()
    if not jpeg or len(jpeg) >= len(source):
        return None
    content["image_url"] = f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode('ascii')}"
    return candidate
