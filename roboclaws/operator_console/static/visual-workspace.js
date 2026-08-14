import { state, els, STABLE_VIEW_MODES } from "./state.js";
import { artifactHref, copyText, escapeHtml } from "./http-dom.js";

export function renderViews(assets, route = state.selectedRoute) {
  const sourceAssets = assets || {};
  const displayAssets = { ...sourceAssets };
  setImageSlot(
    "fpv",
    displayAssets.fpv,
    artifactEmptyText(route, "fpv", "Missing run camera artifact: expected robot_views/*.fpv.png.")
  );
  const metricMapAsset =
    sourceAssets.runtime_map || sourceAssets.map || routePreviewAsset(route, "map");
  displayAssets.map = metricMapAsset;
  setImageSlot(
    "map",
    metricMapAsset,
    artifactEmptyText(
      route,
      "map",
      "Missing Map artifact: expected runtime_metric_map_preview.png or map_bundle/preview.png."
    )
  );
  setImageSlot(
    "topdown",
    sourceAssets.topdown || routePreviewAsset(route, "topdown"),
    artifactEmptyText(route, "topdown", "Missing run top-down artifact: expected a run-local topdown image.")
  );
  displayAssets.topdown = sourceAssets.topdown || routePreviewAsset(route, "topdown");
  displayAssets.chase = sourceAssets.chase || routePreviewAsset(route, "chase");
  setImageSlot(
    "chase",
    displayAssets.chase,
    artifactEmptyText(route, "chase", "Missing run third-person artifact: expected robot_views/*.chase.png.")
  );
  renderGroundingSlot(
    sourceAssets,
    artifactEmptyText(route, "grounding", "No perception overlay has been written yet.")
  );
  state.latestViewAssets = displayAssets;
  ensureActiveViewAvailable(route);
  renderViewModes(route);
}

export function renderSelectedScenePreview(route = state.selectedRoute) {
  if (state.activeRunId) {
    return;
  }
  const previews = route && route.preview_assets ? route.preview_assets : {};
  state.latestViewAssets = previews;
  setImageSlot("fpv", previews.fpv, artifactEmptyText(route, "fpv", "No scene camera preview is available."));
  setImageSlot("map", previews.map, artifactEmptyText(route, "map", "No base Map preview is available."));
  setImageSlot(
    "topdown",
    previews.topdown,
    artifactEmptyText(route, "topdown", "No top-down scene preview is available.")
  );
  setImageSlot(
    "grounding",
    null,
    artifactEmptyText(route, "grounding", "Perception output will appear after a camera-grounded run starts.")
  );
  setImageSlot(
    "chase",
    previews.chase,
    artifactEmptyText(route, "chase", "Third-person preview will appear after a run starts.")
  );
}

export function artifactEmptyText(route, view, fallback) {
  if (routeHasView(route, view)) {
    return fallback;
  }
  return {
    fpv: "Camera view unavailable for this backend.",
    map: "Map view unavailable for this backend.",
    grounding: "Perception view unavailable for this backend.",
    chase: "Third-person view unavailable for this backend.",
    topdown: "Top-down scene view unavailable for this backend.",
  }[view] || `${imageLabel(view)} view unavailable for this backend.`;
}

export function setImageSlot(name, asset, emptyText) {
  const slot = document.getElementById(`${name}-frame`);
  if (!slot) {
    return;
  }
  const label = imageLabel(name, asset);
  updatePanelTitle(name, label);
  updateCopyButton(name, asset);
  if (!asset || !asset.path) {
    slot.textContent = emptyText;
    return;
  }
  const src = asset.href || artifactHref(asset.path);
  const visualRole = asset.visual_role || name;
  const sourceFamily = asset.artifact_source_family || "";
  slot.innerHTML = `
    <button
      type="button"
      class="image-preview-button"
      data-image-src="${escapeHtml(src)}"
      data-image-title="${escapeHtml(label)}"
      data-image-path="${escapeHtml(asset.path || "")}"
      data-view-role="${escapeHtml(visualRole)}"
      data-artifact-source-family="${escapeHtml(sourceFamily)}"
      aria-label="Open ${escapeHtml(label)} image preview"
      title="Open image preview"
    >
      <img alt="${escapeHtml(label)} artifact" src="${escapeHtml(src)}" />
    </button>
  `;
  const button = slot.querySelector(".image-preview-button");
  button.addEventListener("click", () => {
    openImageDialog({
      src,
      title: label,
      path: asset.path || "",
    });
  });
}

