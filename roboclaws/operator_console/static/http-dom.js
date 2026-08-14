import { els } from "./state.js";

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) {
    els.eventList.textContent = `Copy failed: ${error.message || error}`;
  }
}

export async function fetchJson(url, options) {
  const response = await fetch(url, options);
  return response.json();
}

export function artifactHref(path) {
  const marker = "output/operator-console/";
  const index = String(path || "").indexOf(marker);
  if (index >= 0) {
    return `/artifacts/${encodeURIComponent(path.slice(index + marker.length)).replaceAll(
      "%2F",
      "/"
    )}`;
  }
  return "";
}

export function statusClass(value) {
  if (!value) return "neutral";
  const text = String(value);
  if (text.includes("pass") || text.includes("finish")) return "passed";
  if (text.includes("rate_limit")) return "failed";
  if (text.includes("fail") || text.includes("stop")) return "failed";
  if (text.includes("run") || text.includes("start")) return "running";
  return "warning";
}

export function formatElapsed(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = String(Math.floor(value / 60)).padStart(2, "0");
  const rest = String(value % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

export function compactRunId(runId) {
  return compactRunPart(String(runId || ""));
}

export function compactDisplayRunId(displayRunId) {
  return String(displayRunId || "")
    .split("/")
    .map((part) => compactRunPart(part))
    .join("/");
}

export function compactRunPart(part) {
  const fullTimestamp = String(part || "").match(
    /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(?:[-_].*)?$/
  );
  if (fullTimestamp) {
    return `${fullTimestamp[2]}${fullTimestamp[3]}-${fullTimestamp[4]}${fullTimestamp[5]}`;
  }
  const shortTimestamp = String(part || "").match(/^(\d{2})(\d{2})_(\d{2})(\d{2})(?:[-_].*)?$/);
  if (shortTimestamp) {
    return `${shortTimestamp[1]}${shortTimestamp[2]}_${shortTimestamp[3]}${shortTimestamp[4]}`;
  }
  return String(part || "");
}

export function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
