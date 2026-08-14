from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from roboclaws.maps.b1_alignment_contract import ALIGNMENT_ANCHOR_ROLE


def render_review_report(
    packet: dict[str, Any],
    *,
    output_dir: Path,
    packet_path: Path,
    correspondences_path: Path,
) -> str:
    anchor_rows = "".join(
        render_anchor_row(row, output_dir=output_dir) for row in packet["anchors"]
    )
    packet_href = escape(relative_href(output_dir, packet_path))
    manifest_href = escape(relative_href(output_dir, correspondences_path))
    picker_html = render_picker_section(packet, output_dir=output_dir)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>B1 / Map 12 Correspondence Review</title>
  <style>
    :root {{
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      color: #17202a;
      background: #fff;
      --line: #d8dee6;
      --muted: #5d6b7a;
      --panel: #f7f8fa;
      --warn: #8a5a00;
      --accent: #0b6bcb;
      --ok: #16794c;
    }}
    body {{ margin: 0; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px 24px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; line-height: 1.15; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; letter-spacing: 0; }}
    p {{ color: var(--muted); line-height: 1.5; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      margin: 18px 0;
    }}
    .summary div {{
      padding: 12px 14px;
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }}
    .summary dt {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .summary dd {{ margin: 0; font-weight: 650; overflow-wrap: anywhere; }}
    .notice {{
      border: 1px solid #e3c075;
      background: #fff8e8;
      border-radius: 8px;
      padding: 12px 14px;
      color: #5b3e00;
    }}
    .preview {{
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #101820;
    }}
    .picker-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      align-items: start;
      margin-top: 14px;
    }}
    .picker-panel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }}
    .picker-panel h3 {{
      margin: 0;
      padding: 10px 12px;
      font-size: 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    .image-stage {{
      position: relative;
      min-height: 260px;
      background: #101820;
      overflow: auto;
    }}
    .image-stage img {{
      display: block;
      width: 100%;
      height: auto;
      image-rendering: pixelated;
      cursor: crosshair;
    }}
    .pick-marker {{
      position: absolute;
      width: 14px;
      height: 14px;
      margin-left: -7px;
      margin-top: -7px;
      border: 2px solid #fff;
      border-radius: 50%;
      box-shadow: 0 0 0 2px var(--accent);
      background: var(--accent);
      pointer-events: none;
    }}
    .pick-marker.scene {{
      box-shadow: 0 0 0 2px var(--ok);
      background: var(--ok);
    }}
    .pick-readout {{
      min-height: 54px;
      padding: 10px 12px;
      border-top: 1px solid var(--line);
      background: #fff;
      color: #29333d;
      font-size: 12px;
    }}
    .pick-form {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .pick-form label {{
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 12px;
    }}
    .pick-form input,
    .pick-form select {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      font: inherit;
      font-size: 13px;
      background: #fff;
      color: #17202a;
    }}
    .pick-form .wide {{ grid-column: span 2; }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-top: 10px;
    }}
    button {{
      border: 1px solid #96adc5;
      border-radius: 6px;
      padding: 8px 11px;
      background: #fff;
      color: #17202a;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }}
    button.primary {{
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }}
    .draft-output {{
      margin-top: 12px;
      width: 100%;
      min-height: 150px;
      box-sizing: border-box;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      color: #17202a;
      background: #fff;
    }}
    table {{ width: 100%; border-collapse: collapse; border: 1px solid var(--line); }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 10px;
      border-bottom: 1px solid var(--line);
    }}
    th {{ background: var(--panel); color: #39424e; font-size: 12px; }}
    td {{ font-size: 13px; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    .warn {{ color: var(--warn); font-weight: 700; }}
    @media (max-width: 720px) {{
      main {{ padding: 22px 16px 36px; }}
      .picker-grid {{ grid-template-columns: 1fr; }}
      .pick-form {{ grid-template-columns: 1fr; }}
      .pick-form .wide {{ grid-column: span 1; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
<main>
  <h1>B1 / Map 12 Correspondence Review</h1>
  <p>Operator review packet for map-scene correspondence anchors before residual fitting.</p>
  <section class="summary">
    {summary_rows(packet)}
  </section>
  <div class="notice">{escape(str(packet["known_poor_seed_rule"]))}</div>
  <h2>Two-Map Anchor Picker</h2>
  {picker_html}
  <h2>Anchors</h2>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Status</th><th>Map Pick</th><th>Scene Pick</th>
        <th>Area / Partition</th><th>Evidence</th><th>Action</th>
      </tr>
    </thead>
    <tbody>{anchor_rows}</tbody>
  </table>
  <h2>Artifacts</h2>
  <p><a href="{packet_href}">correspondence_review_packet.json</a></p>
  <p><a href="{manifest_href}">source correspondence manifest</a></p>
</main>
</body>
</html>
"""


def render_picker_section(packet: dict[str, Any], *, output_dir: Path) -> str:
    source_map = packet.get("source_map") if isinstance(packet.get("source_map"), dict) else {}
    scene = packet.get("scene_topdown") if isinstance(packet.get("scene_topdown"), dict) else {}
    map_image = str(source_map.get("image") or "")
    scene_image = str(scene.get("image") or "")
    scene_policy = (
        scene.get("pixel_to_scene_xyz") if isinstance(scene.get("pixel_to_scene_xyz"), dict) else {}
    )
    map_img = picker_image_html(
        output_dir=output_dir,
        image=map_image,
        image_id="mapImage",
        alt="Map12 occupancy map",
    )
    scene_img = picker_image_html(
        output_dir=output_dir,
        image=scene_image,
        image_id="sceneImage",
        alt="B1 Gaussian scene top-down render",
    )
    return f"""
  <p>
    Pick one point on Map12 and one corresponding point on the rendered Gaussian scene top-down,
    then export a draft manifest. Draft anchors default to proposed review status.
  </p>
  <div class="notice">{escape(str(scene_policy.get("note") or ""))}</div>
  <div class="picker-grid" id="two-map-anchor-picker">
    <section class="picker-panel">
      <h3>Map12 Source Map</h3>
      <div class="image-stage" id="mapStage">
        {map_img}
        <span id="mapMarker" class="pick-marker" hidden></span>
      </div>
      <div class="pick-readout" id="mapReadout">No map pick.</div>
    </section>
    <section class="picker-panel">
      <h3>B1 Gaussian Scene Top-Down</h3>
      <div class="image-stage" id="sceneStage">
        {scene_img}
        <span id="sceneMarker" class="pick-marker scene" hidden></span>
      </div>
      <div class="pick-readout" id="sceneReadout">No scene top-down pick.</div>
    </section>
  </div>
  <div class="pick-form">
    <label>Anchor ID<input id="anchorId" value="anchor_001" /></label>
    <label>Anchor Type<input id="anchorType" value="operator_correspondence" /></label>
    <label>Navigation Area<input id="navigationAreaId" placeholder="map area id" /></label>
    <label>Scene Partition<input id="assetPartitionId" placeholder="partition id" /></label>
    <label>Status
      <select id="reviewStatus">
        <option value="proposed" selected>proposed</option>
        <option value="accepted">accepted</option>
      </select>
    </label>
    <label class="wide">
      Evidence Note<input id="operatorNote" placeholder="why these points correspond" />
    </label>
    <div class="actions">
      <button class="primary" type="button" id="addAnchorButton">Add Draft Anchor</button>
      <button type="button" id="downloadButton">Download Manifest JSON</button>
      <button type="button" id="resetButton">Reset Draft</button>
    </div>
  </div>
  <div class="pick-readout">
    Rendered Gaussian scene picks may be accepted after operator review.
  </div>
  <textarea class="draft-output" id="draftOutput" readonly></textarea>
  <script id="reviewPacketData" type="application/json">{script_json(packet)}</script>
  <script>
{picker_javascript()}
  </script>
"""


def picker_image_html(*, output_dir: Path, image: str, image_id: str, alt: str) -> str:
    if not image:
        return f'<p class="pick-readout">{escape(alt)} image missing.</p>'
    href = escape(relative_href(output_dir, Path(image)))
    return f'<img id="{escape(image_id)}" src="{href}" alt="{escape(alt)}" />'


def script_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True)
    return payload.replace("</", "<\\/")


def picker_javascript() -> str:
    return r"""
const packet = JSON.parse(document.getElementById("reviewPacketData").textContent);
const draftManifest = JSON.parse(JSON.stringify(packet.export_manifest_template || {}));
draftManifest.anchors = Array.isArray(draftManifest.anchors) ? draftManifest.anchors : [];
let currentMapPick = null;
let currentScenePick = null;

function imageRelativePixel(event, image) {
  const rect = image.getBoundingClientRect();
  const scaleX = image.naturalWidth / rect.width;
  const scaleY = image.naturalHeight / rect.height;
  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  };
}

function placeMarker(markerId, stageId, image, pixel) {
  const marker = document.getElementById(markerId);
  const stageRect = document.getElementById(stageId).getBoundingClientRect();
  const imageRect = image.getBoundingClientRect();
  const markerLeft = imageRect.left - stageRect.left
    + (pixel.x / image.naturalWidth) * imageRect.width;
  const markerTop = imageRect.top - stageRect.top
    + (pixel.y / image.naturalHeight) * imageRect.height;
  marker.style.left = `${markerLeft}px`;
  marker.style.top = `${markerTop}px`;
  marker.hidden = false;
}

function mapPixelToMapXY(pixel) {
  const sourceMap = packet.source_map || {};
  const transform = sourceMap.pixel_to_map_xy || {};
  const resolution = Number(transform.resolution_m || 0.05);
  const originX = Number(transform.origin_x || 0);
  const originY = Number(transform.origin_y || 0);
  const yaw = Number(transform.origin_yaw_rad || 0);
  const height = Number(sourceMap.height_px || 0);
  const gridX = pixel.x * resolution;
  const gridY = (height - pixel.y) * resolution;
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);
  return [
    round6(originX + cosYaw * gridX - sinYaw * gridY),
    round6(originY + sinYaw * gridX + cosYaw * gridY),
  ];
}

function scenePixelToSceneXYZ(pixel) {
  const policy = (packet.scene_topdown || {}).pixel_to_scene_xyz || {};
  const eye = vector3(policy.eye);
  const target = vector3(policy.target);
  const width = Number(policy.width_px);
  const height = Number(policy.height_px);
  const fov = Number(policy.vertical_fov_deg);
  const zPlane = Number(policy.z_plane || 0);
  if (!eye || !target || ![width, height, fov, zPlane].every(Number.isFinite)) {
    throw new Error("Scene top-down packet is missing ray-plane transform.");
  }
  const forward = normalize([
    target[0] - eye[0],
    target[1] - eye[1],
    target[2] - eye[2],
  ]);
  const worldUp = [0, 0, 1];
  let right = normalize(cross(forward, worldUp));
  if (!right) right = [1, 0, 0];
  const up = normalize(cross(right, forward));
  const aspect = width / height;
  const tanY = Math.tan((fov * Math.PI / 180) / 2);
  const ndcX = ((pixel.x + 0.5) / width) * 2 - 1;
  const ndcY = 1 - ((pixel.y + 0.5) / height) * 2;
  const direction = normalize([
    forward[0] + right[0] * ndcX * aspect * tanY + up[0] * ndcY * tanY,
    forward[1] + right[1] * ndcX * aspect * tanY + up[1] * ndcY * tanY,
    forward[2] + right[2] * ndcX * aspect * tanY + up[2] * ndcY * tanY,
  ]);
  if (!direction || Math.abs(direction[2]) < 1e-9) {
    throw new Error("Scene top-down ray does not intersect z plane.");
  }
  const t = (zPlane - eye[2]) / direction[2];
  return [round6(eye[0] + direction[0] * t), round6(eye[1] + direction[1] * t), round6(zPlane)];
}

function vector3(value) {
  if (!Array.isArray(value) || value.length < 3) return null;
  const parsed = [Number(value[0]), Number(value[1]), Number(value[2])];
  return parsed.every(Number.isFinite) ? parsed : null;
}

function cross(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function normalize(value) {
  const length = Math.hypot(value[0], value[1], value[2]);
  if (!Number.isFinite(length) || length <= 1e-9) return null;
  return [value[0] / length, value[1] / length, value[2] / length];
}

function round6(value) {
  return Math.round(Number(value) * 1000000) / 1000000;
}

function onMapPick(event) {
  if (!event.currentTarget.naturalWidth) return;
  const pixel = imageRelativePixel(event, event.currentTarget);
  currentMapPick = {pixel, map_xy: mapPixelToMapXY(pixel)};
  placeMarker("mapMarker", "mapStage", event.currentTarget, pixel);
  const mapPickJson = JSON.stringify(currentMapPick.map_xy);
  document.getElementById("mapReadout").textContent =
    `pixel=(${round6(pixel.x)}, ${round6(pixel.y)}) map_xy=${mapPickJson}`;
}

function onScenePick(event) {
  if (!event.currentTarget.naturalWidth) return;
  const pixel = imageRelativePixel(event, event.currentTarget);
  currentScenePick = {pixel, scene_xyz: scenePixelToSceneXYZ(pixel)};
  placeMarker("sceneMarker", "sceneStage", event.currentTarget, pixel);
  const scenePickJson = JSON.stringify(currentScenePick.scene_xyz);
  document.getElementById("sceneReadout").textContent =
    `pixel=(${round6(pixel.x)}, ${round6(pixel.y)}) scene_xyz=${scenePickJson}`;
}

function nextAnchorId() {
  return `anchor_${String(draftManifest.anchors.length + 1).padStart(3, "0")}`;
}

function addDraftAnchor() {
  if (!currentMapPick || !currentScenePick) {
    alert("Pick both a Map12 point and a scene diagnostic point before adding an anchor.");
    return;
  }
  const scenePolicy = (packet.scene_topdown || {}).pixel_to_scene_xyz || {};
  const anchor = {
    anchor_id: document.getElementById("anchorId").value || nextAnchorId(),
    anchor_type: document.getElementById("anchorType").value || "operator_correspondence",
    anchor_role: "alignment",
    navigation_area_id: document.getElementById("navigationAreaId").value || "",
    asset_partition_id: document.getElementById("assetPartitionId").value || "",
    map_xy: currentMapPick.map_xy,
    scene_xyz: currentScenePick.scene_xyz,
    review_status: document.getElementById("reviewStatus").value || "proposed",
    confidence: null,
    map_coordinate_source: "operator_map_pick",
    scene_coordinate_source: scenePolicy.source || "rendered_gaussian_scene_topdown_ray_plane_pick",
    evidence: {
      source: "two_map_anchor_picker",
      scene_pick_policy: scenePolicy.status || "unknown",
      map_pixel_xy: [round6(currentMapPick.pixel.x), round6(currentMapPick.pixel.y)],
      scene_pixel_xy: [round6(currentScenePick.pixel.x), round6(currentScenePick.pixel.y)],
      operator_note: document.getElementById("operatorNote").value || "",
    },
  };
  draftManifest.anchors.push(anchor);
  document.getElementById("anchorId").value = nextAnchorId();
  renderDraftManifest();
}

function renderDraftManifest() {
  document.getElementById("draftOutput").value = `${JSON.stringify(draftManifest, null, 2)}\n`;
}

function downloadCorrespondenceManifest() {
  renderDraftManifest();
  const blob = new Blob([document.getElementById("draftOutput").value], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "b1-map12-scene-correspondences.draft.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function resetDraftManifest() {
  draftManifest.anchors = [];
  document.getElementById("anchorId").value = nextAnchorId();
  renderDraftManifest();
}

const mapImage = document.getElementById("mapImage");
if (mapImage) mapImage.addEventListener("click", onMapPick);
const sceneImage = document.getElementById("sceneImage");
if (sceneImage) sceneImage.addEventListener("click", onScenePick);
document.getElementById("addAnchorButton").addEventListener("click", addDraftAnchor);
document.getElementById("downloadButton").addEventListener("click", downloadCorrespondenceManifest);
document.getElementById("resetButton").addEventListener("click", resetDraftManifest);
renderDraftManifest();
"""


def render_anchor_row(row: dict[str, Any], *, output_dir: Path) -> str:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    map_image = str(evidence.get("map_image") or "")
    scene_image = str(evidence.get("scene_image") or "")
    evidence_bits = []
    if map_image:
        evidence_bits.append(
            f'<a href="{escape(relative_href(output_dir, Path(map_image)))}">map image</a>'
        )
    if scene_image:
        evidence_bits.append(
            f'<a href="{escape(relative_href(output_dir, Path(scene_image)))}">scene image</a>'
        )
    note = str(evidence.get("operator_note") or "")
    if note:
        evidence_bits.append(escape(note))
    action_class = "warn" if not row.get("fit_ready") else ""
    anchor_cell = (
        f"<td><code>{escape(str(row['anchor_id']))}</code><br />"
        f"{escape(str(row['anchor_type']))}<br />"
        f"{escape(str(row.get('anchor_role') or ALIGNMENT_ANCHOR_ROLE))}</td>"
    )
    area_cell = (
        f"<td>{escape(str(row['navigation_area_id']))}<br />"
        f"{escape(str(row['asset_partition_id']))}</td>"
    )
    return (
        "<tr>"
        f"{anchor_cell}"
        f"<td>{escape(str(row['review_status']))}</td>"
        f"<td>{escape(json.dumps(row.get('map_xy')))}</td>"
        f"<td>{escape(json.dumps(row.get('scene_xyz')))}</td>"
        f"{area_cell}"
        f"<td>{'<br />'.join(evidence_bits) if evidence_bits else ''}</td>"
        f'<td class="{action_class}">{escape(str(row["review_action"]))}</td>'
        "</tr>"
    )


def summary_rows(packet: dict[str, Any]) -> str:
    rows = [
        ("Review status", str(packet.get("review_status") or "")),
        ("Anchors", str(packet.get("anchor_count") or 0)),
        ("Accepted", str(packet.get("accepted_anchor_count") or 0)),
        ("Fit-ready", f"{packet.get('fit_ready_anchor_count') or 0}/6"),
        ("Source frame", str(packet.get("source_map_frame") or "")),
        ("Scene frame", str(packet.get("target_scene_frame") or "")),
        ("BBox seed policy", str(packet.get("bbox_seed_policy") or "")),
        ("Next action", str(packet.get("next_action") or "")),
    ]
    return "".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in rows
    )


def first_existing_path(paths: list[Path]) -> str:
    for path in paths:
        if path.is_file():
            return str(path)
    return ""


def relative_href(base_dir: Path, path: Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = target.resolve()
    base = Path(base_dir).resolve()
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        return target.as_posix()