export function renderGroundingSlot(assets, emptyText) {
  const slot = document.getElementById("grounding-frame");
  if (!slot) {
    return;
  }
  updatePanelTitle("grounding", imageLabel("grounding"));
  const framePayload = assets && assets.grounding_frames;
  const frames = framePayload && Array.isArray(framePayload.frames) ? framePayload.frames : [];
  if (!frames.length) {
    setImageSlot("grounding", assets && assets.grounding, emptyText);
    return;
  }
  const copyAsset = firstGroundingFrameAsset(frames);
  updateCopyButton("grounding", copyAsset);
  const candidateCount = framePayload.candidate_count || groundingCandidateCount(frames);
  slot.innerHTML = `
    <div class="grounding-gallery" data-frame-count="${frames.length}" data-candidate-count="${candidateCount}">
      <div class="grounding-gallery-summary">
        ${frames.length} frame${frames.length === 1 ? "" : "s"} / ${candidateCount} candidate${candidateCount === 1 ? "" : "s"}
      </div>
      <div class="grounding-frame-list">
        ${frames.map((frame) => groundingFrameHtml(frame)).join("")}
      </div>
    </div>
  `;
  slot.querySelectorAll(".grounding-image-button").forEach((button) => {
    button.addEventListener("click", () => {
      openImageDialog({
        src: button.dataset.imageSrc || "",
        title: button.dataset.imageTitle || imageLabel("grounding"),
        path: button.dataset.imagePath || "",
      });
    });
  });
}

export function firstGroundingFrameAsset(frames) {
  const first = frames.find((frame) => frame && frame.image && frame.image.path);
  return first ? first.image : null;
}

export function groundingCandidateCount(frames) {
  return frames.reduce((total, frame) => total + ((frame && frame.candidates && frame.candidates.length) || 0), 0);
}

export function groundingFrameHtml(frame) {
  const image = (frame && frame.image) || {};
  const src = image.href || artifactHref(image.path);
  const observationId = frame.observation_id || "raw_fpv";
  const candidates = Array.isArray(frame.candidates) ? frame.candidates : [];
  return `
    <article class="grounding-frame-card">
      <div class="grounding-frame-header">
        <span>${escapeHtml(observationId)}</span>
        <span>${candidates.length} candidate${candidates.length === 1 ? "" : "s"}</span>
      </div>
      <button
        type="button"
        class="grounding-image-button"
        data-image-src="${escapeHtml(src)}"
        data-image-title="${escapeHtml(`Perception ${observationId}`)}"
        data-image-path="${escapeHtml(image.path || "")}"
        aria-label="Open ${escapeHtml(observationId)} perception frame"
        title="Open perception frame"
      >
        <img alt="${escapeHtml(observationId)} camera frame" src="${escapeHtml(src)}" />
        <span class="grounding-box-layer" aria-hidden="true">
          ${candidates.map((candidate, index) => groundingCandidateBoxHtml(candidate, index)).join("")}
        </span>
      </button>
    </article>
  `;
}

export function groundingCandidateBoxHtml(candidate, index) {
  const bbox = Array.isArray(candidate.bbox_xywh) ? candidate.bbox_xywh : [];
  if (bbox.length !== 4) {
    return "";
  }
  const [x, y, width, height] = bbox.map((value) => Math.max(0, Math.min(1, Number(value) || 0)));
  const label = groundingCandidateLabel(candidate, index);
  return `
    <span
      class="grounding-box"
      style="left:${x * 100}%;top:${y * 100}%;width:${width * 100}%;height:${height * 100}%"
    >
      <span class="grounding-box-label">${escapeHtml(label)}</span>
    </span>
  `;
}

