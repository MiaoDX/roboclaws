import { state, els } from "./state.js";
import { escapeHtml, fetchJson, statusClass } from "./http-dom.js";
import { refreshSelectedRouteReadiness } from "./launch.js";

export async function refreshRuntimeTasks() {
  const port = els.portInput.value || "18788";
  const payload = await fetchJson(`/api/runtime/tasks?port=${encodeURIComponent(port)}`);
  if (payload.error) {
    els.eventList.textContent = payload.error;
    return;
  }
  state.runtime = payload;
  renderBackgroundTaskButton();
  els.eventList.textContent = backgroundTaskEventText();
  renderBackgroundTasks(payload);
  if (!els.backgroundTasksDialog.open) {
    els.backgroundTasksDialog.showModal();
  }
}

export function renderBackgroundTasks(payload = state.runtime) {
  const tasks = payload.tasks || [];
  const summary = payload.summary || {};
  els.backgroundTasksSummary.textContent = `${summary.active || 0} active / ${summary.total || tasks.length || 0} total`;
  els.backgroundTaskList.innerHTML = "";
  if (!tasks.length) {
    els.backgroundTaskList.textContent = "No blocking background resources detected.";
    return;
  }
  for (const task of tasks) {
    const row = document.createElement("article");
    row.className = "background-task-row";
    const resources = (task.resources || [])
      .map((resource) => resource.label || resource.kind)
      .filter(Boolean)
      .join(" / ");
    row.innerHTML = `
      <header>
        <strong>${escapeHtml(task.label || task.id)}</strong>
        <span class="badge ${statusClass(task.status)}">${escapeHtml(task.status || "unknown")}</span>
      </header>
      <div class="field-help">${escapeHtml(task.owner || "unknown")} / ${escapeHtml(task.id || "")}</div>
      <div>${escapeHtml(resources || task.resource || "background resource")}</div>
      <div class="background-task-actions"></div>
    `;
    const actions = row.querySelector(".background-task-actions");
    for (const action of task.actions || []) {
      actions.appendChild(backgroundTaskActionButton(action));
    }
    for (const artifact of task.artifacts || []) {
      if (!artifact.href) {
        continue;
      }
      const link = document.createElement("a");
      link.href = artifact.href;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = artifact.label || artifact.kind || "Artifact";
      link.className = "secondary";
      actions.appendChild(link);
    }
    if (!actions.childNodes.length) {
      actions.textContent = "No console action available.";
    }
    els.backgroundTaskList.appendChild(row);
  }
}

export function backgroundTaskActionButton(action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = action.type === "api_post" ? "danger" : "secondary";
  button.textContent = action.label || "Open";
  button.addEventListener("click", () => runBackgroundTaskAction(action));
  return button;
}

export async function runBackgroundTaskAction(action) {
  if (action.type === "link" && action.href) {
    window.open(action.href, "_blank", "noopener");
    return;
  }
  if (action.type !== "api_post" || !action.href) {
    els.backgroundTasksSummary.textContent = "Unsupported console action.";
    return;
  }
  const result = await fetchJson(action.href, { method: action.method || "POST" });
  if (result.error) {
    els.backgroundTasksSummary.textContent = result.error;
    return;
  }
  els.backgroundTasksSummary.textContent = result.terminal_reason || result.phase || "Action complete.";
  await refreshSelectedRouteReadiness();
  await refreshRuntimeTasks();
}

export function renderBackgroundTaskButton() {
  const tasks = (state.runtime && state.runtime.tasks) || [];
  const summary = (state.runtime && state.runtime.summary) || {};
  const activeCount = Number(summary.active || tasks.length || 0);
  els.backgroundTasksButton.hidden = activeCount <= 0;
}

export function backgroundTaskEventText() {
  const tasks = (state.runtime && state.runtime.tasks) || [];
  const summary = (state.runtime && state.runtime.summary) || {};
  const activeCount = Number(summary.active || tasks.length || 0);
  if (!activeCount) {
    return "No blocking background resources detected.";
  }
  const first = tasks[0] || {};
  return `${activeCount} background blocker${activeCount === 1 ? "" : "s"}: ${
    first.label || first.id || "resource active"
  }.`;
}