export function groundingCandidateLabel(candidate, index) {
  const category = candidate.category || `candidate ${index + 1}`;
  const confidence =
    typeof candidate.confidence === "number" ? ` ${Math.round(candidate.confidence * 100)}%` : "";
  return `${category}${confidence}`;
}

export function routePreviewAsset(route, name) {
  const previews = route && route.preview_assets ? route.preview_assets : {};
  return previews[name] || null;
}

export function imageLabel(name, asset = {}) {
  const labels = {
    fpv: "Camera",
    map: "Map",
    topdown: "Top-down Scene",
    grounding: "Perception",
    chase: "Third-person",
  };
  return labels[name] || name;
}

export function updatePanelTitle(name, label) {
  const title = document.querySelector(`[data-panel-title="${name}"]`);
  if (title) {
    title.textContent = label;
  }
}

export function updateCopyButton(name, asset) {
  const button = document.querySelector(`[data-copy="${name}"]`);
  if (!button) {
    return;
  }
  button.disabled = !asset || !asset.path;
  button.title = asset && asset.path ? asset.path : "No artifact path yet";
}

export async function copyVisualPath(name) {
  const asset =
    state.latestViewAssets &&
    (name === "grounding"
      ? firstGroundingFrameAsset(
          state.latestViewAssets.grounding_frames && state.latestViewAssets.grounding_frames.frames
            ? state.latestViewAssets.grounding_frames.frames
            : []
        ) || state.latestViewAssets.grounding
      : name === "map"
      ? state.latestViewAssets.runtime_map || state.latestViewAssets.map
      : state.latestViewAssets[name]);
  if (!asset || !asset.path) {
    els.eventList.textContent = `${imageLabel(name)} artifact path is not available yet.`;
    return;
  }
  await copyText(asset.path);
  els.eventList.textContent = `Copied ${imageLabel(name, asset)} path.`;
}

export function openImageDialog({ src, title, path }) {
  if (!src) {
    return;
  }
  els.imageDialogTitle.textContent = title;
  els.imageDialogPath.textContent = path;
  els.imageDialogImg.src = src;
  els.imageDialogImg.alt = `${title} artifact`;
  els.imageDialog.showModal();
}

export function renderViewModes(route = state.selectedRoute) {
  const visualGrid = document.getElementById("visual-grid");
  if (!visualGrid || !route) {
    return;
  }
  const modes = routeViewModes(route);
  const activeView = state.activeView || "overview";
  visualGrid.className = `view-grid mode-${activeView}`;

  document.querySelectorAll(".view-mode").forEach((button) => {
    const enabled = modes.has(button.dataset.view);
    button.hidden = !STABLE_VIEW_MODES.has(button.dataset.view);
    button.disabled = !enabled;
    button.title = enabled ? "" : "Unavailable for this backend.";
    button.classList.toggle("active", enabled && button.dataset.view === activeView);
  });

  const visiblePanels = visiblePanelsForView(activeView, modes, route);
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.hidden = !visiblePanels.has(panel.dataset.panel);
  });
}

export function ensureActiveViewAvailable(route = state.selectedRoute) {
  if (!route) {
    return;
  }
  const modes = routeViewModes(route);
  if (!modes.has(state.activeView)) {
    state.activeView = "overview";
  }
}

export function routeViewModes(route) {
  const modes = new Set(route && route.view_modes ? route.view_modes : []);
  for (const view of STABLE_VIEW_MODES) {
    modes.add(view);
  }
  return modes;
}

export function routeHasView(route, view) {
  if (["overview", "outputs"].includes(view)) {
    return true;
  }
  if (view === "topdown") {
    return Boolean(routePreviewAsset(route, "topdown"));
  }
  return new Set((route && route.backend_view_modes) || (route && route.view_modes) || []).has(view);
}

export function visiblePanelsForView(view, modes, route = state.selectedRoute) {
  if (view === "overview") {
    return new Set(["fpv", "map", "chase", "topdown"]);
  }
  if (!modes.has(view)) {
    return new Set(["fpv", "map", "chase"]);
  }
  if (view === "outputs") {
    return new Set(["outputs"]);
  }
  return new Set([view]);
}
